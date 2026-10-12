"""Checks for the roadmap prototypes. Run: python research/verify.py [name ...]"""
import json
import sys
import time
import numpy as np
sys.path.insert(0, "research")
from proto import (transverse_iso_D, interlayer_factor, buckling, AMFilter, unsupported_fraction,
                   equivalent_static_force)
from anneal.fem import Grid, FEM, elasticity_D, hex8_matrices

R = {}


def rec(name, ok, **kw):
    R[name] = {"ok": bool(ok), **kw}
    print(("PASS " if ok else "FAIL ") + name, json.dumps(kw, default=float))


def t_iso_limit():
    E, nu = 1.0, 0.36
    D = transverse_iso_D(E, E, nu, nu, E / (2 * (1 + nu)))
    err = np.abs(D - elasticity_D(nu)).max()
    rec("D isotropic limit equals elasticity_D", err < 1e-12, maxErr=err)
    for d in ([1, 0, 0], [0, 1, 0], [0.3, -0.5, 0.8]):
        Dr = transverse_iso_D(E, E, nu, nu, E / (2 * (1 + nu)), d)
        rec(f"D isotropic invariant under rotation {d}", np.abs(Dr - elasticity_D(nu)).max() < 1e-12)
    Dz = transverse_iso_D(3500, 2400, 0.36, 0.30, 900)
    Dx = transverse_iso_D(3500, 2400, 0.36, 0.30, 900, [1, 0, 0])
    rec("D symmetric positive definite", np.allclose(Dz, Dz.T) and np.linalg.eigvalsh(Dz).min() > 0)
    rec("D for build +X: stiffness xx equals zz of build +Z", abs(Dx[0, 0] - Dz[2, 2]) < 1e-12,
        Dxx=Dx[0, 0], Dzz=Dz[2, 2])


def _bar_tension(D, axis, Eref, n=(4, 4, 12)):
    """Uniaxial tension of a bar along 'axis' with roller supports: returns apparent modulus."""
    shape = [4, 4, 4]
    shape[axis] = 12
    g = Grid(shape, 1.0, (0, 0, 0))
    nn = np.arange(g.nnode)
    p = g.node_coords(nn)
    L = shape[axis]
    fixed = list(3 * nn[p[:, axis] < 1e-9] + axis)
    o = nn[np.all(p < 1e-9, axis=1)][0]
    a1, a2 = [a for a in range(3) if a != axis]
    fixed += [3 * o + a1, 3 * o + a2]
    o2 = nn[(p[:, axis] < 1e-9) & (abs(p[:, a1] - 4) < 1e-9) & (p[:, a2] < 1e-9)][0]
    fixed += [3 * o2 + a2]
    fem = FEM(g, np.ones(g.nelem, bool), fixed, 0.3, D=D)
    F = np.zeros(3 * g.nnode)
    end = nn[abs(p[:, axis] - L) < 1e-9]
    w = np.ones(end.size)
    # consistent nodal loads for a uniform traction on a 4x4 face of unit quads
    on_edge = [(abs(p[end, a] - 0) < 1e-9) | (abs(p[end, a] - 4) < 1e-9) for a in (a1, a2)]
    w = np.where(on_edge[0] & on_edge[1], 0.25, np.where(on_edge[0] | on_edge[1], 0.5, 1.0))
    sigma = 10.0
    F[3 * end + axis] = sigma * 16 * w / w.sum()
    u = fem.expand(fem.solve(fem.assemble(np.full(g.nelem, Eref)), [fem.reduce_load(F)])[0])
    strain = u[3 * end + axis].mean() / L
    return sigma / strain


def t_fem_aniso():
    Ep, Ez = 3500.0, 2400.0
    D = transverse_iso_D(Ep, Ez, 0.36, 0.30, 900.0, Eref=Ep)
    Ez_fem = _bar_tension(D, 2, Ep)
    Ex_fem = _bar_tension(D, 0, Ep)
    rec("FEM bar along build axis shows Ez", abs(Ez_fem / Ez - 1) < 1e-6, Ez_fem=Ez_fem, Ez=Ez)
    rec("FEM bar in layer plane shows Ep", abs(Ex_fem / Ep - 1) < 1e-6, Ex_fem=Ex_fem, Ep=Ep)


def t_backward_compat():
    from anneal.optimize import benchmark_cantilever
    t = time.time()
    r = benchmark_cantilever()
    base = 91.59699612657158
    rec("Cantilever benchmark unchanged by the hooks (AM off, D None)", abs(r["stiffer_pct"] - base) < 1e-9,
        stiffer=r["stiffer_pct"], baseline=base, seconds=time.time() - t)
    ke0, _, _ = hex8_matrices(0.3, 1.0)
    ke1, _, _ = hex8_matrices(0.3, 1.0, elasticity_D(0.3))
    rec("hex8 with explicit isotropic D is bit-identical", np.array_equal(ke0, ke1))


def t_kuznetsov():
    rows = [(0.8, .15, 70.7), (0.8, .2, 66.8), (0.8, .4, 48.1), (0.8, .6, 31.3), (0.6, .1, 68.0), (0.6, .15, 62.7),
            (0.6, .2, 60.4), (0.6, .25, 52.6), (0.6, .3, 50.5), (0.6, .35, 49.9), (0.6, .4, 39.6), (0.6, .45, 26.0),
            (0.6, .5, 20.2), (0.6, .6, 18.2), (0.4, .06, 67.8), (0.4, .1, 59.9), (0.4, .2, 50.8), (0.4, .3, 38.5),
            (0.4, .35, 25.6), (0.4, .4, 17.5)]
    r = np.array([n / l for n, l, _ in rows]); y = np.array([u for *_, u in rows])
    pred = 70.7 * interlayer_factor(r)
    res = y - pred
    ss = 1 - (res ** 2).sum() / ((y - y.mean()) ** 2).sum()
    # free fit of a in a - 58.19/r^1.5, and a free (a, b)
    a_fit = float(np.mean(y + 58.19 / r ** 1.5))
    A = np.stack([np.ones_like(r), -1 / r ** 1.5], 1)
    ab = np.linalg.lstsq(A, y, rcond=None)[0]
    rec("Kuznetsov fit reproduces Table 1 trend (R2 > 0.9)", ss > 0.9, R2_with_UFSmax_70p7=ss,
        a_bestfit_with_58p19=a_fit, free_fit_a_b=ab.tolist(),
        worst_abs_err_MPa=float(np.abs(res).max()), worst_at_r=float(r[np.argmax(np.abs(res))]),
        pred_r1=float(70.7 * interlayer_factor(1.0)))


def t_buckling():
    E = 1000.0
    out = {}
    for h, a in ((1.0, 4), (0.5, 8)):
        n = int(4 / h)
        L = 60.0
        g = Grid((n, n, int(L / h)), h, (0, 0, 0))
        nn = np.arange(g.nnode); p = g.node_coords(nn)
        base = nn[p[:, 2] < 1e-9]
        fixed = (3 * base[:, None] + np.arange(3)).ravel()
        fem = FEM(g, np.ones(g.nelem, bool), fixed, 0.3)
        top = nn[abs(p[:, 2] - L) < 1e-9]
        F = np.zeros(3 * g.nnode); F[3 * top + 2] = -1.0 / top.size
        Ee = np.full(g.nelem, E)
        t = time.time()
        u = fem.solve(fem.assemble(Ee), [fem.reduce_load(F)])[0]
        lam, _ = buckling(fem, Ee, u, n_modes=4)
        I = 4 ** 4 / 12
        Pcr = np.pi ** 2 * E * I / (4 * L ** 2)
        out[h] = (lam[0], Pcr, time.time() - t)
        rec(f"Euler cantilever column, h={h} ({n} voxels across)", abs(lam[0] / Pcr - 1) < 0.05,
            BLF=lam[0], euler=Pcr, ratio=lam[0] / Pcr, modes=lam[:4].tolist(), seconds=time.time() - t)


def t_am_gradient():
    rng = np.random.default_rng(1)
    for ax, sg in ((2, 1), (0, -1)):
        f = AMFilter((7, 6, 8), ax, sg)
        x = rng.uniform(0.05, 1, (7, 6, 8))
        x[rng.uniform(size=x.shape) < 0.3] = 1e-9          # near-void voxels: the NaN trap
        w = rng.normal(size=x.shape)
        F = lambda x: (f.forward(x) * w).sum()
        F(x); g = f.backward(w)
        err = 0
        for _ in range(12):
            idx = tuple(rng.integers(0, s) for s in x.shape)
            e = np.zeros_like(x); e[idx] = 1e-6
            fd = (F(x + e) - F(x - e)) / 2e-6
            err = max(err, abs(fd - g[idx]) / max(abs(fd), 1e-8))
        rec(f"AM filter adjoint matches finite differences (axis {ax}, sign {sg})", err < 1e-4, maxRelErr=err)
    # a floating block is removed, a block on the plate is kept
    x = np.zeros((10, 10, 10)); x[2:5, 2:5, 0:4] = 1; x[6:9, 6:9, 5:8] = 1
    y = AMFilter(x.shape).forward(x)
    rec("AM filter keeps supported, removes floating material",
        y[2:5, 2:5, 0:4].min() > 0.95 and y[6:9, 6:9, 5:8].max() < 0.05,
        supportedMin=y[2:5, 2:5, 0:4].min(), floatingMax=y[6:9, 6:9, 5:8].max())


def t_am_simp():
    """Cantilever 48x8x24 (z up), clamp at x=0, tip load mid-height: SIMP with and without AM filter."""
    from anneal.optimize import simp, EMIN
    g = Grid((48, 8, 24), 1.0, (0, 0, 0))
    nn = np.arange(g.nnode); p = g.node_coords(nn)
    clamp = nn[p[:, 0] < 1e-9]
    fixed = (3 * clamp[:, None] + np.arange(3)).ravel()
    tip = nn[(abs(p[:, 0] - 48) < 1e-9) & (abs(p[:, 2] - 12) < 1e-9)]
    F = np.zeros(3 * g.nnode); F[3 * tip + 2] = -1.0 / tip.size
    fill = np.ones(g.nelem); act = np.ones(g.nelem, bool); frz = np.zeros(g.nelem, bool)
    res = {}
    import os
    for name, am in (("plain", None), ("am+z", AMFilter(g.shape, 2, 1))):
        t = time.time()
        if os.path.exists(f"research/out_{name}.npy"):
            r = {"x": np.load(f"research/out_{name}.npy"), "history": [None]}
        else:
          r = simp(g, fill, act, frz, fixed, {"c": F}, {"c": 1.0}, 1000.0, 0.3, 0.25, iters=60, r_mm=1.6,
                 log=print, am=am)
        fem = FEM(g, act, fixed, 0.3); Fr = fem.reduce_load(F)
        xb = (r["x"] > 0.5).astype(float)
        u = fem.solve(fem.assemble(1000.0 * (EMIN + xb * (1 - EMIN))), [Fr])[0]
        res[name] = {"compliance01": float(Fr @ u), "vol01": float(xb.mean()),
                     "unsupported": unsupported_fraction(g.to3d(r["x"])), "seconds": time.time() - t,
                     "iters": len(r["history"])}
        np.save(f"research/out_{name}.npy", r["x"])
    a, b = res["plain"], res["am+z"]
    rec("AM filter in SIMP cuts unsupported voxels", b["unsupported"] < 0.25 * max(a["unsupported"], 1e-9) or b["unsupported"] < 0.01,
        **{k + "_plain": v for k, v in a.items()}, **{k + "_am": v for k, v in b.items()},
        stiffnessCostPct=100 * (b["compliance01"] / b["vol01"] * 0 + b["compliance01"] / a["compliance01"] - 1))


def t_impact():
    # rigid mass on a linear spring, integrated explicitly, vs closed form
    m, v, k = 2.0, 3.0, 500.0          # kg, m/s, N/mm
    F = equivalent_static_force(m, v, k)
    kk = k * 1000.0                     # N/m
    x, vv, dt, fmax = 0.0, v, 1e-7, 0.0
    while vv > 0:
        a = -kk * x / m; vv += a * dt; x += vv * dt; fmax = max(fmax, kk * x)
    rec("Equivalent static impact force equals mass-spring peak", abs(fmax / F - 1) < 1e-3, F_closed=F, F_ode=fmax)


TESTS = {k[2:]: v for k, v in globals().items() if k.startswith("t_")}
if __name__ == "__main__":
    names = sys.argv[1:] or list(TESTS)
    for n in names:
        TESTS[n]()
    json.dump(R, open(f"research/results_{'_'.join(names) if sys.argv[1:] else 'all'}.json", "w"), indent=1, default=float)
