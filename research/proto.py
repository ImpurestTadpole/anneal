"""Prototypes for the roadmap (branch verify-roadmap). Not part of the anneal package yet.

- transverse_iso_D : print-aware stiffness (layers in the plane normal to the build direction)
- interlayer_factor: Kuznetsov 2018 trend, scaled to a user's calibration point
- stress_stiffness_parts / buckling: linear buckling load factor on the voxel FEM
- AMFilter         : Langelaar layer-by-layer overhang filter (3-D, 5-element support stencil)
- equivalent_static_force: impact energy -> static force for a linear part
"""
import numpy as np
import scipy.sparse.linalg as sla
from anneal.fem import _dN, LOCAL

VOIGT = [(0, 0), (1, 1), (2, 2), (0, 1), (1, 2), (2, 0)]


# ---------------------------------------------------------------- material
def _voigt_to_tensor(D):
    C = np.zeros((3, 3, 3, 3))
    for I, (i, j) in enumerate(VOIGT):
        for J, (k, l) in enumerate(VOIGT):
            for a, b in ((i, j), (j, i)):
                for c, d in ((k, l), (l, k)):
                    C[a, b, c, d] = D[I, J]
    return C


def _tensor_to_voigt(C):
    D = np.zeros((6, 6))
    for I, (i, j) in enumerate(VOIGT):
        for J, (k, l) in enumerate(VOIGT):
            D[I, J] = C[i, j, k, l]
    return D


def _rot_z_to(d):
    """Rotation matrix whose third column is unit vector d (maps local z to d)."""
    d = np.asarray(d, float) / np.linalg.norm(d)
    a = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(a, d); x /= np.linalg.norm(x)
    y = np.cross(d, x)
    return np.stack([x, y, d], axis=1)


def transverse_iso_D(Ep, Ez, nu_p, nu_zp, Gzp, build_dir=(0, 0, 1), Eref=None):
    """Stiffness (Voigt xx yy zz xy yz zx, engineering shear) of a transversely isotropic
    material whose isotropic plane is the print layer and whose axis is build_dir.
    nu_zp: strain in the layer for stress along the build axis (nu_zp/Ez = nu_pz/Ep).
    Returned normalised by Eref (default Ep) so FEM can scale it by E per element."""
    S = np.zeros((6, 6))
    S[0, 0] = S[1, 1] = 1 / Ep
    S[2, 2] = 1 / Ez
    S[0, 1] = S[1, 0] = -nu_p / Ep
    S[0, 2] = S[2, 0] = S[1, 2] = S[2, 1] = -nu_zp / Ez
    S[3, 3] = 2 * (1 + nu_p) / Ep
    S[4, 4] = S[5, 5] = 1 / Gzp
    D = np.linalg.inv(S)
    R = _rot_z_to(build_dir)
    C = np.einsum("ia,jb,kc,ld,abcd->ijkl", R, R, R, R, _voigt_to_tensor(D))
    return _tensor_to_voigt(C) / (Eref or Ep)


# ---------------------------------------------------------------- FDM strength trend
KUZ_COEF = 58.19   # MPa, Kuznetsov et al. 2018, Polymers 10(3):313, PLA, 3-point bending


def interlayer_factor(r, r_cal=None, f_cal=None, ufs_max=70.7):
    """Kuznetsov fit UFS = UFS_max - 58.19 / r^1.5 (r = nozzle / layer height), as a
    fraction of UFS_max. With a user calibration point (r_cal, f_cal) the curve is
    rescaled to pass through it. Clipped to [0.05, 1]."""
    f = lambda rr: 1 - KUZ_COEF / ufs_max / np.asarray(rr, float) ** 1.5
    out = f(r)
    if r_cal is not None:
        out = out * f_cal / f(r_cal)
    return np.clip(out, 0.05, 1.0)


# ---------------------------------------------------------------- buckling
def stress_stiffness_parts(h):
    """Six 24x24 matrices M_c with ke_sigma = sum_c sigma_c * M_c for constant element stress."""
    g = 1 / np.sqrt(3)
    jac = h / 2
    G = [np.zeros((8, 8)) for _ in range(6)]
    for xi in (-g, g):
        for eta in (-g, g):
            for zeta in (-g, g):
                d = _dN(xi, eta, zeta) / jac          # (8, 3)
                w = jac ** 3
                for c, (i, j) in enumerate(VOIGT):
                    if i == j:
                        G[c] += w * np.outer(d[:, i], d[:, i])
                    else:
                        G[c] += w * (np.outer(d[:, i], d[:, j]) + np.outer(d[:, j], d[:, i]))
    return [np.kron(m, np.eye(3)) for m in G]


def buckling(fem, Ee, u_red, n_modes=6, rtol_inner=1e-10, sigma_scale=None):
    """Buckling load factors for the load that produced u_red (K(Ee) u = F).
    Ee: element stiffness scale used in K. sigma_scale: per-element scale for the stress used
    in K_sigma (default Ee; for SIMP designs Ferrari et al. use x^p without Emin).
    Returns (lambdas ascending, modes)."""
    K = fem.assemble(Ee)
    u = fem.expand(u_red)
    sig = fem.stress(u, sigma_scale if sigma_scale is not None else Ee)
    parts = stress_stiffness_parts(fem.grid.h)
    Ks = sum(fem.assemble_matrix(parts[c], sig[:, c]) for c in range(6))
    fem.solve(K, [np.zeros(fem.nfree) + 1e-30], rebuild=True)   # build the AMG hierarchy
    M = fem.M

    def kinv(b):
        x, info = sla.cg(K, b, rtol=rtol_inner, maxiter=5000, M=M)
        return x
    Kinv = sla.LinearOperator(K.shape, matvec=kinv, dtype=float)
    mu, V = sla.eigsh(-Ks, k=n_modes, M=K, Minv=Kinv, which="LA", tol=1e-8)
    order = np.argsort(-mu)
    mu, V = mu[order], V[:, order]
    pos = mu > 0
    return 1.0 / mu[pos], V[:, pos]


# ---------------------------------------------------------------- AM filter
class AMFilter:
    """Langelaar layer-by-layer AM filter. Printed density of an element <= smooth max of the
    printed densities in its support region (the element below and its 4 in-layer neighbours
    of that lower layer: 45 deg on cubic voxels). The lowest layer of the grid is the base plate.
    Works on 3-D arrays [i, j, k]. build_axis 0/1/2, sign +1 builds toward increasing index."""

    def __init__(self, shape, build_axis=2, sign=1, P=40.0, eps=1e-4, xi0=0.5, keep=None):
        self.shape, self.ax, self.sign = shape, build_axis, sign
        self.P, self.eps = P, eps
        ns = 5
        self.Q = P + np.log(ns) / np.log(xi0)
        self.keep = None if keep is None else self._to(keep.astype(float))

    def _to(self, a):                  # global [i,j,k] -> local, build axis last and increasing
        a = np.moveaxis(a, self.ax, 2)
        return a[:, :, ::-1] if self.sign < 0 else a

    def _back(self, a):
        a = a[:, :, ::-1] if self.sign < 0 else a
        return np.moveaxis(a, 2, self.ax)

    @staticmethod
    def _stencil(a):                   # the 5 support values for every element of a layer
        p = np.pad(a, 1)
        return np.stack([p[1:-1, 1:-1], p[2:, 1:-1], p[:-2, 1:-1], p[1:-1, 2:], p[1:-1, :-2]])

    @staticmethod
    def _stencil_T(s):                 # adjoint of _stencil
        out = s[0].copy()
        p = np.zeros((s.shape[1] + 2, s.shape[2] + 2))
        p[2:, 1:-1] += s[1]; p[:-2, 1:-1] += s[2]; p[1:-1, 2:] += s[3]; p[1:-1, :-2] += s[4]
        return out + p[1:-1, 1:-1]

    def _smin(self, x, s):
        e = self.eps
        r = np.sqrt((x - s) ** 2 + e)
        return 0.5 * (x + s - r + np.sqrt(e)), 0.5 * (1 - (x - s) / r), 0.5 * (1 + (x - s) / r)

    def forward(self, x3):
        x = self._to(x3)
        nz = x.shape[2]
        xi = np.zeros_like(x)
        xi[:, :, 0] = x[:, :, 0]
        self._cache = []
        for k in range(1, nz):
            st = self._stencil(xi[:, :, k - 1])
            sp_ = (st ** self.P).sum(0)
            sig = sp_ ** (1 / self.Q)
            v, dx, ds = self._smin(x[:, :, k], sig)
            if self.keep is not None:      # frozen voxels are printed as asked (they get supports)
                kk = self.keep[:, :, k]
                v = np.where(kk > 0, x[:, :, k], v)
                dx = np.where(kk > 0, 1.0, dx)
                ds = np.where(kk > 0, 0.0, ds)
            xi[:, :, k] = v
            # d sig / d st_i = (P/Q) st_i^(P-1) sp^(1/Q-1), evaluated in logs: the naive product
            # gives inf * 0 = NaN when the support region is almost empty
            with np.errstate(divide="ignore"):
                ls = np.log(np.maximum(st, 1e-300))
                lsp = np.log(np.maximum(sp_, 1e-300))
            dsig = np.where(st > 1e-30, (self.P / self.Q) * np.exp((self.P - 1) * ls + (1 / self.Q - 1) * lsp), 0.0)
            self._cache.append((dx, ds, dsig))
        return self._back(xi)

    def backward(self, g3):
        """Given dF/d(printed), return dF/d(blueprint). Call after forward."""
        g = self._to(g3).copy()
        nz = g.shape[2]
        out = np.zeros_like(g)
        lam = g[:, :, nz - 1].copy()
        for k in range(nz - 1, 0, -1):
            dx, ds, dsig = self._cache[k - 1]
            out[:, :, k] = lam * dx
            lam = g[:, :, k - 1] + self._stencil_T((lam * ds)[None] * dsig)
        out[:, :, 0] = lam
        return self._back(out)


def unsupported_fraction(x3, build_axis=2, sign=1, thr=0.5):
    """Fraction of solid voxels (above the first layer) with no solid voxel in the 5-voxel
    support region below: the same 45 deg rule as AMFilter, measured on the 0/1 design."""
    f = AMFilter(x3.shape, build_axis, sign)
    s = f._to((x3 > thr).astype(float))
    bad = tot = 0
    for k in range(1, s.shape[2]):
        sup = f._stencil(s[:, :, k - 1]).max(0)
        lay = s[:, :, k] > 0
        bad += int((lay & (sup == 0)).sum()); tot += int(lay.sum())
    return bad / max(tot, 1)


# ---------------------------------------------------------------- impact
def equivalent_static_force(mass_kg, v_ms, k_N_per_mm):
    """Peak force of a rigid mass hitting a massless linear spring: E = F^2 / (2k)."""
    E_Nmm = 0.5 * mass_kg * v_ms ** 2 * 1000.0
    return np.sqrt(2 * E_Nmm * k_N_per_mm)
