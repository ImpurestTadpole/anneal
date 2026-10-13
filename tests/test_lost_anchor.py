"""As-built check: a finishing step that cuts off an anchor must not lose the run (owner crash, 0.4.2 preview:
"The optimized part lost contact with anchor 'load-2'" after exact features cut 3 keep-outs)."""
import json

import numpy as np
import pytest
import trimesh

from anneal.problem import Problem
from anneal.run import evaluate

from test_core import _spec


def _prob():
    return Problem(spec=_spec(), log=lambda *a: None).build()


def _bar(p, x_gap=None, x_end=None):
    """Fill of the full design box, with an empty slab at x_gap or nothing beyond x_end (mm)."""
    g = p.grid
    xc = g.origin[0] + (np.indices(g.shape)[0] + 0.5) * g.h
    f = np.ones(g.shape)
    if x_gap is not None:
        f[np.abs(xc - x_gap) < 1.0] = 0.0
    if x_end is not None:
        f[xc > x_end] = 0.0
    return g.to1d(f) * p.active


def test_lost_anchors_causes():
    p = _prob()
    assert p.lost_anchors(_bar(p)) == []
    assert p.lost_anchors(_bar(p, x_gap=20)) == [("tip", "not connected")]
    assert p.lost_anchors(_bar(p, x_end=30)) == [("tip", "no material")]


def test_evaluate_names_the_cause():
    p = _prob()
    with pytest.raises(RuntimeError, match="does not connect anchor 'tip' to a support"):
        evaluate(p, _bar(p, x_gap=20), "Optimized (as built)", lambda *a: None)
    with pytest.raises(RuntimeError, match="has no material at anchor 'tip'"):
        evaluate(p, _bar(p, x_end=30), "Optimized (as built)", lambda *a: None)


def test_run_falls_back_to_smooth_surface(tmp_path, monkeypatch):
    """Exact finishing that cuts the bar in two: the run ends on the smooth surface and says why."""
    import anneal.finish as F
    from anneal.run import run

    def cutting_finish(prob, surf, log=print):
        cut = trimesh.creation.box(bounds=[[18, -5, -5], [22, 15, 15]])
        out = trimesh.boolean.difference([surf, cut], engine="manifold")
        return out, {"kept": [], "cut": ["keep-out 1"]}

    monkeypatch.setattr(F, "finish", cutting_finish)
    spec = tmp_path / "beam.json"
    spec.write_text(json.dumps(_spec(optimizer={"iterations": 8}, output={"exactFeatures": True})))
    record, _ = run(str(spec), str(tmp_path / "out"), log=lambda *a: None)
    ex = record["derived"]["exactFeatures"]
    assert "cut off anchor 'tip' (not connected)" in ex["skipped"]
    assert record["results"]["optimized"]["maxDisplacementMM"] > 0
