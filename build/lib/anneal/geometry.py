"""Model import and voxelization.

Reads STL, OBJ, PLY, OFF, 3MF and GLB through trimesh, and STEP/STP through OCP
(cadquery-ocp, the OpenCASCADE wrapper; optional). Voxelizes a closed mesh into fill
fractions on the grid by ray parity along z at s x s x s sample points per voxel.
"""
import os
import numpy as np
import trimesh


class ModelError(ValueError):
    pass


def load_mesh(path, log=print):
    if not os.path.isfile(path):
        raise ModelError(f"Model file not found: {path}. Give the path relative to the spec file, "
                         f"or an absolute path.")
    ext = os.path.splitext(path)[1].lower()
    if ext in (".step", ".stp"):
        mesh = _load_step(path)
    else:
        loaded = trimesh.load(path, force="mesh")
        if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
            raise ModelError(f"No triangles found in {path}.")
        mesh = loaded
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    if not mesh.is_watertight:
        trimesh.repair.fill_holes(mesh)
        trimesh.repair.fix_normals(mesh)
        if not mesh.is_watertight:
            log("  WARNING: the model is not closed (watertight). Inside/outside may be wrong where "
                "it has holes. Repair it in your CAD or mesh tool for reliable results.")
    elif mesh.volume < 0:
        mesh.invert()
    return mesh


def _load_step(path):
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
        from OCP.BRep import BRep_Tool
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
    except ImportError:
        raise ModelError("STEP import needs the optional OpenCASCADE wrapper. Install it with "
                         "'pip install cadquery-ocp', or export the model from CAD as STL.") from None
    reader = STEPControl_Reader()
    if reader.ReadFile(path) != IFSelect_RetDone:
        raise ModelError(f"OpenCASCADE could not read the STEP file {path}.")
    reader.TransferRoots()
    shape = reader.OneShape()
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    pmin, pmax = box.CornerMin(), box.CornerMax()
    diag = float(np.linalg.norm([pmax.X() - pmin.X(), pmax.Y() - pmin.Y(), pmax.Z() - pmin.Z()]))
    BRepMesh_IncrementalMesh(shape, max(diag * 1e-3, 0.01), False, 0.3, True)
    verts, faces, off = [], [], 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = (TopoDS.Face_s if hasattr(TopoDS, "Face_s") else TopoDS.Face)(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                verts.append((p.X(), p.Y(), p.Z()))
            rev = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                faces.append((off + a - 1, off + c - 1, off + b - 1) if rev else (off + a - 1, off + b - 1, off + c - 1))
            off += tri.NbNodes()
        exp.Next()
    if not faces:
        raise ModelError(f"The STEP file {path} has no solid faces to mesh.")
    return trimesh.Trimesh(np.array(verts), np.array(faces), process=True)


def voxel_fill(mesh, grid, s=3, chunk=4_000_000):
    """Fill fraction (0..1) per grid element of a closed mesh. Returns a flat element array."""
    h = grid.h
    sub = (np.arange(s) + 0.5) / s
    xs = (grid.origin[0] + h * (np.arange(grid.nx)[:, None] + sub[None, :])).ravel() + h * 6.18e-6
    ys = (grid.origin[1] + h * (np.arange(grid.ny)[:, None] + sub[None, :])).ravel() + h * 4.14e-6
    zs = (grid.origin[2] + h * (np.arange(grid.nz)[:, None] + sub[None, :])).ravel()
    nxs, nys = xs.size, ys.size

    tri = mesh.triangles
    tmin, tmax = tri.min(axis=1), tri.max(axis=1)
    ix0 = np.searchsorted(xs, tmin[:, 0])
    ix1 = np.searchsorted(xs, tmax[:, 0], side="right")
    iy0 = np.searchsorted(ys, tmin[:, 1])
    iy1 = np.searchsorted(ys, tmax[:, 1], side="right")
    nxr, nyr = ix1 - ix0, iy1 - iy0
    npair = nxr * nyr
    keep = npair > 0
    tids = np.flatnonzero(keep)

    zlo, zhi = tmin[:, 2].min(), tmax[:, 2].max()
    zr = (zhi - zlo) * 1.001 + 1e-9
    cols_all, zn_all = [], []
    cum = np.cumsum(npair[tids])
    start = 0
    while start < tids.size:
        stop = int(np.searchsorted(cum, (cum[start - 1] if start else 0) + chunk, side="right"))
        stop = max(stop, start + 1)
        t = tids[start:stop]
        n = npair[t]
        rep = np.repeat(np.arange(t.size), n)
        first = np.concatenate([[0], np.cumsum(n)[:-1]])
        local = np.arange(n.sum()) - np.repeat(first, n)
        tt = t[rep]
        lx = local % nxr[tt]
        ly = local // nxr[tt]
        px, py = xs[ix0[tt] + lx], ys[iy0[tt] + ly]
        v = tri[tt]
        x0, y0, x1, y1, x2, y2 = v[:, 0, 0], v[:, 0, 1], v[:, 1, 0], v[:, 1, 1], v[:, 2, 0], v[:, 2, 1]
        d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        with np.errstate(divide="ignore", invalid="ignore"):
            l0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / d
            l1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / d
            l2 = 1 - l0 - l1
            hit = (d != 0) & (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
            z = l0 * v[:, 0, 2] + l1 * v[:, 1, 2] + l2 * v[:, 2, 2]
        cols_all.append(((ix0[tt] + lx) + nxs * (iy0[tt] + ly))[hit])
        zn_all.append(((z - zlo) / zr)[hit])
        start = stop

    cols = np.concatenate(cols_all) if cols_all else np.zeros(0, np.int64)
    zn = np.concatenate(zn_all) if zn_all else np.zeros(0)
    keys = np.sort(cols.astype(np.float64) + zn)
    ncol = nxs * nys
    starts = np.searchsorted(keys, np.arange(ncol, dtype=np.float64))
    zq = np.clip((zs - zlo) / zr, 0.0, 0.999999)
    q = np.arange(ncol, dtype=np.float64)[:, None] + zq[None, :]
    below = np.searchsorted(keys, q.ravel()).reshape(ncol, zs.size) - starts[:, None]
    inside = (below % 2 == 1).reshape(nys, nxs, zs.size)
    frac = inside.reshape(grid.ny, s, grid.nx, s, grid.nz, s).mean(axis=(1, 3, 5))
    return grid.to1d(frac.transpose(1, 0, 2))
