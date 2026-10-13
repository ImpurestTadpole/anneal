"""0.4.2 temperature: material keys and import (H1), spec (H3), thermal load and stress (H5), derating (H4),
buckling with thermal pre-stress (H7), study, check rows and advanced output (H8, H9, H11).

Material values in this file are TEST-ONLY numbers chosen to make the arithmetic easy. They are not
data for any real material. Real values come from docs/research/thermal-material-data.md."""
import json

import numpy as np
import pytest

from anneal.materials import LibraryError, parse_import, validate_material, get_material


@pytest.fixture(autouse=True)
def lib_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNEAL_HOME", str(tmp_path / "home"))


# TEST-ONLY material (not real data): round numbers so expected results are exact
TEST_MAT = {"name": "test-only-metal", "E": 70000.0, "nu": 0.3, "density": 2.7, "yield": 200.0,
            "alpha": 2.0e-5, "maxServiceTempC": 150.0,
            "tempDerating": [[-40, 1.0, 1.0], [20, 1.0, 1.0], [120, 0.5, 0.5], [150, 0.4, 0.4]]}


# ------------------------------------------------------------------ H1: material keys and import
BASE_CSV = "name,E (GPa),nu,density (g/cm3),yield (MPa)"


def _one(header, cell):
    out, problems = parse_import("m.csv", f"{BASE_CSV},{header}\nM,70,0.33,2.7,200,{cell}\n")
    return out.get("M"), [p for p in problems if not p.startswith("Note:")]


@pytest.mark.parametrize("header, cell, want", [
    ("CTE (1/K)", "2.3e-5", 2.3e-5),
    ("CTE (1/°C)", "2.3e-5", 2.3e-5),
    ("CTE (ppm/K)", "23", 2.3e-5),
    ("thermal expansion (µm/(m·K))", "23", 2.3e-5),
    ("alpha (um/m/K)", "23", 2.3e-5),
    ("CTE (ppm/°F)", "10", 1.8e-5),
    ("alpha", "2.3e-5", 2.3e-5),                       # no unit: only 1/K gives so small a number
    ("CTE", "23 ppm/K", 2.3e-5),                       # unit written in the cell
])
def test_import_expansion_units(header, cell, want):
    m, problems = _one(header, cell)
    assert not problems
    assert m["alpha"] == pytest.approx(want, rel=1e-12)


def test_import_expansion_across_layers_and_round_numbers():
    m, problems = _one("CTE Z (ppm/K)", "25")
    assert not problems and m["alphaZ"] == 2.5e-5        # exactly, no float noise from the unit factor


@pytest.mark.parametrize("header, cell, want", [
    ("maxServiceTempC", "150", 150.0),
    ("HDT (°C)", "150", 150.0),
    ("Glass transition (°F)", "302", 150.0),
    ("Max service temperature (K)", "423.15", 150.0),
    ("Tg (degC)", "60", 60.0),
])
def test_import_temperature_units(header, cell, want):
    m, problems = _one(header, cell)
    assert not problems
    assert m["maxServiceTempC"] == pytest.approx(want, abs=1e-9)


def test_import_keeps_the_column_name_of_the_service_limit():
    m, _ = _one("HDT (°C)", "150")
    assert "HDT (°C)" in m["source"]                  # HDT and Tg are not the same thing: the owner sees which
    m, _ = _one("maxServiceTempC", "150")
    assert "source" not in m


@pytest.mark.parametrize("header, cell, words", [
    ("CTE", "23", "no unit"),                         # 23 1/K is impossible; the unit must be written
    ("HDT", "150", "no unit"),                        # °C or °F cannot be guessed
    ("CTE (furlong/K)", "23", "not known"),
    ("CTE (ppm/K)", "2000", "outside"),
])
def test_import_expansion_errors_name_the_row(header, cell, words):
    m, problems = _one(header, cell)
    assert m is None and len(problems) == 1
    assert problems[0].startswith("Row 2") and words in problems[0]


def test_import_derating_table_from_a_cell_and_in_fahrenheit():
    m, problems = _one("tempDerating", '"20:1:1; 60:0.8:0.7"')
    assert not problems and m["tempDerating"] == [[20.0, 1.0, 1.0], [60.0, 0.8, 0.7]]
    m, problems = _one("tempDerating (°F)", '"68:1:1; 140:0.8:0.7"')
    assert not problems and m["tempDerating"][1][0] == pytest.approx(60.0)


@pytest.mark.parametrize("cell, words", [
    ('"60:0.9:0.9; 100:0.8:0.8"', "no reference row"),
    ('"20:1:1; 60:0:0.5"', "more than 0"),
    ('"20:1:1; 60:0.8:-0.1"', "more than 0"),
    ('"60:0.9:0.9; 20:1:1"', "not above the row before"),
    ('"20:1:1; 20:0.9:0.9"', "not above the row before"),
    ('"20:1; 60:0.9:0.9"', "three numbers"),
])
def test_bad_derating_table_gives_a_row_level_error(cell, words):
    m, problems = _one("tempDerating", cell)
    assert m is None and len(problems) == 1
    assert problems[0].startswith("Row 2, column 'tempDerating'") and words in problems[0]


def test_json_import_with_thermal_keys_and_source():
    js = {"materials": {"J": {"E": 70000, "nu": 0.33, "density": 2.7, "yield": 200, "alpha": 2.3e-5,
                              "alphaZ": 2.5e-5, "maxServiceTempC": 150, "tempDerating": [[20, 1, 1], [150, 0.9, 0.7]],
                              "source": "a datasheet"}}}
    out, problems = parse_import("m.json", json.dumps(js))
    assert not [p for p in problems if not p.startswith("Note:")]
    j = out["J"]
    assert (j["alpha"], j["alphaZ"], j["maxServiceTempC"]) == (2.3e-5, 2.5e-5, 150.0)
    assert j["tempDerating"] == [[20.0, 1.0, 1.0], [150.0, 0.9, 0.7]] and j["source"] == "a datasheet"


def test_validate_material_ranges():
    ok = validate_material(dict(TEST_MAT))
    assert ok["alpha"] == 2e-5 and ok["tempDerating"][2] == [120.0, 0.5, 0.5]
    for key, bad, words in (("alpha", 23.0, "1/K"), ("alphaZ", -1e-6, "1/K"), ("maxServiceTempC", -300, "°C"),
                            ("tempDerating", [[20, 1, 1], [10, 1, 1]], "not above"),
                            ("tempDerating", [[20, 1, 1], [60, 2.5, 1]], "at most 2")):
        with pytest.raises(LibraryError, match=words):
            validate_material({**TEST_MAT, key: bad})


def test_inline_material_keeps_thermal_keys_and_old_materials_do_not_change():
    m = get_material(dict(TEST_MAT))
    assert m["alpha"] == 2e-5 and m["maxServiceTempC"] == 150.0
    plain = get_material({"E": 70000, "nu": 0.3, "density": 2.7, "yield": 200})
    assert not set(plain) & {"alpha", "alphaZ", "maxServiceTempC", "tempDerating"}


# ------------------------------------------------------------------ H3: the "thermal" spec
from anneal.problem import Problem, SpecError  # noqa: E402


def _bar_spec(material=None, **over):
    """A bar 40 x 10 x 10 mm held at x = 0, loaded at x = 40 (voxels of 2 mm: a few hundred elements)."""
    s = {"name": "tbar", "designSpace": {"type": "box", "min": [0, 0, 0], "max": [40, 10, 10]},
         "material": dict(TEST_MAT if material is None else material), "process": "none",
         "resolution": {"voxelMM": 2.0},
         "anchors": [{"name": "wall", "role": "fixed", "region": {"type": "box", "min": [-1, -1, -1], "max": [0.9, 11, 11]}},
                     {"name": "tip", "role": "load", "region": {"type": "box", "min": [39.1, -1, -1], "max": [41, 11, 11]},
                      "loads": {"main": [0, 0, -100]}}],
         "objective": {"volumeFraction": 0.5}, "optimizer": {"iterations": 25},
         "output": {"report": False, "formats": ["stl"]}}
    s.update(over)
    return s


def _prob(**over):
    return Problem(spec=_bar_spec(**over), log=lambda *a: None)


def test_thermal_cases_join_the_load_cases():
    p = _prob(thermal={"referenceTempC": 20, "cases": {"main": 60, "cold": -20}})
    assert p.cases == ["cold", "main"] and p.mech_cases == ["main"] and p.thermal_only == ["cold"]
    assert p.t_ref == 20 and p.t_case == {"main": 60.0, "cold": -20.0}
    assert p.disp_incl_thermal is False
    assert _prob(limits={"displacementIncludesThermal": True}).disp_incl_thermal is True


def test_no_thermal_key_leaves_the_problem_as_before():
    p = _prob()
    assert p.cases == ["main"] and p.t_case == {} and p.thermal_only == [] and p.t_ref == 20.0


@pytest.mark.parametrize("thermal, words", [
    ([20, 60], "must be an object"),
    ({"referenceTemp": 20, "cases": {"main": 60}}, "unknown key"),
    ({"referenceTempC": "warm", "cases": {"main": 60}}, "referenceTempC must be one number"),
    ({"cases": [60]}, "cases must be an object"),
    ({"cases": {"main": "hot"}}, "must be one number"),
    ({"cases": {"main": -300}}, "below absolute zero"),
    ({"cases": {"main": 151}}, "above the service limit"),
    ({"cases": {"main": -50}}, "outside the tempDerating table"),
])
def test_thermal_spec_errors_name_the_fix(thermal, words):
    with pytest.raises(SpecError, match=words):
        _prob(thermal=thermal)


def test_service_limit_message_names_the_limit_and_the_fix():
    with pytest.raises(SpecError) as e:
        _prob(thermal={"cases": {"main": 160}})
    msg = str(e.value)
    assert "160" in msg and "150" in msg and "maxServiceTempC" in msg and "higher service temperature" in msg


def test_material_without_alpha_stops_a_thermal_run():
    m = {k: v for k, v in TEST_MAT.items() if k != "alpha"}
    with pytest.raises(SpecError, match="no alpha") as e:
        _prob(material=m, thermal={"cases": {"main": 60}})
    assert "Add alpha (1/K) to the material" in str(e.value)
    _prob(material=m)                                   # without a thermal case, alpha is not needed


def test_every_built_in_material_without_alpha_stops_a_thermal_run():
    """No built-in material has a confirmed alpha yet (H2 sources are not confirmed): each one stops."""
    from anneal.materials import MATERIALS
    for name, mat in MATERIALS.items():
        if "alpha" in mat:
            continue
        with pytest.raises(SpecError, match="alpha"):
            Problem(spec={**_bar_spec(), "material": name, "thermal": {"cases": {"main": 40}}}, log=lambda *a: None)


# ------------------------------------------------------------------ H5: thermal load vector and stress
from anneal.fem import FEM, Grid, elasticity_D, thermal_element_vector  # noqa: E402
from anneal.physics import thermal_strain, transverse_iso_D  # noqa: E402


@pytest.mark.parametrize("D", [elasticity_D(0.3), transverse_iso_D(1.0, 0.6, 0.3, 0.25, 0.3, (0.3, 0.2, 0.93))])
def test_e9_bubble_thermal_load_is_zero(D):
    m = thermal_strain(1.0, 1.4, (0.3, 0.2, 0.93))
    fa, fb = thermal_element_vector(D, 1.7, m, "e9")
    assert fb.shape == (9,) and np.abs(fb).max() < 1e-14 * np.abs(fa).max()
    fa_fi, fb_fi = thermal_element_vector(D, 1.7, m, "hex8fi")
    assert fb_fi.size == 0 and np.abs(fa - fa_fi).max() < 1e-14 * np.abs(fa).max()


def test_thermal_element_load_is_v_b0t_d_m():
    """For a constant strain on a cube the Gauss sum equals V B0^T D m (B is linear in each coordinate)."""
    from anneal.fem import hex8_matrices
    D = elasticity_D(0.3)
    m = thermal_strain(2e-5)
    _, B0, _ = hex8_matrices(0.3, 2.0, element="hex8fi")
    fa, _ = thermal_element_vector(D, 2.0, m, "e9")
    assert np.abs(fa - 8.0 * B0.T @ D @ m).max() < 1e-15


@pytest.mark.parametrize("element", ["e9", "hex8fi"])
def test_thermal_nodal_forces_sum_to_zero_for_any_active_set(element):
    rng = np.random.default_rng(3)
    g = Grid((7, 5, 4), 1.5, (0, 0, 0))
    active = rng.random(g.nelem) > 0.4
    fem = FEM(g, active, [], 0.3, element=element)
    fhat = fem.thermal_vector(thermal_strain(2e-5))
    Ee = 70000.0 * rng.uniform(0.05, 1.0, fem.act.size)
    f = fem.thermal_load(fhat, Ee * rng.uniform(-80, 80, fem.act.size)).reshape(-1, 3)
    scale = np.abs(f).sum()
    assert scale > 0 and np.abs(f.sum(0)).max() < 1e-13 * scale
    xyz = g.node_coords(np.arange(g.nnode))
    assert np.abs(np.cross(xyz, f).sum(0)).max() < 1e-12 * scale * g.h * max(g.shape)   # no net moment


def test_stress_with_eps0_default_is_unchanged():
    g = Grid((3, 2, 2), 1.0, (0, 0, 0))
    fem = FEM(g, np.ones(g.nelem, bool), [], 0.3)
    u = np.random.default_rng(0).normal(size=3 * g.nnode)
    a = fem.stress(u, 1000.0)
    assert np.array_equal(a, fem.stress(u, 1000.0, None))
    m = thermal_strain(1e-3)
    assert np.allclose(fem.stress(u, 1000.0, m), a - 1000.0 * (fem.D @ m))


def test_thermal_strain_rotates_with_the_build_direction():
    assert np.array_equal(thermal_strain(2e-5), [2e-5, 2e-5, 2e-5, 0, 0, 0])
    assert np.allclose(thermal_strain(2e-5, 5e-5, (0, 0, 1)), [2e-5, 2e-5, 5e-5, 0, 0, 0], atol=1e-20)
    assert np.allclose(thermal_strain(2e-5, 5e-5, (1, 0, 0)), [5e-5, 2e-5, 2e-5, 0, 0, 0], atol=1e-20)
    d = np.array([1.0, 1.0, 0.0]) / np.sqrt(2)          # tilted: shear term 2 * 0.5 * (5e-5 - 2e-5)
    assert np.allclose(thermal_strain(2e-5, 5e-5, d), [3.5e-5, 3.5e-5, 2e-5, 3e-5, 0, 0], atol=1e-20)


def _trun(tmp_path, name="t", **over):
    from anneal.run import run
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(_bar_spec(**over)))
    rec, _ = run(str(p), str(tmp_path / name), log=lambda *a: None, db_path=False)
    return rec


def test_thermal_run_end_to_end(tmp_path):
    rec = _trun(tmp_path, thermal={"cases": {"main": 70, "cold": -20}},
                limits={"maxDisplacementMM": 5.0, "minSafetyFactor": 1.0})
    o = rec["results"]["optimized"]
    hot, cold = o["cases"]["main"], o["cases"]["cold"]
    assert hot["deltaTC"] == 50 and cold["deltaTC"] == -40 and cold["thermalOnly"] and not hot["thermalOnly"]
    assert cold["mechanicalDisplacementMM"] == 0 and cold["complianceNmm"] == 0
    assert cold["maxDisplacementMM"] == 0                       # the limit checks the mechanical part
    assert cold["thermalDisplacementMM"] > 0 and cold["thermalStressShare"] == 1.0
    assert hot["maxDisplacementMM"] == hot["mechanicalDisplacementMM"] > 0
    assert o["thermalDisplacementMM"] == max(hot["thermalDisplacementMM"], cold["thermalDisplacementMM"])
    assert o["thermal"]["referenceTempC"] == 20 and o["thermal"]["displacementLimitUses"] == "mechanical"


def test_mechanical_part_of_a_thermal_case_equals_the_case_without_temperature(tmp_path):
    """Linear superposition: the extra right-hand side (mechanical load alone) gives the run at 20 °C."""
    m = {k: v for k, v in TEST_MAT.items() if k != "tempDerating"}        # no derating: same E at 70 °C
    a = _trun(tmp_path, "a", material=m)["results"]["optimized"]["cases"]["main"]
    b = _trun(tmp_path, "b", material=m, thermal={"cases": {"main": 70}})["results"]["optimized"]["cases"]["main"]
    assert b["mechanicalDisplacementMM"] == pytest.approx(a["maxDisplacementMM"], rel=1e-6)
    assert b["complianceNmm"] == pytest.approx(a["complianceNmm"], rel=1e-6)
    assert b["peakStressMechanicalMPa"] == pytest.approx(a["peakStressMPa"], rel=1e-6)


# ------------------------------------------------------------------ H8, H9, H11: study, report, check rows, statements
@pytest.fixture(scope="module")
def hot_run(tmp_path_factory):
    """One run for the output tests: a hot mechanical case and a cold thermal-only case, report and advanced
    output on, two fixed anchors held in x, y and z (the held-supports warning must appear)."""
    import os
    os.environ["ANNEAL_HOME"] = str(tmp_path_factory.mktemp("home"))
    from anneal.run import run
    d = tmp_path_factory.mktemp("hot")
    s = _bar_spec(thermal={"cases": {"main": 70, "cold": -20}},
                  limits={"maxDisplacementMM": 5.0, "minSafetyFactor": 1.0},
                  output={"report": True, "advanced": True, "formats": ["stl"]})
    s["anchors"].insert(1, {"name": "wall-2", "role": "fixed",
                            "region": {"type": "box", "min": [19.1, -1, -1], "max": [20.9, 11, 0.9]}})
    p = d / "hot.json"
    p.write_text(json.dumps(s))
    rec, html = run(str(p), str(d / "out"), log=lambda *a: None, db_path=False)
    return rec, open(html, encoding="utf-8").read()


def test_fea_study_reports_temperature_and_thermal_reactions(hot_run):
    rec, _ = hot_run
    f = rec["results"]["optimized"]["fea"]["cases"]
    hot, cold = f["main"], f["cold"]
    assert hot["temperatureC"] == 70 and hot["deltaTC"] == 50 and cold["deltaTC"] == -40
    assert hot["deratingE"] == pytest.approx(0.75) and hot["EMPa"] == pytest.approx(52500)
    assert hot["uresThermalMaxMM"] > 0 and cold["uresMechanicalMaxMM"] == 0
    # the thermal load has no net force: its support reactions cancel (to the solver tolerance)
    R = np.sum([v for v in hot["reactionsThermalN"].values()], axis=0)
    assert np.abs(R).max() < 1e-6 * hot["thermalNodalForceAbsSumN"]
    # mechanical + thermal case: equilibrium against the applied mechanical load
    assert hot["equilibriumError"] < 1e-6


def test_report_shows_temperature_assumptions_and_limits(hot_run):
    rec, html = hot_run
    for words in ("<h2>Temperature</h2>", "Mechanical displacement, mm", "Thermal displacement, mm",
                  "used the mechanical loads only", "one uniform temperature per load case",
                  "E and yield derated at the case temperature", "creep and stress relaxation",
                  "temperature gradients and heat flow", "slip in bolted joints", "from the thermal load"):
        assert words in html, words
    assert "<li>temperature and thermal stress</li>" not in html
    from anneal.fea import report_lines
    text = "\n".join(report_lines(rec["results"]["optimized"]["fea"]))
    assert "temperature 70 °C" in text and "from the thermal load" in text


def test_thermal_check_rows_appear_and_held_supports_warn(hot_run):
    rec, html = hot_run
    names = {c["name"]: c for c in rec["checks"]}
    svc = names["Service temperature vs material limit"]
    assert svc["ok"] and "main 70 °C (margin 80 K)" in svc["value"] and not svc["warn"]
    assert "Thermal stress share" in names and "cold 100 %" in names["Thermal stress share"]["value"]
    held = names["Held supports and thermal expansion"]
    assert held["warn"] and "wall, wall-2" in held["value"] and "bolt-axis direction" in held["fix"]
    assert "thermal expansion" in names[next(n for n in names if n.startswith("Maximum displacement"))]["value"]


def _fake_built(temps, share=0.2):
    cases = {c: {"temperatureC": t, "deltaTC": t - 20, "thermalStressShare": share} for c, t in temps.items()}
    return {"thermal": {"cases": cases}, "cases": cases}


def test_held_supports_warning_only_with_two_fully_held_anchors():
    from anneal.run import thermal_checks
    p = _prob(thermal={"cases": {"main": 70}})
    names = [r["name"] for r in thermal_checks(p, _fake_built({"main": 70}), [])]
    assert "Held supports and thermal expansion" not in names          # one fixed anchor only
    s = _bar_spec(thermal={"cases": {"main": 70}})
    s["anchors"].append({"name": "end2", "role": "fixed", "dofs": "xyz",
                         "region": {"type": "box", "min": [19.1, -1, -1], "max": [20.9, 11, 0.9]}})
    p2 = Problem(spec=s, log=lambda *a: None)
    assert "Held supports and thermal expansion" in [r["name"] for r in thermal_checks(p2, _fake_built({"main": 70}), [])]
    s["anchors"][-1]["dofs"] = "z"                                     # the joint can slide in x and y
    p3 = Problem(spec=s, log=lambda *a: None)
    assert "Held supports and thermal expansion" not in [r["name"] for r in thermal_checks(p3, _fake_built({"main": 70}), [])]


def test_service_row_warns_for_a_warm_polymer_without_derating_and_without_a_limit():
    from anneal.run import thermal_checks
    # TEST-ONLY polymer-like values (not real data)
    poly = {"E": 3000.0, "nu": 0.35, "density": 1.2, "yield": 50.0, "alpha": 7e-5, "maxServiceTempC": 55.0}
    row = thermal_checks(_prob(material=poly, thermal={"cases": {"main": 40}}), _fake_built({"main": 40}), [])[0]
    assert row["ok"] and row["warn"] and "room-temperature E and yield are used up to 40 °C" in row["fix"]
    nolim = {k: v for k, v in poly.items() if k != "maxServiceTempC"}
    row = thermal_checks(_prob(material=nolim, thermal={"cases": {"main": 15}}), _fake_built({"main": 15}), [])[0]
    assert row["warn"] and "no maxServiceTempC" in row["fix"] and row["limit"] == "no limit in the material"
    share = thermal_checks(_prob(thermal={"cases": {"main": 70}}), _fake_built({"main": 70}, 0.8), [])[1]
    assert share["name"] == "Thermal stress share" and share["warn"] and "slide" in share["fix"]


# ------------------------------------------------------------------ H7: buckling with thermal pre-stress
@pytest.mark.parametrize("element", ["e9", "hex8fi"])
def test_heated_column_held_at_both_ends_buckles_at_the_euler_temperature(element):
    """Column 4 x 4 x 60 voxels, both ends held axially (every end node in z: the end faces stay plane, so the
    ends cannot turn) with the centre line held sideways at both ends, heated by 1 K, no mechanical load.
    That is a clamped-clamped column whose sides can expand freely (no extra lateral stress at the ends).
    The buckling factor is the critical temperature rise dT_cr = pi^2 I / (alpha A L_eff^2), L_eff = 0.5 L,
    with the shear correction of a short column (Engesser): / (1 + P_e / (5/6 G A)), here 4.4 %.
    Measured (factor / shear-corrected Euler): L = 60: e9 0.9922, hex8fi raw 1.0248;
    L = 120: e9 0.9979, hex8fi 1.0313 (against plain Euler at L = 120: e9 0.987, the 1.1 % shear effect).
    Tolerance as V7: e9 within 1 %; hex8fi times the locking factor (as run.py reports it) conservative,
    0 to -3 %. With the ends held in all directions instead, the lateral expansion is also held there and
    the factor falls a further 1.3 % (e9 0.936 of plain Euler): that is a different problem, not an error."""
    from anneal.run import locking_factor
    from anneal.physics import buckling
    a, L, E, alpha = 4, 60, 1000.0, 1e-5
    g = Grid((a, a, L), 1.0, (0, 0, 0))
    p = g.node_coords(np.arange(g.nnode))
    ends = np.flatnonzero((p[:, 2] < 1e-9) | (p[:, 2] > L - 1e-9))
    axis = np.flatnonzero((abs(p[:, 0] - a / 2) < 1e-9) & (abs(p[:, 1] - a / 2) < 1e-9)
                          & ((p[:, 2] < 1e-9) | (p[:, 2] > L - 1e-9)))
    twist = np.flatnonzero((p[:, 0] < 1e-9) & (abs(p[:, 1] - a / 2) < 1e-9) & (p[:, 2] < 1e-9))
    fixed = list(3 * ends + 2) + list(3 * axis) + list(3 * axis + 1) + list(3 * twist + 1)
    fem = FEM(g, np.ones(g.nelem, bool), fixed, 0.3, element=element)
    m = thermal_strain(alpha)
    Ee = np.full(g.nelem, E)
    K = fem.assemble(Ee)
    u = fem.solve(K, [fem.reduce_load(fem.thermal_load(fem.thermal_vector(m), Ee * 1.0))], rtol=1e-12)[0]
    lam, _ = buckling(fem, K, u, Ee, eps0=m)
    A, I, nu = a * a, a ** 4 / 12, 0.3
    Pe = np.pi ** 2 * E * I / (0.5 * L) ** 2
    exact = Pe / (E * A * alpha) / (1 + Pe / (5 / 6 * E / (2 * (1 + nu)) * A))
    r = lam[0] / exact
    if element == "e9":
        assert abs(r - 1) < 0.01, r
    else:
        rc = r * locking_factor(a, "hex8fi")
        assert -0.03 <= rc - 1 <= 0.0, rc


# ------------------------------------------------------------------ H4: derating
def test_derate_interpolates_the_table_linearly():
    from anneal.physics import derate
    assert derate(TEST_MAT, 20) == (1.0, 1.0)
    assert derate(TEST_MAT, 70) == pytest.approx((0.75, 0.75))           # half way from 20 (1.0) to 120 (0.5)
    assert derate(TEST_MAT, 135) == pytest.approx((0.45, 0.45))
    assert derate({k: v for k, v in TEST_MAT.items() if k != "tempDerating"}, 135) == (1.0, 1.0)


def test_derating_factor_half_doubles_displacement_and_halves_yield(tmp_path):
    """TEST-ONLY table: factor 0.5 at 120 °C. The mechanical displacement doubles; the yield halves; the
    mechanical stress is unchanged (same loads on the same shape)."""
    a = _trun(tmp_path, "a")["results"]["optimized"]
    b = _trun(tmp_path, "b", thermal={"cases": {"main": 120}})["results"]["optimized"]
    ca, cb = a["cases"]["main"], b["cases"]["main"]
    assert cb["deratingE"] == 0.5 and cb["EMPa"] == 35000 and cb["yieldMPa"] == 100
    assert cb["mechanicalDisplacementMM"] == pytest.approx(2 * ca["maxDisplacementMM"], rel=1e-6)
    assert cb["peakStressMechanicalMPa"] == pytest.approx(ca["peakStressMPa"], rel=1e-6)
    assert cb["safetyFactor"] == pytest.approx(100.0 / cb["peakStressMPa"])
    assert b["safetyFactor"] == cb["safetyFactor"]


def test_impact_uses_the_derated_stiffness_of_the_case_it_names():
    from anneal.run import impact_check
    spec = _bar_spec(thermal={"cases": {"main": 120}},
                     impact={"hit": {"anchor": "tip", "massKg": 1.0, "speedMS": 1.0, "direction": [-1, 0, 0]}})
    p = Problem(spec=spec, log=lambda *a: None).build()
    fill = np.where(p.active, 1.0, 0.0)
    cold = impact_check(p, fill, 1.0, lambda *a: None)["hit"]
    p.spec["impact"]["hit"]["case"] = "main"
    hot = impact_check(p, fill, 1.0, lambda *a: None)["hit"]
    assert hot["stiffnessNperMM"] == pytest.approx(0.5 * cold["stiffnessNperMM"], rel=1e-6)
    assert hot["peakForceN"] == pytest.approx(cold["peakForceN"] / np.sqrt(2), rel=1e-6)
    assert hot["safetyFactor"] == pytest.approx(cold["safetyFactor"] * 0.5 * np.sqrt(2), rel=1e-6)
    assert hot["temperatureC"] == 120
    p.spec["impact"]["hit"]["case"] = "nope"
    from anneal.physics import PhysicsError
    with pytest.raises(PhysicsError, match="case 'nope'"):
        impact_check(p, fill, 1.0, lambda *a: None)
