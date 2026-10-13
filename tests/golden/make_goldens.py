"""Regenerate golden values: python tests/golden/make_goldens.py <element> [--write]
Runs each golden spec and prints (or stores under that element) the fields the golden test checks."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from anneal.run import run

FIELDS = ["massG", "maxDisplacementMM", "safetyFactor"]


def measure(spec_name, element):
    with open(os.path.join(HERE, spec_name)) as fh:
        spec = json.load(fh)
    spec.setdefault("solver", {})["element"] = element
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, spec_name)
        spec["model"] = os.path.join(HERE, spec["model"]) if "model" in spec else None
        if spec["model"] is None:
            spec.pop("model")
        with open(p, "w") as fh:
            json.dump(spec, fh)
        rec, _ = run(p, os.path.join(d, "out"), log=lambda *a: None, db_path=False)
    o = rec["results"]["optimized"]
    return {**{k: o[k] for k in FIELDS}, "iterations": rec["optimizer"]["iterations"],
            "amgBuilds": rec["optimizer"]["amgBuilds"]}


if __name__ == "__main__":
    element = sys.argv[1]
    path = os.path.join(HERE, "goldens.json")
    gold = json.load(open(path)) if os.path.exists(path) else {}
    for name in ("cantilever.anneal.json", "plate_hole.anneal.json"):
        gold.setdefault(element, {})[name] = measure(name, element)
        print(element, name, gold[element][name])
    if "--write" in sys.argv:
        json.dump(gold, open(path, "w"), indent=1)
