"""Optional physics for Anneal 0.4: print-aware (anisotropic) material, Hill strength, buckling.

All of it is off unless the spec asks for it, so runs without these options are unchanged.

Print-aware material
    A printed part is transversely isotropic: one stiffness in the layer plane (E, nu from the
    material) and another along the build direction (Ez, nuZ, Gz). transverse_iso_D builds the
    6x6 stiffness in Anneal's Voigt order (xx yy zz xy yz zx, engineering shear), rotated so the
    material axis is the build direction, and normalised by E so the FEM can still scale it by
    E x density per voxel.

Hill strength (Hill 1948, the anisotropic form of von Mises)
    In-plane strength X = yield; strength across layers Z = yield x zStrengthFactor.
    Assumed shear strengths: X / sqrt(3) in the layer plane, Z / sqrt(3) across layers.
    With Z = X the criterion is exactly von Mises / yield (tested).

Linear buckling
    K_sigma from the element-centre stress, then (K + lambda K_sigma) phi = 0 solved for the smallest
    positive lambda (the buckling load factor) with eigsh in generalized mode, K^-1 applied by
    AMG-preconditioned CG. Voxel models are too stiff in bending (shear locking), which makes the
    factor too high (+3.5 % at 4 voxels across a column, +0.8 % at 8); run.py multiplies it by the
    locking factor from check V3, which makes both cases conservative (check V7).
"""
import numpy as np
import scipy.sparse.linalg as sla
from .fem import _dN

VOIGT = [(0, 0), (1, 1), (2, 2), (0, 1), (1, 2), (2, 0)]


class PhysicsError(ValueError):
    pass


# ------------------------------------------------------------------ material
def _to_tensor(D):
    C = np.zeros((3, 3, 3, 3))
    for I, (i, j) in enumerate(VOIGT):
        for J, (k, l) in enumerate(VOIGT):
            for a, b in ((i, j), (j, i)):
                for c, d in ((k, l), (l, k)):
                    C[a, b, c, d] = D[I, J]
    return C


def _to_voigt(C):
    D = np.zeros((6, 6))
    for I, (i, j) in enumerate(VOIGT):
        for J, (k, l) in enumerate(VOIGT):
            D[I, J] = C[i, j, k, l]
    return D


def frame(d):
    """Rotation whose third column is the unit vector d."""
    d = np.asarray(d, float)
    d = d / np.linalg.norm(d)
    a = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(a, d)
    x /= np.linalg.norm(x)
    return np.stack([x, np.cross(d, x), d], axis=1)


def transverse_iso_D(E, Ez, nu, nuZ, Gz, build_dir=(0, 0, 1)):
    """Normalised (by E) stiffness of a material with layers normal to build_dir."""
    S = np.zeros((6, 6))
    S[0, 0] = S[1, 1] = 1 / E
    S[2, 2] = 1 / Ez
    S[0, 1] = S[1, 0] = -nu / E
    S[0, 2] = S[2, 0] = S[1, 2] = S[2, 1] = -nuZ / Ez
    S[3, 3] = 2 * (1 + nu) / E
    S[4, 4] = S[5, 5] = 1 / Gz
    if np.linalg.eigvalsh(S).min() <= 0:
        raise PhysicsError("The print-aware material is not physically possible (its stiffness matrix is not "
                           "positive definite). Check Ez, nuZ and Gz; nuZ is usually 0.2 to 0.4.")
    R = frame(build_dir)
    C = np.einsum("ia,jb,kc,ld,abcd->ijkl", R, R, R, R, _to_tensor(np.linalg.inv(S)))
    return _to_voigt(C) / E


def material_D(material, process):
    """(D, info) for a print-aware run, from material keys Ez (required), nuZ and Gz (optional)."""
    if not process or not process.get("buildDirection"):
        raise PhysicsError("physics.anisotropic needs a process with a build direction. Set \"process\": \"FDM\" "
                           "(or another process) in the spec.")
    if "Ez" not in material:
        raise PhysicsError(f"physics.anisotropic needs the material's stiffness across the layers. Add \"Ez\" "
                           f"(MPa) to material '{material.get('name', '')}', from a test or the filament data sheet "
                           f"(Z-direction tensile modulus).")
    E, nu, Ez = float(material["E"]), float(material["nu"]), float(material["Ez"])
    nuZ = float(material.get("nuZ", nu))
    Gz = float(material.get("Gz", Ez / (2 * (1 + nuZ))))
    assumed = [k for k in ("nuZ", "Gz") if k not in material]
    D = transverse_iso_D(E, Ez, nu, nuZ, Gz, process["buildDirection"])
    return D, {"E": E, "Ez": Ez, "nu": nu, "nuZ": nuZ, "Gz": Gz, "assumed": assumed,
               "buildDirection": list(map(float, process["buildDirection"]))}


# ------------------------------------------------------------------ temperature
def thermal_strain(alpha, alpha_z=None, build_dir=None):
    """Thermal strain per kelvin in the global Voigt order (xx yy zz xy yz zx, engineering shear).
    Isotropic: [a, a, a, 0, 0, 0]. With alpha_z and a build direction (print-aware runs): diag(a, a, a_z)
    in the layer frame, rotated like D (physics.frame)."""
    a = float(alpha)
    if alpha_z is None or build_dir is None or float(alpha_z) == a:
        return np.array([a, a, a, 0.0, 0.0, 0.0])
    R = frame(build_dir)
    M = R @ np.diag([a, a, float(alpha_z)]) @ R.T
    return np.array([M[0, 0], M[1, 1], M[2, 2], 2 * M[0, 1], 2 * M[1, 2], 2 * M[2, 0]])


# ------------------------------------------------------------------ strength
def hill_index(sig, X, Z, build_dir):
    """Hill failure index sqrt(f) per element (failure at 1). sig: (n, 6) global Voigt stress."""
    R = frame(build_dir)
    s = np.zeros((sig.shape[0], 3, 3))
    for c, (i, j) in enumerate(VOIGT):
        s[:, i, j] = sig[:, c]
        s[:, j, i] = sig[:, c]
    sl = np.einsum("ai,nab,bj->nij", R, s, R)        # stress in the layer frame (3 = build axis)
    F = G = 1 / (2 * Z ** 2)
    H = 1 / X ** 2 - 1 / (2 * Z ** 2)
    L = M = 3 / (2 * Z ** 2)                          # interlayer shear strength Z / sqrt(3)
    N = 3 / (2 * X ** 2)                              # in-plane shear strength X / sqrt(3)
    s11, s22, s33 = sl[:, 0, 0], sl[:, 1, 1], sl[:, 2, 2]
    f = (F * (s22 - s33) ** 2 + G * (s33 - s11) ** 2 + H * (s11 - s22) ** 2
         + 2 * L * sl[:, 1, 2] ** 2 + 2 * M * sl[:, 0, 2] ** 2 + 2 * N * sl[:, 0, 1] ** 2)
    return np.sqrt(np.maximum(f, 0.0))


# ------------------------------------------------------------------ buckling
def stress_stiffness_parts(h):
    """Six 24x24 matrices M_c with element K_sigma = sum_c sigma_c M_c (constant element stress)."""
    g = 1 / np.sqrt(3)
    jac = h / 2
    G = [np.zeros((8, 8)) for _ in range(6)]
    for xi in (-g, g):
        for eta in (-g, g):
            for zeta in (-g, g):
                d = _dN(xi, eta, zeta) / jac
                w = jac ** 3
                for c, (i, j) in enumerate(VOIGT):
                    if i == j:
                        G[c] += w * np.outer(d[:, i], d[:, i])
                    else:
                        G[c] += w * (np.outer(d[:, i], d[:, j]) + np.outer(d[:, j], d[:, i]))
    return [np.kron(m, np.eye(3)) for m in G]


def buckling(fem, K, u_red, E_scale, n_modes=4, tol=1e-6):
    """Buckling load factors (ascending, positive only) and modes for the load that gave u_red.
    E_scale: per-element modulus scale used for the stress (as in fem.stress)."""
    sig = fem.stress(fem.expand(u_red), E_scale)
    parts = stress_stiffness_parts(fem.grid.h)
    Ks = sum(fem.assemble_matrix(parts[c], sig[:, c]) for c in range(6))
    if fem.M is None:
        fem.solve(K, [np.zeros(fem.nfree)], rebuild=True)
    M = fem.M

    def kinv(b):
        x, _ = sla.cg(K, b, rtol=1e-10, maxiter=5000, M=M) if _has_rtol() else sla.cg(K, b, tol=1e-10, maxiter=5000, M=M)
        return x
    Kinv = sla.LinearOperator(K.shape, matvec=kinv, dtype=float)
    k = min(n_modes, fem.nfree - 2)
    state = np.random.get_state()
    np.random.seed(20261012)                       # deterministic start vector
    v0 = np.random.rand(fem.nfree)
    np.random.set_state(state)
    mu, V = sla.eigsh(-Ks, k=k, M=K, Minv=Kinv, which="LA", tol=tol, v0=v0)
    order = np.argsort(-mu)
    mu, V = mu[order], V[:, order]
    pos = mu > 1e-12
    return 1.0 / mu[pos], V[:, pos]


def _has_rtol():
    import inspect
    return "rtol" in inspect.signature(sla.cg).parameters


# ------------------------------------------------------------------ impact (equivalent static)
G_MS2 = 9.80665


def impact_energy(case, where="impact"):
    """Kinetic energy (N mm) and speed (m/s) of an impact case: massKg with speedMS or dropHeightMM."""
    try:
        m = float(case["massKg"])
    except (KeyError, TypeError, ValueError):
        raise PhysicsError(f"{where}: give massKg, the mass that hits the part (kg).") from None
    if m <= 0:
        raise PhysicsError(f"{where}: massKg must be more than 0.")
    if ("speedMS" in case) == ("dropHeightMM" in case):
        raise PhysicsError(f"{where}: give either speedMS (impact speed, m/s) or dropHeightMM (free-fall height, mm), "
                           f"not both and not neither.")
    if "speedMS" in case:
        v = float(case["speedMS"])
    else:
        v = float(np.sqrt(2 * G_MS2 * float(case["dropHeightMM"]) / 1000.0))
    if v <= 0:
        raise PhysicsError(f"{where}: the impact speed must be more than 0.")
    return 0.5 * m * v * v * 1000.0, v


def impact_peak_force(energy_Nmm, k_N_per_mm):
    """Peak force when a rigid mass is stopped by a linear spring of stiffness k: E = F^2 / (2k)."""
    return float(np.sqrt(2.0 * energy_Nmm * k_N_per_mm))
