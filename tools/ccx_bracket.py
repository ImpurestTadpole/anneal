"""Independent check of an Anneal as-built result with gmsh + CalculiX.

Meshes the exported STL into second-order tetrahedra, applies the spec's anchors (fixed regions
fully held, loads spread equally over the nodes in each load region, as Anneal does), and runs
a linear static step per load case plus *BUCKLE. Compares with the run's run.json.

Usage: python research/ccx_bracket.py <spec.json> <run_dir> <workdir> [meshMM]
"""
import json
import os
import re
import subprocess
import sys
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from anneal.problem import Problem

spec_path, run_dir, wd = sys.argv[1:4]
size = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
os.makedirs(wd, exist_ok=True)
prob = Problem(spec_path, log=lambda *a: None)
rec = json.load(open(os.path.join(run_dir, "run.json")))
stl = [f for f in os.listdir(run_dir) if f.endswith("-optimized.stl")][0]
mat = rec["material"]
t0 = time.time()

geo = os.path.join(wd, "part.geo")
open(geo, "w").write(f'Merge "{os.path.abspath(os.path.join(run_dir, stl))}";\n'
                     'ClassifySurfaces{40*Pi/180, 1, 1, Pi};\nCreateGeometry;\n'
                     'Surface Loop(1) = Surface{:};\nVolume(1) = {1};\n'
                     f'Mesh.MeshSizeMax = {size};\nMesh.ElementOrder = 2;\nMesh.SecondOrderLinear = 1;\n'
                     'Mesh.Optimize = 1;\n')
r = subprocess.run(["gmsh", "-3", geo, "-format", "inp", "-o", os.path.join(wd, "mesh.inp")],
                   capture_output=True, text=True)
if r.returncode != 0:
    raise SystemExit("gmsh failed:\n" + r.stdout[-2000:] + r.stderr[-2000:])
nodes, elems, mode = {}, [], None
for line in open(os.path.join(wd, "mesh.inp")):
    if line.startswith("*"):
        u = line.upper()
        mode = "n" if u.startswith("*NODE") else ("e" if "C3D10" in u else None)
        continue
    if mode == "n":
        p = line.split(","); nodes[int(p[0])] = [float(v) for v in p[1:4]]
    elif mode == "e":
        elems.append([int(v) for v in line.replace(" ", "").rstrip(",\n").split(",") if v])
used = sorted({n for e in elems for n in e[1:]})
ids = np.array(used)
xyz = np.array([nodes[n] for n in used])
mesh_s = time.time() - t0

tol = 0.5  # mm: nodes within this distance of an anchor region
sets, loads = {}, {}
for a in prob.anchors:
    sel = ids[a.region.sdf(xyz) <= tol]
    if sel.size == 0:
        raise SystemExit(f"anchor {a.name}: no mesh nodes found")
    sets[a.name] = sel
    if a.role == "load":
        loads[a.name] = a.loads


def deck(name, step):
    L = ["*NODE"] + [f"{n},{x:.9g},{y:.9g},{z:.9g}" for n, (x, y, z) in zip(ids, xyz)]
    L += ["*ELEMENT,TYPE=C3D10,ELSET=EALL"] + [",".join(map(str, e)) for e in elems]
    L += ["*NSET,NSET=NALL"] + [",".join(map(str, ids[i:i + 12])) for i in range(0, len(ids), 12)]
    for s, v in sets.items():
        L += [f"*NSET,NSET={s.upper().replace('-', '_')}"] + [",".join(map(str, v[i:i + 12])) for i in range(0, len(v), 12)]
    L += ["*MATERIAL,NAME=M", "*ELASTIC", f"{mat['E']},{mat['nu']}", "*SOLID SECTION,ELSET=EALL,MATERIAL=M", "*BOUNDARY"]
    L += [f"{a.name.upper().replace('-', '_')},1,3" for a in prob.anchors if a.role == "fixed"]
    L += step
    open(os.path.join(wd, f"{name}.inp"), "w").write("\n".join(L) + "\n")
    t = time.time()
    subprocess.run(["ccx", "-i", name], cwd=wd, capture_output=True, text=True)
    return time.time() - t


def cload(case):
    out = ["*CLOAD"]
    for an, ld in loads.items():
        if case in ld:
            v = ld[case]
            s = sets[an]
            for n in s:
                for d in range(3):
                    if v[d]:
                        out.append(f"{n},{d + 1},{v[d] / s.size:.9g}")
    return out


res = {"mesh": {"elements": len(elems), "nodes": int(ids.size), "sizeMM": size, "seconds": mesh_s},
       "anchorNodes": {k: int(v.size) for k, v in sets.items()}, "cases": {}}
for case in prob.cases:
    secs = deck(f"static_{case}", ["*STEP", "*STATIC"] + cload(case) + ["*NODE PRINT,NSET=NALL", "U", "*END STEP"])
    txt = open(os.path.join(wd, f"static_{case}.dat")).read().split("displacements")[-1]
    U = np.array([list(map(float, l.split()[1:4])) for l in txt.splitlines() if re.match(r"^\s+\d+\s", l)])
    umax = float(np.linalg.norm(U, axis=1).max()) if U.size else float("nan")
    secs_b = deck(f"buckle_{case}", ["*STEP", "*BUCKLE", "2"] + cload(case) + ["*END STEP"])
    dat = open(os.path.join(wd, f"buckle_{case}.dat")).read()
    blf = [float(m.group(1)) for m in re.finditer(r"^\s+\d+\s+([0-9.Ee+-]+)\s*$", dat, re.M)]
    a = rec["results"]["optimized"]
    an = a["cases"][case]["maxDisplacementMM"]
    res["cases"][case] = {"ccxMaxDisplacementMM": umax, "anneal_raw": an,
                          "anneal_corrected": an / a.get("lockingFactor", 1.0),
                          "ccxBucklingFactors": blf[:2], "anneal_buckling": a.get("buckling", {}).get(case),
                          "secondsStatic": secs, "secondsBuckle": secs_b}
res["seconds"] = time.time() - t0
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(wd, "ccx_bracket.json"), "w"), indent=1)
