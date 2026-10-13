"""Solver provenance: which solver code made a result, and whether that exact code passed the
validation gate.

The solver hash is SHA-256 over the source files that decide the numbers (element, solver,
optimizer, physics, study, run). `python -m anneal validate` stores its result under that hash in
the Anneal home folder; every run records the hash and looks the result up, so a report can say
"this solver build passed the gate on <date>" or "this build has not been validated"."""
import hashlib
import json
import os
import time

from . import __version__

SOLVER_FILES = ("fem.py", "optimize.py", "physics.py", "fea.py", "run.py", "export.py", "problem.py", "validate.py")
HERE = os.path.dirname(os.path.abspath(__file__))


def solver_hash():
    h = hashlib.sha256()
    for f in SOLVER_FILES:
        with open(os.path.join(HERE, f), "rb") as fh:
            h.update(f.encode() + b"\0" + fh.read())
    return h.hexdigest()


def _cache_path(sha):
    from .paths import home
    return os.path.join(home(), ".validation", f"gate-{sha[:16]}.json")


def store_gate(passed, lines):
    sha = solver_hash()
    rec = {"solverSha256": sha, "anneal": __version__, "passed": bool(passed), "lines": list(lines),
           "createdUTC": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        p = _cache_path(sha)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=1)
    except OSError:
        pass
    return rec


def gate_status():
    sha = solver_hash()
    try:
        with open(_cache_path(sha), encoding="utf-8") as fh:
            rec = json.load(fh)
        if rec.get("solverSha256") == sha:
            return rec
    except (OSError, ValueError):
        pass
    return {"solverSha256": sha, "anneal": __version__, "passed": None, "lines": [],
            "note": "This solver build has not been validated on this computer. Run: python -m anneal validate"}


def record(element):
    g = gate_status()
    return {"anneal": __version__, "element": element, "solverSha256": g["solverSha256"],
            "files": list(SOLVER_FILES), "validation": {k: g.get(k) for k in ("passed", "createdUTC", "note", "lines")}}
