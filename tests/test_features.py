"""0.4 feature tools: picking on coarse meshes, face-outline regions, exact geometry, growing from
interfaces, bolt access, and the Windows taskbar icon hooks."""
import json
import sys
import types
import numpy as np
import pytest
import trimesh

from anneal.pick import pick
from anneal.kernel import make_region


@pytest.fixture(autouse=True)
def lib_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNEAL_HOME", str(tmp_path / "home"))


def _plate_with_hole(sections):
    box = trimesh.creation.box(extents=[40, 40, 10])
    box.apply_translation([0, 0, 5])
    cyl = trimesh.creation.cylinder(radius=3, height=30, sections=sections)
    cyl.apply_translation([8, 5, 5])
    boss = trimesh.creation.cylinder(radius=4, height=6, sections=sections)
    boss.apply_translation([-10, -10, 13])
    return box.difference(cyl, engine="manifold").union(boss, engine="manifold")


@pytest.mark.parametrize("sections", [6, 8, 12, 64])
def test_holes_and_bosses_are_recognised_on_coarse_meshes(sections):
    m = _plate_with_hole(sections)
    c = m.triangles_center
    d = np.linalg.norm(c[:, :2] - [8, 5], axis=1)
    f = int(np.flatnonzero((d < 3.05) & (abs(c[:, 2] - 5) < 4))[0])
    r = pick(m, f, c[f], pad=1.0)
    assert r["kind"] == "hole" and r["radius"] == pytest.approx(3.0, abs=0.01)
    assert r["region"]["type"] == "pipe" and r["region"]["rIn"] < 3.0 < r["region"]["r"]
    db = np.linalg.norm(c[:, :2] - [-10, -10], axis=1)
    fb = int(np.flatnonzero((db < 4.05) & (db > 3.0) & (abs(c[:, 2] - 13) < 2.5))[0])
    assert pick(m, fb, c[fb], pad=1.0)["kind"] == "boss"


def test_face_pick_fits_the_face_and_carries_its_outline():
    m = _plate_with_hole(8)
    c = m.triangles_center
    top = np.flatnonzero((abs(c[:, 2] - 10) < 1e-6) & (m.face_normals[:, 2] > 0.99))
    f = int(top[np.argmax(m.area_faces[top])])
    r = pick(m, f, c[f], pad=1.0)
    assert r["kind"] == "face"
    assert sorted(r["region"]["size"][:2]) == pytest.approx([42, 42])      # 40 x 40 face + 2 x pad
    o = r["outline"]
    P = make_region({"type": "prism", "origin": o["origin"], "normal": o["normal"], "xdir": o["xdir"],
                     "tris": o["tris"], "z0": 0, "z1": 5})
    pts = np.array([[0, -10, 12], [8, 5, 12], [25, 0, 12], [0, -10, 9]])
    s = P.sdf(pts)
    assert s[0] < 0                    # above the face, inside the extrusion
    assert s[1] > 0                    # above the hole: the hole is not part of the face
    assert s[2] == pytest.approx(5.0, abs=1e-6)   # 5 mm beside the face edge
    assert s[3] == pytest.approx(1.0, abs=1e-6)   # 1 mm below the face
    assert P.mesh().is_watertight


def _small_spec(tmp_path, **over):
    m = _plate_with_hole(16)
    stl = tmp_path / "plate.stl"
    m.export(stl)
    s = {"name": "p", "model": str(stl), "material": "AlSi10Mg-LPBF", "resolution": {"voxelMM": 1.0},
         "anchors": [{"name": "bolt", "role": "fixed", "hole": True,
                      "region": {"type": "pipe", "from": [8, 5, 0], "to": [8, 5, 10], "r": 4.0, "rIn": 2.0}},
                     {"name": "edge", "role": "load", "region": {"type": "box", "min": [-21, -21, -1], "max": [-19.5, 21, 11]},
                      "loads": {"down": [0, 0, -100]}}],
         "objective": {"volumeFraction": 0.5}, "optimizer": {"iterations": 12},
         "output": {"report": False, "formats": ["stl"], "exactFeatures": True}}
    s.update(over)
    p = tmp_path / "p.json"
    p.write_text(json.dumps(s))
    return str(p)


def _hole_radii(m, centre_xy, z0, z1):
    """Radii of the hole-wall vertices (vertices of faces with a horizontal normal; flat top and
    bottom faces, which sharp edges keep, are not part of the wall)."""
    wall = np.unique(m.faces[np.abs(m.face_normals[:, 2]) < 0.1])
    v = m.vertices[wall]
    sel = (v[:, 2] > z0 - 0.01) & (v[:, 2] < z1 + 0.01)
    d = np.hypot(v[sel, 0] - centre_xy[0], v[sel, 1] - centre_xy[1])
    return d[d < 3.5]


def test_exact_features_restore_the_hole(tmp_path):
    from anneal.run import run
    rec, _ = run(_small_spec(tmp_path), str(tmp_path / "out"), log=lambda *a: None, db_path=False)
    m = trimesh.load(tmp_path / "out" / "p-optimized.stl")
    assert m.is_watertight
    r = _hole_radii(m, (8, 5), 0, 10)
    assert r.size > 20 and r.min() == pytest.approx(3.0, abs=1e-3) and r.max() == pytest.approx(3.0, abs=1e-3)
    ex = rec["derived"]["exactFeatures"]
    assert "bolt" in ex["kept"] and "skipped" not in ex
    assert any(c["name"].startswith("Exact geometry") and c["ok"] for c in rec["checks"])


def test_exact_features_on_by_default_in_spec_files(tmp_path):
    """0.4.2: exact geometry and sharp edges are the default; exactFeatures false turns it off."""
    from anneal.run import run
    p = _small_spec(tmp_path, output={"report": False, "formats": ["stl"]})
    rec, _ = run(p, str(tmp_path / "out"), log=lambda *a: None, db_path=False)
    assert "bolt" in rec["derived"]["exactFeatures"]["kept"]
    p = _small_spec(tmp_path, output={"report": False, "formats": ["stl"], "exactFeatures": False})
    rec, _ = run(p, str(tmp_path / "out2"), log=lambda *a: None, db_path=False)
    assert "exactFeatures" not in rec["derived"]


def test_hole_anchor_keeps_hole_and_bolt_room_open_in_a_grown_space(tmp_path):
    from anneal.problem import Problem
    s = json.loads(open(_small_spec(tmp_path, designSpace={"type": "bounds", "marginMM": 6})).read())
    s["anchors"][0]["boltAccessMM"] = 5
    p = Problem(spec=s, log=lambda *a: None).build()
    c = p.grid.elem_centers()
    in_hole = (np.hypot(c[:, 0] - 8, c[:, 1] - 5) < 2.0) & (c[:, 2] > 1) & (c[:, 2] < 9)
    above = (np.hypot(c[:, 0] - 8, c[:, 1] - 5) < 4.0) & (c[:, 2] > 11) & (c[:, 2] < 14)
    assert p.fill[in_hole].max() == 0 and p.fill[above].max() == 0
    beside = (np.hypot(c[:, 0] - 8, c[:, 1] - 5) > 8) & (c[:, 2] > 11) & (c[:, 2] < 14)
    assert p.fill[beside].max() > 0.9                                     # the grown space is there


def test_grow_from_interfaces(tmp_path):
    """Two separate blocks, kept as they are; the optimizer adds material to join them."""
    from anneal.run import run
    a = trimesh.creation.box(extents=[4, 20, 20])
    a.apply_translation([2, 10, 10])
    b = trimesh.creation.box(extents=[6, 6, 6])
    b.apply_translation([33, 10, 10])
    stl = tmp_path / "parts.stl"
    trimesh.util.concatenate([a, b]).export(stl)
    s = {"name": "g", "model": str(stl), "material": "AlSi10Mg-LPBF", "resolution": {"voxelMM": 1.0},
         "designSpace": {"type": "bounds", "marginMM": 0, "keepModel": True},
         "anchors": [{"name": "wall", "role": "fixed", "region": {"type": "box", "min": [-1, -1, -1], "max": [0.4, 21, 21]}},
                     {"name": "tip", "role": "load", "region": {"type": "box", "min": [35.6, 6, 6], "max": [37, 14, 14]},
                      "loads": {"down": [0, 0, -200]}}],
         "objective": {"volumeFraction": 0.3}, "optimizer": {"iterations": 15},
         "output": {"report": False, "formats": ["stl"], "exactFeatures": True}}
    p = tmp_path / "g.json"
    p.write_text(json.dumps(s))
    rec, _ = run(str(p), str(tmp_path / "out"), log=lambda *a: None, db_path=False)
    m = trimesh.load(tmp_path / "out" / "g-optimized.stl")
    assert m.is_watertight and len(m.split(only_watertight=False)) == 1        # one connected part
    model_vol = a.volume + b.volume
    assert m.volume > 1.5 * model_vol                                          # material was added
    for blk in (a, b):                                                         # both blocks fully kept
        both = trimesh.boolean.intersection([m, blk], engine="manifold")
        assert both.volume == pytest.approx(blk.volume, rel=1e-3)
    assert rec["derived"]["exactFeatures"]["kept"][0] == "whole model"


def test_taskbar_icon_hooks(monkeypatch):
    from anneal.gui import desktop
    assert desktop.set_app_id() is False or sys.platform.startswith("win")
    calls = []

    class Form:
        Icon = None

        def BeginInvoke(self, action):          # S2: the icon is set without blocking the UI thread
            action()
    System = types.ModuleType("System")
    System.Action = lambda f: f
    drawing = types.ModuleType("System.Drawing")
    drawing.Icon = lambda path: calls.append(path) or ("icon", path)
    monkeypatch.setitem(sys.modules, "System", System)
    monkeypatch.setitem(sys.modules, "System.Drawing", drawing)
    monkeypatch.setattr(sys, "platform", "win32")
    win = types.SimpleNamespace(native=Form())
    assert desktop.set_window_icon(win) is True
    assert calls == [desktop.ICON_ICO] and win.native.Icon == ("icon", desktop.ICON_ICO)


def test_keep_regions_never_add_material(tmp_path):
    """A keep sphere that sticks out of the part keeps only the part's own material (no bubble)."""
    from anneal.problem import Problem
    s = json.loads(open(_small_spec(tmp_path)).read())
    s["keep"] = [{"type": "sphere", "center": [-20, 0, 10], "r": 6}]      # on the top edge: half outside
    p = Problem(spec=s, log=lambda *a: None).build()
    c = p.grid.elem_centers()
    outside = (np.linalg.norm(c - [-20, 0, 10], axis=1) < 5) & ((c[:, 2] > 10.5) | (c[:, 0] < -20.5))
    inside = (np.linalg.norm(c - [-20, 0, 10], axis=1) < 5) & (c[:, 2] < 9.5) & (c[:, 0] > -19.5)
    assert p.fill[outside].max() == 0                       # nothing added outside the model
    assert p.frozen[inside].all()                           # the model's own material there is kept
    for kind in ("bounds", "hull"):                         # also when the design space may grow
        s2 = dict(s, designSpace={"type": kind, "marginMM": 8})
        p2 = Problem(spec=s2, log=lambda *a: None).build()
        c2 = p2.grid.elem_centers()
        out2 = (np.linalg.norm(c2 - [-20, 0, 10], axis=1) < 5) & ((c2[:, 2] > 10.5) | (c2[:, 0] < -20.5))
        assert not p2.frozen[out2].any()
