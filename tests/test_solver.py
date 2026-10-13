"""Element (e9), self-weight, pressure and iso-level volume tests (Anneal 0.4)."""
import numpy as np
import pytest

from anneal.fem import FEM, Grid, hex8_matrices
from anneal.optimize import simp, EMIN
from anneal import validate as V


def test_e9_bubbles_do_not_change_centre_strain():
    ke9, B9, _ = hex8_matrices(0.3, 2.0, element="e9")
    kfi, Bfi, _ = hex8_matrices(0.3, 2.0, element="hex8fi")
    assert np.allclose(B9, Bfi)
    assert np.allclose(ke9, ke9.T)
    # e9 is softer than hex8fi (it removes stiffness), never stiffer
    assert np.linalg.eigvalsh(kfi - ke9).min() > -1e-10


def test_e9_bending_without_locking():
    for nd in (1, 2):
        r = V._cantilever(nd, "e9")
        assert 0.98 < r < 1.01


def test_unknown_element_is_refused():
    with pytest.raises(ValueError):
        hex8_matrices(0.3, 1.0, element="hex20")


def _gravity_problem(extra=None):
    from anneal.problem import Problem
    spec = {"name": "g", "designSpace": {"type": "box", "min": [0, 0, 0], "max": [40, 4, 4]},
            "material": {"E": 1000.0, "nu": 0.3, "density": 1.0, "yield": 100.0}, "resolution": {"voxelMM": 1.0},
            "anchors": [{"name": "wall", "role": "fixed", "region": {"type": "box", "min": [-2, -1, -1], "max": [-0.4, 5, 5]}},
                        {"name": "tip", "role": "load", "region": {"type": "box", "min": [40.4, -1, -1], "max": [42, 5, 5]},
                         "loads": {"push": [0, 0, -1]}}],
            "gravity": {"weight": [0, 0, -2000.0]}}
    spec.update(extra or {})
    return Problem(spec=spec, log=lambda *a: None).build()


def test_self_weight_cantilever_matches_beam_theory():
    p = _gravity_problem()
    assert p.cases == ["push", "weight"]
    fill = np.where(p.active, 1.0, 0.0)
    fixed, F, _ = p.boundary(p.active)
    fb = p.body_loads(fill)["weight"]
    W = 1e-6 * 40 * 4 * 4 * 9.80665 * 2000.0          # N: mass in kg x g x 2000 g
    assert fb.reshape(-1, 3).sum(0) == pytest.approx([0, 0, -W], rel=1e-12)
    fem = FEM(p.grid, p.active, fixed, 0.3, element="e9")
    u = fem.expand(fem.solve(fem.assemble(1000.0 * fill[fem.act]), [fem.reduce_load(fb)], rtol=1e-12)[0])
    n = np.arange(p.grid.nnode)
    xyz = p.grid.node_coords(n)
    tip = n[(np.abs(xyz[:, 0] - 40) < 1e-9) & np.all((xyz[:, 1:] > -1e-9) & (xyz[:, 1:] < 4 + 1e-9), axis=1)]
    w = -u[3 * tip + 2].mean()
    q, L, E, I, G, A = W / 40, 40.0, 1000.0, 4 * 4 ** 3 / 12, 1000 / 2.6, 16.0
    exact = q * L ** 4 / (8 * E * I) + q * L ** 2 / (2 * 5 / 6 * G * A)
    assert 0.98 < w / exact < 1.01


def test_self_weight_sensitivity_matches_finite_difference():
    """The design-dependent weight load: analytic dc/dx vs central differences."""
    g = Grid((12, 3, 4), 1.0, (0, 0, 0))
    n = np.arange(g.nnode)
    xyz = g.node_coords(n)
    clamp = n[xyz[:, 0] < 1e-9]
    fixed = (3 * clamp[:, None] + np.arange(3)).ravel()
    F = np.zeros(3 * g.nnode)
    F[3 * n[np.abs(xyz[:, 0] - 12) < 1e-9] + 2] = -0.05
    fill = np.ones(g.nelem)
    act = np.ones(g.nelem, bool)
    coef, acc = 1e-3, {"c": [0, 0, -1.0]}
    seen = {}

    def probe(it, x, cs, dcx, dvx, physical, p):
        if it == 3:
            seen.update(x=x, c=cs[0], d=dcx, phys=physical, p=p)

    simp(g, fill, act, np.zeros(g.nelem, bool), fixed, {"c": F}, {"c": 1.0}, 1000.0, 0.3, 0.5,
         iters=3, r_mm=1.5, probe=probe, log=lambda *a: None, gravity=(coef, acc), beta_max=0)
    fem = FEM(g, act, fixed, 0.3)

    def comp(x):
        xp = seen["phys"](x)
        Ee = 1000.0 * (EMIN + xp ** seen["p"] * (1 - EMIN))
        wt = coef * xp / 8
        fb = np.bincount(fem.edof.ravel(), weights=(wt[:, None] * np.tile(acc["c"], 8)).ravel(), minlength=3 * g.nnode)
        f = fem.reduce_load(F + fb)
        u = fem.solve(fem.assemble(Ee), [f], rtol=1e-13)[0]
        return f @ u

    rng = np.random.default_rng(0)
    for e in rng.choice(g.nelem, 5, replace=False):
        h = 1e-5
        xp, xm = seen["x"].copy(), seen["x"].copy()
        xp[e] += h
        xm[e] -= h
        fd = (comp(xp) - comp(xm)) / (2 * h)
        assert seen["d"][e] == pytest.approx(fd, rel=2e-3, abs=1e-9 * abs(seen["c"]))


def test_pressure_on_a_picked_face():
    from anneal.problem import Anchor
    a = Anchor({"name": "p", "role": "load", "pressure": {"c": 2.0},
                "region": {"type": "prism", "origin": [0, 0, 10], "normal": [0, 0, 1], "xdir": [1, 0, 0],
                           "tris": [[0, 0, 10, 0, 10, 5], [0, 0, 10, 5, 0, 5]], "z0": -1, "z1": 0}}, 0)
    assert a.loads["c"] == pytest.approx([0, 0, -100.0])       # 2 MPa x 50 mm2, pushing into the face
    b = Anchor({"name": "q", "role": "load", "pressure": {"c": 1.0}, "loads": {"c": [1, 0, 0]},
                "areaMM2": 30, "normal": [1, 0, 0], "region": {"type": "box", "min": [0, 0, 0], "max": [1, 1, 1]}}, 0)
    assert b.loads["c"] == pytest.approx([-29.0, 0, 0])
    with pytest.raises(Exception):
        Anchor({"name": "r", "role": "load", "pressure": {"c": 1.0},
                "region": {"type": "box", "min": [0, 0, 0], "max": [1, 1, 1]}}, 0)


def test_iso_level_volume_estimate_matches_marching_cubes():
    """choose_level counts voxels above the level. That count is the volume marching cubes encloses
    (within 1 %); weighting by density (f * (f > t)) would under-count by 4-20 %."""
    import trimesh
    from skimage import measure
    n = 40
    x = np.arange(n) + 0.5
    X, Y, Z = np.meshgrid(x, x, x, indexing="ij")
    f = np.clip(0.5 - (np.sqrt((X - 20) ** 2 + (Y - 20) ** 2 + (Z - 20) ** 2) - 12) / 4, 0, 1)
    for t in (0.3, 0.5, 0.7):
        v, fa, _, _ = measure.marching_cubes(np.pad(f, 1), t)
        mc = abs(trimesh.Trimesh(v, fa).volume)
        assert abs((f > t).sum() / mc - 1) < 0.01
        assert (f * (f > t)).sum() / mc < 0.97


def test_zz_error_estimate():
    """ZZ estimate: zero for a uniform stress field; halves when the voxels halve (bending)."""
    from anneal.fea import zz_error
    g, e, i, j, k, fill = V._bar(10, 2, 4, 1.0)
    fem = FEM(g, np.ones(g.nelem, bool), [], 0.3, element="e9")
    xyz = g.node_coords(np.arange(g.nnode))
    u = (xyz @ np.array([[1e-3, 0, 0], [0, -3e-4, 0], [0, 0, -3e-4]]).T).ravel()
    Ee = np.full(g.nelem, 1000.0)
    _, rel, _ = zz_error(fem, fem.stress(u, Ee), Ee, 1000.0)
    assert rel < 1e-10
    errs = []
    for nd in (2, 4):
        d, L, P = 4.0, 40.0, 10.0
        g, e, i, j, k, fill = V._bar(10 * nd, nd, nd, d / nd)
        clamp = V._nodes_where(g, lambda p: p[:, 0] < 1e-9)
        fem = FEM(g, np.ones(g.nelem, bool), (3 * clamp[:, None] + np.arange(3)).ravel(), 0.3, element="e9")
        end = e[i == g.nx - 1]
        Fg = V._face_load(g, end, np.ones(end.size), -P, 2, [1, 2, 5, 6])
        Ee = np.full(g.nelem, 1000.0)
        u = fem.expand(fem.solve(fem.assemble(Ee), [fem.reduce_load(Fg)], rtol=1e-12)[0])
        errs.append(zz_error(fem, fem.stress(u, Ee), Ee, 1000.0)[1])
    assert 1.8 < errs[0] / errs[1] < 2.2
