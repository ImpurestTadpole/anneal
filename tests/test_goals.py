"""Goals in percent of the original part (goals.massPct, displacementPct, strainPct)."""
import json
import os

import pytest

from anneal.problem import Problem, SpecError

EX = os.path.join(os.path.dirname(__file__), "..", "examples")


def _bracket(**over):
    s = json.load(open(os.path.join(EX, "bracket.json")))
    s["model"] = os.path.abspath(os.path.join(EX, "bracket.stl"))
    s.update({"resolution": "draft", "optimizer": {"iterations": 10}})
    s.update(over)
    return s


@pytest.mark.parametrize("goals,msg", [({"mass": 50}, "goals may hold only"), ({"massPct": 0}, "between 1 and 1000"),
                                       ({"strainPct": "x"}, "between 1 and 1000")])
def test_goal_spec_errors(goals, msg):
    with pytest.raises(SpecError, match=msg):
        Problem(spec=_bracket(goals=goals), log=lambda *a: None)


def test_goals_end_to_end_sharp_exact(tmp_path):
    from anneal.run import run
    spec = tmp_path / "b.json"
    out = dict(json.load(open(os.path.join(EX, "bracket.json"))).get("output", {}), edges="sharp", exactFeatures=True)
    spec.write_text(json.dumps(_bracket(goals={"massPct": 45, "displacementPct": 400, "strainPct": 400},
                                        output=out, objective={"volumeFraction": 0.3})))
    rec, _ = run(str(spec), str(tmp_path / "out"), log=lambda *a: None)
    g = rec["derived"]["goals"]
    assert set(g["targets"]) == {"massG", "maxDisplacementMM", "peakStrain"}
    rows = {c["name"]: c for c in rec["checks"] if c.get("group") == "goals"}
    assert set(rows) == {"Goal: mass", "Goal: maximum displacement", "Goal: peak strain (peak stress / E)"}
    mass_pct = 100 * rec["results"]["optimized"]["massG"] / g["original"]["massG"]
    assert 35 < mass_pct < 60          # 45 % of the original, plus frozen and exact kept material
