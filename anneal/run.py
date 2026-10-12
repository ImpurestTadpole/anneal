"""anneal run: spec -> optimized part, as-built re-solve, checks, report, run record."""
import hashlib
import json
import os
import platform
import shutil
import sys
import time
import numpy as np

from . import __version__
from .problem import Problem
from .fem import FEM
from .geometry import voxel_fill
from .optimize import simp
from .export import output_field, choose_level, keep_load_paths, surface, member_thickness
from . import report


# Measured in validation check V3: hex8 stiffness ratio (exact / voxel model) vs voxels through depth.
LOCKING = [(1.0, 0.70), (2.0, 0.869), (4.0, 0.957), (8.0, 0.983), (16.0, 0.995)]


def locking_factor(n_vox):
    """Fraction of true compliance the voxel model shows for members n_vox thick (conservative)."""
    xs = np.log2([p[0] for p in LOCKING])
    ys = [p[1] for p in LOCKING]
    return float(np.interp(np.log2(max(n_vox, 1.0)), xs, ys))


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def evaluate(prob, fill, label, log):
    """Solve a geometry (fill fractions, penalty 1) for every load case and measure it."""
    g = prob.grid
    active = prob._connected(fill >= 0.05)   # drop islands that touch no support
    fill = np.where(active, fill, 0.0)
    try:
        fixed, F, _ = prob.boundary(active)
    except Exception as e:
        if "touches no material" in str(e) and label.startswith("Optimized"):
            name = str(e).split("'")[1]
            raise RuntimeError(f"The optimized part lost contact with anchor '{name}'. Give that anchor a "
                               f"larger freezeMM (for example 3) so material stays where the part is held "
                               f"or loaded, then run again.") from None
        raise
    fem = FEM(g, active, fixed, prob.material["nu"], log=log)
    E0 = prob.material["E"]
    K = fem.assemble(E0 * fill[fem.act])
    Us = fem.solve(K, [fem.reduce_load(F[c]) for c in prob.cases], rtol=1e-9)
    anchor_nodes = prob.load_nodes(active)
    near = np.zeros(fem.act.size, bool)
    all_anchor = np.concatenate(list(anchor_nodes.values()))
    en = g.element_nodes(fem.act)
    near |= np.isin(en, all_anchor).any(axis=1)
    solid = fill[fem.act] >= 0.5
    res = {"label": label, "massG": float(fill.sum() * g.h ** 3 * prob.material["density"] / 1000),
           "volumeCM3": float(fill.sum() * g.h ** 3 / 1000), "cases": {}}
    worst_disp, worst_sig = 0.0, 0.0
    u_fields, vm_fields = {}, {}
    for c, u_r in zip(prob.cases, Us):
        u = fem.expand(u_r)
        mag = np.linalg.norm(u.reshape(-1, 3), axis=1)
        vm = fem.von_mises(u, E0)
        u_fields[c] = u.reshape(-1, 3).astype(np.float32)
        vm_full = np.zeros(g.nelem, np.float32)
        vm_full[fem.act] = vm
        vm_fields[c] = vm_full
        pool = vm[solid & ~near] if (solid & ~near).any() else vm
        peak = float(np.percentile(pool, 99.5))
        load_disp = {a.name: float(mag[anchor_nodes[a.name]].mean())
                     for a in prob.anchors if a.role == "load" and c in a.loads}
        res["cases"][c] = {"complianceNmm": float(fem.reduce_load(F[c]) @ u_r),
                           "maxDisplacementMM": float(mag.max()),
                           "loadPointDisplacementMM": load_disp,
                           "peakStressMPa": peak, "maxStressAtAnchorsMPa": float(vm.max())}
        worst_disp = max(worst_disp, float(mag.max()))
        worst_sig = max(worst_sig, peak)
    res["maxDisplacementMM"] = worst_disp
    res["peakStressMPa"] = worst_sig
    res["safetyFactor"] = prob.material["yield"] / worst_sig if worst_sig > 0 else float("inf")
    res["_fields"] = {"active": active, "u": u_fields, "vm": vm_fields}
    return res


def save_fields(path, grid, res):
    """Nodal displacement (mm) and element von Mises stress (MPa) per load case, for viewers."""
    if res is None:
        return
    arrays = {"origin": grid.origin, "h": np.array([grid.h]), "shape": np.array(grid.shape)}
    for c, u in res["_fields"]["u"].items():
        arrays[f"u::{c}"] = u
    for c, vm in res["_fields"]["vm"].items():
        arrays[f"vm::{c}"] = vm
    np.savez_compressed(path, **arrays)


def checks(prob, built, thick):
    out = []
    lim = prob.limits
    vf = prob.vf
    if "maxDisplacementMM" in lim:
        ok = built["maxDisplacementMM"] <= lim["maxDisplacementMM"]
        out.append({"name": "Maximum displacement (corrected for shear locking)", "ok": ok,
                    "value": f"{built['maxDisplacementMM']:.4g} mm (raw {built.get('maxDisplacementRawMM', built['maxDisplacementMM']):.4g})",
                    "limit": f"≤ {lim['maxDisplacementMM']} mm",
                    "fix": "" if ok else f"Raise objective.volumeFraction (now {vf}), widen the design space, "
                                         f"or use a stiffer material."})
    if "minSafetyFactor" in lim:
        ok = built["safetyFactor"] >= lim["minSafetyFactor"]
        out.append({"name": "Safety factor on yield", "ok": ok,
                    "value": f"{built['safetyFactor']:.2f}", "limit": f"≥ {lim['minSafetyFactor']}",
                    "fix": "" if ok else f"Raise volumeFraction (now {vf}), raise optimizer.minMemberMM so members "
                                         f"get thicker, or reduce the load."})
    if thick.size:
        frac = float((thick < 5.5).mean())
        good = frac < 0.25
        out.append({"name": "Members ≥ 6 voxels thick (shear locking)", "ok": True, "warn": not good,
                    "value": f"{100 * (1 - frac):.0f} % of skeleton", "limit": "≥ 75 % (else warning)",
                    "fix": "" if good else f"Displacement was scaled by {1 / built.get('lockingFactor', 1):.3f} to stay "
                                           f"conservative. For a sharper answer, rerun with resolution 'fine'."})
    minwall = prob.material.get("minWallMM", 0)
    if thick.size and minwall:
        tmin = float(np.percentile(thick, 2)) * prob.grid.h
        ok = tmin >= minwall
        out.append({"name": "Thinnest member vs process minimum wall", "ok": ok,
                    "value": f"{tmin:.2f} mm (2nd percentile)", "limit": f"≥ {minwall} mm",
                    "fix": "" if ok else f"Set optimizer.minMemberMM to at least {2 * minwall} mm."})
    return out


def next_volume_fraction(passes, limit, tol=0.01):
    """Bracketed log-log secant search for the lightest volume fraction that meets the limit.
    Returns None to stop."""
    aim = 0.93 * limit
    pts = sorted((p["vf"], p["built"]["maxDisplacementMM"]) for p in passes)
    good = [(v, d) for v, d in pts if d <= limit]
    bad = [(v, d) for v, d in pts if d > limit]
    if good and min(good)[1] >= 0.85 * limit:   # lightest passing design is close to the limit
        return None
    if good and bad:
        vb, db = max(bad)
        vg, dg = min(good)
        if vg - vb < tol:
            return None
        if vb < vg:
            a = np.log(db / dg) / np.log(vg / vb) if db > dg else 2.5
            v = vg * (dg / aim) ** (1 / max(a, 0.5))
            gap = vg - vb
            return float(np.clip(v, vb + 0.15 * gap, vg - 0.15 * gap))
        return float((vb + vg) / 2 + 0.01)
    (v1, d1) = (max(bad) if bad else min(good))
    a = 2.5
    if len(pts) >= 2:
        (va, da), (vc, dc) = pts[0], pts[-1]
        if vc > va and da > dc > 0:
            a = float(np.clip(np.log(da / dc) / np.log(vc / va), 1.0, 4.0))
    v = float(np.clip(v1 * (d1 / aim) ** (1 / a), 0.05, 0.9))
    if bad and v >= 0.9 and max(bad)[0] >= 0.89:
        return None
    if abs(v - v1) < tol:
        return None
    return v


def run(spec_path, out_dir=None, log=print, db_path=None):
    t0 = time.time()
    log(f"Anneal {__version__} — {spec_path}")
    prob = Problem(spec_path, log=log)
    log("Building the design space")
    prob.build()
    g = prob.grid
    out_dir = out_dir or os.path.join(prob.base, "runs", prob.name)
    os.makedirs(out_dir, exist_ok=True)

    fixed, F, info = prob.boundary(prob.active)
    log("  anchor nodes: " + ", ".join(f"{k} {v}" for k, v in info.items()))
    opt = prob.opt
    if int(opt.get("iterations", 80)) < 25:
        log("  WARNING: fewer than 25 iterations leaves the design grey; the exported part will be heavier "
            "than the target. Use 60 or more for a part you will make.")
    # D9: members at least 6 voxels thick unless the user asks for a larger minimum
    min_member = float(opt.get("minMemberMM", max(2 * prob.material.get("minWallMM", 0), 6 * g.h)))
    r_mm = max(min_member / 2, 1.5 * g.h)
    prob.derived.update({"filterRadiusMM": r_mm, "minMemberMM": min_member})

    def one_pass(vf, x0=None):
        log(f"Optimizing at volume fraction {vf:.3f} ({len(prob.cases)} load case(s): {', '.join(prob.cases)})")
        res = simp(g, prob.fill, prob.active, prob.frozen, fixed, F, prob.weights,
                   prob.material["E"], prob.material["nu"], vf,
                   iters=int(opt.get("iterations", 80)) if x0 is None else max(15, int(opt.get("iterations", 80)) * 2 // 5),
                   r_mm=r_mm, x0=x0,
                   p_final=float(opt.get("penalty", 3.0)), move=float(opt.get("move", 0.2)),
                   combine=prob.combine, log=log, beta_max=float(opt.get("sharpness", 4.0)))
        x = res["x"]
        log("Generating the surface")
        f = output_field(prob, x)
        iso = prob.out_opts.get("isoLevel", "auto")
        level = choose_level(prob, f, x) if iso in (None, "auto") else float(iso)
        lp = prob.spec.get("loadPaths", {})
        if lp.get("guard", True):
            f, level = keep_load_paths(prob, f, level, log=log, margin=float(lp.get("margin", 0.1)),
                                       max_drop=float(lp.get("maxDrop", 0.15)), repair=bool(lp.get("repair", True)))
        mesh = surface(g, f, level, upsample=int(prob.out_opts.get("upsample", 2)),
                       smooth=int(prob.out_opts.get("smoothing", 10)), log=log)
        log(f"  {len(mesh.faces):,} triangles, watertight: {mesh.is_watertight}")
        log("Re-solving the as-built part (voxelized from the exported surface)")
        fill_b = voxel_fill(mesh, g)
        fill_b = np.minimum(np.maximum(fill_b, np.where(prob.frozen, prob.fill, 0)), 1 - prob.void_fill)
        built = evaluate(prob, fill_b, "Optimized (as built)", log)
        thick = member_thickness(g, fill_b)
        n25 = float(np.percentile(thick, 25)) if thick.size else 8.0
        lf = locking_factor(n25)
        built["memberVoxelsP25"] = n25
        built["lockingFactor"] = lf
        built["maxDisplacementRawMM"] = built["maxDisplacementMM"]
        built["maxDisplacementMM"] = built["maxDisplacementMM"] / lf
        log(f"  thin members (25th percentile) {n25:.1f} voxels -> displacement corrected x{1 / lf:.3f} "
            f"for shear locking: {built['maxDisplacementMM']:.4g} mm")
        return {"vf": vf, "res": res, "x": x, "f": f, "level": level, "mesh": mesh,
                "fill_b": fill_b, "built": built, "thick": thick}

    target = prob.limits.get("maxDisplacementMM")
    minimise_mass = prob.spec.get("objective", {}).get("minimise") == "mass" and target
    max_passes = int(opt.get("massPasses", 5)) if minimise_mass else 1
    passes = []
    vf = prob.vf
    for k in range(max_passes):
        P = one_pass(vf, None if not passes else min(passes, key=lambda q: abs(q['vf'] - vf))['x'])
        passes.append(P)
        d = P["built"]["maxDisplacementMM"]
        if not minimise_mass:
            break
        log(f"  pass {k + 1}: volume fraction {vf:.3f}, displacement {d:.4g} mm vs limit {target} mm, "
            f"mass {P['built']['massG']:.1f} g")
        vf = next_volume_fraction(passes, target)
        if vf is None:
            break
    ok = [p for p in passes if p["built"]["maxDisplacementMM"] <= (target or np.inf)]
    best = min(ok, key=lambda p: p["built"]["massG"]) if (minimise_mass and ok) else \
        (min(passes, key=lambda p: p["built"]["maxDisplacementMM"]) if minimise_mass else passes[-1])
    if minimise_mass:
        prob.derived["massPasses"] = [f"vf {p['vf']:.3f}: {p['built']['maxDisplacementMM']:.3g} mm, "
                                      f"{p['built']['massG']:.1f} g" for p in passes]
        log(f"  chose volume fraction {best['vf']:.3f} ({best['built']['massG']:.1f} g)"
            + ("" if ok else " — no pass met the limit; this is the stiffest"))
    res, x, f, level, mesh, fill_b, built, thick = (best[k] for k in
                                                    ("res", "x", "f", "level", "mesh", "fill_b", "built", "thick"))
    prob.vf = best["vf"]
    res["all_history"] = [(f"pass {i + 1}: vf {p['vf']:.3f}", p["res"]["history"]) for i, p in enumerate(passes)] \
        if len(passes) > 1 else [("", res["history"])]
    history_record = [{"volumeFraction": p["vf"], "history": p["res"]["history"]} for p in passes]
    passes = [{"volumeFraction": p["vf"], "maxDisplacementMM": p["built"]["maxDisplacementMM"],
               "massG": p["built"]["massG"]} for p in passes]

    stl = os.path.join(out_dir, f"{prob.name}-optimized.stl")
    mesh.export(stl)          # always written: the viewer and the as-built check use it
    files = [stl]
    for fmt in prob.out_opts.get("formats", ["stl", "3mf"]):
        fmt = str(fmt).lower().lstrip(".")
        if fmt == "stl":
            continue
        if fmt not in ("3mf", "obj", "ply", "glb", "off"):
            log(f"  output format '{fmt}' is not supported; use stl, 3mf, obj, ply, glb or off")
            continue
        try:
            pth = os.path.join(out_dir, f"{prob.name}-optimized.{fmt}")
            mesh.export(pth)
            files.append(pth)
        except Exception as e:  # some formats need optional packages; STL is always written
            log(f"  ({fmt.upper()} not written: {e.__class__.__name__}; STL is complete)")
    prob.derived["isoLevel"] = level
    original = None
    if prob.mesh is not None:
        try:
            orig_fill = prob.space_fill if prob.spec.get("designSpace", "model") == "model" else voxel_fill(prob.mesh, g)
            original = evaluate(prob, orig_fill, "Original model", log)
        except Exception as e:
            log(f"  original model not evaluated: {e}")
    chk = checks(prob, built, thick)
    for c in chk:
        log(f"  [{'WARN' if c.get('warn') else 'PASS' if c['ok'] else 'FAIL'}] {c['name']}: {c['value']} (limit {c['limit']})"
            + (f" — {c['fix']}" if c["fix"] else ""))

    np.save(os.path.join(out_dir, "density.npy"), g.to3d(x).astype(np.float32))
    save_fields(os.path.join(out_dir, "fields-optimized.npz"), g, built)
    save_fields(os.path.join(out_dir, "fields-original.npz"), g, original)
    record = {
        "passes": passes,
        "anneal": __version__, "createdUTC": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0], "platform": platform.platform(),
        "spec": os.path.abspath(spec_path), "specSha256": _sha(spec_path),
        "model": getattr(prob, "model_path", None),
        "modelSha256": _sha(prob.model_path) if getattr(prob, "model_path", None) else None,
        "material": prob.material, "derived": prob.derived,
        "optimizer": {"iterations": len(res["history"]), "seconds": res["seconds"],
                      "amgBuilds": res["fem_builds"], "final": res["history"][-1]},
        "results": {"optimized": {k: v for k, v in built.items() if not k.startswith("_")},
                    "original": {k: v for k, v in original.items() if not k.startswith("_")} if original else None},
        "checks": chk,
        "history": history_record,
        "outputs": {os.path.basename(p): _sha(p) for p in files},
        "totalSeconds": time.time() - t0,
    }
    with open(os.path.join(out_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, default=float)
    shutil.copy(spec_path, os.path.join(out_dir, "spec.json"))
    html = None
    if prob.out_opts.get("report", True):
        view = mesh
        if len(mesh.faces) > 160_000:
            view = surface(g, f, level, upsample=1, smooth=int(prob.out_opts.get("smoothing", 10)), log=lambda *a: None)
        html = report.write(out_dir, prob, res, view, built, original, chk, thick, record)
    copy_to = prob.out_opts.get("copyTo")
    if copy_to:
        try:
            os.makedirs(copy_to, exist_ok=True)
            for pth in files:
                shutil.copy(pth, copy_to)
            log(f"  copied {len(files)} file(s) to {copy_to}")
        except OSError as e:
            log(f"  WARNING: could not copy the outputs to {copy_to}: {e}")
    if db_path is not False:
        try:
            from . import db
            db.record_run(out_dir, record, prob.name, db_path)
        except Exception as e:  # the run is complete even if the history database is not writable
            log(f"  (run not added to the history database: {e})")
    log(f"Done in {time.time() - t0:.0f} s." + (f" Report: {html}" if html else f" Files in {out_dir}"))
    return record, html
