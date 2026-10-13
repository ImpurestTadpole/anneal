"""Write VERIFICATION.md from verification/evidence.json."""
import json
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ev = json.load(open(os.path.join(root, "verification", "evidence.json")))
f = lambda v, n=3: "–" if v is None else (f"{v:.{n}g}" if isinstance(v, (int, float)) else str(v))
L = []
w = L.append
reg = ev["regression"]
oh = ev["overhang"]
pa = ev["printAware"]
w("# Anneal 0.4.0 — release verification\n")
w(f"Commit `{ev['commit'][:12]}` (code tree clean: {'no' if ev['dirty'] else 'yes'}). "
  f"Python {ev['python']}, numpy {ev['numpy']}, scipy {ev['scipy']}, {ev['platform']}, {ev['cpus']} CPU cores.")
w("All raw numbers are in `verification/evidence.json`. Scripts: `research/prove_release.py`, "
  "`research/ccx_bracket.py`, `research/gui_smoke.py`, `research/am_tune.py`.\n")
w("## Result\n")
gate_ok = any("GATE: OPEN" in l for l in ev["validate"])
gui_ok = ev["gui"] and all(c["ok"] for c in ev["gui"])
w("| Proof | Result |\n|---|---|")
w(f"| Test suite | {ev['pytest']} |")
w(f"| Validation gate | {'OPEN' if gate_ok else 'CLOSED'} — {[l for l in ev['validate'] if 'GATE' in l][0]} |")
w(f"| 0.4.0 with the new options off gives the same part as 0.3.0 | {'**Yes, bit for bit**' if reg['allIdentical'] else '**NO**'} |")
w(f"| GUI in a headless browser | {'all checks pass' if gui_ok else 'FAILED'} |")
w("")
w("## 1. Validation gate\n")
w("```\n" + "\n".join(ev["validate"]) + "\n```\n")
w("## 2. Nothing that worked before has changed\n")
w(f"The example `examples/bracket.json` was run on 0.3.0 (commit {reg['baselineCommit']}) and on this release. "
  "The new options are off by default.\n")
w("| Quantity | 0.3.0 | 0.4.0 | Same |\n|---|---|---|---|")
for k, lab in (("stlSha256", "STL file SHA-256"), ("densitySha256", "Density field SHA-256"),
               ("3mfModelSha256NoUUID", "3MF model SHA-256 (random object UUID removed)"),
               ("massG", "Mass, g"), ("maxDisplacementMM", "Max displacement, mm"), ("safetyFactor", "Safety factor"),
               ("volumeCM3", "Volume, cm³"), ("optimizerIterations", "Optimizer iterations (last pass)")):
    a, b = reg["baseline"].get(k), reg["release"].get(k)
    same = a == b
    if isinstance(a, str):
        a, b = a[:16] + "…", b[:16] + "…"
    w(f"| {lab} | {a} | {b} | {'yes' if same else '**no**'} |")
w(f"| Mass-search passes, DFM summary, every check line | | | {'yes' if reg['identical']['passes'] and reg['identical']['dfm'] and reg['identical']['checks'] else '**no**'} |")
w("\nThe 3MF zip differs only in the object UUID that the exporter makes at random for each file.\n")
w("## 3. Overhang filter (`optimizer.overhangFilter`)\n")
r0, r1 = oh["R0"], oh["R1"]
w("Same bracket, same loads and limits, built along +X (the best direction found by the design-space check).\n")
w("| | Without filter (0.3.0 behaviour) | With filter |\n|---|---|---|")
w(f"| Mass, g | {f(r0['massG'], 4)} | {f(r1['massG'], 4)} |")
w(f"| Max displacement, mm (limit 0.3) | {f(r0['maxDisplacementMM'])} | {f(r1['maxDisplacementMM'])} |")
w(f"| Solid voxels with no support below (along +X) | {100 * r0['unsupportedVoxelsXup']:.1f} % | {100 * r1['unsupportedVoxelsXup']:.1f} % |")
w(f"| PrusaSlicer support filament, part turned +X up | {f(r0['slicerXup']['supportFilamentCM3'])} cm³ | {f(r1['slicerXup']['supportFilamentCM3'])} cm³ |")
w(f"| PrusaSlicer total filament with supports | {f(r0['slicerXup']['filamentWithSupportCM3'])} cm³ | {f(r1['slicerXup']['filamentWithSupportCM3'])} cm³ |")
d1 = (r1.get("dfm") or {})
d0 = (r0.get("dfm") or {})
ox = lambda d: (d.get("directions") or {}).get("+X", {}).get("overhangMM2")
w(f"| Anneal DFM overhang area steeper than 45°, along +X | {f(ox(d0), 4)} mm² | {f(ox(d1), 4)} mm² |")
w(f"| Anneal DFM support envelope along the run's own direction | {f(d0.get('supportVolumeCM3'))} cm³ (+Z) | {f(d1.get('supportVolumeCM3'))} cm³ (+X) |")
w(f"\nSlicer: `{r0['slicerXup']['slicer']}`, 0.2 mm layers, 0.4 mm nozzle, supports at 45°, 20 % infill. "
  "Support filament = filament with supports − filament without supports.\n")
w("Tuning on a 48 × 8 × 24 cantilever (build +Z, volume 25 %), which set the filter's position and the advice of 100–120 iterations:\n")
w("| Run | Grey voxels | Unsupported | Compliance × volume |\n|---|---|---|---|")
for t in ev["overhangTuning"]:
    w(f"| {t['name']} | {100 * t['grey']:.1f} % | {100 * t['unsupported']:.1f} % | {t['c_times_v']:.5f} |")
w("\nContinuation of the filter parameter ξ₀ toward 0.9 broke the load path (solver failure) and was dropped. "
  "A first proof run along +Z showed that 41 % of the bracket's design space overhangs in that direction; the "
  "filter then removed the arm. The release now stops such runs and names a direction that works.\n")
w("## 4. Buckling check (`physics.buckling`)\n")
w("| Load case | Anneal raw | Anneal × locking factor | CalculiX *BUCKLE (tet10) |\n|---|---|---|---|")
ccx1 = ev.get("calculix_R1", {}).get("cases", {})
for c, v in (r1.get("buckling") or {}).items():
    cb = ccx1.get(c, {}).get("ccxBucklingFactors", [None])[0]
    w(f"| {c} | {f(v['raw'])} | {f(v['corrected'])} | {f(cb)} |")
w("\nCalculiX meshes the exported STL with gmsh (second-order tetrahedra), holds the bolt regions and spreads "
  "each load over its region's nodes, as Anneal does.\n")
for tag, lab in (("calculix_R0", "default bracket (0.4.0, options off)"), ("calculix_R1", "overhang-filter bracket")):
    c = ev.get(tag)
    if not c:
        continue
    w(f"Linear static cross-check, {lab}: {c['mesh']['elements']:,} tet10 elements.\n")
    w("| Load case | Anneal max displacement raw | Anneal corrected | CalculiX |\n|---|---|---|---|")
    for k, v in c["cases"].items():
        w(f"| {k} | {f(v['anneal_raw'])} mm | {f(v['anneal_corrected'])} mm | {f(v['ccxMaxDisplacementMM'])} mm |")
    w("")
w("## 5. Print-aware material (`physics.anisotropic`)\n")
w("Bracket in PLA with illustrative inputs (E 3500 MPa, Ez 2400 MPa, yield 50 MPa, layer strength × 0.5), "
  "loads divided by 10, build +Z.\n")
w("| Quantity | Value |\n|---|---|")
for k in ("massG", "maxDisplacementMM", "safetyFactorVonMises", "safetyFactorHill", "safetyFactor", "safetyFactorLayers"):
    w(f"| {k} | {f(pa.get(k))} |")
w(f"\nAssumed by the run (not given): {', '.join(pa['derived']['assumed']) or 'none'}.\n")
w("## 6. GUI\n")
w("| Check | Result |\n|---|---|")
for c in ev["gui"] or []:
    w(f"| {c['name']} | {'pass' if c['ok'] else 'FAIL'} |")
w("\n## 7. Not covered here\n")
w("- Windows and Ubuntu 20.04: this proof ran on Linux only (see the platform line above). The 0.4 code adds "
  "no new dependencies and no platform-specific code.")
w("- The desktop window (pywebview) was not opened; the same pages were tested in headless Chromium.")
w("- Values for the PLA example are illustrative inputs, not measured material data.")
open(os.path.join(root, "VERIFICATION.md"), "w").write("\n".join(L) + "\n")
print("\n".join(L))
