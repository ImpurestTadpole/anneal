"""Overhang (AM) filter: adjoint, behaviour, and the full SIMP sensitivity chain."""
import numpy as np
import pytest
import scipy.sparse.linalg as sla

from anneal.amfilter import AMFilter, unsupported_fraction, axis_of
from anneal.fem import Grid, FEM
from anneal.optimize import simp, EMIN


def _fd_check(f, x, rng, n=15, h=1e-6):
    w = rng.normal(size=x.shape)
    F = lambda z: float((f.forward(z) * w).sum())
    F(x)
    g = f.backward(w)
    worst = 0.0
    for _ in range(n):
        idx = tuple(rng.integers(0, s) for s in x.shape)
        e = np.zeros_like(x)
        e[idx] = h
        fd = (F(x + e) - F(x - e)) / (2 * h)
        worst = max(worst, abs(fd - g[idx]) / max(abs(fd), 1e-6))
    return worst


@pytest.mark.parametrize("ax,sg", [(2, 1), (2, -1), (0, 1), (1, -1)])
def test_adjoint_matches_finite_differences(ax, sg):
    rng = np.random.default_rng(ax * 10 + sg)
    x = rng.uniform(0.05, 1, (7, 6, 8))
    x[rng.uniform(size=x.shape) < 0.3] = 1e-9          # near-void voxels: the NaN trap
    active = np.ones_like(x)
    sl = [slice(None)] * 3
    sl[ax] = slice(0, 2) if sg > 0 else slice(-2, None)
    active[tuple(sl)] = 0                               # padded grid: plate is not layer 0
    keep = np.zeros_like(x)
    keep[3, 3, 4] = 1
    f = AMFilter(x.shape, ax, sg, active=active, keep=keep)
    assert f.base == 2
    assert _fd_check(f, x, rng) < 1e-4


def test_no_nan_on_empty_support():
    x = np.zeros((6, 6, 6))
    x[2, 2, 4] = 1.0
    f = AMFilter(x.shape)
    y = f.forward(x)
    g = f.backward(np.ones_like(x))
    assert np.isfinite(y).all() and np.isfinite(g).all()


def test_floating_removed_supported_kept_with_padding():
    x = np.zeros((12, 12, 12))
    active = np.zeros_like(x)
    active[:, :, 2:] = 1                                # two empty padding layers under the part
    x[2:5, 2:5, 2:6] = 1                                # stands on the plate (layer 2)
    x[7:10, 7:10, 7:10] = 1                             # floats
    y = AMFilter(x.shape, active=active).forward(x)
    assert y[2:5, 2:5, 2:6].min() > 0.95
    assert y[7:10, 7:10, 7:10].max() < 0.05
    assert unsupported_fraction(x, active=active) > 0
    assert unsupported_fraction(y, active=active) == 0


def test_45_degree_staircase_is_kept():
    x = np.zeros((14, 3, 10))
    for k in range(10):
        x[k:k + 3, :, k] = 1                            # leans one voxel per layer = 45 deg
    y = AMFilter(x.shape).forward(x)
    assert y[x > 0].min() > 0.95


def test_axis_of():
    assert axis_of([0, 0, 1]) == (2, 1)
    assert axis_of([-1, 0, 0]) == (0, -1)
    with pytest.raises(ValueError):
        axis_of([1, 0, 1])


def _tiny():
    g = Grid((10, 3, 6), 1.0, (0, 0, 0))
    n = np.arange(g.nnode)
    p = g.node_coords(n)
    clamp = n[p[:, 0] < 1e-9]
    fixed = (3 * clamp[:, None] + np.arange(3)).ravel()
    tip = n[(abs(p[:, 0] - 10) < 1e-9) & (abs(p[:, 2] - 3) < 1e-9)]
    F = np.zeros(3 * g.nnode)
    F[3 * tip + 2] = -1.0 / tip.size
    return g, fixed, F


@pytest.mark.parametrize("order", [None, "after", "before"])
def test_simp_sensitivities_through_the_whole_chain(order):
    """dc/dx and dV/dx that SIMP uses agree with finite differences of the real compliance and
    volume, with the projection active, for no AM filter and both filter positions."""
    g, fixed, F = _tiny()
    act = np.ones(g.nelem, bool)
    frz = np.zeros(g.nelem, bool)
    frz[g.elem_ijk(np.arange(g.nelem))[0] == 0] = True   # frozen clamp layer
    fill = np.ones(g.nelem)
    rng = np.random.default_rng(3)
    x0 = rng.uniform(0.3, 0.9, g.nelem)
    am = None if order is None else AMFilter(g.shape, active=g.to3d(act.astype(float)), keep=g.to3d(frz.astype(float)))
    fem = FEM(g, act, fixed, 0.3)
    Fr = fem.reduce_load(F)
    got = {}

    def probe(it, x, cs, dcx, dvx, physical, p):
        if it != 1:
            return
        def comp(z):
            xp = physical(z)
            K = fem.assemble(1000.0 * fill * (EMIN + xp ** p * (1 - EMIN)))
            return float(Fr @ sla.spsolve(K.tocsc(), Fr)), float((fill * xp).sum())
        errs_c, errs_v = [], []
        for i in rng.choice(np.flatnonzero(~frz), 8, replace=False):
            e = np.zeros_like(x)
            e[i] = 1e-6
            (cp, vp), (cm, vm) = comp(x + e), comp(x - e)
            errs_c.append(abs((cp - cm) / 2e-6 - dcx[i]) / max(abs(dcx[i]), 1e-12))
            errs_v.append(abs((vp - vm) / 2e-6 - dvx[i]) / max(abs(dvx[i]), 1e-12))
        got["c"], got["v"] = max(errs_c), max(errs_v)

    simp(g, fill, act, frz, fixed, {"c": F}, {"c": 1.0}, 1000.0, 0.3, 0.5, iters=1, r_mm=1.6,
         log=lambda *a: None, x0=x0, am=am, am_order=order or "after", probe=probe)
    assert got["c"] < 1e-3, got
    assert got["v"] < 1e-5, got
