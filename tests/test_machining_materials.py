"""Wrought aluminium for machining (6061-T6, 7075-T6): library entries resolve to a CNC process."""
import pytest

from anneal import materials as M


@pytest.mark.parametrize("name,E,Y,rho", [("Al6061-T6", 68900.0, 276.0, 2.70), ("Al7075-T6", 71700.0, 503.0, 2.81)])
def test_machining_material(name, E, Y, rho):
    m = M.get_material(name)
    assert (m["E"], m["yield"], m["density"]) == (E, Y, rho)
    assert m["source"].startswith("ASM Aerospace Specification Metals")
    p = M.get_process(None, m)
    assert p["method"] == "machining" and p["axes"] == 3


def test_machining_material_with_5axis():
    p = M.get_process("CNC-5axis", M.get_material("Al7075-T6"))
    assert p["method"] == "machining" and p["axes"] == 5
