"""Collect the 0.4.0 release evidence into verification/evidence.json.

Usage: python tools/prove_release.py <proof_dir> <baseline_run_dir> <gui_dir>
<proof_dir>/R0  : examples/bracket.json on this release (options off)
<proof_dir>/RP  : examples/bracket-pla.json (print-aware, buckling, impact, large deformation)
<proof_dir>/pytest.log, validate.log ; <proof_dir>/ccx_R0/ccx_bracket.json ; <gui_dir>/gui_smoke.json
"""
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import zipfile
import numpy as np
import scipy

P, BASE, GUI = sys.argv[1:4]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(os.path.join(root, "verification"), exist_ok=True)
J = lambda *p: json.load(open(os.path.join(*p)))
sh = lambda c: subprocess.run(c, shell=True, capture_output=True, text=True, cwd=root).stdout.strip()
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()

ev = {"commit": sh("git rev-parse HEAD"), "branch": sh("git rev-parse --abbrev-ref HEAD"),
      "codeChangedSinceCommit": bool(sh("git status --porcelain -- anneal tests examples")),
      "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
      "platform": platform.platform(), "cpus": os.cpu_count(),
      "calculix": sh("ccx -v 2>&1 | head -3 | tr '\\n' ' '"), "gmsh": sh("gmsh --version 2>&1 | head -1")}
tl = open(os.path.join(P, "pytest.log")).read()
ev["pytest"] = re.findall(r"=+ (.*(?:passed|failed).*?) =+", tl)[-1]
ev["pytestSkipped"] = re.findall(r"SKIPPED.*", tl)
ev["validate"] = [l.rstrip() for l in open(os.path.join(P, "validate.log")) if "[" in l or "GATE" in l]


def model_3mf(d):
    f = [x for x in os.listdir(d) if x.endswith(".3mf")][0]
    t = zipfile.ZipFile(os.path.join(d, f)).read("3D/3dmodel.model").decode()
    return hashlib.sha256(re.sub(r'UUID="[0-9a-f-]+"', 'UUID=""', t).encode()).hexdigest()


def summary(rec, d):
    o = rec["results"]["optimized"]
    stl = [f for f in os.listdir(d) if f.endswith("-optimized.stl")][0]
    return {"anneal": rec["anneal"], "massG": o["massG"], "maxDisplacementMM": o["maxDisplacementMM"],
            "safetyFactor": o["safetyFactor"], "volumeCM3": o["volumeCM3"], "passes": rec["passes"],
            "optimizerIterations": rec["optimizer"]["iterations"], "dfm": rec.get("dfm"),
            "checks": [(c["name"], c["ok"], c["value"]) for c in rec["checks"]],
            "stlSha256": sha(os.path.join(d, stl)), "densitySha256": sha(os.path.join(d, "density.npy")),
            "fieldsSha256": sha(os.path.join(d, "fields-optimized.npz")), "3mfModelSha256NoUUID": model_3mf(d),
            "totalSeconds": rec["totalSeconds"]}


b, r0 = J(BASE, "run.json"), J(P, "R0", "run.json")
kb, k0 = summary(b, BASE), summary(r0, os.path.join(P, "R0"))
same = {k: kb[k] == k0[k] for k in kb if k not in ("anneal", "totalSeconds")}
ev["regression"] = {"baseline": kb, "release": k0, "identical": same, "allIdentical": all(same.values())}

rp = J(P, "RP", "run.json")
o = rp["results"]["optimized"]
ev["physicsRun"] = {"spec": "examples/bracket-pla.json", "summary": summary(rp, os.path.join(P, "RP")),
                    "printAware": rp["derived"].get("printAware"),
                    "safety": {k: o.get(k) for k in ("safetyFactor", "safetyFactorVonMises", "safetyFactorHill",
                                                     "safetyFactorLayers")},
                    "buckling": o.get("buckling"), "impact": o.get("impact"), "nonlinear": o.get("nonlinear"),
                    "lockingFactor": o.get("lockingFactor"), "cases": o.get("cases")}
ri_dir = os.path.join(P, "RI")
if os.path.exists(os.path.join(ri_dir, "run.json")):
    import trimesh
    ri = J(ri_dir, "run.json")
    part = trimesh.load(os.path.join(ri_dir, "interfaces-optimized.stl"))
    model = trimesh.load(os.path.join(root, "examples", "interfaces.stl"))
    kept = trimesh.boolean.intersection([part, model], engine="manifold").volume
    v = part.vertices
    holes = {}
    for name, (y, z) in {"bolt-1": (10, 8), "bolt-2": (50, 8), "bolt-3": (10, 32), "bolt-4": (50, 32)}.items():
        sel = (v[:, 0] > -0.01) & (v[:, 0] < 6.01)
        d = np.hypot(v[sel, 1] - y, v[sel, 2] - z)
        d = d[d < 4.5]
        holes[name] = [float(d.min()), float(d.max())] if d.size else None
    sel = (v[:, 1] > 19.99) & (v[:, 1] < 40.01)
    d = np.hypot(v[sel, 0] - 90, v[sel, 2] - 60)
    d = d[d < 5.5]
    holes["pin"] = [float(d.min()), float(d.max())] if d.size else None
    # bolt-head room: nothing of the part within the access cylinders in front of the pad
    acc = 0
    for (y, z) in ((10, 8), (50, 8), (10, 32), (50, 32)):
        cyl = trimesh.creation.cylinder(radius=3.6 * 3.3 / 2, height=15,
                                        transform=trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
        cyl.apply_translation([6 + 7.5, y, z])
        acc += trimesh.boolean.intersection([part, cyl], engine="manifold").volume
    ev["interfacesRun"] = {"summary": summary(ri, ri_dir), "modelCM3": model.volume / 1000, "partCM3": part.volume / 1000,
                           "modelKeptCM3": kept / 1000, "pieces": len(part.split(only_watertight=False)),
                           "watertight": bool(part.is_watertight), "holeRadiiMM": holes,
                           "boltAccessMaterialMM3": float(acc), "exactFeatures": ri["derived"].get("exactFeatures")}
p = os.path.join(P, "ccx_R0", "ccx_bracket.json")
ev["calculixR0"] = J(p) if os.path.exists(p) else None
g = os.path.join(GUI, "gui_smoke.json")
ev["gui"] = J(g)["checks"] if os.path.exists(g) else None
json.dump(ev, open(os.path.join(root, "verification", "evidence.json"), "w"), indent=1, default=float)
print(json.dumps({"commit": ev["commit"][:12], "pytest": ev["pytest"], "regressionIdentical": ev["regression"]["allIdentical"],
                  "differs": [k for k, v in same.items() if not v]}, indent=1))
