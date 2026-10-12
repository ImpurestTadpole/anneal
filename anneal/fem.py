"""Voxel finite element solver.

One grid, no mesh: each voxel is a trilinear 8-node brick (hex8). Connectivity is
implicit in the grid index. Partial voxels (fill fraction < 1) are solved with their
fill fraction as a stiffness scale with penalty 1 (Phase 0 finding V6: a fill fraction
is real material in parallel, not a design variable).

Linear system: assembled once into a fixed CSR pattern, refilled each iteration with
np.bincount, solved by conjugate gradients with a smoothed-aggregation algebraic
multigrid preconditioner (pyamg, MIT) seeded with the six rigid-body modes.

Units: mm, N, MPa. Displacement comes out in mm, stress in MPa.
"""
import time
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import cg
import pyamg

LOCAL = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                  [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]])


class SolverError(RuntimeError):
    pass


def _cg(A, b, x0, rtol, maxiter, M, callback):
    """scipy renamed cg's tol to rtol in 1.12; support both so older installs work."""
    try:
        return cg(A, b, x0=x0, rtol=rtol, maxiter=maxiter, M=M, callback=callback)
    except TypeError:
        return cg(A, b, x0=x0, tol=rtol, maxiter=maxiter, M=M, callback=callback)


def elasticity_D(nu):
    """Isotropic constitutive matrix for E = 1 (Voigt order xx yy zz xy yz zx, engineering shear)."""
    c = 1.0 / ((1 + nu) * (1 - 2 * nu))
    D = np.zeros((6, 6))
    D[:3, :3] = nu
    D[0, 0] = D[1, 1] = D[2, 2] = 1 - nu
    D[3, 3] = D[4, 4] = D[5, 5] = (1 - 2 * nu) / 2
    return D * c


def _dN(xi, eta, zeta):
    s = 2 * LOCAL - 1
    dN = np.empty((8, 3))
    dN[:, 0] = s[:, 0] * (1 + s[:, 1] * eta) * (1 + s[:, 2] * zeta) / 8
    dN[:, 1] = s[:, 1] * (1 + s[:, 0] * xi) * (1 + s[:, 2] * zeta) / 8
    dN[:, 2] = s[:, 2] * (1 + s[:, 0] * xi) * (1 + s[:, 1] * eta) / 8
    return dN


def _B(dNdx):
    B = np.zeros((6, 24))
    for a in range(8):
        dx, dy, dz = dNdx[a]
        B[0, 3 * a] = dx
        B[1, 3 * a + 1] = dy
        B[2, 3 * a + 2] = dz
        B[3, 3 * a] = dy
        B[3, 3 * a + 1] = dx
        B[4, 3 * a + 1] = dz
        B[4, 3 * a + 2] = dy
        B[5, 3 * a] = dz
        B[5, 3 * a + 2] = dx
    return B


def hex8_matrices(nu, h=1.0):
    """Element stiffness (E = 1) for a cube of side h by 2x2x2 Gauss quadrature,
    plus the strain-displacement matrix at the centre and D."""
    D = elasticity_D(nu)
    ke = np.zeros((24, 24))
    g = 1 / np.sqrt(3)
    jac = h / 2
    for xi in (-g, g):
        for eta in (-g, g):
            for zeta in (-g, g):
                B = _B(_dN(xi, eta, zeta) / jac)
                ke += B.T @ D @ B * jac ** 3
    B0 = _B(_dN(0, 0, 0) / jac)
    return ke, B0, D


class Grid:
    """Regular voxel grid. Element (i,j,k) spans origin + h*[i,i+1] x ..."""

    def __init__(self, shape, h, origin):
        self.shape = tuple(int(s) for s in shape)
        self.nx, self.ny, self.nz = self.shape
        self.h = float(h)
        self.origin = np.asarray(origin, dtype=float)
        self.nelem = self.nx * self.ny * self.nz
        self.nnode = (self.nx + 1) * (self.ny + 1) * (self.nz + 1)
        o = LOCAL
        self._noff = o[:, 0] + (self.nx + 1) * (o[:, 1] + (self.ny + 1) * o[:, 2])

    def elem_ijk(self, e):
        e = np.asarray(e)
        return e % self.nx, (e // self.nx) % self.ny, e // (self.nx * self.ny)

    def element_nodes(self, e):
        i, j, k = self.elem_ijk(e)
        base = i + (self.nx + 1) * (j + (self.ny + 1) * k)
        return base[:, None] + self._noff[None, :]

    def node_coords(self, n):
        n = np.asarray(n)
        i = n % (self.nx + 1)
        j = (n // (self.nx + 1)) % (self.ny + 1)
        k = n // ((self.nx + 1) * (self.ny + 1))
        return self.origin + self.h * np.stack([i, j, k], axis=-1)

    def elem_centers(self, e=None):
        if e is None:
            e = np.arange(self.nelem)
        i, j, k = self.elem_ijk(e)
        return self.origin + self.h * (np.stack([i, j, k], axis=-1) + 0.5)

    def to3d(self, flat):
        """Flat element array (x fastest) -> array indexed [i, j, k]."""
        return np.asarray(flat).reshape(self.nz, self.ny, self.nx).transpose(2, 1, 0)

    def to1d(self, arr3):
        return np.asarray(arr3).transpose(2, 1, 0).ravel()


class FEM:
    """Linear elastic solve on the active voxels of a grid."""

    def __init__(self, grid, active, fixed_dofs, nu, log=None):
        t0 = time.time()
        self.grid = grid
        self.log = log or (lambda *a: None)
        self.act = np.flatnonzero(active)
        if self.act.size == 0:
            raise SolverError("No active voxels: the design space is empty.")
        ke, self.B0, self.D = hex8_matrices(nu, grid.h)
        self.ke = ke
        en = grid.element_nodes(self.act)
        self.edof = (3 * en[:, :, None] + np.arange(3)).reshape(-1, 24)

        used = np.unique(en)
        dofmask = np.zeros(3 * grid.nnode, dtype=bool)
        dofmask[(3 * used[:, None] + np.arange(3)).ravel()] = True
        fixed_dofs = np.asarray(fixed_dofs, dtype=np.int64)
        dofmask[fixed_dofs] = False
        self.free = np.flatnonzero(dofmask)
        self.nfree = self.free.size
        red = np.full(3 * grid.nnode, -1, dtype=np.int64)
        red[self.free] = np.arange(self.nfree)
        self.red = red
        redof = red[self.edof]

        R = np.repeat(redof, 24, axis=1)
        C = np.tile(redof, (1, 24))
        valid = ((R >= 0) & (C >= 0)).ravel()
        idx = np.flatnonzero(valid)
        rows = R.ravel()[idx]
        cols = C.ravel()[idx]
        del R, C
        key = rows * self.nfree + cols
        ukey, inv = np.unique(key, return_inverse=True)
        urow = ukey // self.nfree
        self.indices = (ukey % self.nfree).astype(np.int32)
        self.indptr = np.searchsorted(urow, np.arange(self.nfree + 1)).astype(np.int64)
        self.map = inv.astype(np.int32 if ukey.size < 2 ** 31 else np.int64)
        self.ei = (idx // 576).astype(np.int32)
        self.kev = ke.ravel()[idx % 576]
        self.nnz = ukey.size

        # Rigid-body modes as the multigrid near-null space
        gd = self.free
        node = gd // 3
        comp = gd % 3
        xyz = grid.node_coords(node)
        xyz = xyz - xyz.mean(axis=0)
        Bn = np.zeros((self.nfree, 6))
        for c in range(3):
            Bn[comp == c, c] = 1.0
        x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
        Bn[comp == 0, 3] = -y[comp == 0]
        Bn[comp == 1, 3] = x[comp == 1]
        Bn[comp == 1, 4] = -z[comp == 1]
        Bn[comp == 2, 4] = y[comp == 2]
        Bn[comp == 2, 5] = -x[comp == 2]
        Bn[comp == 0, 5] = z[comp == 0]
        self.Bnull = Bn
        self.ml = None
        self.M = None
        self.amg_builds = 0
        self.cg_iters = []
        self.log(f"  system: {self.act.size:,} elements, {self.nfree:,} free dofs, "
                 f"{self.nnz:,} nonzeros, built in {time.time() - t0:.1f} s")

    def assemble(self, Ee):
        """Ee: stiffness scale per active element (E in MPa times fill times density law)."""
        data = np.bincount(self.map, weights=self.kev * Ee[self.ei], minlength=self.nnz)
        return sp.csr_matrix((data, self.indices, self.indptr), shape=(self.nfree, self.nfree))

    def reduce_load(self, F_global):
        return F_global[self.free]

    def solve(self, K, F_list, x0_list=None, rebuild=True, rtol=1e-8, maxiter=2000):
        if rebuild or self.ml is None:
            # pyamg estimates spectral radii from a random start vector; seed it so reruns
            # are bit-identical, then restore the caller's random state.
            state = np.random.get_state()
            np.random.seed(20260913)
            self.ml = pyamg.smoothed_aggregation_solver(
                K, B=self.Bnull, symmetry="symmetric", max_coarse=600)
            np.random.set_state(state)
            self.M = self.ml.aspreconditioner(cycle="V")
            self.amg_builds += 1
        out = []
        for i, f in enumerate(F_list):
            x0 = None if x0_list is None else x0_list[i]
            count = [0]

            def cb(_):
                count[0] += 1
            u, info = _cg(K, f, x0=x0, rtol=rtol, maxiter=maxiter, M=self.M, callback=cb)
            if info != 0 or not np.all(np.isfinite(u)):
                raise SolverError(
                    f"The solver did not converge in {maxiter} iterations. Usual causes: the part can move "
                    f"or turn freely (add a fixed anchor, or fix more directions on one), or the design has "
                    f"pieces held only by near-empty voxels (raise volumeFraction or iterations).")
            self.cg_iters.append(count[0])
            out.append(u)
        return out

    def expand(self, u_red):
        u = np.zeros(3 * self.grid.nnode)
        u[self.free] = u_red
        return u

    def element_energy(self, u_full):
        """u_e^T ke u_e per active element (for E = 1)."""
        ue = u_full[self.edof]
        return np.einsum("ij,ij->i", ue @ self.ke, ue)

    def stress(self, u_full, E_material):
        """Element-centre stress (MPa), Voigt order xx yy zz xy yz zx, shape (n, 6)."""
        ue = u_full[self.edof]
        eps = ue @ self.B0.T
        return (eps @ self.D.T) * (np.asarray(E_material)[:, None] if np.ndim(E_material) else E_material)

    @staticmethod
    def normal_stress(sig, d):
        """Normal stress on planes across direction d (for example the build direction)."""
        d = np.asarray(d, float) / np.linalg.norm(d)
        x, y, z = d
        return (sig[:, 0] * x * x + sig[:, 1] * y * y + sig[:, 2] * z * z
                + 2 * (sig[:, 3] * x * y + sig[:, 4] * y * z + sig[:, 5] * z * x))

    def von_mises(self, u_full, E_material):
        """Element-centre von Mises stress in the material (MPa)."""
        sig = self.stress(u_full, E_material)
        sx, sy, sz, txy, tyz, tzx = sig.T
        return np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2)
                       + 3 * (txy ** 2 + tyz ** 2 + tzx ** 2))
