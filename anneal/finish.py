"""Exact-geometry finishing (spec output.exactFeatures).

The optimizer works on voxels, so the exported surface is smooth but not exact: bolt holes come
out slightly round-off and flange faces slightly wavy. This step puts the exact geometry back:

  part = (optimized surface  UNION  (original model  INTERSECT  kept regions))  MINUS  keep-outs

Kept regions are the spec's 'keep' regions and, for every support or load picked on a hole, boss
or face, the original material around that feature (to the anchor's freezeMM depth). Keep-outs are
the spec's 'keepOut' regions, the holes of anchors marked "hole": true, and bore features.
Booleans use manifold3d (Apache-2.0). If it is missing or a Boolean fails, the unfinished surface
is kept and the run says so.
"""
import numpy as np
import trimesh

from .kernel import Box, Cylinder, Sphere, Prism, Union


def shape_mesh(s, sections=96):
    """Closed mesh of a kernel shape."""
    if isinstance(s, Union):
        parts = [shape_mesh(x, sections) for x in s.shapes]
        parts = [p for p in parts if p is not None]
        return trimesh.boolean.union(parts, engine="manifold") if len(parts) > 1 else (parts[0] if parts else None)
    if isinstance(s, Prism):
        return s.mesh()
    if isinstance(s, Sphere):
        m = trimesh.creation.icosphere(subdivisions=4, radius=s.r)
        m.apply_translation(s.c)
        return m
    if isinstance(s, Cylinder):
        T = trimesh.geometry.align_vectors([0, 0, 1], s.ax)
        T[:3, 3] = (s.a + s.b) / 2
        if s.r_in > 0:
            return trimesh.creation.annulus(r_min=s.r_in, r_max=s.r, height=s.L, sections=sections, transform=T)
        return trimesh.creation.cylinder(radius=s.r, height=s.L, sections=sections, transform=T)
    if isinstance(s, Box):
        if s.frame is None:
            return trimesh.creation.box(bounds=[s.lo, s.hi])
        f = s.frame
        T = np.eye(4)
        T[:3, 0], T[:3, 1], T[:3, 2] = f.x, f.y, f.z
        T[:3, 3] = f.to_world(np.array([0.0, 0.0, s.z0 + s.size[2] / 2]))
        return trimesh.creation.box(extents=s.size, transform=T)
    return None


def _feature_keep(a, h):
    """Solid around an anchor's picked feature, to the anchor's freeze depth."""
    fz = 2.0 * h if a.freeze_mm is None else a.freeze_mm
    d = a.region_dict or {}
    t = d.get("type")
    if t == "pipe":
        r = (d["r"] + d["rIn"]) / 2
        return Cylinder(d["from"], d["to"], r + max(fz, h))
    if t == "obox":
        from .kernel import Frame
        size = np.asarray(d["size"], float)
        return Box(frame=Frame(d["center"], d["normal"], d.get("xdir")), size=[size[0], size[1], 2 * max(fz, h)],
                   z0=-max(fz, h))
    return None


def _clean(m):
    m = trimesh.Trimesh(m.vertices, m.faces, process=True)
    if m.volume < 0:
        m.invert()
    return m


def finish(prob, surf, log=print):
    """Return (mesh, info). info is None when the option is off."""
    if not prob.out_opts.get("exactFeatures", True):
        return surf, None
    info = {"kept": [], "cut": []}
    try:
        import manifold3d  # noqa: F401
    except Exception:
        info["skipped"] = "manifold3d is not installed (pip install manifold3d); the surface is not finished."
        log("  exact features skipped: " + info["skipped"])
        return surf, info
    h = prob.grid.h
    keeps, cuts = [], []
    for i, r in enumerate(prob.keep):
        keeps.append((f"keep {i + 1}", r))
    for a in prob.anchors:
        s = _feature_keep(a, h)
        if s is not None:
            keeps.append((a.name, s))
    for i, r in enumerate(prob.keepout):
        cuts.append((f"keep-out {i + 1}", r))
    for a in prob.anchors:
        for k, v in enumerate(a.voids):
            cuts.append((f"{a.name} hole" + (f" {k + 1}" if len(a.voids) > 1 else ""), v))
    out = surf
    try:
        if getattr(prob, "keep_model", False) and prob.mesh is not None:   # grow from interfaces
            model = _clean(prob.mesh)
            out = trimesh.boolean.union([out, model], engine="manifold")
            info["kept"].append("whole model")
            info["keptModelCM3"] = float(model.volume / 1000)
            keeps = []
        if keeps and prob.mesh is not None:
            model = _clean(prob.mesh)
            K = [shape_mesh(s) for _, s in keeps]
            K = [k for k in K if k is not None]
            region = trimesh.boolean.union(K, engine="manifold") if len(K) > 1 else K[0]
            kept = trimesh.boolean.intersection([model, region], engine="manifold")
            if kept.volume > 1e-9:
                out = trimesh.boolean.union([out, kept], engine="manifold")
            info["kept"] += [n for n, _ in keeps]
            info["keptCM3"] = float(kept.volume / 1000)
        if cuts:
            C = [shape_mesh(s) for _, s in cuts]
            C = [c for c in C if c is not None]
            if C:
                before = out.volume
                cut = trimesh.boolean.union(C, engine="manifold") if len(C) > 1 else C[0]
                out = trimesh.boolean.difference([out, cut], engine="manifold")
                info["cut"] = [n for n, _ in cuts]
                info["cutCM3"] = float((before - out.volume) / 1000)
        out = _clean(out)
        if not out.is_watertight or out.volume <= 0:
            raise RuntimeError("the result is not a closed solid")
        # keep only pieces that touch the main body (a kept region may sit outside the design)
        parts = out.split(only_watertight=False)
        if len(parts) > 1:
            big = max(parts, key=lambda m: m.volume)
            out = big
            info["droppedPieces"] = len(parts) - 1
            log(f"  exact features: {len(parts) - 1} separate piece(s) removed; only the largest piece is kept")
        log(f"  exact features: kept {len(info['kept'])} region(s) of the original model"
            f" ({info.get('keptCM3', info.get('keptModelCM3', 0)):.2f} cm3), cut {len(info['cut'])} keep-out(s)"
            f" ({info.get('cutCM3', 0):.2f} cm3)")
        return out, info
    except Exception as e:
        info["skipped"] = f"exact-geometry Boolean failed ({e}); the smooth surface is used."
        log("  " + info["skipped"])
        return surf, info
