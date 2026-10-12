"""SIMP topology optimization on the voxel grid.

- Density design variable per voxel, frozen voxels held at 1.
- Stiffness: E = E0 * fill * (Emin + x^p (1 - Emin)); fill uses penalty 1 (V6).
- Linear hat density filter with radius from the minimum member size (sets member width).
- Penalty continuation 1 -> p (without it SIMP stalls grey in a local minimum).
- Optimality Criteria update (single volume constraint; no GPL MMA code).
- Several load cases: weighted sum of compliances, or a p-norm of normalized
  compliances ('worst') that tracks the worst case smoothly.
- Multigrid reuse: the AMG hierarchy is rebuilt only when CG iterations grow past
  1.6 x the count right after the last rebuild (adaptive answer to "rebuild every N").
"""
import time
import numpy as np
from scipy import ndimage
from .fem import FEM

EMIN = 1e-6
PNORM = 8.0
ETA = 0.5          # Heaviside projection threshold
BETA_MAX = 4.0     # final projection sharpness (moderate: keeps OC stable on short budgets)


class Filter:
    def __init__(self, grid, active, r_vox):
        self.g = grid
        self.active3 = grid.to3d(active).astype(float)
        R = max(int(np.ceil(r_vox)) - 1, 1)
        ax = np.arange(-R, R + 1)
        X, Y, Z = np.meshgrid(ax, ax, ax, indexing="ij")
        self.k = np.maximum(0.0, r_vox - np.sqrt(X ** 2 + Y ** 2 + Z ** 2))
        self.Hs = ndimage.convolve(self.active3, self.k, mode="constant")
        self.Hs[self.Hs == 0] = 1.0
        self.act = np.flatnonzero(active)

    def _full(self, v_act):
        f = np.zeros(self.g.nelem)
        f[self.act] = v_act
        return self.g.to3d(f)

    def forward(self, x_act):
        y = ndimage.convolve(self._full(x_act) * self.active3, self.k, mode="constant") / self.Hs
        return self.g.to1d(y)[self.act]

    def backward(self, d_act):
        y = ndimage.convolve(self._full(d_act) / self.Hs, self.k, mode="constant") * self.active3
        return self.g.to1d(y)[self.act]


def simp(grid, fill, active, frozen, fixed, loads, weights, E0, nu, vf,
         iters=80, r_mm=None, p_final=3.0, move=0.2, combine="sum", log=print, tol=0.01, x0=None):
    t_start = time.time()
    fem = FEM(grid, active, fixed, nu, log=log)
    act = fem.act
    phi = fill[act]
    frz = frozen[act]
    des = ~frz
    h = grid.h
    r_vox = max((r_mm or 1.5 * h) / h, 1.5)
    filt = Filter(grid, active, r_vox)
    cases = list(loads)
    Fr = [fem.reduce_load(loads[c]) for c in cases]
    w = np.array([weights[c] for c in cases])
    if all(np.allclose(f, 0) for f in Fr):
        raise ValueError("All loads are zero after mapping onto the grid. Check the load anchors' regions.")

    Vtot = phi.sum()
    Vtarget = vf * Vtot
    Vfrozen = phi[frz].sum()
    x = np.ones(act.size)
    x[des] = np.clip((Vtarget - Vfrozen) / max(phi[des].sum(), 1e-12), 0.01, 1.0)
    warm = x0 is not None
    if warm:  # restart from a previous design, rescaled toward the new volume target
        xs = np.clip(x0[act], 0.0, 1.0)
        cur = (phi[des] * xs[des]).sum()
        if cur > 0:
            x[des] = np.clip(xs[des] * (Vtarget - Vfrozen) / cur, 0.001, 1.0)

    beta = [0.0]   # 0 = no projection; set > 0 once the penalty is at full strength

    def project(xt):
        b = beta[0]
        if b <= 0:
            return xt, np.ones_like(xt)
        t0, t1 = np.tanh(b * ETA), np.tanh(b * (1 - ETA))
        th = np.tanh(b * (xt - ETA))
        return (t0 + th) / (t0 + t1), b * (1 - th ** 2) / (t0 + t1)

    def physical(xd, with_grad=False):
        xt = filt.forward(xd)
        xp, dxp = project(xt)
        xp[frz] = 1.0
        return (xp, dxp) if with_grad else xp

    hist = []
    U = [None] * len(cases)
    c0 = None
    base_iters = None
    p = 1.0
    if warm:
        beta[0] = BETA_MAX / 2
    xPhys = physical(x)
    beta_step = max(5, int(0.12 * iters))
    beta_since = 0
    for it in range(1, iters + 1):
        t0 = time.time()
        # continuation: hold each penalty step for a few iterations
        # continuation: 0.25 steps, held long enough to reach p_final within 40 % of the budget
        hold = max(1, min(3, int(0.4 * iters / max((p_final - 1.0) / 0.25, 1))))
        p = p_final if warm else min(p_final, 1.0 + 0.25 * ((it - 1) // hold))
        if p >= p_final and not warm:     # projection continuation after the penalty ramp
            if beta[0] == 0:
                beta[0], beta_since = 1.0, 0
            elif beta_since >= beta_step and beta[0] < BETA_MAX:
                beta[0], beta_since = min(BETA_MAX, 2 * beta[0]), 0
            beta_since += 1
        xPhys, dxp = physical(x, with_grad=True)
        Ee = E0 * phi * (EMIN + xPhys ** p * (1 - EMIN))
        K = fem.assemble(Ee)
        last = fem.cg_iters[-1] if fem.cg_iters else None
        rebuild = base_iters is None or (last is not None and last > 1.6 * base_iters)
        U = fem.solve(K, Fr, x0_list=None if U[0] is None else U, rebuild=rebuild, rtol=1e-6)
        if rebuild:
            base_iters = fem.cg_iters[-1]
        cs = np.array([f @ u for f, u in zip(Fr, U)])
        dce = []
        for u in U:
            ce = fem.element_energy(fem.expand(u))
            dce.append(-p * xPhys ** (p - 1) * (1 - EMIN) * E0 * phi * ce)
        if c0 is None:
            c0 = cs.copy()
        if combine == "sum" or len(cases) == 1:
            obj = float(w @ cs)
            dc = sum(wi * d for wi, d in zip(w, dce))
        else:
            r = w * cs / c0
            obj = float((r ** PNORM).sum() ** (1 / PNORM))
            coef = (r / obj) ** (PNORM - 1) * w / c0
            dc = sum(ci * d for ci, d in zip(coef, dce))
        dc = np.minimum(dc, 0.0)
        dcx = filt.backward(dc * dxp)
        dvx = filt.backward(phi * dxp)

        # OC: geometric bisection on the multiplier, bracketed around the sensitivity scale
        scale = max(float(np.mean(-dcx[des]) / max(np.mean(dvx[des]), 1e-30)), 1e-300) if des.any() else 1.0
        lo, hi = scale * 1e-8, scale * 1e8
        xd = x.copy()
        for _ in range(100):
            lam = np.sqrt(lo * hi)
            ratio = np.sqrt(np.maximum(-dcx, 0) / np.maximum(dvx * lam, 1e-300))
            mv = move if beta[0] <= 1 else move / 2
            xn = np.clip(x * ratio, np.maximum(0.0, x - mv), np.minimum(1.0, x + mv))
            xn[frz] = 1.0
            vol = (phi * physical(xn)).sum()
            if vol > Vtarget:
                lo = lam
            else:
                hi = lam
            xd = xn
            if hi / lo < 1 + 1e-9:
                break
        change = float(np.abs(xd - x)[des].max()) if des.any() else 0.0
        x = xd
        xPhys = physical(x)
        grey = float(((xPhys > 0.1) & (xPhys < 0.9))[des].mean()) if des.any() else 0.0
        hist.append({"iter": it, "objective": obj, "compliance": cs.tolist(), "p": p, "beta": beta[0],
                     "volumeFraction": float((phi * xPhys).sum() / Vtot), "change": change,
                     "grey": grey, "cgIters": fem.cg_iters[-len(cases):], "amgRebuilt": bool(rebuild),
                     "seconds": time.time() - t0})
        log(f"  it {it:3d}  p {p:.2f}  b {beta[0]:.0f}  obj {obj:.4g}  vol {hist[-1]['volumeFraction']:.3f}  "
            f"change {change:.3f}  grey {grey:.2f}  cg {fem.cg_iters[-1]}{' amg' if rebuild else ''}  "
            f"{hist[-1]['seconds']:.1f}s")
        if p >= p_final and beta[0] >= BETA_MAX and it > (5 if warm else 10) and change < tol:
            log(f"  converged at iteration {it}")
            break

    full = np.zeros(grid.nelem)
    full[act] = xPhys
    return {"x": full, "history": hist, "fem_builds": fem.amg_builds, "rMM": r_vox * h,
            "seconds": time.time() - t_start, "cases": cases}


def benchmark_cantilever(log=lambda *a: None):
    """V6: optimized cantilever must beat a uniform design at equal mass and equal penalty."""
    from .fem import Grid
    g = Grid((32, 8, 12), 1.0, (0, 0, 0))
    e = np.arange(g.nelem)
    i, j, k = g.elem_ijk(e)
    fill = np.ones(g.nelem)
    active = np.ones(g.nelem, bool)
    frozen = np.zeros(g.nelem, bool)
    n = np.arange(g.nnode)
    p = g.node_coords(n)
    clamp = n[p[:, 0] < 1e-9]
    fixed = (3 * clamp[:, None] + np.arange(3)).ravel()
    tip = n[(abs(p[:, 0] - 32) < 1e-9) & (abs(p[:, 2] - 6) < 1e-9)]
    F = np.zeros(3 * g.nnode)
    F[3 * tip + 2] = -1.0 / tip.size
    vf = 0.3
    r = simp(g, fill, active, frozen, fixed, {"c": F}, {"c": 1.0}, 1000.0, 0.3, vf,
             iters=40, r_mm=1.6, log=log)
    fem = FEM(g, active, fixed, 0.3)
    Fr = fem.reduce_load(F)

    def comp(xp):
        u = fem.solve(fem.assemble(1000.0 * (EMIN + xp ** 3 * (1 - EMIN))), [Fr], rebuild=True)[0]
        return float(Fr @ u)
    c_opt = comp(r["x"])
    c_uni = comp(np.full(g.nelem, vf))
    return {"stiffer_pct": 100 * (1 - c_opt / c_uni), "vol_err": r["history"][-1]["volumeFraction"] - vf}
