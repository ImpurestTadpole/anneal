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
