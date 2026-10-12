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


def keep_load_paths(prob, f, level, log=print, floor=0.08):
    """Lower the iso level until every anchor's frozen material is connected to a fixed anchor."""
    g = prob.grid
    centres = None
    groups = []
    for a in prob.anchors:
        if centres is None:
            centres = g.elem_centers()
        sel = (a.region.sdf(centres) <= 2.5 * g.h) & prob.active
        if sel.any():
            groups.append((a.name, a.role, np.flatnonzero(sel)))
    t = level
    while True:
        lab, _ = ndimage.label(g.to3d(f > t))
        lab = g.to1d(lab)
        fixed_labels = {int(l) for n, r, e in groups if r == "fixed" for l in np.unique(lab[e]) if l > 0}
        broken = [n for n, r, e in groups if r == "load" and not (set(np.unique(lab[e]).tolist()) & fixed_labels)]
        if not broken or t <= floor:
            if broken:
                log(f"  WARNING: anchor(s) {broken} stay disconnected from the supports even at level {t:.2f}. "
                    f"Raise volumeFraction or run more iterations.")
            elif t < level:
                log(f"  iso level lowered {level:.2f} -> {t:.2f} so every load path stays connected")
            return t
        t = max(floor, t - 0.02)


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
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def member_thickness(grid, fill_b):
    """Member thickness in voxels along the skeleton of the as-built part (D9 check)."""
    from skimage.morphology import skeletonize
    b = grid.to3d(fill_b >= 0.5)
    if not b.any():
        return np.zeros(0)
    edt = ndimage.distance_transform_edt(np.pad(b, 1))[1:-1, 1:-1, 1:-1]
    sk = skeletonize(b)
    return 2.0 * edt[sk > 0]
