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


ELEMENTS = ("e9", "hex8fi")
DEFAULT_ELEMENT = "e9"


def hex8_e9(nu, h=1.0, D=None):
    """Hex8 with 9 incompatible (bubble) modes, statically condensed to 24 x 24 (Wilson et al. 1973;
    Taylor, Beresford and Wilson 1976). Each displacement component gets the three bubbles
    P_k = 1 - xi_k^2. On a cube the Jacobian is constant, so Wilson's element and Taylor's patch-test
    correction are the same element; it passes the patch test (check V10) and removes the parasitic
    shear that makes a full-integration hex8 too stiff in bending.
    Condensation: ke = Kaa - Kab inv(Kbb) Kba. The bubbles have zero gradient at the centre, so the
    centre strain B0 u (used for stress) is unchanged."""
    D = elasticity_D(nu) if D is None else np.asarray(D, float)
    g = 1 / np.sqrt(3)
    jac = h / 2
    Kaa, Kab, Kbb = np.zeros((24, 24)), np.zeros((24, 9)), np.zeros((9, 9))
    for xi in (-g, g):
        for eta in (-g, g):
            for zeta in (-g, g):
                Ba = _B(_dN(xi, eta, zeta) / jac)
                G = np.diag([-2 * xi, -2 * eta, -2 * zeta]) / jac      # gradients of the 3 bubbles
                Gp = np.zeros((8, 3))
                Gp[:3] = G
                Bi = _B(Gp)[:, :9]
                w = jac ** 3
                Kaa += Ba.T @ D @ Ba * w
                Kab += Ba.T @ D @ Bi * w
                Kbb += Bi.T @ D @ Bi * w
    ke = Kaa - Kab @ np.linalg.solve(Kbb, Kab.T)
    ke = 0.5 * (ke + ke.T)
    B0 = _B(_dN(0, 0, 0) / jac)
    return ke, B0, D


def hex8_matrices(nu, h=1.0, D=None, element="hex8fi"):
    if element == "e9":
        return hex8_e9(nu, h, D)
    if element != "hex8fi":
        raise ValueError(f"Unknown element '{element}'. Use one of {', '.join(ELEMENTS)}.")
    return _hex8_full(nu, h, D)


def _hex8_full(nu, h=1.0, D=None):
    """Element stiffness (E = 1) for a cube of side h by 2x2x2 Gauss quadrature,
    plus the strain-displacement matrix at the centre and D.
    D (optional): a 6x6 constitutive matrix normalised to the reference modulus
    (for an anisotropic material). None = isotropic with Poisson ratio nu."""
    D = elasticity_D(nu) if D is None else np.asarray(D, float)
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


def thermal_element_vector(D, h, m, element="hex8fi"):
    """Element load of a thermal strain (eigenstrain) m, for E = 1 and a 1 K rise, constant in the voxel:
    f_a = sum_gp Ba^T D m w (24 values, 2x2x2 Gauss points, the same loop as the stiffness).
    For e9 also the bubble part f_b = sum_gp Bi^T D m w (9 values). The bubble gradients (-2 xi_k / jac)
    are odd in each coordinate, so f_b = 0 for a constant strain and the condensed load f_a - Kab Kbb^-1 f_b
    is just f_a (tests/test_thermal.py checks f_b = 0). If the strain is ever made to vary inside a voxel,
    f_b is no longer zero and the condensation term must be added.
    m: thermal strain per kelvin in Voigt order xx yy zz xy yz zx (engineering shear)."""
    D = np.asarray(D, float)
    m = np.asarray(m, float)
    g = 1 / np.sqrt(3)
    jac = h / 2
    fa, fb = np.zeros(24), np.zeros(9)
    for xi in (-g, g):
        for eta in (-g, g):
            for zeta in (-g, g):
                w = jac ** 3
                fa += _B(_dN(xi, eta, zeta) / jac).T @ D @ m * w
                if element == "e9":
                    Gp = np.zeros((8, 3))
                    Gp[:3] = np.diag([-2 * xi, -2 * eta, -2 * zeta]) / jac
                    fb += _B(Gp)[:, :9].T @ D @ m * w
    return fa, (fb if element == "e9" else np.zeros(0))


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

    def __init__(self, grid, active, fixed_dofs, nu, log=None, D=None, element=DEFAULT_ELEMENT):
        t0 = time.time()
        self.grid = grid
        self.log = log or (lambda *a: None)
        self.act = np.flatnonzero(active)
        if self.act.size == 0:
            raise SolverError("No active voxels: the design space is empty.")
        self.element = element
        ke, self.B0, self.D = hex8_matrices(nu, grid.h, D, element)
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
        self.loc = (idx % 576).astype(np.int16)
        self.kev = ke.ravel()[self.loc]
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

    def assemble_matrix(self, m24, w):
        """Assemble any 24x24 element matrix m24 scaled by w per active element, on K's pattern."""
        data = np.bincount(self.map, weights=m24.ravel()[self.loc] * w[self.ei], minlength=self.nnz)
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

    def internal_forces(self, u_full, Ee):
        """Global internal force vector K u (all DOFs, fixed ones included), N."""
        ue = u_full[self.edof]
        fe = (ue @ self.ke) * np.asarray(Ee)[:, None]
        return np.bincount(self.edof.ravel(), weights=fe.ravel(), minlength=3 * self.grid.nnode)

    def element_energy(self, u_full):
        """u_e^T ke u_e per active element (for E = 1)."""
        ue = u_full[self.edof]
        return np.einsum("ij,ij->i", ue @ self.ke, ue)

    def stress(self, u_full, E_material, eps0=None):
        """Element-centre stress (MPa), Voigt order xx yy zz xy yz zx, shape (n, 6).
        eps0 (optional): eigenstrain (thermal strain), shape (6,) or (n, 6): sigma = E D (B0 u - eps0).
        None (the default) gives exactly the numbers of the earlier versions."""
        ue = u_full[self.edof]
        eps = ue @ self.B0.T
        if eps0 is not None:
            eps = eps - np.asarray(eps0, float)
        return (eps @ self.D.T) * (np.asarray(E_material)[:, None] if np.ndim(E_material) else E_material)

    def thermal_vector(self, m):
        """24-vector f_hat = sum_gp B^T D m w for E = 1 and a 1 K rise (see thermal_element_vector)."""
        return thermal_element_vector(self.D, self.grid.h, m, self.element)[0]

    def thermal_load(self, fhat, EdT):
        """Global nodal load (N) of a thermal strain: element e adds EdT[e] * fhat to its 24 dofs.
        EdT: per active element, the modulus scale (E x fill x derating) times the temperature change.
        The load of each element sums to zero (a free voxel expands without net force)."""
        w = np.broadcast_to(np.asarray(EdT, float), (self.act.size,))
        fe = w[:, None] * np.asarray(fhat, float)[None, :]
        return np.bincount(self.edof.ravel(), weights=fe.ravel(), minlength=3 * self.grid.nnode)

    def element_energy_thermal(self, u_full, fhat, m, dT):
        """Twice the strain energy per active element for E = 1 with a thermal strain dT * m:
        integral of (B u - eps0)^T D (B u - eps0) = u^T ke u - 2 dT u^T f_hat + dT^2 V m^T D m.
        For e9 the condensed ke gives the energy with the bubbles at equilibrium (their load is zero)."""
        ue = u_full[self.edof]
        m = np.asarray(m, float)
        dT = np.asarray(dT, float)
        return (np.einsum("ij,ij->i", ue @ self.ke, ue) - 2 * dT * (ue @ fhat)
                + dT ** 2 * self.grid.h ** 3 * float(m @ self.D @ m))

    @staticmethod
    def normal_stress(sig, d):
        """Normal stress on planes across direction d (for example the build direction)."""
        d = np.asarray(d, float) / np.linalg.norm(d)
        x, y, z = d
        return (sig[:, 0] * x * x + sig[:, 1] * y * y + sig[:, 2] * z * z
                + 2 * (sig[:, 3] * x * y + sig[:, 4] * y * z + sig[:, 5] * z * x))

    def von_mises(self, u_full, E_material, eps0=None):
        """Element-centre von Mises stress in the material (MPa). eps0: as in stress()."""
        sig = self.stress(u_full, E_material, eps0)
        sx, sy, sz, txy, tyz, tzx = sig.T
        return np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2)
                       + 3 * (txy ** 2 + tyz ** 2 + tzx ** 2))
