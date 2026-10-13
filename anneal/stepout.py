"""STEP export of the optimized part (output.formats "step").

The part is a triangle surface, so the STEP holds a faceted solid: one planar face per triangle,
sewn into one closed shell. SolidWorks, Fusion, Onshape and FreeCAD open it as a solid body that
you can measure, add features to and use in assemblies. To keep the file small the surface is first
reduced to output.stepFaces triangles (default 20 000) with quadric decimation, which keeps the
shape within a small fraction of a millimetre on parts of the size Anneal makes.
Needs OpenCASCADE (pip install cadquery-ocp, the same package as STEP import).
"""
import numpy as np


class StepExportError(RuntimeError):
    pass


def reduce(mesh, max_faces):
    if max_faces and len(mesh.faces) > max_faces:
        try:
            m = mesh.simplify_quadric_decimation(face_count=int(max_faces))
            if m.is_watertight and abs(m.volume - mesh.volume) < 0.01 * abs(mesh.volume):
                return m, True
        except Exception:
            pass
    return mesh, False


def export_step(mesh, path, max_faces=20000):
    """Write mesh as a faceted solid to path. Returns a dict with face count, volume and checks."""
    try:
        from OCP.Poly import Poly_Triangulation, Poly_Triangle
        from OCP.gp import gp_Pnt
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeShapeOnMesh, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
        from OCP.TopAbs import TopAbs_SHELL
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp
    except Exception as e:
        raise StepExportError("STEP export needs OpenCASCADE: pip install cadquery-ocp") from e
    m, reduced = reduce(mesh, max_faces)
    V, F = np.asarray(m.vertices, float), np.asarray(m.faces, int)
    tri = Poly_Triangulation(len(V), len(F), False)
    for i, (x, y, z) in enumerate(V, 1):
        tri.SetNode(i, gp_Pnt(float(x), float(y), float(z)))
    for i, (a, b, c) in enumerate(F, 1):
        tri.SetTriangle(i, Poly_Triangle(int(a) + 1, int(b) + 1, int(c) + 1))
    mk = BRepBuilderAPI_MakeShapeOnMesh(tri)
    mk.Build()
    shape = mk.Shape()
    ex = TopExp_Explorer(shape, TopAbs_SHELL)
    if not ex.More():
        sew = BRepBuilderAPI_Sewing(1e-6)
        sew.Add(shape)
        sew.Perform()
        shape = sew.SewedShape()
        ex = TopExp_Explorer(shape, TopAbs_SHELL)
    shell = TopoDS.Shell_s(ex.Current()) if hasattr(TopoDS, "Shell_s") else TopoDS.Shell(ex.Current())
    solid = BRepBuilderAPI_MakeSolid(shell).Solid()
    props = GProp_GProps()
    (BRepGProp.VolumeProperties_s if hasattr(BRepGProp, "VolumeProperties_s") else BRepGProp.VolumeProperties)(solid, props)
    vol = abs(props.Mass())
    w = STEPControl_Writer()
    w.Transfer(solid, STEPControl_AsIs)
    if w.Write(str(path)) != IFSelect_RetDone:
        raise StepExportError(f"OpenCASCADE could not write {path}")
    return {"faces": int(len(F)), "reduced": reduced, "volumeMM3": vol, "meshVolumeMM3": float(abs(mesh.volume))}
