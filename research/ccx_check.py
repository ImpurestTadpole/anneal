"""CalculiX sidecar checks: gmsh tet10 column -> *BUCKLE, and a cantilever linear vs NLGEOM.
Usage: python research/ccx_check.py <workdir>"""
import json
import re
import subprocess
import sys
from pathlib import Path
import numpy as np

wd = Path(sys.argv[1]); wd.mkdir(parents=True, exist_ok=True)
E, NU = 1000.0, 0.3


def mesh_box(name, lx, ly, lz, size):
    geo = wd / f"{name}.geo"
    geo.write_text(f'SetFactory("OpenCASCADE");\nBox(1) = {{0,0,0,{lx},{ly},{lz}}};\n'
                   f'Mesh.ElementOrder = 2;\nMesh.MeshSizeMax = {size};\nMesh.SecondOrderLinear = 1;\n')
    subprocess.run(["gmsh", "-3", str(geo), "-format", "inp", "-o", str(wd / f"{name}_m.inp")],
                   check=True, capture_output=True)
    txt = (wd / f"{name}_m.inp").read_text().splitlines()
    nodes, elems, mode = {}, [], None
    for line in txt:
        if line.startswith("*"):
            mode = "n" if line.upper().startswith("*NODE") else ("e" if "C3D10" in line.upper() else None)
            continue
        if mode == "n":
            p = line.split(","); nodes[int(p[0])] = [float(v) for v in p[1:4]]
        elif mode == "e":
            p = [int(v) for v in line.replace(" ", "").rstrip(",").split(",")]; elems.append(p)
    used = sorted({n for e in elems for n in e[1:]})
    return {n: nodes[n] for n in used}, elems


def write_deck(name, nodes, elems, step):
    xyz = np.array(list(nodes.values())); ids = np.array(list(nodes.keys()))
    zmax = xyz[:, 2].max(); xmax = xyz[:, 0].max()
    sets = {"BASE": ids[xyz[:, 2] < 1e-6], "TOP": ids[abs(xyz[:, 2] - zmax) < 1e-6],
            "XEND": ids[abs(xyz[:, 0] - xmax) < 1e-6], "X0": ids[xyz[:, 0] < 1e-6]}
    L = ["*NODE"] + [f"{n},{x:.9g},{y:.9g},{z:.9g}" for n, (x, y, z) in nodes.items()]
    L += ["*ELEMENT,TYPE=C3D10,ELSET=EALL"] + [",".join(map(str, e)) for e in elems]
    for s, v in sets.items():
        L += [f"*NSET,NSET={s}"] + [",".join(map(str, v[i:i + 12])) for i in range(0, len(v), 12)]
    L += ["*MATERIAL,NAME=M", "*ELASTIC", f"{E},{NU}", "*SOLID SECTION,ELSET=EALL,MATERIAL=M"]
    L += step(sets)
    (wd / f"{name}.inp").write_text("\n".join(L) + "\n")
    r = subprocess.run(["ccx", "-i", name], cwd=wd, capture_output=True, text=True)
    return r.stdout


out = {}
# 1. Euler column 4 x 4 x 60, clamped base, unit axial load spread on the top face
nodes, elems = mesh_box("col", 4, 4, 60, 1.0)
def buckle(sets):
    n = len(sets["TOP"])
    return ["*BOUNDARY", "BASE,1,3", "*STEP", "*BUCKLE", "4", "*CLOAD"] + [f"{i},3,{-1.0 / n:.9g}" for i in sets["TOP"]] + ["*END STEP"]
write_deck("col", nodes, elems, buckle)
dat = (wd / "col.dat").read_text()
blf = [float(m.group(1)) for m in re.finditer(r"^\s+\d+\s+([0-9.Ee+-]+)\s*$", dat, re.M)]
euler = np.pi ** 2 * E * (4 ** 4 / 12) / (4 * 60 ** 2)
out["column"] = {"elements": len(elems), "ccx_BLF": blf[:4], "euler": euler, "ratio": blf[0] / euler}

# 2. Cantilever 100 x 10 x 10 with a large tip load: linear vs NLGEOM
nodes, elems = mesh_box("cant", 100, 10, 10, 2.0)
P = 40.0     # N; linear tip deflection P L^3 / 3EI = 40e6 / (3*1000*833.3) = 16 mm (16 % of L)
def static(nl):
    def st(sets):
        n = len(sets["XEND"])
        s = ["*BOUNDARY", "X0,1,3", "*STEP" + (",NLGEOM,INC=200" if nl else ""), "*STATIC"] + (["0.05,1.0"] if nl else [])
        s += ["*CLOAD"] + [f"{i},3,{-P / n:.9g}" for i in sets["XEND"]]
        s += ["*NODE PRINT,NSET=XEND", "U", "*END STEP"]
        return s
    return st
res = {}
for nl in (False, True):
    nm = "cant_nl" if nl else "cant_lin"
    write_deck(nm, nodes, elems, static(nl))
    dat = (wd / f"{nm}.dat").read_text().split("displacements")[-1]
    rows = [list(map(float, l.split()[1:4])) for l in dat.splitlines() if re.match(r"^\s+\d+\s", l)]
    u = np.array(rows)
    res[nm] = {"uz_tip": float(u[:, 2].mean()), "ux_tip": float(u[:, 0].mean())}
I = 10 ** 4 / 12
out["cantilever"] = {**res, "beam_linear_uz": -P * 100 ** 3 / (3 * E * I), "elements": len(elems)}
print(json.dumps(out, indent=1))
json.dump(out, open(wd / "ccx_results.json", "w"), indent=1)
