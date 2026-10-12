"""Sample saved displacement / stress fields at the corners of a display mesh.

The viewer draws a non-indexed triangle list in file order, so values are returned per
triangle corner: [dx, dy, dz, vonMises] x 3 corners x faces, float32, little endian.
"""
import numpy as np
from scipy import ndimage


def load(path):
    z = np.load(path)
    meta = {"origin": z["origin"], "h": float(z["h"][0]), "shape": tuple(int(v) for v in z["shape"])}
    cases = sorted(k.split("::", 1)[1] for k in z.files if k.startswith("u::"))
    return z, meta, cases


def corner_values(mesh, npz_path, case):
    z, meta, cases = load(npz_path)
    if case not in cases:
        case = cases[0]
    nx, ny, nz = meta["shape"]
    h, o = meta["h"], meta["origin"]
    tri = np.asarray(mesh.triangles, dtype=float)              # (F, 3, 3)
    pts = tri.reshape(-1, 3)
    # displacement: trilinear on the node grid
    u = z[f"u::{case}"].reshape(nz + 1, ny + 1, nx + 1, 3).transpose(2, 1, 0, 3)
    c = ((pts - o) / h).T
    disp = np.stack([ndimage.map_coordinates(u[..., k], c, order=1, mode="nearest") for k in range(3)], 1)
    # stress: element just inside the surface (corner moved half a voxel against the normal)
    vm3 = z[f"vm::{case}"].reshape(nz, ny, nx).transpose(2, 1, 0)
    vm3 = ndimage.grey_dilation(vm3, size=(2, 2, 2)) if vm3.size else vm3   # fill one-voxel gaps
    n = np.repeat(np.asarray(mesh.face_normals, float), 3, axis=0)
    inside = pts - 0.6 * h * n
    ci = ((inside - o) / h - 0.5).T
    vm = ndimage.map_coordinates(vm3, ci, order=0, mode="nearest")
    out = np.concatenate([disp, vm[:, None]], axis=1).astype("<f4")
    return out.tobytes(), cases, case
