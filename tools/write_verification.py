"""Write VERIFICATION.md from verification/evidence.json (made by tools/prove_release.py)."""
import json
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ev = json.load(open(os.path.join(root, "verification", "evidence.json")))
f = lambda v, n=4: "–" if v is None else (f"{v:.{n}g}" if isinstance(v, (int, float)) else str(v))
L = []
w = L.append
reg, ph = ev["regression"], ev["physicsRun"]
gate = [l for l in ev["validate"] if "GATE" in l][0].strip()
gui_ok = bool(ev["gui"]) and all(c["ok"] for c in ev["gui"])

w("# Anneal 0.4.0 — release verification\n")
w(f"Commit `{ev['commit'][:12]}` on `{ev['branch']}`; code changed after the commit: "
  f"{'**yes**' if ev['codeChangedSinceCommit'] else 'no'}. Python {ev['python']}, numpy {ev['numpy']}, "
  f"scipy {ev['scipy']}, {ev['platform']}, {ev['cpus']} CPU cores. CalculiX: {ev['calculix'] or 'not found'}; "
  f"gmsh {ev['gmsh'] or 'not found'}.\n")
w("Raw numbers: `verification/evidence.json`. Scripts: `tools/prove_release.py`, `tools/ccx_bracket.py`, "
  "`tools/gui_smoke.py`, `tools/write_verification.py`.\n")
w("## Summary\n")
w("| Proof | Result |\n|---|---|")
w(f"| Test suite | {ev['pytest']} |")
w(f"| Validation gate | {gate} |")
w(f"| New options off: same part as 0.3.0 | {'**Yes, bit for bit**' if reg['allIdentical'] else '**NO** — see section 2'} |")
w(f"| GUI in headless Chromium | {'all ' + str(len(ev['gui'])) + ' checks pass' if gui_ok else '**FAILED**'} |")
w("")
w("## 1. Validation gate\n")
w("```\n" + "\n".join(ev["validate"]) + "\n```\n")
w("## 2. Nothing that worked before has changed\n")
w("`examples/bracket.json` (no 0.4 options) on 0.3.0, commit 17a3e31, and on this release:\n")
w("| Quantity | 0.3.0 | 0.4.0 | Same |\n|---|---|---|---|")
rows = (("stlSha256", "STL SHA-256"), ("densitySha256", "Density field SHA-256"),
        ("fieldsSha256", "Stress/displacement fields SHA-256"),
        ("3mfModelSha256NoUUID", "3MF model SHA-256, random object UUID removed"), ("massG", "Mass, g"),
        ("maxDisplacementMM", "Max displacement, mm"), ("safetyFactor", "Safety factor"),
        ("volumeCM3", "Volume, cm³"), ("optimizerIterations", "Iterations, last pass"))
for k, lab in rows:
    a, b = reg["baseline"][k], reg["release"][k]
    if isinstance(a, str):
        a, b = a[:16] + "…", b[:16] + "…"
    w(f"| {lab} | {a} | {b} | {'yes' if reg['identical'][k] else '**no**'} |")
w(f"| Mass-search passes, DFM summary, every check line | | | "
  f"{'yes' if all(reg['identical'][k] for k in ('passes', 'dfm', 'checks')) else '**no**'} |")
w("\nThe 3MF zip file differs only in the object UUID that the exporter makes at random for every file.\n")

w("## 3. The new physics on the example bracket\n")
w("`examples/bracket-pla.json`: the bracket in PLA with illustrative inputs (E 3500 MPa, Ez 2400 MPa, "
  "yield 50 MPa, layer strength × 0.5, build +Z), loads divided by 10, with every 0.4 option on.\n")
s = ph["summary"]
w(f"Mass {f(s['massG'])} g, max displacement {f(s['maxDisplacementMM'])} mm (limit 0.3), run time "
  f"{s['totalSeconds'] / 60:.0f} min.\n")
w("| Check | Result |\n|---|---|")
sf = ph["safety"]
w(f"| Safety factor, von Mises | {f(sf['safetyFactorVonMises'])} |")
w(f"| Safety factor, Hill (print-aware) | {f(sf['safetyFactorHill'])} |")
w(f"| Safety factor used (lower of the two) | {f(sf['safetyFactor'])} |")
w(f"| Safety factor across layers | {f(sf['safetyFactorLayers'])} |")
for c, v in (ph["buckling"] or {}).items():
    w(f"| Buckling factor, load case {c} | {f(v['corrected'])} (raw {f(v['raw'])} × locking {f(ph['lockingFactor'], 3)}) |")
for c, v in (ph["impact"] or {}).items():
    w(f"| Impact '{c}': {f(v['energyJ'], 3)} J at {f(v['speedMS'], 3)} m/s | stiffness {f(v['stiffnessNperMM'])} N/mm, "
      f"peak force {f(v['peakForceN'])} N, deflection {f(v['deflectionMM'], 3)} mm, safety factor {f(v['safetyFactor'], 3)}"
      f"{', across layers ' + f(v['safetyFactorLayers'], 3) if 'safetyFactorLayers' in v else ''} |")
nl = ph["nonlinear"] or {}
if "skipped" in nl:
    w(f"| Large deformation | skipped: {nl['skipped']} |")
else:
    for c, v in nl.get("cases", {}).items():
        an = (ph["cases"] or {}).get(c, {}).get("maxDisplacementMM")
        w(f"| Large deformation, load case {c} | CalculiX linear {f(v['linear'])} mm, nonlinear {f(v['nonlinear'])} mm "
          f"(ratio {f(v['ratio'], 4)}); Anneal voxel solve {f(an)} mm |")
    w(f"\nCalculiX mesh: {nl.get('meshElements', 0):,} tet10 elements, {f(nl.get('meshSizeMM'), 3)} mm.\n")

ri = ev.get("interfacesRun")
if ri:
    w("## 3b. Growing a part from bolt-on points, with exact geometry\n")
    w("`examples/interfaces.json`: the model holds only a mounting pad with four M6 holes and a pin lug "
      "(`examples/make_interfaces.py`). Design space: its bounding box, model kept (`keepModel`), holes marked "
      "`\"hole\": true` with 15 mm of bolt-head room, one keep-out box, exact geometry on.\n")
    s = ri["summary"]
    w("| Check | Result |\n|---|---|")
    w(f"| Material added | model {f(ri['modelCM3'])} cm³ → part {f(ri['partCM3'])} cm³ |")
    w(f"| Imported interfaces kept | {f(ri['modelKeptCM3'])} of {f(ri['modelCM3'])} cm³ "
      f"({100 * ri['modelKeptCM3'] / ri['modelCM3']:.2f} %) |")
    w(f"| One closed solid | pieces {ri['pieces']}, watertight {ri['watertight']} |")
    for k, v in ri["holeRadiiMM"].items():
        want = 4.0 if k == "pin" else 3.3
        w(f"| Hole '{k}' radius (model {want} mm) | {f(v[0])} to {f(v[1])} mm |" if v else f"| Hole '{k}' | not found |")
    w(f"| Part material inside the bolt-head room | {f(ri['boltAccessMaterialMM3'], 3)} mm³ |")
    w(f"| Mass, displacement (limit 0.3 mm) | {f(s['massG'])} g, {f(s['maxDisplacementMM'])} mm |")
    w("")
c0 = ev.get("calculixR0")
if c0:
    w("## 4. Independent solver on the default bracket\n")
    w(f"`tools/ccx_bracket.py` meshes the 0.4.0 default bracket STL ({c0['mesh']['elements']:,} tet10 elements), "
      "holds the bolt regions and spreads each load as a uniform traction over its region, then runs a linear "
      "step and *BUCKLE in CalculiX.\n")
    w("| Load case | Anneal displacement, raw | Anneal, locking-corrected | CalculiX | CalculiX buckling factor |\n|---|---|---|---|---|")
    for c, v in c0["cases"].items():
        w(f"| {c} | {f(v['anneal_raw'])} mm | {f(v['anneal_corrected'])} mm | {f(v['ccxMaxDisplacementMM'])} mm | "
          f"{f((v['ccxBucklingFactors'] or [None])[0])} |")
    w("")
w("## 5. GUI\n")
w("| Check | Result |\n|---|---|")
for c in ev["gui"] or []:
    w(f"| {c['name']} | {'pass' if c['ok'] else '**FAIL**'} |")
w("\n## 6. Not covered by this proof\n")
w("- Windows and Ubuntu 20.04. This proof ran on the platform in the header line. 0.4.0 adds no new required "
  "dependency and no platform-specific code; CalculiX and gmsh are optional.")
w("- The desktop window (pywebview) was not opened; the same pages were tested in headless Chromium.")
w("- The PLA values in `bracket-pla.json` are illustrative inputs, not measured material data.")
w("- The impact check is equivalent static: no part mass, stress waves, rate effects or yielding.")
w("- The overhang filter is not in 0.4.0. It stays on branch `verify-roadmap`.")
open(os.path.join(root, "VERIFICATION.md"), "w").write("\n".join(L) + "\n")
print("\n".join(L))
