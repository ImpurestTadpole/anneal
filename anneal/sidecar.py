"""Large-deformation check with CalculiX (optional sidecar, spec physics.nonlinear).

Anneal's own solver is linear. This check meshes the exported as-built STL into second-order
tetrahedra with gmsh, applies the same anchors (fixed regions fully held, each load spread equally
over the nodes in its region, as Anneal does), and runs CalculiX twice per load case: a linear
static step and a geometrically nonlinear step (NLGEOM, large deflection and rotation). It reports
both maximum displacements and their ratio. Material plasticity is not included.

CalculiX (GPL-2.0) and gmsh (GPL-2.0-or-later) run as separate programs and are not part of Anneal.
Install:
  Ubuntu:  sudo apt install calculix-ccx gmsh      (or: pip install gmsh)
  Windows: pip install gmsh, and download CalculiX (ccx.exe) from www.dhondt.de; then put ccx on the
           PATH or set the environment variable ANNEAL_CCX to the full path of ccx.exe.
"""
import os
import re
import shutil
import subprocess
import sys
import time
import numpy as np

from .physics import frame


def find_ccx():
    p = os.environ.get("ANNEAL_CCX")
    if p and os.path.isfile(p):
        return p
    for name in ("ccx", "ccx.exe", "ccx_2.22", "ccx_2.21", "ccx_2.20"):
        q = shutil.which(name)
        if q:
            return q
    return None


def find_gmsh():
    """('exe', path) or ('module', None) or (None, None)."""
    p = os.environ.get("ANNEAL_GMSH") or shutil.which("gmsh") or shutil.which("gmsh.exe")
    if p:
        return "exe", p
    try:
        import gmsh  # noqa: F401
        return "module", None
    except Exception:
        return None, None


def _mesh(stl, wd, size, how, exe):
    out = os.path.join(wd, "mesh.inp")
    if how == "exe":
        geo = os.path.join(wd, "part.geo")
        with open(geo, "w") as fh:
            fh.write(f'Merge "{os.path.abspath(stl)}";\nClassifySurfaces{{40*Pi/180, 1, 1, Pi}};\nCreateGeometry;\n'
                     'Surface Loop(1) = Surface{:};\nVolume(1) = {1};\n'
                     f'Mesh.MeshSizeMax = {size};\nMesh.ElementOrder = 2;\nMesh.SecondOrderLinear = 1;\nMesh.Optimize = 1;\n')
        r = subprocess.run([exe, "-3", geo, "-format", "inp", "-o", out], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(out):
            raise RuntimeError("gmsh could not mesh the part: " + (r.stdout + r.stderr)[-600:])
    else:
        import gmsh
        gmsh.initialize(["gmsh", "-v", "0"])
        try:
            gmsh.merge(os.path.abspath(stl))
            gmsh.model.mesh.classifySurfaces(40 * np.pi / 180, True, True, np.pi)
            gmsh.model.mesh.createGeometry()
            surf = [e[1] for e in gmsh.model.getEntities(2)]
            loop = gmsh.model.geo.addSurfaceLoop(surf)
            gmsh.model.geo.addVolume([loop])
            gmsh.model.geo.synchronize()
            for k, v in (("Mesh.MeshSizeMax", size), ("Mesh.ElementOrder", 2), ("Mesh.SecondOrderLinear", 1),
                         ("Mesh.Optimize", 1)):
                gmsh.option.setNumber(k, v)
            gmsh.model.mesh.generate(3)
            gmsh.write(out)
        finally:
            gmsh.finalize()
    nodes, elems, mode = {}, [], None
    with open(out) as fh:
        for line in fh:
            if line.startswith("*"):
                u = line.upper()
                mode = "n" if u.startswith("*NODE") else ("e" if "C3D10" in u else None)
                continue
            if mode == "n":
                p = line.split(",")
                nodes[int(p[0])] = [float(v) for v in p[1:4]]
            elif mode == "e":
                elems.append([int(v) for v in line.replace(" ", "").rstrip(",\n").split(",") if v])
    if not elems:
        raise RuntimeError("gmsh made no solid elements. The STL may not be watertight.")
    used = sorted({n for e in elems for n in e[1:]})
    return np.array(used), np.array([nodes[n] for n in used]), elems


def _material_cards(prob):
    m = prob.material
    D = getattr(prob, "D", None)
    if D is None:
        return ["*MATERIAL,NAME=M", "*ELASTIC", f"{m['E']},{m['nu']}"], ""
    info = prob.derived["printAware"]
    E, Ez, nu, nuZ, Gz = info["E"], info["Ez"], info["nu"], info["nuZ"], info["Gz"]
    nu13 = nuZ * E / Ez                               # CalculiX nu13 = -eps3/eps1 under stress 1
    R = frame(info["buildDirection"])
    a, b = R[:, 0], R[:, 1]
    cards = ["*MATERIAL,NAME=M", "*ELASTIC,TYPE=ENGINEERING CONSTANTS",
             f"{E},{E},{Ez},{nu},{nu13},{nu13},{E / (2 * (1 + nu))},{Gz},", f"{Gz}",
             "*ORIENTATION,NAME=OR1,SYSTEM=RECTANGULAR", ",".join(f"{v:.9g}" for v in (*a, *b))]
    return cards, ",ORIENTATION=OR1"


def _thermal_material_cards(prob):
    """Material cards for a spec with thermal cases: E (and the engineering constants) as a table over
    temperature from tempDerating (CalculiX interpolates linearly, as Anneal does), and *EXPANSION with
    ZERO = the reference temperature, so the thermal strain is alpha (T - Tref). alphaZ (print-aware runs)
    gives *EXPANSION,TYPE=ORTHO in the *ORIENTATION frame of the engineering constants."""
    m = prob.material
    D = getattr(prob, "D", None)
    rows = m.get("tempDerating") or [[prob.t_ref, 1.0, 1.0]]
    a = float(m["alpha"])
    if D is None:
        cards = ["*MATERIAL,NAME=M", "*ELASTIC"] + [f"{m['E'] * fe},{m['nu']},{t}" for t, fe, _ in rows]
        cards += [f"*EXPANSION,ZERO={prob.t_ref}", f"{a:.9g}"]
        return cards, ""
    info = prob.derived["printAware"]
    E, Ez, nu, nuZ, Gz = info["E"], info["Ez"], info["nu"], info["nuZ"], info["Gz"]
    nu13 = nuZ * E / Ez
    R = frame(info["buildDirection"])
    cards = ["*MATERIAL,NAME=M", "*ELASTIC,TYPE=ENGINEERING CONSTANTS"]
    for t, fe, _ in rows:
        cards += [f"{E * fe},{E * fe},{Ez * fe},{nu},{nu13},{nu13},{E * fe / (2 * (1 + nu))},{Gz * fe},", f"{Gz * fe},{t}"]
    az = float(m.get("alphaZ", a))
    cards += [f"*EXPANSION,TYPE=ORTHO,ZERO={prob.t_ref}", f"{a:.9g},{a:.9g},{az:.9g}",
              "*ORIENTATION,NAME=OR1,SYSTEM=RECTANGULAR", ",".join(f"{v:.9g}" for v in (*R[:, 0], *R[:, 1]))]
    return cards, ",ORIENTATION=OR1"


def thermal_step_cards(prob, case):
    """*TEMPERATURE for a case at temperature (inside the step); nothing for a case at the reference."""
    t = getattr(prob, "t_case", {}).get(case)
    return [] if t is None else ["*TEMPERATURE", f"NALL,{t}"]


def _max_disp(dat):
    txt = open(dat).read()
    if "displacements" not in txt:
        return float("nan")
    block = txt.split("displacements")[-1]
    U = np.array([list(map(float, l.split()[1:4])) for l in block.splitlines() if re.match(r"^\s+\d+\s", l)])
    return float(np.linalg.norm(U, axis=1).max()) if U.size else float("nan")


TET10_FACES = [((0, 1, 2), (4, 5, 6)), ((0, 1, 3), (4, 8, 7)), ((1, 2, 3), (5, 9, 8)), ((0, 2, 3), (6, 9, 7))]


def load_weights(elems, node_xyz, region_nodes):
    """Nodal weights (summing to 1) for a uniform traction on the boundary faces inside a region.
    On a 6-node triangle a uniform traction goes to the mid-side nodes only, A/3 each; equal forces
    on every node instead push the corner nodes in and inflate the peak displacement."""
    inside = set(int(n) for n in region_nodes)
    count, faces = {}, {}
    for e in elems:
        nd = e[1:]
        for c, m in TET10_FACES:
            key = tuple(sorted(nd[i] for i in c))
            count[key] = count.get(key, 0) + 1
            faces[key] = ([nd[i] for i in c], [nd[i] for i in m])
    w = {}
    for key, k in count.items():
        if k != 1 or not all(n in inside for n in key):
            continue
        cn, mn = faces[key]
        a, b, c = (node_xyz[n] for n in cn)
        A = 0.5 * np.linalg.norm(np.cross(b - a, c - a))
        for n in mn:
            w[n] = w.get(n, 0.0) + A / 3.0
    tot = sum(w.values())
    if tot <= 0:                       # no whole face inside the region: fall back to equal shares
        return {int(n): 1.0 / len(region_nodes) for n in region_nodes}
    return {n: v / tot for n, v in w.items()}


def nonlinear_check(prob, stl, wd, log=print, size=None):
    """Linear and NLGEOM CalculiX runs of the as-built part, per load case. Returns a dict; when the
    tools are missing it returns {"skipped": reason} and the run carries on."""
    ccx = find_ccx()
    how, gexe = find_gmsh()
    if not ccx or not how:
        miss = " and ".join(x for x, ok in (("CalculiX (ccx)", ccx), ("gmsh", how)) if not ok)
        return {"skipped": f"{miss} not found. See 'Large-deformation check' in the README to install it."}
    os.makedirs(wd, exist_ok=True)
    size = float(size or max(2.0, 1.3 * prob.grid.h))
    t0 = time.time()
    ids, xyz, elems = _mesh(stl, wd, size, how, gexe)
    sets = {}
    for a in prob.anchors:
        sel = ids[a.region.sdf(xyz) <= 0.5 * prob.grid.h]
        if sel.size == 0:
            return {"skipped": f"no mesh nodes inside anchor '{a.name}'"}
        sets[a.name] = sel
    thermal = bool(getattr(prob, "t_case", None))
    mat, orient = _thermal_material_cards(prob) if thermal else _material_cards(prob)
    tag = lambda n: re.sub(r"[^A-Za-z0-9_]", "_", n).upper()[:70]
    base = ["*NODE"] + [f"{n},{x:.9g},{y:.9g},{z:.9g}" for n, (x, y, z) in zip(ids, xyz)]
    base += ["*ELEMENT,TYPE=C3D10,ELSET=EALL"] + [",".join(map(str, e)) for e in elems]
    base += ["*NSET,NSET=NALL"] + [",".join(map(str, ids[i:i + 12])) for i in range(0, len(ids), 12)]
    for s, v in sets.items():
        base += [f"*NSET,NSET=A_{tag(s)}"] + [",".join(map(str, v[i:i + 12])) for i in range(0, len(v), 12)]
    base += mat + [f"*SOLID SECTION,ELSET=EALL,MATERIAL=M{orient}", "*BOUNDARY"]
    for a in prob.anchors:
        if a.role == "fixed":
            dofs = sorted(d + 1 for d in a.dofs)
            base += [f"A_{tag(a.name)},{d},{d}" for d in dofs]
    if thermal:   # stress-free at the reference temperature (NALL is defined above: ccx 2.21 does not predefine it)
        base += ["*INITIAL CONDITIONS,TYPE=TEMPERATURE", f"NALL,{prob.t_ref}"]
    node_xyz = {int(n): x for n, x in zip(ids, xyz)}
    weights = {a.name: load_weights(elems, node_xyz, sets[a.name]) for a in prob.anchors if a.role == "load"}
    out = {"meshElements": len(elems), "meshNodes": int(ids.size), "meshSizeMM": size,
           "meshSeconds": time.time() - t0, "solver": ccx, "cases": {}}
    for case in prob.cases:
        cl = ["*CLOAD"]
        for a in prob.anchors:
            if a.role == "load" and case in a.loads:
                v = a.loads[case]
                for n, wn in weights[a.name].items():
                    for d in range(3):
                        if v[d]:
                            cl.append(f"{n},{d + 1},{v[d] * wn:.9g}")
        if thermal:
            if len(cl) == 1:
                cl = []                                # thermal-only case: no point loads
            cl += thermal_step_cards(prob, case)
        res = {}
        for kind, step in (("linear", ["*STEP", "*STATIC"]),
                           ("nonlinear", ["*STEP,NLGEOM,INC=200", "*STATIC", "0.1,1.0,1e-5,0.25"])):
            name = f"{kind}_{tag(case)}"
            with open(os.path.join(wd, name + ".inp"), "w") as fh:
                fh.write("\n".join(base + step + cl + ["*NODE PRINT,NSET=NALL", "U", "*END STEP"]) + "\n")
            t = time.time()
            r = subprocess.run([ccx, "-i", name], cwd=wd, capture_output=True, text=True)
            res[kind] = _max_disp(os.path.join(wd, name + ".dat"))
            res[kind + "Seconds"] = time.time() - t
            if not np.isfinite(res[kind]):
                res[kind + "Error"] = (r.stdout + r.stderr)[-400:]
        lin, nl = res["linear"], res["nonlinear"]
        res["ratio"] = nl / lin if lin and np.isfinite(lin) and np.isfinite(nl) else float("nan")
        out["cases"][case] = res
        log(f"  large deformation, load case {case}: CalculiX linear {lin:.4g} mm, nonlinear {nl:.4g} mm "
            f"(ratio {res['ratio']:.3f}), {res['linearSeconds'] + res['nonlinearSeconds']:.0f} s")
    out["seconds"] = time.time() - t0
    return out
