"""Density field -> smooth printable surface, plus geometry checks on the result."""
import numpy as np
import trimesh
from scipy import ndimage
from skimage import measure


def output_field(prob, x):
    """Combine optimized density with the design-space fill, frozen features and voids."""
    f = x * prob.fill
    f = np.maximum(f, np.where(prob.active, prob.solid_fill, 0.0))
    f = np.minimum(f, 1.0 - prob.void_fill)
    f[prob.frozen] = np.maximum(f[prob.frozen], prob.fill[prob.frozen])
    return f


def choose_level(prob, f, x):
    """Iso level that keeps the optimized material volume (clamped to 0.3..0.7)."""
    target = float((x * prob.fill).sum())
    lo, hi = 0.05, 0.95
    for _ in range(40):
        t = 0.5 * (lo + hi)
        v = float((f > t).sum())
        if v > target:
            lo = t
        else:
            hi = t
    return float(np.clip(0.5 * (lo + hi), 0.3, 0.7))


def keep_load_paths(prob, f, level, log=print, margin=0.1, max_drop=0.15, repair=True):
    """Make sure every load anchor connects to a fixed anchor through material at least `margin`
    above the iso level, so the connection survives smoothing and re-voxelization.

    Stage 1: lower the iso level by up to max_drop. Stage 2 (last resort): add material along the
    cheapest voxel path (Dijkstra; each voxel costs the density it lacks). Returns (field, level)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    g = prob.grid
    centres = g.elem_centers()
    groups = []
    for a in prob.anchors:
        sel = (a.region.sdf(centres) <= 2.5 * g.h) & prob.active
        if sel.any():
            groups.append((a.name, a.role, np.flatnonzero(sel)))
    f = f.copy()
    state = {"need": min(level + margin, 0.95)}

    def broken():
        lab, _ = ndimage.label(g.to3d(f > state["need"]))
        lab = g.to1d(lab)
        fixed_labels = {int(l) for n, r, e in groups if r == "fixed" for l in np.unique(lab[e]) if l > 0}
        return [(n, e) for n, r, e in groups if r == "load" and not (set(np.unique(lab[e]).tolist()) & fixed_labels)]

    level0 = level
    rec = {"isoLevelFrom": float(level0), "isoLevelTo": float(level0), "repaired": [], "addedVoxels": 0, "stillCut": []}
    prob._load_path_record = rec
    cut = broken()
    while cut and level > level0 - max_drop + 1e-9:
        level = max(0.1, level - 0.02)
        state["need"] = min(level + margin, 0.95)
        cut = broken()
        if level <= 0.1:
            break
    rec["isoLevelTo"] = float(level)
    if level < level0:
        log(f"  iso level lowered {level0:.2f} -> {level:.2f} to keep load paths connected")
    if not cut:
        return f, level
    if not repair:
        rec["stillCut"] = [n for n, _ in cut]
        log(f"  WARNING: anchor(s) {[n for n, _ in cut]} are not connected to a support and path repair is off. "
            f"Turn repair on, or raise volumeFraction or iterations.")
        return f, level
    need = state["need"]
    act = np.flatnonzero(prob.active)
    pos = np.full(g.nelem, -1)
    pos[act] = np.arange(act.size)
    i, j, k = g.elem_ijk(act)
    rows, cols = [], []
    for ok, step in ((i < g.nx - 1, 1), (j < g.ny - 1, g.nx), (k < g.nz - 1, g.nx * g.ny)):
        a_ = act[ok]
        b_ = a_ + step
        m = pos[b_] >= 0
        rows.append(pos[a_[m]])
        cols.append(pos[b_[m]])
    r = np.concatenate(rows)
    c = np.concatenate(cols)
    cost = np.maximum(0.0, need - f[act]) + 1e-3
    W = coo_matrix((np.concatenate([cost[c], cost[r]]), (np.concatenate([r, c]), np.concatenate([c, r]))),
                   shape=(act.size, act.size)).tocsr()
    sources = np.unique(np.concatenate([pos[e] for n, ro, e in groups if ro == "fixed"]))
    sources = sources[sources >= 0]
    dist, pred, _ = dijkstra(W, indices=sources, min_only=True, return_predecessors=True)
    added = 0
    nb = [1, -1, g.nx, -g.nx, g.nx * g.ny, -g.nx * g.ny]
    for name, e in cut:
        tgt = pos[e]
        tgt = tgt[tgt >= 0]
        start = tgt[np.argmin(dist[tgt])]
        if not np.isfinite(dist[start]):
            log(f"  WARNING: anchor '{name}' cannot be reached from any support inside the design space.")
            continue
        path = []
        v = start
        while v >= 0:
            path.append(act[v])
            v = pred[v]
        path = np.array(path)
        ring = np.unique(np.concatenate([path + d for d in nb]))
        ring = ring[(ring >= 0) & (ring < g.nelem)]
        ring = ring[prob.active[ring]]
        before = f.copy()
        f[ring] = np.maximum(f[ring], np.minimum(need + 0.05, prob.fill[ring]))
        f[path] = np.maximum(f[path], np.minimum(1.0, prob.fill[path]))
        added += int((f > level).sum() - (before > level).sum())
        rec["repaired"].append(name)
        log(f"  reconnected anchor '{name}' to the supports along a {path.size}-voxel path "
            f"({added} voxels of material added)")
    still = [n for n, _ in broken()]
    rec["addedVoxels"], rec["stillCut"] = int(added), still
    if still:
        log(f"  WARNING: anchor(s) {still} are still thinly connected. Raise volumeFraction or iterations.")
    return f, level


def surface(grid, f, level, upsample=2, smooth=10, log=print):
    f3 = np.pad(grid.to3d(f), 1)
    n_in = np.array(f3.shape)
    if upsample > 1:
        f3 = ndimage.zoom(f3, upsample, order=1)
    n_out = np.array(f3.shape)
    spacing = grid.h * (n_in - 1) / (n_out - 1)
    if f3.max() <= level:
        raise RuntimeError("The optimized field is empty at the chosen level. Raise volumeFraction.")
    verts, faces, _, _ = measure.marching_cubes(f3, level, spacing=tuple(spacing))
    verts = verts + grid.origin - 0.5 * grid.h
    mesh = trimesh.Trimesh(verts, faces, process=True)
    if smooth > 0:
        trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53, iterations=int(smooth))
    parts = mesh.split(only_watertight=False)
    if len(parts) > 1:
        vols = np.array([abs(p.volume) for p in parts])
        keep = [p for p, v in zip(parts, vols) if v >= 0.01 * vols.max()]
        if len(keep) < len(parts):
            log(f"  removed {len(parts) - len(keep)} floating fragment(s) under 1 % of the main body")
        mesh = trimesh.util.concatenate(keep)
    # Rebuild from vertices and faces: after smoothing, splitting and inverting, trimesh's cached
    # face normals can disagree with the winding. Every later check reads normals, so start clean.
    mesh = trimesh.Trimesh(np.array(mesh.vertices), np.array(mesh.faces), process=False)
    if mesh.volume < 0:
        mesh = trimesh.Trimesh(np.array(mesh.vertices), np.array(mesh.faces)[:, ::-1], process=False)
    return mesh


# output.detail x output.edges -> (upsample, Taubin smoothing iterations). "normal" + "smooth" is the
# 0.3 default. Sharp edges smooth little and are cut to the exact design space afterwards.
DETAIL = {"coarse": {"smooth": (1, 12), "sharp": (1, 3)},
          "normal": {"smooth": (2, 10), "sharp": (2, 3)},
          "fine":   {"smooth": (3, 8),  "sharp": (3, 2)}}


def surface_settings(out_opts):
    edges = str(out_opts.get("edges", "smooth")).lower()
    detail = str(out_opts.get("detail", "normal")).lower()
    if edges not in ("smooth", "sharp"):
        raise ValueError(f"output.edges '{edges}' is unknown. Use 'smooth' or 'sharp'.")
    if detail not in DETAIL:
        raise ValueError(f"output.detail '{detail}' is unknown. Use 'coarse', 'normal' or 'fine'.")
    up, sm = DETAIL[detail][edges]
    return edges, detail, int(out_opts.get("upsample", up)), int(out_opts.get("smoothing", sm))


def sharp_field(prob, f, x, reach=2):
    """Field for sharp outer edges: inside the design space the density itself (not faded by a
    partly filled boundary voxel), carried `reach` voxels outward from the nearest design voxel, so
    the surface runs past the design-space boundary and the exact cut makes the outer faces."""
    g = prob.grid
    f2 = f.copy()
    edge = (prob.fill > 0) & (prob.fill < 1) & prob.active
    f2[edge] = np.maximum(f2[edge], np.minimum(x[edge], 1.0 - prob.void_fill[edge]))
    f3 = g.to3d(f2)
    inside = g.to3d(prob.active & (prob.fill > 0))
    d, idx = ndimage.distance_transform_edt(~inside, return_indices=True)
    near = (~inside) & (d <= reach)
    f3[near] = f3[tuple(i[near] for i in idx)]
    return g.to1d(f3)


def sharp_clip(prob, mesh, log=print):
    """Cut the surface to the exact design space and remove keep-outs and anchor holes exactly."""
    from .finish import shape_mesh, _clean
    space = prob.space_mesh if prob.space_mesh is not None else trimesh.creation.box(bounds=list(prob.space_box))
    space = _clean(space)
    out = trimesh.boolean.intersection([mesh, space], engine="manifold")
    cuts = [shape_mesh(r) for r in prob.keepout] + [shape_mesh(v) for a in prob.anchors for v in a.voids]
    cuts = [c for c in cuts if c is not None]
    if cuts:
        out = trimesh.boolean.difference([out] + cuts, engine="manifold")
    out = _clean(out)
    parts = out.split(only_watertight=False)
    if len(parts) > 1:
        vols = np.array([abs(p.volume) for p in parts])
        out = trimesh.util.concatenate([p for p, v in zip(parts, vols) if v >= 0.01 * vols.max()])
    if not out.is_watertight or out.volume <= 0:
        raise RuntimeError("the sharp-edge cut did not give a closed solid")
    log(f"  sharp edges: surface cut to the exact design space ({len(out.faces):,} triangles)")
    return out


def member_thickness(grid, fill_b):
    """Member thickness in voxels along the skeleton of the as-built part (D9 check)."""
    from skimage.morphology import skeletonize
    b = grid.to3d(fill_b >= 0.5)
    if not b.any():
        return np.zeros(0)
    edt = ndimage.distance_transform_edt(np.pad(b, 1))[1:-1, 1:-1, 1:-1]
    sk = skeletonize(b)
    return 2.0 * edt[sk > 0]
