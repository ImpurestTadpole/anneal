"""Command line: python -m anneal <command>

  inspect MODEL          sizes, volume, closed or not, and a coordinate preview image
  init MODEL             write a starter spec next to the model (edit the anchors, then run)
  run SPEC               optimize, re-solve the result, check it, write the report
  validate               solver validation gate (10 checks)
  drop PATH              for drag-and-drop: a model gives init, a spec gives run
  gui | app              the graphical interface in the browser | in its own window
  doctor                 start-up check: Python, packages, desktop window, log files
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


def cmd_materials(a):
    from . import materials as M
    if a.action == "list":
        print(f"Library file for your own materials: {M.library_path()}")
        for k, v in M.all_materials().items():
            tag = "built-in" if v["builtIn"] else "yours"
            print(f"  {k:22.22s} E {v['E']:>8.0f} MPa  yield {v['yield']:>6.1f} MPa  {v['density']:.2f} g/cm3  "
                  f"wall {v.get('minWallMM', 1.0)} mm  {v.get('process', '-'):5s} {tag}")
        return 0
    if a.action == "log":
        for e in M.library_log(50):
            print(f"  {e['time']}  {e['action']:8s} {e['kind']:8s} {e['name']}" + (f"  from {e['source']}" if e['source'] else ""))
        return 0
    if a.action == "processes":
        for k, v in M.all_processes().items():
            print(f"  {k:10s} wall {v['minWallMM']} mm, hole {v['minHoleMM']} mm, overhang {v['maxOverhangDeg']:g}°, "
                  f"voids {v['enclosedVoids']}, Z strength x{v['zStrengthFactor']}, build {v['buildVolumeMM']} mm"
                  f"{'' if v['builtIn'] else '  (yours)'}")
        return 0
    if a.action == "import":
        if not a.target:
            raise ValueError("Give the file: anneal materials import my-materials.csv")
        with open(a.target, "rb") as fh:
            new, problems = M.parse_import(a.target, fh.read())
        for name, m in new.items():
            print(f"  {name}: E {m['E']:g} MPa, nu {m['nu']:g}, {m['density']:g} g/cm3, yield {m['yield']:g} MPa"
                  + (f", Z x{m['zStrengthFactor']}" if "zStrengthFactor" in m else "") + (f", {m['process']}" if m.get("process") else ""))
        for p in problems:
            print("  " + p)
        if not new:
            print("Nothing to import.")
            return 1
        if a.dry_run:
            print(f"Dry run: {len(new)} material(s) read, nothing saved.")
            return 0
        added, replaced, skipped = M.add_materials(new, overwrite=not a.keep_existing, source=os.path.basename(a.target))
        print(f"Saved to {M.library_path()}: {len(added)} added, {len(replaced)} replaced, {len(skipped)} kept as they were.")
        return 0
    if a.action == "add":
        if not a.target:
            raise ValueError("Give a name: anneal materials add \"PETG-CF\" --E 3800 --nu 0.35 --density 1.25 --yield 52")
        m = {k: getattr(a, k2) for k, k2 in (("E", "E"), ("nu", "nu"), ("density", "density"), ("yield", "yield"),
                                             ("minWallMM", "min_wall"), ("zStrengthFactor", "z_factor"),
                                             ("process", "process"), ("note", "note")) if getattr(a, k2) is not None}
        m = M.validate_material(m, f"'{a.target}'")
        M.add_materials({a.target: m}, source="typed with anneal materials add")
        print(f"Saved '{a.target}' to {M.library_path()}")
        return 0
    if a.action == "remove":
        M.remove_material(a.target)
        print(f"Removed '{a.target}'.")
        return 0
    if a.action == "export":
        out = a.target or "anneal-materials.json"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(M.export_library(), fh, indent=2)
        print(f"Wrote {out}. Import it on another PC with: anneal materials import {out}")
        return 0


def cmd_run(spec, out=None, open_report=False):
    from .run import run
    record, html = run(spec, out)
    if open_report:
        _open(html)
    return 0 if all(c["ok"] for c in record["checks"]) else 2


GUI_COMMANDS = ("gui", "app", "shortcut", "doctor")


def main(argv=None):
    """Entry point. For the GUI commands an unexpected error goes to the start-up log
    (~/Anneal Projects/anneal-startup.log) and to a message box (Windows) or the console, because the
    desktop icon starts Anneal with pythonw, which has no console to show a traceback."""
    words = list(sys.argv[1:] if argv is None else argv)
    cmd = next((w for w in words if not w.startswith("-")), "")
    if cmd not in GUI_COMMANDS:
        return _main(argv)
    try:
        return _main(argv)
    except (SystemExit, KeyboardInterrupt):
        raise
    except BaseException as e:
        from .gui.desktop import report_startup_error
        report_startup_error(e, f"Anneal could not start ({cmd})", force_box=(cmd == "app"))
        return 1


def _main(argv=None):
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
    a = sub.add_parser("gui", help="open the graphical interface in your browser")
    a.add_argument("--workspace", help="projects folder (default: ~/Anneal Projects)")
    a.add_argument("--port", type=int, default=8765)
    a.add_argument("--no-browser", action="store_true")
    a = sub.add_parser("app", help="open Anneal in its own desktop window")
    a.add_argument("--workspace")
    a.add_argument("--port", type=int, default=8765)
    sub.add_parser("shortcut", help="add Anneal to the desktop and Start menu")
    sub.add_parser("doctor", help="start-up check: Python, packages, desktop window, log files")
    a = sub.add_parser("history", help="list past runs from the history database")
    a.add_argument("--project")
    a.add_argument("--limit", type=int, default=30)
    a = sub.add_parser("materials", help="list, import, add, remove or export materials")
    a.add_argument("action", nargs="?", default="list", choices=["list", "import", "add", "remove", "export", "processes", "log"])
    a.add_argument("target", nargs="?", help="file (import/export) or material name (add/remove)")
    a.add_argument("--dry-run", action="store_true", help="import: show what would be added, save nothing")
    a.add_argument("--keep-existing", action="store_true", help="import: do not replace materials with the same name")
    for k, h in (("E", "Young's modulus, MPa"), ("nu", "Poisson's ratio"), ("density", "g/cm3"), ("yield", "yield strength, MPa"),
                 ("min-wall", "minimum wall, mm"), ("z-factor", "layer strength / in-plane strength"), ("process", "FDM, SLS, LPBF or yours"),
                 ("note", "free text")):
        a.add_argument(f"--{k}", dest=k.replace("-", "_"), help=h)
    a = sub.add_parser("drop", help="drag-and-drop entry point")
    a.add_argument("path")
    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles and redirected output may not be UTF-8
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    try:
        from .problem import SpecError
        from .geometry import ModelError
        from .fem import SolverError
    except Exception:
        if args.cmd not in GUI_COMMANDS + ("history", "materials"):
            raise
        # The solver stack (scipy, pyamg, trimesh...) is broken. The window can still open, so the
        # person sees the problem; runs will report the import error.
        from .gui.desktop import log_startup
        import traceback
        log_startup("The solver could not be loaded. The window opens, but runs will fail.\n" + traceback.format_exc())
        SpecError = ModelError = SolverError = type("Unavailable", (Exception,), {})
    try:
        if args.cmd == "inspect":
            cmd_inspect(args.model, args.out)
        elif args.cmd == "init":
            cmd_init(args.model, args.out, args.material)
        elif args.cmd == "run":
            return cmd_run(args.spec, args.out, args.open)
        elif args.cmd == "gui":
            from .gui.server import serve
            serve(args.workspace, args.port, not args.no_browser)
        elif args.cmd == "app":
            from .gui.desktop import app
            return app(args.workspace, args.port)
        elif args.cmd == "shortcut":
            from .gui.desktop import shortcut
            return shortcut()
        elif args.cmd == "doctor":
            from .gui.desktop import doctor
            return doctor()
        elif args.cmd == "history":
            from . import db
            from .gui.server import default_workspace
            db.index_workspace(default_workspace())
            rows = db.query(project=args.project, limit=args.limit)
            if not rows:
                print("No runs recorded yet.")
            for r in rows:
                print(f"  {r['created'] or '':20s} {r['project']:24.24s} {r['material'] or '':14s} "
                      f"{r['mass_g'] or 0:8.1f} g  {r['max_disp_mm'] or 0:.4g} mm  "
                      f"SF {r['safety_factor'] or 0:.2f}  {'OK  ' if r['all_ok'] else 'FAIL'}  {r['run_dir']}")
        elif args.cmd == "validate":
            from .validate import run_all
            from .provenance import store_gate
            print("Solver validation gate")
            lines = []
            ok = run_all(log=lambda m: (print(m), lines.append(m)))
            rec = store_gate(ok, lines)
            print(f"  solver build {rec['solverSha256'][:12]}: result stored, runs made with this build will cite it")
            return 0 if ok else 1
        elif args.cmd == "materials":
            return cmd_materials(args)
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
    except (SpecError, ModelError, SolverError, ValueError, FileNotFoundError, RuntimeError, OSError) as e:
        if args.cmd in GUI_COMMANDS:   # no console under pythonw: log it and show it
            raise
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    return 0
