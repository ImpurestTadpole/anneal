"""Design for manufacturing: printability checks on the as-built part.

Each rule comes from the process profile (materials.PROCESSES or your library):

  Build volume      the part must fit the machine, on its build direction
  Minimum wall      thinnest members vs the larger of the material's and the process's minimum wall
  Minimum hole      holes smaller than the process can print round (drill them after printing)
  Overhang          downward surfaces steeper than maxOverhangDeg from vertical need support;
                    support volume estimated by casting down to the part or the build plate;
                    the axis build direction with the least support is suggested
  Enclosed voids    closed cavities trap powder (SLS, LPBF) or are fine (FDM)
  Layer strength    tension across the layers vs yield x zStrengthFactor (FDM is weak between layers)

The checks look at the exported part. They do not change the optimization (an overhang
constraint inside SIMP is a later step); they tell you what the printer will see.
"""
import numpy as np
from scipy import ndimage

AXES = {"+Z": (0, 0, 1), "-Z": (0, 0, -1), "+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0)}


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def axis_name(b):
    b = _unit(b)
    for k, v in AXES.items():
        if np.allclose(b, v, atol=1e-6):
            return k
    return "[" + ", ".join(f"{x:.2f}" for x in b) + "]"


def overhang_faces(mesh, b, max_deg, plate_tol):
    """Boolean mask of faces that need support, and of faces resting on the build plate."""
    n = mesh.face_normals
    nb = n @ b
    h = mesh.triangles_center @ b
    hmin = float((mesh.vertices @ b).min())
    plate = (nb < -0.98) & (h - hmin < plate_tol)
    if max_deg >= 90:
        return np.zeros(len(n), bool), plate
    # overhang angle from vertical: 0 = vertical wall, 90 = flat ceiling
    ang = np.degrees(np.arcsin(np.clip(-nb, -1, 1)))
    need = (nb < 0) & (ang > max_deg + 1e-6) & ~plate
    return need, plate


def support_volume(mesh, need, b, grid, fill, step_frac=0.5):
    """Volume (mm3) under the faces that need support, down to the part or the build plate."""
    if not need.any():
        return 0.0
    f3 = grid.to3d(fill) >= 0.5
    h = grid.h
    c = mesh.triangles_center[need]
    a = mesh.area_faces[need] * np.abs(mesh.face_normals[need] @ b)
    hmin = float((mesh.vertices @ b).min())
    start = c - b * 0.75 * h
    length = np.maximum(start @ b - hmin, 0.0)
    L = np.zeros(len(c))
    alive = np.ones(len(c), bool)
    step = step_frac * h
    nmax = int(np.ceil(length.max() / step)) + 1 if len(c) else 0
    for k in range(nmax):
        d = k * step
        p = start - b * d
        idx = np.floor((p - grid.origin) / h).astype(int)
        inside = np.all((idx >= 0) & (idx < np.array(grid.shape)), axis=1)
        hit = np.zeros(len(c), bool)
        ii = np.flatnonzero(inside & alive)
        if ii.size:
            hit[ii] = f3[idx[ii, 0], idx[ii, 1], idx[ii, 2]]
        done = alive & (hit | (d >= length))
        L[done] = np.minimum(d, length[done])
        alive &= ~done
        if not alive.any():
            break
    L[alive] = length[alive]
    return float((a * L).sum())


def enclosed_voids(grid, fill, min_voxels=4):
    empty = np.pad(grid.to3d(fill) < 0.5, 1, constant_values=True)
    lab, n = ndimage.label(empty)
    outside = lab[0, 0, 0]
    sizes = np.bincount(lab.ravel(), minlength=n + 1)
    cav = [i for i in range(1, n + 1) if i != outside and sizes[i] >= min_voxels]
    vol = float(sum(sizes[i] for i in cav)) * grid.h ** 3
    return len(cav), vol


def fits(extent_b, volume):
    """Part extents (a, b along the plate, c along the build direction) vs the machine."""
    xy = sorted(extent_b[:2])
    mxy = sorted(volume[:2])
    return xy[0] <= mxy[0] and xy[1] <= mxy[1] and extent_b[2] <= volume[2]


def _frame(b):
    b = _unit(b)
    x = np.array([1.0, 0, 0]) if abs(b[0]) < 0.9 else np.array([0, 1.0, 0])
    x = x - b * (x @ b)
    x /= np.linalg.norm(x)
    return x, np.cross(b, x), b


def _machining(prob, proc, g, fill_b, checks, summary):
    """3-axis / 5-axis machinability: tool access, tool reach and closed cavities."""
    from .machining import assess as mach, directions
    axes = int(proc.get("axes", 3))
    D = float(proc.get("toolDiameterMM", 6.0))
    dirs = directions(axes, proc.get("setups", ["+z"]), proc.get("fixture", "-z"))
    solid = g.to3d(fill_b) > 0.5
    r = mach(solid, g.h, D, dirs)
    summary["machining"] = {k: v for k, v in r.items() if k != "mask"}
    summary["machining"].update({"axes": axes, "toolDiameterMM": D,
                                 "setups": proc.get("setups") if axes == 3 else None,
                                 "fixture": proc.get("fixture", "-z") if axes == 5 else None})
    share = r["unreachableShare"]
    ok = share <= 0.01
    how = (f"from {', '.join(proc.get('setups', ['+z']))}" if axes == 3 else f"5-axis, fixture on {proc.get('fixture', '-z')}")
    checks.append({"name": f"Machinability: tool access ({axes}-axis, Ø{D:g} mm tool)", "group": "dfm", "ok": ok,
                   "value": f"{r['unreachableAreaMM2']:.0f} mm² of surface the tool cannot reach ({100 * share:.1f} %), {how}",
                   "limit": "≤ 1 % of the surface",
                   "fix": "" if ok else ("Add a setup (for example -z) or use 5-axis, turn on the optimizer's machining "
                                         "filter, or use a smaller tool." if axes == 3 else
                                         "Use a smaller tool, or widen slots and inside corners (optimizer.minMemberMM).")})
    reach = float(proc.get("maxDepthToDiameter", 4.0)) * D
    okr = r["deepestCutMM"] <= reach
    checks.append({"name": "Machinability: tool reach", "group": "dfm", "ok": True, "warn": not okr,
                   "value": f"deepest cut {r['deepestCutMM']:.1f} mm below the stock face ({r['deepestCutMM'] / D:.1f} × tool Ø)",
                   "limit": f"≤ {reach:g} mm ({proc.get('maxDepthToDiameter', 4.0):g} × Ø)",
                   "fix": "" if okr else "Use a longer tool, cut from another side, or make the pocket shallower."})
    summary["stockMM"] = r["stockMM"]
    pv = float(fill_b.sum() * g.h ** 3)
    checks.append({"name": "Machinability: stock and material removed", "group": "dfm", "ok": True,
                   "value": f"stock {r['stockMM'][0]:.0f} × {r['stockMM'][1]:.0f} × {r['stockMM'][2]:.0f} mm, "
                            f"{100 * (1 - pv / r['stockVolumeMM3']):.0f} % of it machined away",
                   "limit": "–", "fix": ""})
    n_cav, v_cav = enclosed_voids(g, fill_b)
    summary["enclosedVoids"] = {"count": n_cav, "volumeCM3": v_cav / 1000}
    checks.append({"name": "Machinability: closed cavities", "group": "dfm", "ok": n_cav == 0,
                   "value": f"{n_cav} cavit{'y' if n_cav == 1 else 'ies'}" if n_cav else "none",
                   "limit": "none (a cutter cannot reach them)",
                   "fix": "" if not n_cav else "Open each cavity to the outside, or turn on the machining filter."})
    return checks, summary


def assess(prob, mesh, fill_b, built, thick):
    """Printability checks. Returns (checks, summary)."""
    proc = prob.process
    g = prob.grid
    checks, summary = [], {}
    if not proc:
        return checks, {"process": None}
    b = _unit(proc.get("buildDirection", [0, 0, 1]))
    name = proc.get("name", "process")
    summary["process"] = name
    summary["buildDirection"] = axis_name(b)
    pre = "Machinability" if proc.get("method") == "machining" else "Printability"

    # build volume
    bv = proc.get("buildVolumeMM")
    x, y, z = _frame(b)
    V = mesh.vertices
    ext = np.array([np.ptp(V @ x), np.ptp(V @ y), np.ptp(V @ z)])
    summary["extentMM"] = ext.round(2).tolist()
    if bv:
        ok = fits(ext, bv)
        checks.append({"name": ("Machinability: fits the machine travel" if proc.get("method") == "machining" else "Printability: fits the build volume"), "ok": ok, "group": "dfm",
                       "value": f"{ext[0]:.0f} × {ext[1]:.0f} × {ext[2]:.0f} mm (height along {axis_name(b)})",
                       "limit": f"{bv[0]:g} × {bv[1]:g} × {bv[2]:g} mm",
                       "fix": "" if ok else "Turn the part (another build direction), split it, or use a larger machine."})

    # minimum wall
    wall = max(prob.material.get("minWallMM", 0.0), proc.get("minWallMM", 0.0))
    if thick.size and wall:
        tmin = float(np.percentile(thick, 2)) * g.h
        ok = tmin >= wall
        checks.append({"name": f"{pre}: thinnest member vs minimum wall", "ok": ok, "group": "dfm",
                       "value": f"{tmin:.2f} mm (2nd percentile)", "limit": f"≥ {wall:g} mm",
                       "fix": "" if ok else f"Set the smallest member (optimizer.minMemberMM) to at least {2 * wall:g} mm."})
        summary["thinnestMemberMM"] = tmin

    # minimum hole
    hmin = proc.get("minHoleMM")
    if hmin:
        holes = []
        for a in prob.spec.get("anchors", []):
            r = a.get("region", {})
            if r.get("type") == "pipe":
                holes.append((a.get("name", "hole"), r["rIn"] + r["r"]))
        for i, r in enumerate(prob.spec.get("keepOut", [])):
            if r.get("type") == "cylinder":
                holes.append((f"keep-out {i + 1}", 2 * r["r"]))
        small = [(n, d) for n, d in holes if d < hmin]
        if holes:
            checks.append({"name": f"{pre}: holes at least the minimum hole size", "ok": True, "warn": bool(small),
                           "group": "dfm", "value": ", ".join(f"{n} Ø{d:.1f}" for n, d in (small or holes)[:4]),
                           "limit": f"Ø ≥ {hmin:g} mm",
                           "fix": "" if not small else "Print these holes undersize and drill or ream them to size."})

    if proc.get("method") == "machining":
        return _machining(prob, proc, g, fill_b, checks, summary)

    # overhangs and support
    max_deg = float(proc.get("maxOverhangDeg", 90))
    need, plate = overhang_faces(mesh, b, max_deg, plate_tol=0.6 * g.h)
    area = float(mesh.area_faces[need].sum())
    total = float(mesh.area_faces.sum())
    summary["overhangAreaMM2"] = area
    summary["overhangPercent"] = 100 * area / total if total else 0
    if max_deg < 90:
        sv = support_volume(mesh, need, b, g, fill_b)
        summary["supportVolumeCM3"] = sv / 1000
        part_v = abs(float(mesh.volume))
        best = {}
        for k, v in AXES.items():
            bb = np.array(v, float)
            nd, _ = overhang_faces(mesh, bb, max_deg, 0.6 * g.h)
            xx, yy, zz = _frame(bb)
            e = np.array([np.ptp(V @ xx), np.ptp(V @ yy), np.ptp(V @ zz)])
            best[k] = {"overhangMM2": float(mesh.area_faces[nd].sum()), "fits": bool(fits(e, bv)) if bv else True}
        cand = [k for k in best if best[k]["fits"]] or list(best)
        bk = min(cand, key=lambda k: best[k]["overhangMM2"])
        summary["directions"] = best
        summary["bestDirection"] = bk
        allowed = proc.get("supportsAllowed", True)
        small = area <= 0.01 * total
        better = best[bk]["overhangMM2"] < 0.7 * area and bk != axis_name(b)
        checks.append({
            "name": f"Printability: overhangs steeper than {max_deg:g}° from vertical", "group": "dfm",
            "ok": small or allowed, "warn": (not small) and allowed,
            "value": f"{area:.0f} mm² ({summary['overhangPercent']:.1f} % of the surface), "
                     f"support about {sv / 1000:.1f} cm³ ({100 * sv / part_v if part_v else 0:.0f} % of the part)",
            "limit": "none, or supports allowed" if allowed else "none (this process has no supports)",
            "fix": "" if small else (f"Build along {bk} instead: {best[bk]['overhangMM2']:.0f} mm² of overhang. "
                                     if better else "") + ("Supports will be needed; add them in the slicer."
                                                           if allowed else "Change the build direction.")})
    else:
        checks.append({"name": "Printability: overhangs", "ok": True, "group": "dfm",
                       "value": f"{name} needs no support (the powder holds the part)", "limit": "–", "fix": ""})

    # enclosed voids
    policy = proc.get("enclosedVoids", "allow")
    n_cav, v_cav = enclosed_voids(g, fill_b)
    summary["enclosedVoids"] = {"count": n_cav, "volumeCM3": v_cav / 1000}
    if n_cav:
        checks.append({"name": "Printability: closed cavities", "group": "dfm",
                       "ok": policy != "fail", "warn": policy == "warn",
                       "value": f"{n_cav} cavit{'y' if n_cav == 1 else 'ies'}, {v_cav / 1000:.2f} cm³",
                       "limit": {"allow": "allowed", "warn": "avoid", "fail": "none (powder is trapped)"}[policy],
                       "fix": "" if policy == "allow" else "Add a drain hole of at least 2 mm into each cavity, or open it in CAD."})
    else:
        checks.append({"name": "Printability: closed cavities", "ok": True, "group": "dfm", "value": "none",
                       "limit": "–", "fix": ""})

    # layer strength
    if "safetyFactorLayers" in built:
        zf = float(proc.get("zStrengthFactor", 1.0))
        sf = built["safetyFactorLayers"]
        need_sf = prob.limits.get("minSafetyFactor", 1.0)
        ok = sf >= need_sf
        if zf < 0.999 or not ok:
            checks.append({"name": "Printability: strength across the layers", "group": "dfm", "ok": ok,
                           "value": f"safety factor {sf:.2f} (tension {built['peakLayerTensionMPa']:.1f} MPa across "
                                    f"layers, layer strength {prob.material['yield'] * zf:.1f} MPa)",
                           "limit": f"≥ {need_sf:g}",
                           "fix": "" if ok else "Turn the part so the main tension runs along the layers, or raise the "
                                                "share of material, or use a material with better layer adhesion."})
        summary["safetyFactorLayers"] = sf
    return checks, summary
