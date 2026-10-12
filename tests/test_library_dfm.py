"""Material import, process rules and printability (DFM) geometry."""
import numpy as np
import pytest
import trimesh

from anneal import materials as M
from anneal import dfm
from anneal.fem import Grid
from anneal.geometry import voxel_fill


@pytest.fixture(autouse=True)
def lib_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNEAL_HOME", str(tmp_path))
    return tmp_path


def test_csv_units_and_layer_factor():
    csv = ("Material,Tensile Modulus (GPa),Poisson's ratio,Density (kg/m3),Tensile Strength (psi),Z Strength (MPa),Process\n"
           "Test-CF,3.8,0.35,1250,7542,30,FFF\n")
    mats, problems = M.parse_import("a.csv", csv.encode())
    m = mats["Test-CF"]
    assert m["E"] == pytest.approx(3800)
    assert m["density"] == pytest.approx(1.25)
    assert m["yield"] == pytest.approx(52.0, rel=1e-3)
    assert m["zStrengthFactor"] == pytest.approx(30 / 52.0, abs=2e-3)
    assert m["process"] == "FDM"
    assert not [p for p in problems if not p.startswith("Note:")]


def test_semicolon_decimal_comma_and_bad_rows():
    csv = "name;E [MPa];nu;density;yield [MPa]\nA;2000;0,36;1,24;40\nB;;0,3;1,2;30\nC;2000;0,7;1,2;30\n"
    mats, problems = M.parse_import("b.csv", csv.encode())
    assert list(mats) == ["A"] and mats["A"]["nu"] == 0.36
    assert any("Row 3" in p and "E missing" in p for p in problems)
    assert any("Row 4" in p and "nu" in p for p in problems)


def test_e_without_unit_is_refused_when_ambiguous():
    mats, problems = M.parse_import("c.csv", b"name,E,nu,density,yield\nX,3.5,0.35,1.2,40\n")
    assert not mats and "has no unit" in problems[0]


def test_json_import_and_library_history():
    js = b'{"materials": {"ASA": {"E": "2.0 GPa", "nu": 0.35, "density": 1.07, "yield": "40 MPa", "process": "FDM"}}}'
    mats, _ = M.parse_import("lib.json", js)
    added, replaced, _ = M.add_materials(mats, source="lib.json")
    assert added == ["ASA"]
    M.add_materials(mats, source="lib.json")
    M.remove_material("ASA")
    log = M.library_log()
    assert [e["action"] for e in log] == ["removed", "replaced", "added"]
    assert log[0]["before"]["E"] == 2000.0
    with pytest.raises(M.LibraryError):
        M.remove_material("PLA-FDM")


def test_process_merge_order():
    M.add_materials({"MyPETG": {"E": 2000, "nu": 0.38, "density": 1.27, "yield": 45, "process": "FDM", "zStrengthFactor": 0.4}})
    mat = M.get_material("MyPETG")
    p = M.get_process(None, mat)
    assert p["name"] == "FDM" and p["zStrengthFactor"] == 0.4          # material beats process
    p = M.get_process({"name": "FDM", "zStrengthFactor": 0.7, "buildDirection": [1, 0, 0]}, mat)
    assert p["zStrengthFactor"] == 0.7 and p["buildDirection"] == [1, 0, 0]   # spec beats material
    assert M.get_process("none", mat) is None


def test_overhang_box_and_bridge():
    box = trimesh.creation.box(extents=[20, 20, 10])
    box.apply_translation([0, 0, 5])
    b = np.array([0.0, 0, 1])
    need, plate = dfm.overhang_faces(box, b, 45, plate_tol=0.5)
    assert need.sum() == 0 and box.area_faces[plate].sum() == pytest.approx(400)
    # a table: top 40x40x5 at z 20..25 on four 5x5 legs -> the underside between legs needs support
    parts = [trimesh.creation.box(extents=[40, 40, 5], transform=trimesh.transformations.translation_matrix([0, 0, 22.5]))]
    for x in (-17.5, 17.5):
        for y in (-17.5, 17.5):
            parts.append(trimesh.creation.box(extents=[5, 5, 20], transform=trimesh.transformations.translation_matrix([x, y, 10])))
    table = trimesh.util.concatenate(parts)   # top not merged with the legs: its whole underside faces down
    need, plate = dfm.overhang_faces(table, b, 45, plate_tol=0.5)
    assert table.area_faces[need].sum() == pytest.approx(1600)
    assert table.area_faces[plate].sum() == pytest.approx(4 * 25)   # leg feet stand on the plate
    need, _ = dfm.overhang_faces(table, -b, 45, plate_tol=0.5)   # upside down: the top is on the plate
    # only the 4 leg ends remain (they touch the top's face here because the meshes are not merged)
    assert table.area_faces[need].sum() == pytest.approx(4 * 25)


def test_support_volume_under_a_slab():
    slab = trimesh.creation.box(extents=[20, 20, 4], transform=trimesh.transformations.translation_matrix([0, 0, 12]))
    post = trimesh.creation.box(extents=[4, 4, 10], transform=trimesh.transformations.translation_matrix([0, 0, 5]))
    m = trimesh.util.concatenate([slab, post])
    h = 0.5
    g = Grid(np.ceil((m.extents + 2 * h) / h).astype(int), h, m.bounds[0] - h)
    fill = voxel_fill(slab, g)
    fill = np.maximum(fill, voxel_fill(post, g))
    need, _ = dfm.overhang_faces(m, np.array([0, 0, 1.0]), 45, 0.3)
    v = dfm.support_volume(m, need, np.array([0, 0, 1.0]), g, fill)
    assert v == pytest.approx((400 - 16) * 10, rel=0.08)


def test_enclosed_void():
    outer = trimesh.creation.box(extents=[20, 20, 20])
    h = 0.5
    g = Grid(np.ceil((outer.extents + 2 * h) / h).astype(int), h, outer.bounds[0] - h)
    fill = voxel_fill(outer, g)
    c = g.elem_centers()
    fill[np.linalg.norm(c, axis=1) < 5] = 0.0        # a closed spherical cavity
    n, vol = dfm.enclosed_voids(g, fill)
    assert n == 1 and vol == pytest.approx(4 / 3 * np.pi * 125, rel=0.1)


def test_fits_build_volume():
    assert dfm.fits([200, 100, 50], [256, 256, 256])
    assert dfm.fits([100, 300, 50], [320, 120, 100])      # turned on the plate
    assert not dfm.fits([100, 100, 300], [256, 256, 256])


def test_surface_normals_point_out():
    """Regression: the exported surface's face normals must agree with its winding and point outward."""
    from anneal.export import surface
    g = Grid((20, 20, 20), 1.0, (0, 0, 0))
    c = g.elem_centers()
    f = (np.linalg.norm(c - 10, axis=1) < 6).astype(float)
    m = surface(g, f, 0.5, upsample=2, smooth=10, log=lambda *a: None)
    tri = m.triangles
    raw = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    raw /= np.linalg.norm(raw, axis=1)[:, None]
    assert m.volume > 0
    assert np.mean(np.sum(raw * m.face_normals, 1) > 0.99) > 0.999
    out = m.triangles_center - 10
    assert np.mean(np.sum(out * m.face_normals, 1) > 0) > 0.99
