"""Fast tests: python -m pytest -q   (about one minute)."""
import json
import os
import numpy as np
import pytest
import trimesh

from anneal import validate
from anneal.fem import Grid
from anneal.geometry import voxel_fill
from anneal.problem import Problem, SpecError
from anneal.run import locking_factor, next_volume_fraction


def test_rigid_body():
    assert validate.check_rigid_body()[1]


def test_tension_exact():
    assert validate.check_tension()[1]


def test_partial_volume():
    assert validate.check_partial_volume()[1]


def test_determinism():
    assert validate.check_determinism()[1]


def test_voxel_sphere_volume():
    m = trimesh.creation.icosphere(subdivisions=4, radius=10.0)
    h = 0.75
    g = Grid(np.ceil((m.extents + 2 * h) / h).astype(int), h, m.bounds[0] - h)
    v = voxel_fill(m, g).sum() * h ** 3
    assert abs(v - m.volume) / m.volume < 0.005


def test_locking_factor_matches_v3():
    assert abs(locking_factor(2) - 0.869) < 1e-9
    assert abs(locking_factor(8) - 0.983) < 1e-9
    assert locking_factor(3) < locking_factor(6) < 1.0


def test_mass_search_brackets():
    P = lambda v, d: {"vf": v, "built": {"maxDisplacementMM": d}}
    v = next_volume_fraction([P(0.30, 0.36), P(0.40, 0.20)], 0.30)
    assert 0.30 < v < 0.40


def _spec(**over):
    s = {"name": "t", "designSpace": {"type": "box", "min": [0, 0, 0], "max": [40, 10, 10]},
         "material": "AlSi10Mg-LPBF", "resolution": {"voxelMM": 1.0},
         "anchors": [{"name": "wall", "role": "fixed", "region": {"type": "box", "min": [-1, -1, -1], "max": [0.5, 11, 11]}},
                     {"name": "tip", "role": "load", "region": {"type": "box", "min": [39.5, -1, -1], "max": [41, 11, 11]},
                      "loads": {"down": [0, 0, -100]}}],
         "objective": {"volumeFraction": 0.4}, "optimizer": {"iterations": 30}}
    s.update(over)
    return s


def test_spec_needs_fixed_anchor():
    s = _spec()
    s["anchors"] = s["anchors"][1:]
    with pytest.raises(SpecError, match="no fixed anchor"):
        Problem(spec=s, log=lambda *a: None)


def test_anchor_missing_material_names_fix():
    s = _spec()
    s["anchors"][1]["region"] = {"type": "box", "min": [100, 100, 100], "max": [101, 101, 101]}
    p = Problem(spec=s, log=lambda *a: None).build()
    with pytest.raises(SpecError, match="touches no material"):
        p.boundary(p.active)


def test_end_to_end_box(tmp_path):
    from anneal.run import run
    spec = tmp_path / "beam.json"
    spec.write_text(json.dumps(_spec(limits={"maxDisplacementMM": 10.0})))
    record, html = run(str(spec), str(tmp_path / "out"), log=lambda *a: None)
    assert os.path.isfile(html)
    assert os.path.isfile(tmp_path / "out" / "t-optimized.stl")
    opt = record["results"]["optimized"]
    assert 0.2 < opt["volumeCM3"] / 4.0 < 0.6
    m = trimesh.load(tmp_path / "out" / "t-optimized.stl")
    assert m.is_watertight
