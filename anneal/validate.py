"""Solver validation gate. Run with:  python -m anneal validate

Each check compares the solver with a closed-form answer. The gate passes only if all
checks pass. Re-run it after any change to fem.py or optimize.py.
"""
import hashlib
import numpy as np
from .fem import Grid, FEM, hex8_matrices

E0, NU = 1000.0, 0.3


def _face_load(grid, elems_on_face, weights, total, comp, face_local_nodes):
    """Distribute 'total' force over the face of each listed element in proportion to weights."""
    F = np.zeros(3 * grid.nnode)
    en = grid.element_nodes(elems_on_face)
    share = total * weights / weights.sum()
    for k in face_local_nodes:
        np.add.at(F, 3 * en[:, k] + comp, share / 4.0)
    return F


def _bar(nx, ny, nz, h, fill=None):
    g = Grid((nx, ny, nz), h, (0, 0, 0))
    e = np.arange(g.nelem)
    i, j, k = g.elem_ijk(e)
    if fill is None:
        fill = np.ones(g.nelem)
    return g, e, i, j, k, fill


def _nodes_where(grid, fn):
    n = np.arange(grid.nnode)
    p = grid.node_coords(n)
    return n[fn(p)]


def check_rigid_body():
    ke, _, _ = hex8_matrices(NU, 1.0)
    xyz = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                    [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
    t = np.tile([1.0, 0, 0], 8)
    r = np.stack([-xyz[:, 1], xyz[:, 0], np.zeros(8)], axis=1).ravel()
    et, er = float(t @ ke @ t), float(r @ ke @ r)
    return "V1 rigid body stores no energy", max(abs(et), abs(er)) < 1e-10, f"translation {et:.2e}, rotation {er:.2e}"


def _tension(fill_layer=None, nz=4, L=10, ny=2, h=1.0, F=100.0):
    g, e, i, j, k, fill = _bar(L, ny, nz, h)
    if fill_layer is not None:
        fill = np.where(k == nz - 1, fill_layer, 1.0)
    fixed = []
    for n in _nodes_where(g, lambda p: p[:, 0] < 1e-9):
        fixed.append(3 * n)
    n0 = _nodes_where(g, lambda p: (p[:, 0] < 1e-9) & (p[:, 1] < 1e-9) & (p[:, 2] < 1e-9))[0]
    n1 = _nodes_where(g, lambda p: (p[:, 0] < 1e-9) & (abs(p[:, 1] - ny * h) < 1e-9) & (p[:, 2] < 1e-9))[0]
    fixed += [3 * n0 + 1, 3 * n0 + 2, 3 * n1 + 2]
    fem = FEM(g, np.ones(g.nelem, bool), fixed, NU)
    end = e[i == L - 1]
    Fg = _face_load(g, end, fill[end], F, 0, [1, 2, 5, 6])
    K = fem.assemble(E0 * fill)
    u = fem.expand(fem.solve(K, [fem.reduce_load(Fg)], rtol=1e-12)[0])
    tip = _nodes_where(g, lambda p: abs(p[:, 0] - L * h) < 1e-9)
    return u[3 * tip].mean(), g


def check_tension():
    ux, g = _tension()
    A = 2 * 4 * 1.0
    exact = 100.0 * 10 / (A * E0)
    err = abs(ux - exact) / exact
    return "V2 uniform tension = FL/(AE)", err < 1e-8, f"relative error {err:.2e}"


def check_cantilever():
    res, ok = [], True
    want = {2: (0.84, 0.90), 4: (0.93, 0.98), 8: (0.97, 0.995)}
    for nd in (2, 4, 8):
        d, b, L, P = 4.0, 4.0, 40.0, 10.0
        h = d / nd
        g, e, i, j, k, fill = _bar(10 * nd, nd, nd, h)
        clamp = _nodes_where(g, lambda p: p[:, 0] < 1e-9)
        fixed = (3 * clamp[:, None] + np.arange(3)).ravel()
        fem = FEM(g, np.ones(g.nelem, bool), fixed, NU)
        end = e[i == g.nx - 1]
        Fg = _face_load(g, end, np.ones(end.size), -P, 2, [1, 2, 5, 6])
        K = fem.assemble(E0 * fill)
        u = fem.expand(fem.solve(K, [fem.reduce_load(Fg)], rtol=1e-12)[0])
        tip = _nodes_where(g, lambda p: abs(p[:, 0] - L) < 1e-9)
        uz = -u[3 * tip + 2].mean()
        I = b * d ** 3 / 12
        G = E0 / (2 * (1 + NU))
        timo = P * L ** 3 / (3 * E0 * I) + P * L / (5 / 6 * G * b * d)
        r = uz / timo
        lo, hi = want[nd]
        ok &= lo <= r <= hi
        res.append(f"{nd} deep {100 * r:.1f}%")
    return "V3 cantilever vs Timoshenko (shear locking expected)", ok, " · ".join(res)


def check_partial_volume():
    ux_partial, _ = _tension(fill_layer=0.4, nz=7)
    ux_binary, _ = _tension(fill_layer=None, nz=6)
    exact = 100.0 * 10 / (2 * 6.4 * E0)
    ep = abs(ux_partial - exact) / exact
    eb = abs(ux_binary - exact) / exact
    return "V4 partial volume beats binary (bar 6.4 cells deep)", ep < 1e-8 and eb > 0.05, \
        f"binary {100 * eb:.2f}% error, partial {ep:.1e}"


def check_determinism():
    hashes = []
    for _ in range(2):
        g, e, i, j, k, fill = _bar(20, 4, 4, 1.0)
        clamp = _nodes_where(g, lambda p: p[:, 0] < 1e-9)
        fem = FEM(g, np.ones(g.nelem, bool), (3 * clamp[:, None] + np.arange(3)).ravel(), NU)
        end = e[i == g.nx - 1]
        Fg = _face_load(g, end, np.ones(end.size), -1.0, 2, [1, 2, 5, 6])
        u = fem.solve(fem.assemble(E0 * fill), [fem.reduce_load(Fg)])[0]
        hashes.append(hashlib.sha256(u.tobytes()).hexdigest())
    return "V5 deterministic reruns", hashes[0] == hashes[1], f"sha256 {hashes[0][:12]}…"


def check_simp():
    from .optimize import benchmark_cantilever
    r = benchmark_cantilever()
    ok = r["stiffer_pct"] > 20 and abs(r["vol_err"]) < 1e-3
    return "V6 SIMP beats uniform at equal mass", ok, \
        f"{r['stiffer_pct']:.1f}% stiffer, volume error {r['vol_err']:.1e}"


def check_buckling():
    """Clamped column 4 x 4 x 60 voxels under axial load vs Euler; the locking-corrected factor
    must be conservative (not above theory) and within 3 %."""
    from .physics import buckling
    from .run import locking_factor
    L, a = 60, 4
    g = Grid((a, a, L), 1.0, (0, 0, 0))
    base = _nodes_where(g, lambda p: p[:, 2] < 1e-9)
    top = _nodes_where(g, lambda p: abs(p[:, 2] - L) < 1e-9)
    fem = FEM(g, np.ones(g.nelem, bool), (3 * base[:, None] + np.arange(3)).ravel(), NU)
    F = np.zeros(3 * g.nnode)
    F[3 * top + 2] = -1.0 / top.size
    Ee = np.full(g.nelem, E0)
    K = fem.assemble(Ee)
    u = fem.solve(K, [fem.reduce_load(F)])[0]
    lam, _ = buckling(fem, K, u, Ee)
    euler = np.pi ** 2 * E0 * (a ** 4 / 12) / (4 * L ** 2)
    corr = lam[0] * locking_factor(a)
    ok = -0.03 <= corr / euler - 1 <= 0.0
    return "V7 buckling vs Euler (column 4 voxels across)", ok, \
        f"raw {100 * (lam[0] / euler - 1):+.2f}%, corrected {100 * (corr / euler - 1):+.2f}%"


def check_anisotropic():
    """Print-aware stiffness: bars along and across the layers show Ez and E exactly; with equal
    strengths the Hill index equals von Mises / yield."""
    from .physics import transverse_iso_D, hill_index
    E, Ez = 3500.0, 2400.0
    errs = []
    for axis in (0, 2):
        D = transverse_iso_D(E, Ez, 0.36, 0.30, 900.0, (0, 0, 1))
        shape = [4, 4, 4]
        shape[axis] = 12
        g = Grid(shape, 1.0, (0, 0, 0))
        nn = np.arange(g.nnode)
        p = g.node_coords(nn)
        a1, a2 = [k for k in range(3) if k != axis]
        fixed = list(3 * nn[p[:, axis] < 1e-9] + axis)
        o = nn[np.all(p < 1e-9, axis=1)][0]
        o2 = nn[(p[:, axis] < 1e-9) & (abs(p[:, a1] - 4) < 1e-9) & (p[:, a2] < 1e-9)][0]
        fixed += [3 * o + a1, 3 * o + a2, 3 * o2 + a2]
        fem = FEM(g, np.ones(g.nelem, bool), fixed, 0.36, D=D)
        end = nn[abs(p[:, axis] - 12) < 1e-9]
        edge = [(abs(p[end, b]) < 1e-9) | (abs(p[end, b] - 4) < 1e-9) for b in (a1, a2)]
        w = np.where(edge[0] & edge[1], 0.25, np.where(edge[0] | edge[1], 0.5, 1.0))
        F = np.zeros(3 * g.nnode)
        F[3 * end + axis] = 10.0 * 16 * w / w.sum()
        u = fem.expand(fem.solve(fem.assemble(np.full(g.nelem, E)), [fem.reduce_load(F)], rtol=1e-12)[0])
        app = 10.0 / (u[3 * end + axis].mean() / 12)
        errs.append(abs(app / (Ez if axis == 2 else E) - 1))
    rng = np.random.default_rng(0)
    sig = rng.normal(size=(50, 6)) * 20
    vm = np.sqrt(0.5 * ((sig[:, 0] - sig[:, 1]) ** 2 + (sig[:, 1] - sig[:, 2]) ** 2 + (sig[:, 2] - sig[:, 0]) ** 2)
                 + 3 * (sig[:, 3] ** 2 + sig[:, 4] ** 2 + sig[:, 5] ** 2))
    herr = float(np.abs(hill_index(sig, 50.0, 50.0, (0.3, -0.5, 0.8)) - vm / 50.0).max())
    ok = max(errs) < 1e-8 and herr < 1e-12
    return "V8 print-aware stiffness and Hill strength", ok, \
        f"E error {max(errs):.1e}, Hill vs von Mises {herr:.1e}"


def check_impact():
    """Equivalent-static impact on a bar, 40 long, 10 x 10, E 1000, nu 0, held at one end and hit
    end-on at the other: k must equal EA/L and the peak force sqrt(2 E k). The anchor regions sit
    just outside the bar so each takes exactly one layer of nodes (anchors take nodes within half a
    voxel of their region)."""
    from .problem import Problem
    from .run import impact_check
    spec = {"name": "v9", "designSpace": {"type": "box", "min": [0, 0, 0], "max": [40, 10, 10]},
            "material": {"E": E0, "nu": 0.0, "density": 1.0, "yield": 100.0}, "resolution": {"voxelMM": 1.0},
            "anchors": [{"name": "wall", "role": "fixed", "dofs": "x",
                         "region": {"type": "box", "min": [-2, -1, -1], "max": [-0.4, 11, 11]}},
                        {"name": "end", "role": "load", "region": {"type": "box", "min": [40.4, -1, -1], "max": [42, 11, 11]},
                         "loads": {"axial": [-1, 0, 0]}}],
            "impact": {"hit": {"anchor": "end", "massKg": 2.0, "speedMS": 1.0, "direction": [-1, 0, 0]}}}
    p = Problem(spec=spec, log=lambda *a: None).build()
    fill = np.where(p.active, 1.0, 0.0)
    r = impact_check(p, fill, 1.0, lambda *a: None)["hit"]
    k_exact = E0 * 100.0 / 40.0
    F_exact = np.sqrt(2 * 1000.0 * k_exact)            # E = 0.5 * 2 kg * (1 m/s)^2 = 1 J = 1000 N mm
    ek = r["stiffnessNperMM"] / k_exact - 1
    ef = r["peakForceN"] / F_exact - 1
    # The hit is spread as equal forces on the region's nodes (as Anneal spreads every load). The
    # corner and edge nodes then move a little more than under a uniform pressure, so k comes out
    # about 1 % low and the force about 0.5 % low. Allowed: 2 % on k, 1 % on the force.
    ok = abs(ek) < 0.02 and abs(ef) < 0.01
    return "V9 impact force on a bar = sqrt(2 E k), k = EA/L", ok, \
        f"stiffness {100 * ek:+.2f}%, force {100 * ef:+.2f}% (limits 2 % and 1 %)"


CHECKS = [check_rigid_body, check_tension, check_cantilever, check_partial_volume,
          check_determinism, check_simp, check_buckling, check_anisotropic, check_impact]


def run_all(log=print):
    passed = 0
    for fn in CHECKS:
        name, ok, detail = fn()
        passed += ok
        log(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    log(f"  GATE: {'OPEN' if passed == len(CHECKS) else 'CLOSED'} - {passed} of {len(CHECKS)} checks pass")
    return passed == len(CHECKS)
