"""GUI back end: picking, history database, and the HTTP API (no browser needed)."""
import json
import os
import urllib.request

import numpy as np
import pytest

from anneal import db
from anneal.geometry import load_mesh
from anneal.pick import pick

HERE = os.path.dirname(os.path.abspath(__file__))
STL = os.path.join(HERE, "..", "examples", "bracket.stl")


@pytest.fixture(scope="module")
def bracket():
    return load_mesh(STL, log=lambda *a: None)


def _face_near(m, p):
    return int(np.argmin(np.linalg.norm(m.triangles_center - np.asarray(p), axis=1)))


def test_pick_hole(bracket):
    f = _face_near(bracket, (5, 10, 10 - 3.3))
    r = pick(bracket, f, bracket.triangles_center[f], pad=1.0)
    assert r["kind"] == "hole"
    assert abs(r["radius"] - 3.3) < 0.05
    assert r["region"]["type"] == "pipe" and r["region"]["rIn"] < 3.3 < r["region"]["r"]


def test_pick_flat_face(bracket):
    f = _face_near(bracket, (0, 30, 30))
    r = pick(bracket, f, bracket.triangles_center[f], pad=1.0)
    assert r["kind"] == "face" and r["region"]["type"] == "obox"
    assert np.allclose(np.abs(r["normal"]), [1, 0, 0], atol=1e-3)


def test_pick_patch(bracket):
    f = _face_near(bracket, (60, 30, 60))
    r = pick(bracket, f, (60, 30, 60), pad=1.0, mode="patch", patch_r=5)
    assert r["kind"] == "patch" and r["region"] == {"type": "sphere", "center": [60.0, 30.0, 60.0], "r": 5.0}


def test_history_roundtrip(tmp_path):
    run_dir = tmp_path / "proj" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    rec = {"createdUTC": "2026-10-12T00:00:00Z", "anneal": "x", "material": {"name": "PLA-FDM"},
           "derived": {"voxelMM": 1.0}, "passes": [{"volumeFraction": 0.3, "massG": 10.0}], "totalSeconds": 5,
           "checks": [{"ok": True}],
           "results": {"optimized": {"massG": 10.0, "maxDisplacementMM": 0.1, "safetyFactor": 3.0,
                                     "cases": {"main": {"complianceNmm": 2.0}}},
                       "original": {"massG": 30.0, "cases": {"main": {"complianceNmm": 1.0}}}}}
    (run_dir / "spec.json").write_text(json.dumps({"name": "proj", "objective": {"minimise": "mass"},
                                                   "limits": {"maxDisplacementMM": 0.2}}))
    (run_dir / "run.json").write_text(json.dumps(rec))
    path = str(tmp_path / "a.db")
    assert db.index_workspace(str(tmp_path), path) == 1
    rows = db.query(path)
    assert len(rows) == 1 and rows[0]["goal"] == "mass" and abs(rows[0]["stiffness_per_gram"] - 1.5) < 1e-9
    db.annotate(rows[0]["run_dir"], star=True, note="printed", path=path)
    db.record_run(str(run_dir), rec, "proj", path)            # re-record keeps star and note
    r = db.query(path, star=True)[0]
    assert r["note"] == "printed" and r["volume_fraction"] == 0.3


def test_api_project_pick_save(tmp_path):
    from anneal.gui.server import start_server
    srv, url, app = start_server(str(tmp_path), port=18765)
    try:
        with open(STL, "rb") as fh:
            req = urllib.request.Request(url + "api/projects", data=fh.read(), method="POST",
                                         headers={"X-Filename": "bracket.stl"})
        p = json.load(urllib.request.urlopen(req))
        assert p["id"] == "bracket" and p["watertight"]
        m = app.mesh("bracket")
        f = _face_near(m, (95, 30, 34))
        body = json.dumps({"face": f, "point": m.triangles_center[f].tolist(), "mode": "auto"}).encode()
        r = json.load(urllib.request.urlopen(urllib.request.Request(
            url + "api/projects/bracket/pick", data=body, method="POST", headers={"Content-Type": "application/json"})))
        assert r["kind"] == "hole" and abs(r["radius"] - 6.0) < 0.1
        spec = {"model": "bracket.stl", "anchors": []}
        urllib.request.urlopen(urllib.request.Request(url + "api/projects/bracket/save",
                               data=json.dumps({"spec": spec, "gui": {"anchors": []}}).encode(), method="POST"))
        assert os.path.isfile(tmp_path / "bracket" / "bracket.anneal.json")
        st = json.load(urllib.request.urlopen(url + "api/state"))
        assert st["projects"][0]["id"] == "bracket"
    finally:
        srv.shutdown()
