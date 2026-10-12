"""Spec file -> problem on a voxel grid.

The spec is the only input. It names the model, the design space, the material, the
anchors (where the part is held and loaded) and the limits. Every error names the fix.

Parameter taxonomy (kept from the method): the spec holds SPECIFICATION values only.
Voxel size, filter radius, threshold and multigrid settings are DERIVED here and written
to the run record so every number is traceable.
"""
import json
import os
import numpy as np
from scipy import ndimage

from .fem import Grid
from .geometry import load_mesh, voxel_fill
from .kernel import (Frame, Box, Cylinder, Union, make_region, fill_fraction, FASTENERS)
from .materials import get_material

RESOLUTION = {"draft": 15000, "normal": 40000, "fine": 90000}
MIN_FILL = 0.05


class SpecError(ValueError):
    pass


class Anchor:
    def __init__(self, d, index):
        self.name = d.get("name", f"anchor{index + 1}")
        where = f"Anchor '{self.name}'"
        self.role = d.get("role")
        if self.role not in ("fixed", "load"):
            raise SpecError(f"{where}: role must be 'fixed' or 'load', not {self.role!r}.")
        dofs = d.get("dofs", "xyz")
        if not dofs or any(c not in "xyz" for c in dofs):
            raise SpecError(f"{where}: dofs must use the letters x, y, z (for example 'xyz' or 'z').")
        self.dofs = ["xyz".index(c) for c in dofs]
        self.loads = {}
        if self.role == "load":
            loads = d.get("loads")
            if not isinstance(loads, dict) or not loads:
                raise SpecError(f"{where}: a load anchor needs 'loads': {{\"caseName\": [Fx, Fy, Fz]}} in newtons.")
            for case, v in loads.items():
                v = np.asarray(v, float)
                if v.shape != (3,):
                    raise SpecError(f"{where}: load '{case}' must be three numbers [Fx, Fy, Fz] in newtons.")
                self.loads[case] = v
        self.freeze_mm = None if d.get("freezeMM") is None else float(d["freezeMM"])
        self.solids, self.voids = [], []
        regions = []
        if "region" in d:
            regions.append(make_region(d["region"], where))
        if "feature" in d:
            regions += self._feature(d["feature"], where)
        if not regions:
            raise SpecError(f"{where}: give a 'region' (box, sphere, cylinder, pipe) or a 'feature' (bore, pad, boltCircle).")
        self.region = regions[0] if len(regions) == 1 else Union(regions)
        self.raw_region = "region" in d and "feature" not in d

    def _feature(self, f, where):
        if not isinstance(f, dict) or len(f) != 1:
            raise SpecError(f"{where}: 'feature' must hold exactly one of bore, pad, boltCircle.")
        kind, p = next(iter(f.items()))
        if kind in ("bore", "boltCircle"):
            axis = np.asarray(p.get("axis", [0, 0, 1]), float)
            if "bolt" in p:
                if p["bolt"] not in FASTENERS:
                    raise SpecError(f"{where}: unknown bolt '{p['bolt']}'. Use one of {', '.join(FASTENERS)} or give 'd'.")
                d, boss = FASTENERS[p["bolt"]]
            elif "d" in p:
                d, boss = float(p["d"]), 2.0 * float(p["d"])
            else:
                raise SpecError(f"{where}: a {kind} needs 'bolt' (for example 'M5') or a hole diameter 'd'.")
            boss = float(p.get("bossD", boss))
            depth = float(p.get("depthMM", 2.0 * d))
            centres = []
            if kind == "bore":
                centres = [np.asarray(p["at"], float)]
            else:
                fr = Frame(p["at"], axis, p.get("xdir"))
                n = int(p.get("count", 4))
                R = float(p["dia"]) / 2
                for k in range(n):
                    a = 2 * np.pi * k / n
                    centres.append(fr.to_world(np.array([R * np.cos(a), R * np.sin(a), 0.0])))
            ax = axis / np.linalg.norm(axis)
            bcs = []
            for c in centres:
                self.solids.append(Cylinder(c, c + ax * depth, boss / 2))
                self.voids.append(Cylinder(c - ax, c + ax * (depth + 1), d / 2))
                bcs.append(("wall", c, c + ax * depth, d / 2))
            self._bores = bcs
            return [Cylinder(c, c + ax * depth, boss / 2) for c in centres]
        if kind == "pad":
            fr = Frame(p["at"], p.get("normal", [0, 0, 1]), p.get("xdir"))
            size = [float(p["w"]), float(p["h"]), float(p.get("t", 2.0))]
            pad = Box(frame=fr, size=size, z0=-size[2])
            self.solids.append(pad)
            return [pad]
        raise SpecError(f"{where}: unknown feature '{kind}'. Use bore, pad or boltCircle.")

    def nodes(self, grid, cand_nodes, cand_xyz):
        """Grid nodes this anchor acts on, from the candidate (material) nodes."""
        h = grid.h
        if getattr(self, "_bores", None):
            sel = np.zeros(cand_nodes.size, bool)
            for _, a, b, r in self._bores:
                wall = Cylinder(a, b, r + 0.9 * h, max(r - 0.9 * h, 1e-3))
                sel |= wall.sdf(cand_xyz) <= 0
            return cand_nodes[sel]
        return cand_nodes[self.region.sdf(cand_xyz) <= 0.5 * h]


class Problem:
    def __init__(self, spec_path=None, spec=None, log=print):
        self.log = log
        if spec is None:
            if not os.path.isfile(spec_path):
                raise SpecError(f"Spec file not found: {spec_path}")
            with open(spec_path, encoding="utf-8") as fh:
                try:
                    spec = json.load(fh)
                except json.JSONDecodeError as e:
                    raise SpecError(f"The spec file is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}. "
                                    f"Check for a missing comma or quote.") from None
        self.spec = spec
        self.base = os.path.dirname(os.path.abspath(spec_path)) if spec_path else os.getcwd()
        self.name = spec.get("name") or (os.path.splitext(os.path.basename(spec_path))[0] if spec_path else "part")
        self.material = get_material(spec.get("material", "AlSi10Mg-LPBF"))
        obj = spec.get("objective", {})
        self.vf = float(obj.get("volumeFraction", 0.3))
        if not 0.03 <= self.vf <= 0.95:
            raise SpecError(f"objective.volumeFraction is {self.vf}. Give a value between 0.03 and 0.95 "
                            f"(0.3 keeps 30 % of the design space).")
        self.combine = obj.get("combine", "sum")
        if self.combine not in ("sum", "worst"):
            raise SpecError("objective.combine must be 'sum' (weighted total stiffness) or 'worst' (stiffest worst case).")
        self.limits = spec.get("limits", {})
        self.opt = spec.get("optimizer", {})
        self.out_opts = spec.get("output", {})
        self.anchors = [Anchor(a, i) for i, a in enumerate(spec.get("anchors", []))]
        if not any(a.role == "fixed" for a in self.anchors):
            raise SpecError("The spec has no fixed anchor. Add at least one anchor with \"role\": \"fixed\" "
                            "where the part is bolted or held.")
        if not any(a.role == "load" for a in self.anchors):
            raise SpecError("The spec has no load anchor. Add an anchor with \"role\": \"load\" and 'loads'.")
        cases = sorted({c for a in self.anchors for c in a.loads})
        lc = spec.get("loadCases", {})
        unknown = set(lc) - set(cases)
        if unknown:
            raise SpecError(f"loadCases names {sorted(unknown)}, but no anchor has loads with those names. "
                            f"Anchor load cases are: {cases}.")
        self.cases = cases
        self.weights = {c: float(lc.get(c, {}).get("weight", 1.0)) for c in cases}
        self.keepout = [make_region(r, f"keepOut[{i}]") for i, r in enumerate(spec.get("keepOut", []))]
        self.keep = [make_region(r, f"keep[{i}]") for i, r in enumerate(spec.get("keep", []))]
        self.mesh = None
        model = spec.get("model")
        if model:
            mpath = model if os.path.isabs(model) else os.path.join(self.base, model)
            self.model_path = mpath
            self.mesh = load_mesh(mpath, log)
        self.derived = {}

    # ------------------------------------------------------------------ build
    def build(self):
        log, spec = self.log, self.spec
        ds = spec.get("designSpace", "model" if self.mesh is not None else None)
        if ds is None:
            raise SpecError("Give 'model' (an STL, OBJ or STEP file) or a 'designSpace' box.")
        if isinstance(ds, str):
            ds = {"type": ds}
        dtype = ds.get("type")
        solids = [s for a in self.anchors for s in a.solids] + self.keep
        voids = [v for a in self.anchors for v in a.voids] + self.keepout

        if dtype in ("model", "hull", "bounds") and self.mesh is None:
            raise SpecError(f"designSpace '{dtype}' needs a 'model' file.")
        if dtype == "model":
            dmesh = self.mesh
            lo, hi = dmesh.bounds
            vol = abs(dmesh.volume)
        elif dtype == "hull":
            dmesh = self.mesh.convex_hull
            m = float(ds.get("marginMM", 0.0))
            if m > 0:
                dmesh = dmesh.copy()
                c = dmesh.centroid
                ext = dmesh.extents
                dmesh.apply_translation(-c)
                dmesh.apply_scale((ext + 2 * m) / ext)
                dmesh.apply_translation(c)
            lo, hi = dmesh.bounds
            vol = abs(dmesh.volume)
        elif dtype in ("bounds", "box"):
            dmesh = None
            if dtype == "bounds":
                m = float(ds.get("marginMM", 0.0))
                lo, hi = self.mesh.bounds[0] - m, self.mesh.bounds[1] + m
            else:
                lo, hi = np.asarray(ds["min"], float), np.asarray(ds["max"], float)
            box = Box(lo, hi)
            vol = float(np.prod(hi - lo))
        else:
            raise SpecError(f"designSpace type '{dtype}' is unknown. Use model, hull, bounds or box.")

        for s in solids:
            slo, shi = s.bounds()
            lo, hi = np.minimum(lo, slo), np.maximum(hi, shi)

        res = spec.get("resolution", "normal")
        if isinstance(res, str):
            if res not in RESOLUTION:
                raise SpecError(f"resolution '{res}' is unknown. Use draft, normal, fine, "
                                f"{{\"targetElements\": N}} or {{\"voxelMM\": h}}.")
            target = RESOLUTION[res]
            h = (vol / target) ** (1 / 3)
        elif "voxelMM" in res:
            h = float(res["voxelMM"])
        else:
            h = (vol / float(res["targetElements"])) ** (1 / 3)
        h = float(f"{h:.3g}")
        pad = 2 * h
        lo, hi = lo - pad, hi + pad
        shape = np.ceil((hi - lo) / h).astype(int)
        if np.prod(shape) > 12_000_000:
            raise SpecError(f"The grid would have {np.prod(shape):,} cells at {h} mm voxels. "
                            f"Use a coarser resolution or a smaller design space.")
        grid = Grid(shape, h, lo)
        self.grid = grid
        log(f"  grid {shape[0]} x {shape[1]} x {shape[2]} at {h} mm voxels")

        if dtype in ("model", "hull"):
            fill = voxel_fill(dmesh, grid)
        else:
            fill = fill_fraction(box, grid.elem_centers(), h)
        self.space_fill = fill.copy()
        centres = grid.elem_centers()
        solid_fill = np.zeros(grid.nelem)
        for s in solids:
            solid_fill = np.maximum(solid_fill, fill_fraction(s, centres, h))
        void_fill = np.zeros(grid.nelem)
        for v in voids:
            void_fill = np.maximum(void_fill, fill_fraction(v, centres, h))
        fill = np.maximum(fill, solid_fill)
        fill = np.minimum(fill, 1.0 - void_fill)
        fill[fill < MIN_FILL] = 0.0
        self.solid_fill, self.void_fill = solid_fill, void_fill

        frozen = (solid_fill > 0.5) & (fill > 0)
        for a in self.anchors:
            fz = 2.0 * h if a.freeze_mm is None else a.freeze_mm   # default: keep 2 voxels of material
            if fz > 0:
                frozen |= (a.region.sdf(centres) <= fz) & (fill > 0)
        self.frozen = frozen
        self.fill = fill
        self.active = self._connected(fill > 0)
        self.fill[~self.active] = 0
        self.frozen &= self.active

        n_act = int(self.active.sum())
        dom_vol = self.fill.sum() * h ** 3
        frz_vol = (self.fill * self.frozen).sum() * h ** 3
        if frz_vol > self.vf * dom_vol:
            raise SpecError(f"Frozen material ({frz_vol:.0f} mm3) is more than the volume target "
                            f"({self.vf * dom_vol:.0f} mm3). Raise volumeFraction above "
                            f"{frz_vol / dom_vol + 0.05:.2f}, or reduce freezeMM / feature sizes.")
        log(f"  design space {dom_vol / 1000:.1f} cm3, {n_act:,} active voxels, "
            f"{int(self.frozen.sum()):,} frozen")
        self.derived.update({"voxelMM": h, "grid": list(map(int, shape)), "activeVoxels": n_act,
                             "designSpaceCM3": dom_vol / 1000, "frozenCM3": frz_vol / 1000})
        return self

    def _connected(self, mask):
        """Keep only face-connected pieces of the design space that touch a fixed anchor."""
        g = self.grid
        lab, n = ndimage.label(g.to3d(mask))
        lab = g.to1d(lab)
        if n <= 1:
            return mask
        keep = np.zeros(n + 1, bool)
        cand = np.flatnonzero(mask)
        en = g.element_nodes(cand)
        for a in self.anchors:
            if a.role != "fixed":
                continue
            nodes = set(a.nodes(g, np.unique(en), g.node_coords(np.unique(en))).tolist())
            if not nodes:
                continue
            hit = np.isin(en, list(nodes)).any(axis=1)
            keep[np.unique(lab[cand[hit]])] = True
        keep[0] = False
        dropped = n - int(keep[1:].sum())
        if dropped:
            self.log(f"  WARNING: {dropped} piece(s) of the design space touch no fixed anchor and were removed.")
        return keep[lab] & mask

    # ------------------------------------------------------------ boundary
    def boundary(self, active):
        """Fixed dofs and load vectors for a given set of active voxels."""
        g = self.grid
        act = np.flatnonzero(active)
        nodes = np.unique(g.element_nodes(act))
        xyz = g.node_coords(nodes)
        fixed, F = [], {c: np.zeros(3 * g.nnode) for c in self.cases}
        info = {}
        for a in self.anchors:
            sel = a.nodes(g, nodes, xyz)
            if sel.size == 0:
                lo, hi = a.region.bounds()
                raise SpecError(
                    f"Anchor '{a.name}' touches no material. Its region spans {np.round(lo, 2).tolist()} to "
                    f"{np.round(hi, 2).tolist()} mm; the design space spans "
                    f"{np.round(g.origin, 1).tolist()} to {np.round(g.origin + g.h * np.array(g.shape), 1).tolist()} mm. "
                    f"Move the region onto the part surface, or make it thicker than one voxel ({g.h} mm).")
            info[a.name] = int(sel.size)
            if a.role == "fixed":
                fixed += [3 * sel + d for d in a.dofs]
            else:
                for c, v in a.loads.items():
                    for d in range(3):
                        np.add.at(F[c], 3 * sel + d, v[d] / sel.size)
        fixed = np.unique(np.concatenate(fixed)) if fixed else np.zeros(0, int)
        return fixed, F, info

    def load_nodes(self, active):
        g = self.grid
        nodes = np.unique(g.element_nodes(np.flatnonzero(active)))
        xyz = g.node_coords(nodes)
        return {a.name: a.nodes(g, nodes, xyz) for a in self.anchors}
