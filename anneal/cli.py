"""Command line: python -m anneal <command>

  inspect MODEL          sizes, volume, closed or not, and a coordinate preview image
  init MODEL             write a starter spec next to the model (edit the anchors, then run)
  run SPEC               optimize, re-solve the result, check it, write the report
  validate               solver validation gate (6 checks)
  drop PATH              for drag-and-drop: a model gives init, a spec gives run
"""
import argparse
import json
import os
import subprocess
import sys
import webbrowser

import numpy as np

MODEL_EXT = (".stl", ".obj", ".ply", ".off", ".3mf", ".glb", ".step", ".stp")


def _open(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: works on Windows only
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        if path.endswith(".html"):
            webbrowser.open("file://" + os.path.abspath(path))


def cmd_inspect(model, out=None):
    from .geometry import load_mesh, voxel_fill
    from .fem import Grid
    m = load_mesh(model)
    lo, hi = m.bounds
    ext = hi - lo
    print(f"Model: {model}")
    print(f"  triangles {len(m.faces):,}   closed (watertight): {m.is_watertight}")
    print(f"  bounds min {np.round(lo, 3).tolist()}  max {np.round(hi, 3).tolist()} mm")
    print(f"  size {np.round(ext, 3).tolist()} mm   volume {abs(m.volume) / 1000:.2f} cm3")
    for name, n in (("draft", 15000), ("normal", 40000), ("fine", 90000)):
        print(f"  resolution '{name}': about {(abs(m.volume) / n) ** (1 / 3):.2f} mm voxels")
    h = (abs(m.volume) / 20000) ** (1 / 3)
    g = Grid(np.ceil((ext + 2 * h) / h).astype(int), h, lo - h)
    f = g.to3d(voxel_fill(m, g))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, 3, figsize=(13, 4.2))
    views = [("top (look down z)", f.max(2).T, 0, 1), ("front (look along y)", f.max(1).T, 0, 2),
             ("side (look along x)", f.max(0).T, 1, 2)]
    for ax, (t, img, a, b) in zip(axs, views):
        e = [g.origin[a], g.origin[a] + g.h * g.shape[a], g.origin[b], g.origin[b] + g.h * g.shape[b]]
        ax.imshow(img, origin="lower", extent=e, cmap="Greys", vmin=0, vmax=1.5)
        ax.set_title(t, fontsize=10, loc="left")
        ax.set_xlabel("xyz"[a] + " (mm)")
        ax.set_ylabel("xyz"[b] + " (mm)")
        ax.grid(True, color="#2563eb", lw=0.4, alpha=0.5)
        ax.minorticks_on()
    out = out or os.path.splitext(model)[0] + "-preview.png"
    fig.savefig(out, dpi=140, bbox_inches="tight")
    print(f"  coordinate preview: {out}  (read anchor positions off its mm grid)")
    return m


def cmd_init(model, out=None, material="AlSi10Mg-LPBF"):
    from .geometry import load_mesh
    m = load_mesh(model)
    lo, hi = m.bounds
    ext = hi - lo
    ax = int(np.argmax(ext))
    t = max(ext[ax] * 0.06, 1.0)
    fix_lo, fix_hi = lo - 1.0, hi + 1.0
    fix_hi = fix_hi.copy()
    fix_hi[ax] = lo[ax] + t
    load_lo, load_hi = lo - 1.0, hi + 1.0
    load_lo = load_lo.copy()
    load_lo[ax] = hi[ax] - t
    down = [0.0, 0.0, 0.0]
    down[2 if ax != 2 else 0] = -100.0
    spec = {
        "name": os.path.splitext(os.path.basename(model))[0],
        "_readme": "EDIT the anchors: where the part is held (fixed) and where it is loaded (load, newtons). "
                   "Coordinates are in mm in the model's own frame; see the -preview.png image. Then run.",
        "model": os.path.basename(model),
        "designSpace": "model",
        "material": material,
        "resolution": "normal",
        "anchors": [
            {"name": "support", "role": "fixed", "dofs": "xyz", "freezeMM": round(float(t) * 0.5, 2),
             "region": {"type": "box", "min": np.round(fix_lo, 2).tolist(), "max": np.round(fix_hi, 2).tolist()}},
            {"name": "load", "role": "load", "freezeMM": round(float(t) * 0.5, 2),
             "region": {"type": "box", "min": np.round(load_lo, 2).tolist(), "max": np.round(load_hi, 2).tolist()},
             "loads": {"main": down}},
        ],
        "keepOut": [],
        "objective": {"volumeFraction": 0.35, "combine": "sum"},
        "optimizer": {"iterations": 80},
        "limits": {"maxDisplacementMM": round(float(ext.max()) / 500, 3), "minSafetyFactor": 2.0},
        "output": {"smoothing": 10},
    }
    out = out or os.path.splitext(model)[0] + ".anneal.json"
    if os.path.exists(out):
        print(f"{out} already exists; not overwritten.")
        return out
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2)
    print(f"Wrote starter spec: {out}")
    print("  It fixes one end of the longest axis and loads the other end with 100 N.")
    print("  Edit the anchors to match how your part is really held and loaded, then:")
    print(f"  python -m anneal run \"{out}\"")
    return out


def cmd_run(spec, out=None, open_report=False):
    from .run import run
    record, html = run(spec, out)
    if open_report:
        _open(html)
    return 0 if all(c["ok"] for c in record["checks"]) else 2


def main(argv=None):
    p = argparse.ArgumentParser(prog="anneal", description="Topology optimization of existing parts on a voxel grid.")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("inspect", help="report sizes and write a coordinate preview")
    a.add_argument("model")
    a.add_argument("--out")
    a = sub.add_parser("init", help="write a starter spec for a model")
    a.add_argument("model")
    a.add_argument("--out")
    a.add_argument("--material", default="AlSi10Mg-LPBF")
    a = sub.add_parser("run", help="optimize a part from a spec")
    a.add_argument("spec")
    a.add_argument("--out")
    a.add_argument("--open", action="store_true", help="open the report when done")
    sub.add_parser("validate", help="run the solver validation gate")
    sub.add_parser("materials", help="list the material library")
    a = sub.add_parser("drop", help="drag-and-drop entry point")
    a.add_argument("path")
    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles and redirected output may not be UTF-8
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    from .problem import SpecError
    from .geometry import ModelError
    from .fem import SolverError
    try:
        if args.cmd == "inspect":
            cmd_inspect(args.model, args.out)
        elif args.cmd == "init":
            cmd_init(args.model, args.out, args.material)
        elif args.cmd == "run":
            return cmd_run(args.spec, args.out, args.open)
        elif args.cmd == "validate":
            from .validate import run_all
            print("Solver validation gate")
            return 0 if run_all() else 1
        elif args.cmd == "materials":
            from .materials import MATERIALS
            for k, v in MATERIALS.items():
                print(f"  {k:15s} E {v['E']:>8.0f} MPa  yield {v['yield']:>5.0f} MPa  "
                      f"{v['density']:.2f} g/cm3  min wall {v['minWallMM']} mm  ({v['note']})")
        elif args.cmd == "drop":
            path = args.path
            if path.lower().endswith(".json"):
                return cmd_run(path, None, True)
            if path.lower().endswith(MODEL_EXT):
                cmd_inspect(path)
                spec = cmd_init(path)
                _open(os.path.splitext(path)[0] + "-preview.png")
                _open(spec)
                print("\nEdit the spec that just opened, save it, then drop the .json file on Anneal.")
                return 0
            print(f"Drop a model ({', '.join(MODEL_EXT)}) or a spec (.json), not {path}")
            return 1
    except (SpecError, ModelError, SolverError, ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    return 0
