"""Turn a click on the model into an anchor region.

Flood-fill from the clicked triangle across edges that bend less than a set angle, then
recognise what was selected:
  flat face   -> oriented slab ('obox') a little thicker than one voxel
  hole / boss -> 'pipe' that straddles the cylindrical wall (fit by least squares)
  anything else (or patch mode) -> 'sphere' at the clicked point
"""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

FLOOD_DEG = 25.0


def _flood(mesh, face, max_deg=FLOOD_DEG):
    adj = mesh.face_adjacency
    ang = mesh.face_adjacency_angles
    keep = ang < np.radians(max_deg)
    a, b = adj[keep, 0], adj[keep, 1]
    n = len(mesh.faces)
    G = coo_matrix((np.ones(a.size), (a, b)), shape=(n, n))
    _, lab = connected_components(G, directed=False)
    return np.flatnonzero(lab == lab[face])


def _fit_circle(p2):
    """Kasa least-squares circle through 2D points -> centre, radius, rms error."""
    A = np.c_[2 * p2, np.ones(len(p2))]
    b = (p2 ** 2).sum(1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = sol[:2]
    r = float(np.sqrt(max(sol[2] + c @ c, 1e-12)))
    err = float(np.sqrt(np.mean((np.linalg.norm(p2 - c, axis=1) - r) ** 2)))
    return c, r, err


def _basis(z):
    z = z / np.linalg.norm(z)
    x = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = x - z * (x @ z)
    x /= np.linalg.norm(x)
    return z, x, np.cross(z, x)


def _r(v, d=3):
    return [round(float(t), d) for t in v]


def pick(mesh, face, point, pad, mode="auto", patch_r=None):
    """Return {'region', 'kind', 'label', 'faces', 'centre', 'normal'} for a clicked face."""
    face = int(face)
    if not 0 <= face < len(mesh.faces):
        raise ValueError(f"Face {face} is not on the model ({len(mesh.faces)} faces).")
    point = np.asarray(point, float)
    fn = mesh.face_normals[face]
    diag = float(np.linalg.norm(mesh.extents))
    if mode != "patch":
        faces = _flood(mesh, face)
        N = mesh.face_normals[faces]
        w = mesh.area_faces[faces]
        V = mesh.vertices[np.unique(mesh.faces[faces])]
        mean_n = (N * w[:, None]).sum(0)
        mean_n /= max(np.linalg.norm(mean_n), 1e-12)
        flat = np.degrees(np.arccos(np.clip(N @ mean_n, -1, 1))).max() < 3.0
        if flat:
            z, x, y = _basis(mean_n)
            q = V - V.mean(0)
            # in-plane principal axes for a tight box
            Q2 = np.c_[q @ x, q @ y]
            evals, evecs = np.linalg.eigh(Q2.T @ Q2)
            ax = evecs[:, 1]
            x = ax[0] * x + ax[1] * y
            y = np.cross(z, x)
            px, py, pz = q @ x, q @ y, q @ z
            centre = V.mean(0) + x * (px.max() + px.min()) / 2 + y * (py.max() + py.min()) / 2 + z * pz.mean()
            size = [float(np.ptp(px) + 2 * pad), float(np.ptp(py) + 2 * pad), float(2 * pad)]
            region = {"type": "obox", "center": _r(centre), "normal": _r(mean_n, 4), "xdir": _r(x, 4),
                      "size": _r(size)}
            area = float(w.sum())
            return {"region": region, "kind": "face", "faces": faces.tolist(), "centre": _r(centre),
                    "normal": _r(mean_n, 4),
                    "label": f"Flat face {np.ptp(px):.1f} × {np.ptp(py):.1f} mm ({area:.0f} mm²)"}
        # cylinder test: normals perpendicular to one axis
        M = (N * w[:, None]).T @ N
        evals, evecs = np.linalg.eigh(M)
        axis = evecs[:, 0]
        if len(faces) >= 6 and np.abs(N @ axis).max() < 0.25 and evals[0] < 0.05 * evals[2]:
            z, x, y = _basis(axis)
            c2, r, err = _fit_circle(np.c_[V @ x, V @ y])
            t = V @ z
            if err < 0.05 * r + 0.02:
                base = x * c2[0] + y * c2[1]
                a, b = base + z * t.min(), base + z * t.max()
                # hole if normals point toward the axis
                C = mesh.triangles_center[faces]
                radial = C - (base + np.outer(C @ z, z))
                hole = float(np.mean(np.sum(radial * N, 1))) < 0
                region = {"type": "pipe", "from": _r(a), "to": _r(b), "r": round(r + pad, 3),
                          "rIn": round(max(r - pad, 0.05), 3)}
                kind = "hole" if hole else "boss"
                label = (f"Hole Ø{2 * r:.2f} mm, {np.ptp(t):.1f} mm deep" if hole
                         else f"Boss Ø{2 * r:.2f} mm, {np.ptp(t):.1f} mm long")
                return {"region": region, "kind": kind, "faces": faces.tolist(), "centre": _r((a + b) / 2),
                        "normal": _r(z, 4), "axisLength": float(np.ptp(t)), "radius": r, "label": label}
    # freeform or patch mode: sphere at the clicked point
    r = float(patch_r) if patch_r else max(3 * pad, 0.04 * diag)
    d = np.linalg.norm(mesh.triangles_center - point, axis=1)
    faces = np.flatnonzero(d <= r)
    return {"region": {"type": "sphere", "center": _r(point), "r": round(r, 3)}, "kind": "patch",
            "faces": faces.tolist(), "centre": _r(point), "normal": _r(fn, 4),
            "label": f"Patch Ø{2 * r:.1f} mm around the point"}
