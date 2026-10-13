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
from .materials import get_material, get_process

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
        self.pressure = {}
        if self.role == "load":
            loads = d.get("loads") or {}
            pres = d.get("pressure") or {}
            if not isinstance(loads, dict) or not isinstance(pres, dict) or not (loads or pres):
                raise SpecError(f"{where}: a load anchor needs 'loads': {{\"caseName\": [Fx, Fy, Fz]}} in newtons, "
                                f"or 'pressure': {{\"caseName\": p}} in MPa on a picked face.")
            for case, v in loads.items():
                v = np.asarray(v, float)
                if v.shape != (3,):
                    raise SpecError(f"{where}: load '{case}' must be three numbers [Fx, Fy, Fz] in newtons.")
                self.loads[case] = v
            if pres:
                area, n = self._pressure_face(d, where)
                for case, pv in pres.items():
                    try:
                        pv = float(pv)
                    except (TypeError, ValueError):
                        raise SpecError(f"{where}: pressure '{case}' must be one number in MPa (N/mm2).") from None
                    F = -pv * area * n          # a positive pressure pushes into the face
                    self.loads[case] = self.loads.get(case, np.zeros(3)) + F
                    self.pressure[case] = {"MPa": pv, "areaMM2": area, "normal": n.tolist(), "forceN": F.tolist()}
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
        self.region_dict = d.get("region") if self.raw_region else None
        # "hole": true (set by the app when a hole is picked): the hole stays open, also where the
        # design space would otherwise fill it (bounds, hull or box design spaces)
        self.hole = bool(d.get("hole"))
        if self.hole:
            r = d.get("region") or {}
            if r.get("type") != "pipe":
                raise SpecError(f"{where}: \"hole\": true needs a pipe region (pick the hole wall).")
            rh = (float(r["r"]) + float(r["rIn"])) / 2
            a, b = np.asarray(r["from"], float), np.asarray(r["to"], float)
            self.voids.append(Cylinder(a, b, rh))
            # room for the bolt head, washer, nut or tool at both ends of the hole
            acc = float(d.get("boltAccessMM", 0) or 0)
            if acc > 0:
                ax = (b - a) / np.linalg.norm(b - a)
                rhead = float(d.get("boltHeadD", 3.6 * rh)) / 2
                self.voids.append(Cylinder(a - ax * acc, a, rhead))
                self.voids.append(Cylinder(b, b + ax * acc, rhead))

    @staticmethod
    def _pressure_face(d, where):
        """Area (mm2) and outward unit normal of the face a pressure acts on: from a picked face
        (prism region: its outline triangles and normal) or from 'areaMM2' and 'normal' in the anchor."""
        r = d.get("region") or {}
        if "areaMM2" in d or "normal" in d:
            if "areaMM2" not in d or "normal" not in d:
                raise SpecError(f"{where}: a pressure needs both 'areaMM2' and 'normal' (outward, of the loaded face).")
            area, n = float(d["areaMM2"]), np.asarray(d["normal"], float)
        elif r.get("type") == "prism":
            T = np.asarray(r["tris"], float).reshape(-1, 3, 2)
            v0, v1 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
            area = float(0.5 * np.abs(v0[:, 0] * v1[:, 1] - v0[:, 1] * v1[:, 0]).sum())
            n = np.asarray(r["normal"], float)
        else:
            raise SpecError(f"{where}: a pressure acts on a face. Pick a flat face in the app, or give 'areaMM2' "
                            f"and 'normal' (the outward normal of the loaded face).")
        if area <= 0 or n.shape != (3,) or np.linalg.norm(n) < 1e-12:
            raise SpecError(f"{where}: the pressure face needs a positive area and a non-zero normal.")
        return area, n / np.linalg.norm(n)

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
        self.process = get_process(spec.get("process"), self.material)
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
        from .fem import ELEMENTS, DEFAULT_ELEMENT
        self.element = str(spec.get("solver", {}).get("element", DEFAULT_ELEMENT)).lower()
        if self.element not in ELEMENTS:
            raise SpecError(f"solver.element '{self.element}' is unknown. Use 'e9' (hex8 with incompatible modes, "
                            f"the default) or 'hex8fi' (plain hex8, as in Anneal 0.3).")
        self.anchors =[Anchor(a, i) for i, a in enumerate(spec.get("anchors", []))]
        if not any(a.role == "fixed" for a in self.anchors):
            raise SpecError("The spec has no fixed anchor. Add at least one anchor with \"role\": \"fixed\" "
                            "where the part is bolted or held.")
        if not any(a.role == "load" for a in self.anchors):
            raise SpecError("The spec has no load anchor. Add an anchor with \"role\": \"load\" and 'loads'.")
        grav = spec.get("gravity") or {}
        if not isinstance(grav, dict):
            raise SpecError("gravity must be {\"caseName\": [ax, ay, az]} in g (1 g = 9.81 m/s2), "
                            "for example {\"weight\": [0, 0, -1]}.")
        self.gravity = {}
        for c, v in grav.items():
            v = np.asarray(v, float)
            if v.shape != (3,):
                raise SpecError(f"gravity '{c}' must be three numbers [ax, ay, az] in g, for example [0, 0, -1].")
            self.gravity[c] = v
        self.t_ref, self.t_case = 20.0, {}
        if spec.get("thermal") is not None:
            self._parse_thermal(spec["thermal"])
        self.mech_cases = sorted({c for a in self.anchors for c in a.loads} | set(self.gravity))
        self.thermal_only = sorted(set(self.t_case) - set(self.mech_cases))
        self.disp_incl_thermal = bool(spec.get("limits", {}).get("displacementIncludesThermal", False))
        cases = sorted({c for a in self.anchors for c in a.loads} | set(self.gravity) | set(self.t_case))
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

    THERMAL_FORM = ('"thermal": {"referenceTempC": 20, "cases": {"caseName": tempC}} (temperatures in °C; '
                    'a case name that has loads runs at that temperature, a new name is a thermal-only case)')

    def _parse_thermal(self, th):
        """thermal.referenceTempC (stress-free temperature, default 20 °C) and thermal.cases {case: °C}."""
        if not isinstance(th, dict):
            raise SpecError(f"thermal must be an object: {self.THERMAL_FORM}.")
        unknown = sorted(set(th) - {"referenceTempC", "cases"})
        if unknown:
            raise SpecError(f"thermal has unknown key(s) {unknown}. Use {self.THERMAL_FORM}.")
        try:
            self.t_ref = float(th.get("referenceTempC", 20.0))
        except (TypeError, ValueError):
            raise SpecError("thermal.referenceTempC must be one number in °C (the temperature at which the part "
                            "has no thermal stress, usually the assembly temperature, 20).") from None
        cases = th.get("cases") or {}
        if not isinstance(cases, dict):
            raise SpecError(f"thermal.cases must be an object {{\"caseName\": tempC}}. Use {self.THERMAL_FORM}.")
        for c, t in cases.items():
            try:
                t = float(t)
            except (TypeError, ValueError):
                raise SpecError(f"thermal case '{c}' must be one number, the part temperature in °C, not {t!r}.") from None
            if not np.isfinite(t) or t <= -273.15:
                raise SpecError(f"thermal case '{c}': {t:g} °C is below absolute zero. Give the part temperature in °C.")
            self.t_case[str(c)] = t
        if not np.isfinite(self.t_ref) or self.t_ref <= -273.15:
            raise SpecError("thermal.referenceTempC is below absolute zero. Give it in °C (usually 20).")
        if not self.t_case:
            return
        mat = self.material
        mname = mat.get("name", "inline")
        if "alpha" not in mat:
            raise SpecError(f"thermal: material '{mname}' has no alpha (expansion coefficient). Add alpha (1/K) to the "
                            f"material in the library or the spec, from a datasheet or a test (aluminium about 2.3e-5, "
                            f"PLA about 7e-5). Anneal has no default value.")
        limit = mat.get("maxServiceTempC")
        for c, t in self.t_case.items():
            if limit is not None and t > limit:
                raise SpecError(f"thermal case '{c}' runs at {t:g} °C, above the service limit of material '{mname}' "
                                f"(maxServiceTempC {limit:g} °C). The linear model is not valid there. Choose a material "
                                f"with a higher service temperature, or lower the case temperature.")
        table = mat.get("tempDerating")
        if table:
            lo, hi = table[0][0], table[-1][0]
            for c, t in self.t_case.items():
                if not lo <= t <= hi:
                    raise SpecError(f"thermal case '{c}' runs at {t:g} °C, outside the tempDerating table of material "
                                    f"'{mname}' ({lo:g} to {hi:g} °C). Add a row at {t:g} °C or beyond to the table; "
                                    f"Anneal does not extrapolate material data.")

    # ------------------------------------------------------------------ build
    def build(self):
        log, spec = self.log, self.spec
        ds = spec.get("designSpace", "model" if self.mesh is not None else None)
        if ds is None:
            raise SpecError("Give 'model' (an STL, OBJ or STEP file) or a 'designSpace' box.")
        if isinstance(ds, str):
            ds = {"type": ds}
        dtype = ds.get("type")
        solids = [s for a in self.anchors for s in a.solids]   # bore / pad features: may add material
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

        self.space_mesh = dmesh            # exact design space, for sharp edges (None: the box below)
        self.space_box = (np.array(lo, float), np.array(hi, float))
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
        # material the model already has: "keep" regions and the material frozen around supports and
        # loads come only from it, so neither can add a bubble to the part (a keep region or freeze
        # zone bigger than the feature used to leave one)
        have = voxel_fill(self.mesh, grid) if (self.mesh is not None and dtype != "model") else fill.copy()
        if self.keep:
            for s in self.keep:
                solid_fill = np.maximum(solid_fill, np.minimum(fill_fraction(s, centres, h), have))
        self.keep_model = bool(ds.get("keepModel")) and dtype != "model"
        if self.keep_model:   # grow from interfaces: the imported model is kept as it is
            if self.mesh is None:
                raise SpecError("designSpace keepModel needs a 'model' file.")
            solid_fill = np.maximum(solid_fill, voxel_fill(self.mesh, grid))
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
                frozen |= (a.region.sdf(centres) <= fz) & (fill > 0) & (have > 0)
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

    G_MS2 = 9.80665

    def gravity_coef(self):
        """Weight in N of one full voxel at 1 g (density in g/cm3 = 1e-6 kg/mm3)."""
        return float(self.material["density"]) * 1e-6 * self.grid.h ** 3 * self.G_MS2

    def body_loads(self, fill):
        """Self-weight / acceleration loads {case: nodal force vector} for a fill field (flat, all
        elements): each voxel's weight goes in equal parts to its 8 nodes."""
        g = self.grid
        out = {}
        if not self.gravity:
            return out
        e = np.flatnonzero(fill > 0)
        en = g.element_nodes(e)
        wt = self.gravity_coef() * fill[e] / 8.0
        for c, a in self.gravity.items():
            F = np.zeros(3 * g.nnode)
            for d in range(3):
                if a[d]:
                    np.add.at(F, 3 * en.ravel() + d, np.repeat(wt * a[d], 8))
            out[c] = F
        return out

    def load_nodes(self, active):
        g = self.grid
        nodes = np.unique(g.element_nodes(np.flatnonzero(active)))
        xyz = g.node_coords(nodes)
        return {a.name: a.nodes(g, nodes, xyz) for a in self.anchors}
