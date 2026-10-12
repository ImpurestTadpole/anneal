"""Assemble release evidence into VERIFICATION.md and verification/*.json.

Usage: python research/prove_release.py <scratch> <baseline_run_dir>
<scratch>/proof/R0, R1, R2 : runs of examples/bracket.json, bracket-overhang.json, bracket-pla.json
<scratch>/proof/pytest.log, validate.log ; <scratch>/gui/gui_smoke.json ; <scratch>/proof/ccx_R0, ccx_R1
"""
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import numpy as np
import scipy

S, BASE = sys.argv[1], sys.argv[2]
P = os.path.join(S, "proof")
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
outdir = os.path.join(root, "verification")
os.makedirs(outdir, exist_ok=True)
J = lambda *p: json.load(open(os.path.join(*p)))
sh = lambda c: subprocess.run(c, shell=True, capture_output=True, text=True, cwd=root).stdout.strip()


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def slice_support(stl, tag):
    """Support filament (cm3) from PrusaSlicer: slice with and without supports."""
    vals = {}
    for mode, flag in (("none", ""), ("support", "--support-material --support-material-threshold 45")):
        g = os.path.join(P, f"{tag}_{mode}.gcode")
        subprocess.run(f"prusa-slicer --export-gcode {flag} --layer-height 0.2 --nozzle-diameter 0.4 "
                       f"--fill-density 20% --filament-density 2.67 --center 100,100 -o {g} {stl}",
                       shell=True, capture_output=True)
        txt = open(g).read() if os.path.exists(g) else ""
        m = re.search(r"; filament used \[cm3\] = ([0-9.]+)", txt)
        vals[mode] = float(m.group(1)) if m else float("nan")
    return {"filamentNoSupportCM3": vals["none"], "filamentWithSupportCM3": vals["support"],
            "supportFilamentCM3": vals["support"] - vals["none"],
            "slicer": sh("prusa-slicer --help | head -1")}


ev = {"commit": sh("git rev-parse HEAD"), "branch": sh("git rev-parse --abbrev-ref HEAD"),
      "dirty": bool(sh("git status --porcelain -- anneal tests examples")),
      "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
      "platform": platform.platform(), "cpus": os.cpu_count()}

# 1. tests and gate
tl = open(os.path.join(P, "pytest.log")).read()
ev["pytest"] = re.findall(r"=+ (.*(?:passed|failed).*) =+", tl)[-1]
ev["validate"] = [l.strip() for l in open(os.path.join(P, "validate.log")) if "[" in l or "GATE" in l]

# 2. regression: R0 (0.4, options off) vs baseline (0.3.0)
b, r0 = J(BASE, "run.json"), J(P, "R0", "run.json")
def key_numbers(rec, d):
    o = rec["results"]["optimized"]
    return {"anneal": rec["anneal"], "massG": o["massG"], "maxDisplacementMM": o["maxDisplacementMM"],
            "safetyFactor": o["safetyFactor"], "volumeCM3": o["volumeCM3"], "passes": rec["passes"],
            "optimizerIterations": rec["optimizer"]["iterations"],
            "dfm": rec.get("dfm"), "checks": [(c["name"], c["ok"], c["value"]) for c in rec["checks"]],
            "stlSha256": sha(os.path.join(d, [f for f in os.listdir(d) if f.endswith("-optimized.stl")][0])),
            "densitySha256": sha(os.path.join(d, "density.npy"))}
kb, k0 = key_numbers(b, BASE), key_numbers(r0, os.path.join(P, "R0"))
same = {k: kb[k] == k0[k] for k in kb if k != "anneal"}
ev["regression"] = {"baseline": kb, "release": k0, "identical": same, "allIdentical": all(same.values()),
                    "baselineCommit": "17a3e31 (0.3.0)"}

# 3. overhang filter + buckling (R1) vs R0
r1 = J(P, "R1", "run.json")
o0, o1 = r0["results"]["optimized"], r1["results"]["optimized"]
from anneal.amfilter import unsupported_fraction
x0 = np.load(os.path.join(P, "R0", "density.npy"))
x1 = np.load(os.path.join(P, "R1", "density.npy"))
ev["overhang"] = {
    "R0": {"massG": o0["massG"], "maxDisplacementMM": o0["maxDisplacementMM"], "dfm": r0.get("dfm"),
           "unsupportedVoxels": unsupported_fraction(x0, 2, 1, active=x0 > 0.05),
           "slicer": slice_support(os.path.join(P, "R0", "bracket-optimized.stl"), "R0")},
    "R1": {"massG": o1["massG"], "maxDisplacementMM": o1["maxDisplacementMM"], "dfm": r1.get("dfm"),
           "unsupportedVoxels": unsupported_fraction(x1, 2, 1, active=x1 > 0.05),
           "slicer": slice_support(os.path.join(P, "R1", "bracket-overhang-optimized.stl"), "R1"),
           "buckling": o1.get("buckling"), "checks": [(c["name"], c["ok"], c["value"]) for c in r1["checks"]]}}

# 4. print-aware (R2)
r2 = J(P, "R2", "run.json")
o2 = r2["results"]["optimized"]
ev["printAware"] = {k: o2.get(k) for k in ("massG", "maxDisplacementMM", "safetyFactor", "safetyFactorVonMises",
                                            "safetyFactorHill", "safetyFactorLayers", "peakLayerTensionMPa")}
ev["printAware"]["derived"] = r2["derived"].get("printAware")
ev["printAware"]["checks"] = [(c["name"], c["ok"], c["value"]) for c in r2["checks"]]

# 5. independent solvers and GUI
for tag in ("R0", "R1"):
    p = os.path.join(P, f"ccx_{tag}", "ccx_bracket.json")
    if os.path.exists(p):
        ev[f"calculix_{tag}"] = J(p)
gp = os.path.join(S, "gui", "gui_smoke.json")
ev["gui"] = J(gp)["checks"] if os.path.exists(gp) else None
tune = [json.loads(l) for l in open(os.path.join(root, "research", "tune.log")) if l.startswith("{")]
ev["overhangTuning"] = tune

json.dump(ev, open(os.path.join(outdir, "evidence.json"), "w"), indent=1, default=float)
print(json.dumps({k: ev[k] for k in ("commit", "dirty", "pytest")}, indent=1))
print("regression identical:", ev["regression"]["allIdentical"], same)
