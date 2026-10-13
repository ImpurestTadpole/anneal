"""Build the 'grow from interfaces' example: only the bolt-on points of a part.

Body 1: a mounting pad, 6 mm thick, with four M6 clearance holes (bolted to a wall at x = 0).
Body 2: a load lug 40 mm away from the wall and 60 mm up, with an 8 mm pin bore along y.
Anneal keeps both bodies exactly and grows material between them (examples/interfaces.json).
Needs the optional OpenCASCADE wrapper (pip install cadquery-ocp). interfaces.step and
interfaces.stl are already included.
"""
import os
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Compound
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.StlAPI import StlAPI_Writer
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir

here = os.path.dirname(os.path.abspath(__file__))
pad = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 6.0, 60.0, 40.0).Shape()
for y, z in ((10, 8), (50, 8), (10, 32), (50, 32)):
    pad = BRepAlgoAPI_Cut(pad, BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(-1, y, z), gp_Dir(1, 0, 0)), 3.3, 8.0).Shape()).Shape()
lug = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(90, 20, 60), gp_Dir(0, 1, 0)), 10.0, 20.0).Shape()
lug = BRepAlgoAPI_Cut(lug, BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(90, 19, 60), gp_Dir(0, 1, 0)), 4.0, 22.0).Shape()).Shape()
b, comp = BRep_Builder(), TopoDS_Compound()
b.MakeCompound(comp)
b.Add(comp, pad)
b.Add(comp, lug)
w = STEPControl_Writer()
w.Transfer(comp, STEPControl_AsIs)
w.Write(os.path.join(here, "interfaces.step"))
BRepMesh_IncrementalMesh(comp, 0.05, False, 0.2, True)
StlAPI_Writer().Write(comp, os.path.join(here, "interfaces.stl"))
print("wrote interfaces.step and interfaces.stl")
