"""Like-for-like stress cross-check (0.4.2, H10): Anneal as-built re-solve of the exported STL at 2, 1 and 0.67 mm
voxels vs CalculiX tet10, both as element-centre von Mises (CalculiX: mean of the 4 integration points), both
leaving out everything within EXCL mm of an anchor region; also the thermal and total displacement.
Run tools/ccx_bracket.py first (it writes the decks and .dat files with stresses for a thermal spec).
Usage: python tools/ccx_thermal_xcheck.py <run_dir> <ccx_workdir>   (run_dir: an Anneal run folder with
spec.json and the -optimized.stl)"""
import json
import os
import re
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from anneal.problem import Problem
from anneal.run import evaluate

run_dir, wd = sys.argv[1:3]
EXCL = 3.0
spec = json.load(open(os.path.join(run_dir, "spec.json")))         # the run copies its spec here
stl = [f for f in os.listdir(run_dir) if f.endswith("-optimized.stl")][0]


def vm6(S):
    sx, sy, sz, a, b, c = S.T
    return np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3 * (a * a + b * b + c * c))


# CalculiX: element-centre stress = mean over the 4 integration points of each C3D10
nodes, elems, mode = {}, [], None
for line in open(os.path.join(wd, "mesh.inp")):
    if line.startswith("*"):
        u = line.upper()
        mode = "n" if u.startswith("*NODE") else ("e" if "C3D10" in u else None)
        continue
    if mode == "n":
        p = line.split(",")
        nodes[int(p[0])] = [float(v) for v in p[1:4]]
    elif mode == "e":
        elems.append([int(v) for v in line.replace(" ", "").rstrip(",\n").split(",") if v])
cen = {e[0]: np.mean([nodes[n] for n in e[1:5]], axis=0) for e in elems}
vol = {e[0]: abs(np.linalg.det(np.array([nodes[e[k]] for k in (2, 3, 4)]) - np.array(nodes[e[1]]))) / 6 for e in elems}
prob0 = Problem(spec=spec, log=lambda *a: None)
out = {}
for case in prob0.cases:
    txt = open(os.path.join(wd, f"static_{case}.dat")).read().split("stresses")[-1]
    rows = [l.split() for l in txt.splitlines() if re.match(r"^\s+\d+\s+\d+\s", l)]
    acc = {}
    for r in rows:
        acc.setdefault(int(r[0]), []).append([float(v) for v in r[2:8]])
    el = np.array(sorted(acc))
    S = np.array([np.mean(acc[e], axis=0) for e in el])
    C = np.array([cen[e] for e in el])
    far = np.ones(len(el), bool)
    for a in prob0.anchors:
        far &= a.region.sdf(C) > EXCL
    v = vm6(S)[far]
    w = np.array([vol[e] for e in el])[far]
    o = np.argsort(v)
    cw = np.cumsum(w[o]) / w.sum()
    out[case] = {"ccx": {"p99VolumeWeighted": float(v[o][np.searchsorted(cw, 0.99)]), "max": float(v.max()),
                         "mean": float((v * w).sum() / w.sum())}}

for h in (2.0, 1.0, 0.67):
    s = dict(spec)
    s.update({"model": os.path.join(run_dir, stl), "designSpace": "model", "resolution": {"voxelMM": h},
              "objective": {"volumeFraction": 0.95}})
    s["anchors"] = [{k: v for k, v in a.items() if k != "hole"} for a in spec["anchors"]]   # the STL has the holes
    p = Problem(spec=s, log=lambda *a: None).build()
    p.D = None
    res = evaluate(p, p.space_fill.copy(), "x", lambda *a: None)
    g = p.grid
    fill = res["_fields"]["fill"]
    for case in p.cases:
        vm = res["_fields"]["vm"][case]
        sel = fill >= 0.5
        cc = g.elem_centers()
        for a in p.anchors:
            sel &= a.region.sdf(cc) > EXCL
        v, w = vm[sel].astype(float), fill[sel]
        o = np.argsort(v)
        cw = np.cumsum(w[o]) / w.sum()
        r = res["cases"][case]
        out[case][f"anneal_{h}mm"] = {"p99VolumeWeighted": float(v[o][np.searchsorted(cw, 0.99)]), "max": float(v.max()),
                                     "mean": float((v * w).sum() / w.sum()), "totalDisplacementMM": r.get("totalDisplacementMM"),
                                     "thermalDisplacementMM": r.get("thermalDisplacementMM")}
    print(h, json.dumps({c: out[c][f"anneal_{h}mm"] for c in out}), flush=True)
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(wd, "xcheck_stress.json"), "w"), indent=1)
