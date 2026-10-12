"""Build the example 'existing part': a solid wall bracket with four M6 holes and a load bore.

Needs the optional OpenCASCADE wrapper (pip install cadquery-ocp). The resulting
bracket.step and bracket.stl are already included, so you only need this to change it.
"""
import os
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.StlAPI import StlAPI_Writer
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir

here = os.path.dirname(os.path.abspath(__file__))

flange = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 10.0, 60.0, 60.0).Shape()        # wall flange x 0..10
arm = BRepPrimAPI_MakeBox(gp_Pnt(10, 15, 20), 100.0, 30.0, 40.0).Shape()       # solid arm x 10..110
part = BRepAlgoAPI_Fuse(flange, arm).Shape()
for y, z in ((10, 10), (50, 10), (10, 50), (50, 50)):                           # 4 x M6 clearance, along x
    hole = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(-1, y, z), gp_Dir(1, 0, 0)), 3.3, 12.0).Shape()
    part = BRepAlgoAPI_Cut(part, hole).Shape()
bore = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(95, 14, 40), gp_Dir(0, 1, 0)), 6.0, 32.0).Shape()
part = BRepAlgoAPI_Cut(part, bore).Shape()                                       # load bore, along y

w = STEPControl_Writer()
w.Transfer(part, STEPControl_AsIs)
w.Write(os.path.join(here, "bracket.step"))
BRepMesh_IncrementalMesh(part, 0.05, False, 0.2, True)
s = StlAPI_Writer()
s.Write(part, os.path.join(here, "bracket.stl"))
print("wrote bracket.step and bracket.stl")
