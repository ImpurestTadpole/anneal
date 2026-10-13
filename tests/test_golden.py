"""Golden regression: two small parts run end to end and must give the stored numbers.
Slow (about 3 minutes per run): runs only with ANNEAL_GOLDEN=1, and in tools/prove_release.py.
hex8fi goldens were recorded on Anneal 0.4 before the e9 element existed, so they also prove the
legacy element still gives the earlier results. Regenerate: python tests/golden/make_goldens.py e9 --write"""
import json
import os
import sys

import pytest

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
sys.path.insert(0, HERE)
GOLD = json.load(open(os.path.join(HERE, "goldens.json")))
slow = pytest.mark.skipif(os.environ.get("ANNEAL_GOLDEN") != "1", reason="set ANNEAL_GOLDEN=1 to run the golden tests")


@slow
@pytest.mark.parametrize("element", sorted(GOLD))
@pytest.mark.parametrize("name", ["cantilever.anneal.json", "plate_hole.anneal.json",
                                  "../../examples/thermal-bracket.json"])
def test_golden(element, name):
    from make_goldens import measure
    got = measure(name, element)
    want = GOLD[element][name]
    for k in ("massG", "maxDisplacementMM", "safetyFactor", "thermalDisplacementMM", "mechanicalDisplacementMM"):
        if k not in want:
            continue
        assert got[k] == pytest.approx(want[k], rel=1e-6), k
    assert got["iterations"] == want["iterations"]
