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


CHECKS = [check_rigid_body, check_tension, check_cantilever, check_partial_volume,
          check_determinism, check_simp]


def run_all(log=print):
    passed = 0
    for fn in CHECKS:
        name, ok, detail = fn()
        passed += ok
        log(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    log(f"  GATE: {'OPEN' if passed == len(CHECKS) else 'CLOSED'} - {passed} of {len(CHECKS)} checks pass")
    return passed == len(CHECKS)
