"""0.4 options end to end: print-aware material, buckling, impact, large deformation. All opt-in."""
import json
import numpy as np
import pytest

from anneal.run import run
from anneal.physics import PhysicsError, transverse_iso_D, hill_index
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
    assert "printAware" not in rec["derived"]
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


def test_overhang_filter_is_not_in_this_release(tmp_path):
    with pytest.raises(RuntimeError, match="not part of Anneal 0.4"):
        _run(tmp_path, _beam(optimizer={"iterations": 5, "overhangFilter": True}), "oh")


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



# ---------------------------------------------------------------- impact (equivalent static)
from anneal.physics import impact_energy, impact_peak_force, G_MS2


def test_impact_energy_and_force():
    E, v = impact_energy({"massKg": 2.0, "speedMS": 3.0})
    assert E == pytest.approx(9000.0) and v == 3.0                    # 9 J = 9000 N mm
    E, v = impact_energy({"massKg": 1.0, "dropHeightMM": 1000.0})
    assert v == pytest.approx(np.sqrt(2 * G_MS2)) and E == pytest.approx(G_MS2 * 1000.0)
    assert impact_peak_force(9000.0, 500.0) == pytest.approx(3000.0)   # mass-spring peak
    for bad in ({"speedMS": 3}, {"massKg": 1}, {"massKg": 1, "speedMS": 2, "dropHeightMM": 5}, {"massKg": -1, "speedMS": 1}):
        with pytest.raises(PhysicsError):
            impact_energy(bad)


def _impact_beam(**imp):
    case = {"anchor": "tip", "massKg": 0.2, "dropHeightMM": 100.0, "direction": [0, 0, -1]}
    case.update(imp)
    return _beam(impact={"drop": case}, limits={"minSafetyFactor": 1.0, "minImpactSafetyFactor": 1.0})


def test_impact_run(tmp_path):
    rec = _run(tmp_path, _impact_beam(), "imp")
    r = rec["results"]["optimized"]["impact"]["drop"]
    assert r["energyJ"] == pytest.approx(0.2 * G_MS2 * 0.1)
    assert r["peakForceN"] == pytest.approx(np.sqrt(2 * r["energyJ"] * 1000 * r["stiffnessNperMM"]))
    # deflection uses the locking-corrected (softer) stiffness, so it is at least F / k
    assert r["deflectionMM"] >= r["peakForceN"] / r["stiffnessNperMM"] - 1e-12
    assert "safetyFactorLayers" in r                                   # FDM process: layer check too
    chk = [c for c in rec["checks"] if c["name"].startswith("Impact 'drop'")][0]
    assert chk["ok"] == (r["safetyFactor"] >= 1.0 and r["safetyFactorLayers"] >= 1.0)


@pytest.mark.parametrize("imp,msg", [({"anchor": "nope"}, "not in the spec"), ({"anchor": "wall"}, "fixed support"),
                                     ({"direction": [0, 0, 0]}, "direction")])
def test_impact_spec_errors(tmp_path, imp, msg):
    from anneal.problem import Problem
    from anneal.run import impact_check
    p = Problem(spec=_impact_beam(**imp), log=lambda *a: None).build()
    with pytest.raises(PhysicsError, match=msg):
        impact_check(p, np.where(p.active, 1.0, 0.0), 1.0, lambda *a: None)


# ---------------------------------------------------------------- large deformation (CalculiX)
from anneal.sidecar import find_ccx, find_gmsh, nonlinear_check

needs_ccx = pytest.mark.skipif(not find_ccx() or not find_gmsh()[0], reason="CalculiX or gmsh not installed")


def test_nonlinear_skips_cleanly_without_calculix(tmp_path, monkeypatch):
    import anneal.sidecar as sc
    monkeypatch.setattr(sc, "find_ccx", lambda: None)
    rec = _run(tmp_path, _beam(physics={"nonlinear": True}), "nlskip")
    assert "skipped" in rec["results"]["optimized"]["nonlinear"]
    row = [c for c in rec["checks"] if c["name"].startswith("Large deformation")][0]
    assert row["ok"] and row["warn"]


def _bar_problem(tmp_path, build, aniso):
    import trimesh
    from anneal.problem import Problem
    from anneal.physics import material_D
    spec = {"name": "bar", "designSpace": {"type": "box", "min": [0, 0, 0], "max": [40, 10, 10]},
            "material": {"E": 3500, "nu": 0.0, "nuZ": 0.0, "Ez": 2000, "Gz": 800, "density": 1.2, "yield": 50},
            "process": {"name": "FDM", "buildDirection": build}, "resolution": {"voxelMM": 1.0},
            "anchors": [{"name": "wall", "role": "fixed", "region": {"type": "box", "min": [-2, -1, -1], "max": [0.2, 11, 11]}},
                        {"name": "end", "role": "load", "region": {"type": "box", "min": [39.8, -1, -1], "max": [42, 11, 11]},
                         "loads": {"pull": [100, 0, 0]}}]}
    p = Problem(spec=spec, log=lambda *a: None).build()
    p.D = None
    if aniso:
        p.D, p.derived["printAware"] = material_D(p.material, p.process)
    stl = tmp_path / "bar.stl"
    trimesh.creation.box(extents=[40, 10, 10], transform=trimesh.transformations.translation_matrix([20, 5, 5])).export(stl)
    return p, str(stl)


@needs_ccx
@pytest.mark.parametrize("build,E", [([0, 0, 1], 3500.0), ([1, 0, 0], 2000.0)])
def test_calculix_material_orientation(tmp_path, build, E):
    """A bar pulled along x: built along z it is pulled in the layer plane (E); built along x it is
    pulled across the layers (Ez). CalculiX must give FL/(EA) in both cases (nu = 0)."""
    p, stl = _bar_problem(tmp_path, build, True)
    r = nonlinear_check(p, stl, str(tmp_path / "ccx"), lambda *a: None, size=2.5)
    exact = 100 * 40 / (E * 100)
    assert r["cases"]["pull"]["linear"] == pytest.approx(exact, rel=0.03)


@needs_ccx
def test_calculix_large_deflection_differs_from_linear(tmp_path):
    rec = _run(tmp_path, _beam(physics={"nonlinear": True}, material={**PLA_Z, "E": 500.0, "Ez": 400.0}), "nl")
    nl = rec["results"]["optimized"]["nonlinear"]
    assert "skipped" not in nl, nl
    r = nl["cases"]["down"]
    assert np.isfinite(r["linear"]) and np.isfinite(r["nonlinear"])
    # CalculiX linear agrees with Anneal's as-built displacement (raw, voxel) within 25 %
    an = rec["results"]["optimized"]["cases"]["down"]["maxDisplacementMM"]
    assert r["linear"] == pytest.approx(an, rel=0.25)
