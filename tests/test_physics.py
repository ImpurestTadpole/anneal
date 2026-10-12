"""0.4 options end to end: print-aware material, overhang filter, buckling. All opt-in."""
import json
import numpy as np
import pytest

from anneal.run import run
from anneal.physics import PhysicsError, transverse_iso_D, hill_index
from anneal.amfilter import unsupported_fraction
from anneal.fem import elasticity_D

PLA_Z = {"E": 3500, "nu": 0.36, "density": 1.24, "yield": 50, "Ez": 2400, "process": "FDM"}


@pytest.fixture(autouse=True)
def lib_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNEAL_HOME", str(tmp_path / "home"))


def _beam(**over):
    s = {"name": "t", "designSpace": {"type": "box", "min": [0, 0, 0], "max": [40, 10, 10]},
         "material": dict(PLA_Z), "process": "FDM", "resolution": {"voxelMM": 1.0},
         "anchors": [{"name": "wall", "role": "fixed", "region": {"type": "box", "min": [-1, -1, -1], "max": [0.5, 11, 11]}},
                     {"name": "tip", "role": "load", "region": {"type": "box", "min": [39.5, -1, -1], "max": [41, 11, 11]},
                      "loads": {"down": [0, 0, -100]}}],
         "objective": {"volumeFraction": 0.4}, "optimizer": {"iterations": 30},
         "output": {"report": False, "formats": ["stl"]}, "limits": {"minSafetyFactor": 1.0}}
    s.update(over)
    return s


def _run(tmp_path, spec, name="r"):
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(spec))
    rec, _ = run(str(p), str(tmp_path / name), log=lambda *a: None, db_path=False)
    return rec


def test_options_off_leave_the_record_unchanged(tmp_path):
    rec = _run(tmp_path, _beam())
    opt = rec["results"]["optimized"]
    assert "safetyFactorHill" not in opt and "buckling" not in opt
    assert "printAware" not in rec["derived"] and "overhangFilter" not in rec["derived"]
    assert not any("Buckling" in c["name"] or "Hill" in c["name"] for c in rec["checks"])


def test_print_aware_run(tmp_path):
    rec = _run(tmp_path, _beam(physics={"anisotropic": True}), "aniso")
    opt = rec["results"]["optimized"]
    assert rec["derived"]["printAware"]["Ez"] == 2400
    assert set(rec["derived"]["printAware"]["assumed"]) == {"nuZ", "Gz"}
    assert opt["safetyFactor"] == min(opt["safetyFactorVonMises"], opt["safetyFactorHill"])
    assert any("Hill, print-aware" in c["name"] for c in rec["checks"])


def test_print_aware_needs_ez_and_a_process(tmp_path):
    m = dict(PLA_Z)
    m.pop("Ez")
    with pytest.raises(PhysicsError, match="Ez"):
        _run(tmp_path, _beam(material=m, physics={"anisotropic": True}), "noez")
    with pytest.raises(PhysicsError, match="process"):
        _run(tmp_path, _beam(process="none", physics={"anisotropic": True}), "noproc")


def test_impossible_material_is_refused():
    with pytest.raises(PhysicsError, match="positive definite"):
        transverse_iso_D(3500, 100, 0.36, 0.49, 50)


def test_hill_is_von_mises_when_strengths_are_equal_and_weaker_across_layers():
    sig = np.zeros((1, 6))
    sig[0, 2] = 10.0                                   # tension along the build axis
    assert hill_index(sig, 50, 50, (0, 0, 1))[0] == pytest.approx(0.2)
    assert hill_index(sig, 50, 25, (0, 0, 1))[0] == pytest.approx(0.4)   # half the layer strength
    assert hill_index(sig, 50, 25, (1, 0, 0))[0] == pytest.approx(0.2)   # same load in the layer plane


def test_isotropic_limit_is_exact():
    nu = 0.36
    D = transverse_iso_D(3500, 3500, nu, nu, 3500 / (2 * (1 + nu)), (0.3, 0.2, -0.9))
    assert np.abs(D - elasticity_D(nu)).max() < 1e-12


def test_overhang_filter_run(tmp_path):
    spec = _beam(optimizer={"iterations": 40, "overhangFilter": True})
    rec = _run(tmp_path, spec, "am")
    assert rec["derived"]["overhangFilter"]["angleDeg"] == 45
    x = np.load(tmp_path / "am" / "density.npy")
    assert unsupported_fraction(x, 2, 1, active=x > 0.05) < 0.02


def test_overhang_filter_needs_axis_direction(tmp_path):
    with pytest.raises(ValueError, match="x, y or z"):
        _run(tmp_path, _beam(process={"name": "FDM", "buildDirection": [1, 0, 1]},
                             optimizer={"iterations": 5, "overhangFilter": True}), "diag")


def test_buckling_check_on_a_column(tmp_path):
    spec = {"name": "col", "designSpace": {"type": "box", "min": [0, 0, 0], "max": [6, 6, 60]},
            "material": {"E": 1000, "nu": 0.3, "density": 1.0, "yield": 1000}, "resolution": {"voxelMM": 1.0},
            "anchors": [{"name": "base", "role": "fixed", "region": {"type": "box", "min": [-1, -1, -1], "max": [7, 7, 0.5]}},
                        {"name": "top", "role": "load", "region": {"type": "box", "min": [-1, -1, 59.5], "max": [7, 7, 61]},
                         "loads": {"push": [0, 0, -1]}}],
            "objective": {"volumeFraction": 0.9}, "optimizer": {"iterations": 3},
            "physics": {"buckling": True}, "limits": {"minBucklingFactor": 2.0},
            "output": {"report": False, "formats": ["stl"]}}
    rec = _run(tmp_path, spec, "col")
    b = rec["results"]["optimized"]["buckling"]["push"]
    assert np.isfinite(b["corrected"]) and b["corrected"] <= b["raw"]
    chk = [c for c in rec["checks"] if c["name"].startswith("Buckling")][0]
    assert chk["ok"] == (b["corrected"] >= 2.0)
