"""anneal run: spec -> optimized part, as-built re-solve, checks, report, run record."""
import hashlib
import json
import os
import platform
import shutil
import sys
import time
import numpy as np

from . import __version__
from .problem import Problem
from .fem import FEM
from .geometry import voxel_fill
from .optimize import simp
from .export import output_field, choose_level, keep_load_paths, surface, member_thickness, \
    surface_settings, sharp_field, sharp_clip
from . import report
from . import provenance


# Measured in validation check V3: tip deflection of the voxel cantilever / Timoshenko beam theory vs
# voxels through the depth. Plain hex8 ("hex8fi") locks in shear and is much too stiff when members are
# thin. The incompatible-modes element ("e9", the default) does not lock; what is left (under 1.5 %)
# is mostly the fully clamped end, which beam theory does not model, so dividing by it is conservative.
LOCKING = [(1.0, 0.70), (2.0, 0.869), (4.0, 0.957), (8.0, 0.983), (16.0, 0.995)]
E9_TABLE = [(1.0, 0.985), (2.0, 0.986), (4.0, 0.990), (8.0, 0.992), (16.0, 0.993)]


MIN_ANCHOR_NODES = 8      # fewer nodes act as a point support or point load (singular stress)


def locking_factor(n_vox, element="hex8fi"):
    """Fraction of true compliance the voxel model shows for members n_vox thick (conservative)."""
    tab = E9_TABLE if element == "e9" else LOCKING
    xs = np.log2([p[0] for p in tab])
    ys = [p[1] for p in tab]
    return float(np.interp(np.log2(max(n_vox, 1.0)), xs, ys))


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _derating(prob, temp_c):
    """(E factor, yield factor) of the material at temp_c (tempDerating; (1, 1) without a table)."""
    from .physics import derate
    return derate(prob.material, temp_c)


def _thermal_setup(prob, fem, Ee):
    """Per thermal case: temperature, temperature change, derating, thermal strain and its nodal load.
    Ee: modulus scale per active element (E x fill) at the listed E."""
    from .physics import thermal_strain
    mat = prob.material
    aniso = getattr(prob, "D", None) is not None
    bdir = (getattr(prob, "process", None) or {}).get("buildDirection") if aniso else None
    m = thermal_strain(mat["alpha"], mat.get("alphaZ") if aniso else None, bdir)
    fhat = fem.thermal_vector(m)
    out = {}
    for c, t in prob.t_case.items():
        dT = t - prob.t_ref
        fE, fY = _derating(prob, t)
        out[c] = {"tempC": t, "dT": dT, "fE": fE, "fY": fY, "m": m, "fhat": fhat, "eps0": dT * m,
                  "E": mat["E"] * fE, "yield": mat["yield"] * fY,
                  "f_th": fem.thermal_load(fhat, Ee * (fE * dT))}
    return out


def _thermal_solve(prob, fem, K, Ee, F, th):
    """Solve every load case on one factorisation. A case at temperature has the stiffness fE K (derating
    scales every element alike), so u = K^-1 (F_mech + f_th) / fE with the same preconditioner. A case with
    a mechanical load gets one more right-hand side, the mechanical load alone, for the displacement limit.
    The extra right-hand sides go first, so the last len(cases) CG counts belong to the cases (fea.study)."""
    extra, extra_c, main = [], [], []
    for c in prob.cases:
        tc = th.get(c)
        if tc is None:
            main.append(fem.reduce_load(F[c]))
            continue
        main.append(fem.reduce_load(F[c] + tc["f_th"]) / tc["fE"])
        fm = fem.reduce_load(F[c])
        if np.any(fm):
            extra.append(fm / tc["fE"])
            extra_c.append(c)
    U = fem.solve(K, extra + main, rtol=1e-9)
    for c, tc in th.items():
        tc["u_mech"] = np.zeros(fem.nfree)
        tc["K"] = K if tc["fE"] == 1.0 else K * tc["fE"]
        tc["Ee"] = Ee * tc["fE"]
    for c, u in zip(extra_c, U[:len(extra)]):
        th[c]["u_mech"] = u
    return U[len(extra):]


def _vm6(sig):
    sx, sy, sz, txy, tyz, tzx = sig.T
    return np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3 * (txy ** 2 + tyz ** 2 + tzx ** 2))


def evaluate(prob, fill, label, log):
    """Solve a geometry (fill fractions, penalty 1) for every load case and measure it."""
    g = prob.grid
    active = prob._connected(fill >= 0.05)   # drop islands that touch no support
    fill = np.where(active, fill, 0.0)
    try:
        fixed, F, _ = prob.boundary(active)
    except Exception as e:
        if "touches no material" in str(e) and label.startswith("Optimized"):
            name = str(e).split("'")[1]
            raise RuntimeError(f"The optimized part lost contact with anchor '{name}'. Give that anchor a "
                               f"larger freezeMM (for example 3) so material stays where the part is held "
                               f"or loaded, then run again.") from None
        raise
    for c, fb in prob.body_loads(fill).items():   # self-weight of this geometry
        F[c] = F[c] + fb
    D = getattr(prob, "D", None)
    fem = FEM(g, active, fixed, prob.material["nu"], log=log, D=D, element=prob.element)
    E0 = prob.material["E"]
    K = fem.assemble(E0 * fill[fem.act])
    th = _thermal_setup(prob, fem, E0 * fill[fem.act]) if getattr(prob, "t_case", None) else None
    t_solve = time.time()
    if th is None:
        Us = fem.solve(K, [fem.reduce_load(F[c]) for c in prob.cases], rtol=1e-9)
    else:
        Us = _thermal_solve(prob, fem, K, E0 * fill[fem.act], F, th)
    t_solve = time.time() - t_solve
    anchor_nodes = prob.load_nodes(active)
    near = np.zeros(fem.act.size, bool)
    all_anchor = np.concatenate(list(anchor_nodes.values()))
    en = g.element_nodes(fem.act)
    near |= np.isin(en, all_anchor).any(axis=1)
    solid = fill[fem.act] >= 0.5
    res = {"label": label, "massG": float(fill.sum() * g.h ** 3 * prob.material["density"] / 1000),
           "volumeCM3": float(fill.sum() * g.h ** 3 / 1000), "cases": {}}
    worst_disp, worst_sig, worst_sz, worst_hill = 0.0, 0.0, 0.0, 0.0
    proc = getattr(prob, "process", None)
    bdir = (proc or {}).get("buildDirection")
    u_fields, vm_fields, se_fields = {}, {}, {}
    sf_case, sfl_case = [], []            # thermal runs: safety factors per case (derated yield)
    for c, u_r in zip(prob.cases, Us):
        u = fem.expand(u_r)
        mag = np.linalg.norm(u.reshape(-1, 3), axis=1)
        tc = th.get(c) if th else None
        if tc is None:
            vm = fem.von_mises(u, E0)
        else:
            vm = fem.von_mises(u, tc["E"], tc["eps0"])
        se_full = np.zeros(g.nelem)
        if tc is None:
            se_full[fem.act] = 0.5 * E0 * fill[fem.act] * fem.element_energy(u)
        else:
            se_full[fem.act] = 0.5 * tc["E"] * fill[fem.act] * fem.element_energy_thermal(u, tc["fhat"], tc["m"], tc["dT"])
        se_fields[c] = se_full
        u_fields[c] = u.reshape(-1, 3).astype(np.float32)
        vm_full = np.zeros(g.nelem, np.float32)
        vm_full[fem.act] = vm
        vm_fields[c] = vm_full
        keep = solid & ~near if (solid & ~near).any() else np.ones(vm.size, bool)
        peak = float(np.percentile(vm[keep], 99.5))
        Yc = prob.material["yield"] if tc is None else tc["yield"]
        if bdir is not None:   # tension across the layers (FDM parts split between layers)
            if tc is None:
                sz = np.maximum(FEM.normal_stress(fem.stress(u, E0), bdir), 0.0)
            else:
                sz = np.maximum(FEM.normal_stress(fem.stress(u, tc["E"], tc["eps0"]), bdir), 0.0)
            worst_sz = max(worst_sz, float(np.percentile(sz[keep], 99.5)))
            psz = float(np.percentile(sz[keep], 99.5))
            sfl_case.append(Yc * float(proc.get("zStrengthFactor", 1.0)) / psz if psz > 0 else float("inf"))
        if D is not None:      # print-aware run: Hill criterion with in-plane and interlayer strength
            from .physics import hill_index
            Y = prob.material["yield"]
            if tc is None:
                hi = hill_index(fem.stress(u, E0), Y, Y * float(proc.get("zStrengthFactor", 1.0)), bdir)
            else:
                hi = hill_index(fem.stress(u, tc["E"], tc["eps0"]), Yc, Yc * float(proc.get("zStrengthFactor", 1.0)), bdir)
            worst_hill = max(worst_hill, float(np.percentile(hi[keep], 99.5)))
        sf_case.append(Yc / peak if peak > 0 else float("inf"))
        mag_l = mag                       # the displacement the limit checks
        if tc is not None:
            um = fem.expand(tc["u_mech"])
            mag_m = np.linalg.norm(um.reshape(-1, 3), axis=1)
            mag_t = np.linalg.norm((u - um).reshape(-1, 3), axis=1)
            mag_l = mag if prob.disp_incl_thermal else mag_m
        load_disp = {a.name: float(mag_l[anchor_nodes[a.name]].mean())
                     for a in prob.anchors if a.role == "load" and c in a.loads}
        res["cases"][c] = {"complianceNmm": float(fem.reduce_load(F[c]) @ (u_r if tc is None else tc["u_mech"])),
                           "maxDisplacementMM": float(mag_l.max()),
                           "loadPointDisplacementMM": load_disp,
                           "peakStressMPa": peak, "maxStressAtAnchorsMPa": float(vm.max())}
        if tc is not None:
            sig_m = fem.stress(um, tc["E"])
            vm_m = _vm6(sig_m)
            vm_t = _vm6(fem.stress(u, tc["E"], tc["eps0"]) - sig_m)
            p_m, p_t = float(np.percentile(vm_m[keep], 99.5)), float(np.percentile(vm_t[keep], 99.5))
            res["cases"][c].update({
                "temperatureC": tc["tempC"], "deltaTC": tc["dT"], "thermalOnly": c in prob.thermal_only,
                "deratingE": tc["fE"], "deratingYield": tc["fY"], "EMPa": tc["E"], "yieldMPa": tc["yield"],
                "mechanicalDisplacementMM": float(mag_m.max()), "thermalDisplacementMM": float(mag_t.max()),
                "totalDisplacementMM": float(mag.max()),
                "peakStressMechanicalMPa": p_m, "peakStressThermalMPa": p_t,
                "thermalStressShare": p_t / (p_m + p_t) if p_m + p_t > 0 else 0.0,
                "safetyFactor": sf_case[-1]})
        worst_disp = max(worst_disp, float(mag_l.max()))
        worst_sig = max(worst_sig, peak)
    res["maxDisplacementMM"] = worst_disp
    res["peakStressMPa"] = worst_sig
    res["safetyFactor"] = prob.material["yield"] / worst_sig if worst_sig > 0 else float("inf")
    if th:                 # each case against its own (derated) yield
        res["safetyFactor"] = min(sf_case)
    if bdir is not None:
        zf = float(proc.get("zStrengthFactor", 1.0))
        res["peakLayerTensionMPa"] = worst_sz
        res["safetyFactorLayers"] = prob.material["yield"] * zf / worst_sz if worst_sz > 0 else float("inf")
        if th:
            res["safetyFactorLayers"] = min(sfl_case)
    if th:
        tcs = {c: res["cases"][c] for c in th}
        res["thermalDisplacementMM"] = max(r["thermalDisplacementMM"] for r in tcs.values())
        res["mechanicalDisplacementMM"] = max(
            [r["mechanicalDisplacementMM"] for r in tcs.values()]
            + [res["cases"][c]["maxDisplacementMM"] for c in prob.cases if c not in th])
        res["thermal"] = {"referenceTempC": prob.t_ref,
                          "displacementLimitUses": "total" if prob.disp_incl_thermal else "mechanical",
                          "alpha": prob.material["alpha"],
                          "strainPerK": [float(v) for v in next(iter(th.values()))["m"]],
                          "cases": {c: {k: tcs[c][k] for k in ("temperatureC", "deltaTC", "thermalOnly", "deratingE",
                                                               "deratingYield", "EMPa", "yieldMPa")} for c in tcs}}
    if D is not None:
        res["hillIndex"] = worst_hill
        res["safetyFactorVonMises"] = res["safetyFactor"]
        res["safetyFactorHill"] = 1.0 / worst_hill if worst_hill > 0 else float("inf")
        res["safetyFactor"] = min(res["safetyFactor"], res["safetyFactorHill"])
    try:
        from .fea import study
        keep = solid & ~near if (solid & ~near).any() else np.ones(fem.act.size, bool)
        if th is None:
            res["fea"] = study(prob, fem, K, E0 * fill[fem.act], prob.cases, F, Us, anchor_nodes, keep, label,
                               t_solve, prob.material["yield"], E0)
        else:              # applied loads include the thermal nodal forces (they sum to zero)
            Ft = {c: (F[c] + th[c]["f_th"]) if c in th else F[c] for c in F}
            res["fea"] = study(prob, fem, K, E0 * fill[fem.act], prob.cases, Ft, Us, anchor_nodes, keep, label,
                               t_solve, prob.material["yield"], E0, thermal=th)
    except Exception as e:   # the report is extra information: never lose a run over it
        res["fea"] = {"error": str(e)}
    res["_fields"] = {"active": active, "u": u_fields, "vm": vm_fields, "se": se_fields, "fill": fill}
    return res


def impact_check(prob, fill, lf, log):
    """Equivalent-static impact: a rigid mass at speed v hits an anchor region along a direction.
    The part's stiffness there, k, comes from a unit-load solve; the peak force is sqrt(2 E k).
    Force and stress use the uncorrected (stiffer) k, which gives the larger force; the deflection
    uses the locking-corrected k, which gives the larger deflection. Both are conservative."""
    from .physics import impact_energy, impact_peak_force, hill_index, PhysicsError
    g = prob.grid
    active = prob._connected(fill >= 0.05)
    fill = np.where(active, fill, 0.0)
    fixed, _, _ = prob.boundary(active)
    D = getattr(prob, "D", None)
    fem = FEM(g, active, fixed, prob.material["nu"], log=lambda *a: None, D=D, element=prob.element)
    E0 = prob.material["E"]
    K = fem.assemble(E0 * fill[fem.act])
    anchor_nodes = prob.load_nodes(active)
    en = g.element_nodes(fem.act)
    near = np.isin(en, np.concatenate(list(anchor_nodes.values()))).any(axis=1)
    solid = fill[fem.act] >= 0.5
    keep = solid & ~near if (solid & ~near).any() else np.ones(fem.act.size, bool)
    proc = getattr(prob, "process", None)
    bdir = (proc or {}).get("buildDirection")
    Y = prob.material["yield"]
    by_name = {a.name: a for a in prob.anchors}
    out = {}
    for name, case in prob.spec.get("impact", {}).items():
        where = f"impact '{name}'"
        an = case.get("anchor")
        if an not in by_name:
            raise PhysicsError(f"{where}: anchor '{an}' is not in the spec. Use one of: {', '.join(by_name)}.")
        if by_name[an].role == "fixed":
            raise PhysicsError(f"{where}: anchor '{an}' is a fixed support. Name the region that is hit.")
        d = np.asarray(case.get("direction", []), float)
        if d.shape != (3,) or np.linalg.norm(d) < 1e-12:
            raise PhysicsError(f"{where}: give direction, the way the mass moves, as three numbers (for example [0, 0, -1]).")
        d = d / np.linalg.norm(d)
        E_imp, v = impact_energy(case, where)
        # optional "case": the impact happens at that load case's temperature (derated E and yield, 0.4.2)
        cn, fE, fY = case.get("case"), 1.0, 1.0
        E0, Y = prob.material["E"], prob.material["yield"]
        if cn is not None:
            if cn not in prob.cases:
                raise PhysicsError(f"{where}: case '{cn}' is not a load case. Use one of: {', '.join(prob.cases)}.")
            if cn in getattr(prob, "t_case", {}):
                fE, fY = _derating(prob, prob.t_case[cn])
                E0, Y = E0 * fE, Y * fY
        nodes = anchor_nodes[an]
        Fu = np.zeros(3 * g.nnode)
        for c in range(3):
            Fu[3 * nodes + c] = d[c] / nodes.size          # 1 N in total, spread over the region
        u = fem.expand(fem.solve(K, [fem.reduce_load(Fu)], rtol=1e-10)[0])
        if fE != 1.0:
            u = u / fE                                         # stiffness fE K at the case temperature
        delta = float((u.reshape(-1, 3)[nodes] @ d).mean())  # mm per N at the hit region
        if delta <= 0:
            raise PhysicsError(f"{where}: the part does not resist a push along {d.round(3).tolist()} at '{an}'.")
        k = 1.0 / delta
        F = impact_peak_force(E_imp, k)
        sig = fem.stress(u, E0) * F
        vm = np.sqrt(0.5 * ((sig[:, 0] - sig[:, 1]) ** 2 + (sig[:, 1] - sig[:, 2]) ** 2 + (sig[:, 2] - sig[:, 0]) ** 2)
                     + 3 * (sig[:, 3] ** 2 + sig[:, 4] ** 2 + sig[:, 5] ** 2))
        peak = float(np.percentile(vm[keep], 99.5))
        r = {"anchor": an, "speedMS": v, "energyJ": E_imp / 1000.0, "stiffnessNperMM": k,
             "peakForceN": F, "deflectionMM": float(np.sqrt(2 * E_imp / (k * lf))),
             "peakStressMPa": peak, "safetyFactor": Y / peak if peak > 0 else float("inf")}
        if cn is not None:
            r["case"] = cn
            if cn in getattr(prob, "t_case", {}):
                r.update({"temperatureC": prob.t_case[cn], "deratingE": fE, "deratingYield": fY})
        if D is not None:
            zf = float(proc.get("zStrengthFactor", 1.0))
            hi = float(np.percentile(hill_index(sig, Y, Y * zf, bdir)[keep], 99.5))
            r["safetyFactorHill"] = 1.0 / hi if hi > 0 else float("inf")
            r["safetyFactor"] = min(r["safetyFactor"], r["safetyFactorHill"])
        if bdir is not None:
            sz = np.maximum(FEM.normal_stress(sig, bdir), 0.0)
            pz = float(np.percentile(sz[keep], 99.5))
            r["safetyFactorLayers"] = Y * float(proc.get("zStrengthFactor", 1.0)) / pz if pz > 0 else float("inf")
        out[name] = r
        log(f"  impact '{name}': {r['energyJ']:.3g} J at {v:.3g} m/s on '{an}', stiffness {k:.4g} N/mm -> "
            f"peak force {F:.4g} N, deflection {r['deflectionMM']:.3g} mm, safety factor {r['safetyFactor']:.3g}")
    return out


def buckling_check(prob, fill, lf, log):
    """Linear buckling factor of the as-built part per load case, times the locking factor lf."""
    from .physics import buckling
    g = prob.grid
    active = prob._connected(fill >= 0.05)
    fill = np.where(active, fill, 0.0)
    fixed, F, _ = prob.boundary(active)
    for c, fb in prob.body_loads(fill).items():
        F[c] = F[c] + fb
    fem = FEM(g, active, fixed, prob.material["nu"], log=lambda *a: None, D=getattr(prob, "D", None),
              element=prob.element)
    E0 = prob.material["E"]
    Ee = E0 * fill[fem.act]
    K = fem.assemble(Ee)
    th = _thermal_setup(prob, fem, Ee) if getattr(prob, "t_case", None) else None
    out = {}
    for c in prob.cases:
        t = time.time()
        tc = th.get(c) if th else None
        if tc is None:
            u = fem.solve(K, [fem.reduce_load(F[c])], rtol=1e-9)[0]
            lam, _ = buckling(fem, K, u, Ee)
        else:              # pre-stress of the case: mechanical plus thermal, at the derated stiffness
            fE = tc["fE"]
            u = fem.solve(K, [fem.reduce_load(F[c] + tc["f_th"]) / fE], rtol=1e-9)[0]
            if not np.any(u):
                out[c] = {"raw": float("inf"), "corrected": float("inf"), "seconds": 0.0}
                continue
            lam, _ = buckling(fem, K if fE == 1.0 else K * fE, u, Ee * fE, eps0=tc["eps0"])
        raw = float(lam[0]) if lam.size else float("inf")
        out[c] = {"raw": raw, "corrected": raw * lf, "seconds": time.time() - t}
        log(f"  buckling, load case {c}: factor {raw * lf:.3g} (raw {raw:.3g} x locking {lf:.3f}), "
            f"{time.time() - t:.0f} s")
    return out


def save_fields(path, grid, res):
    """Nodal displacement (mm) and element von Mises stress (MPa) per load case, for viewers."""
    if res is None:
        return
    arrays = {"origin": grid.origin, "h": np.array([grid.h]), "shape": np.array(grid.shape)}
    for c, u in res["_fields"]["u"].items():
        arrays[f"u::{c}"] = u
    for c, vm in res["_fields"]["vm"].items():
        arrays[f"vm::{c}"] = vm
    np.savez_compressed(path, **arrays)


def checks(prob, built, thick):
    out = []
    lim = prob.limits
    vf = prob.vf
    if "maxDisplacementMM" in lim:
        ok = built["maxDisplacementMM"] <= lim["maxDisplacementMM"]
        out.append({"name": "Maximum displacement (corrected for " + ("shear locking)" if prob.element == "hex8fi" else "discretisation)"), "ok": ok,
                    "value": f"{built['maxDisplacementMM']:.4g} mm (raw {built.get('maxDisplacementRawMM', built['maxDisplacementMM']):.4g})",
                    "limit": f"≤ {lim['maxDisplacementMM']} mm",
                    "fix": "" if ok else f"Raise objective.volumeFraction (now {vf}), widen the design space, "
                                         f"or use a stiffer material."})
    if "minSafetyFactor" in lim:
        ok = built["safetyFactor"] >= lim["minSafetyFactor"]
        out.append({"name": "Safety factor on yield" + (" (Hill, print-aware)" if "safetyFactorHill" in built else ""),
                    "ok": ok,
                    "value": f"{built['safetyFactor']:.2f}", "limit": f"≥ {lim['minSafetyFactor']}",
                    "fix": "" if ok else f"Raise volumeFraction (now {vf}), raise optimizer.minMemberMM so members "
                                         f"get thicker, or reduce the load."})
    if thick.size and prob.element != "hex8fi":
        frac = float((thick < 2.5).mean())
        out.append({"name": "Member thickness in voxels (information)", "ok": True, "warn": frac >= 0.25,
                    "value": f"{100 * (1 - frac):.0f} % of skeleton ≥ 3 voxels", "limit": "e9 element: no shear locking",
                    "fix": "" if frac < 0.25 else "Many members are 1–2 voxels thick: stress there is coarse. Rerun with "
                                                 "resolution 'fine' for sharper stress values."})
    elif thick.size:
        frac = float((thick < 5.5).mean())
        good = frac < 0.25
        out.append({"name": "Members ≥ 6 voxels thick (shear locking)", "ok": True, "warn": not good,
                    "value": f"{100 * (1 - frac):.0f} % of skeleton", "limit": "≥ 75 % (else warning)",
                    "fix": "" if good else f"Displacement was scaled by {1 / built.get('lockingFactor', 1):.3f} to stay "
                                           f"conservative. For a sharper answer, rerun with resolution 'fine'."})
    an = prob.derived.get("anchorNodes")
    if an:
        few = {k: v for k, v in an.items() if v < MIN_ANCHOR_NODES}
        out.append({"name": "Nodes per support and load region", "ok": True, "warn": bool(few),
                    "value": f"fewest {min(an.values())} ({min(an, key=an.get)})", "limit": f"≥ {MIN_ANCHOR_NODES} (else warning)",
                    "fix": "" if not few else f"{', '.join(few)}: make the region larger than about two voxels "
                                              f"({2 * prob.grid.h:g} mm) each way, or use a finer resolution. A region "
                                              f"of only a few nodes is a point load or support, and the stress next to it "
                                              f"grows without limit as the mesh gets finer."})
    lpr = built.get("loadPaths")
    if lpr is not None:
        lowered = lpr["isoLevelTo"] < lpr["isoLevelFrom"] - 1e-9
        changed = lowered or lpr["repaired"]
        out.append({"name": "Load paths from every load to a support", "ok": not lpr["stillCut"],
                    "warn": bool(changed) and not lpr["stillCut"],
                    "value": ("connected as optimized" if not changed else
                              (f"iso level lowered {lpr['isoLevelFrom']:.2f} → {lpr['isoLevelTo']:.2f}" if lowered else "")
                              + ("; " if lowered and lpr["repaired"] else "")
                              + (f"material added for {', '.join(lpr['repaired'])} ({lpr['addedVoxels']} voxels)" if lpr["repaired"] else ""))
                             + (f"; still thin: {', '.join(lpr['stillCut'])}" if lpr["stillCut"] else ""),
                    "limit": "connected",
                    "fix": "" if not changed and not lpr["stillCut"] else
                    "The export changed the optimized shape to keep loads connected; the as-built re-solve above includes "
                    "that change. For a cleaner part raise volumeFraction or iterations."})
    if "impact" in built:
        imin = float(lim.get("minImpactSafetyFactor", 1.0))
        for name, r in built["impact"].items():
            ok = r["safetyFactor"] >= imin
            lay = r.get("safetyFactorLayers")
            ok_l = lay is None or lay >= imin
            out.append({"name": f"Impact '{name}' (equivalent static, {r['energyJ']:.3g} J)", "ok": ok and ok_l,
                        "value": f"safety factor {r['safetyFactor']:.3g}" + (f", across layers {lay:.3g}" if lay is not None else "")
                                 + f"; peak force {r['peakForceN']:.4g} N, deflection {r['deflectionMM']:.3g} mm",
                        "limit": f"≥ {imin:g}",
                        "fix": "" if ok and ok_l else "Raise volumeFraction, add a load case with the peak force so the "
                                                      "optimizer builds for it, or choose a tougher material."})
    ex = prob.derived.get("exactFeatures")
    if ex is not None:
        out.append({"name": "Exact geometry of kept features and keep-outs", "ok": True, "warn": "skipped" in ex,
                    "value": "not applied" if "skipped" in ex else
                    f"{len(ex['kept'])} kept, {len(ex['cut'])} cut",
                    "limit": "–", "fix": ex.get("skipped", "")})
    if "nonlinear" in built:
        nl = built["nonlinear"]
        if "skipped" in nl:
            out.append({"name": "Large deformation (CalculiX)", "ok": True, "warn": True, "value": "not run",
                        "limit": "–", "fix": nl["skipped"]})
        else:
            for c, r in nl["cases"].items():
                big = abs(r["ratio"] - 1) > 0.10 if np.isfinite(r["ratio"]) else True
                lim_d = lim.get("maxDisplacementMM")
                if c in getattr(prob, "t_case", {}) and not getattr(prob, "disp_incl_thermal", False):
                    lim_d = None   # CalculiX gives the total displacement; the limit checks the mechanical one
                ok = np.isfinite(r["nonlinear"]) and (lim_d is None or r["nonlinear"] <= lim_d)
                out.append({"name": f"Large deformation, load case {c} (CalculiX NLGEOM)", "ok": bool(ok), "warn": bool(big),
                            "value": f"{r['nonlinear']:.4g} mm nonlinear vs {r['linear']:.4g} mm linear (ratio {r['ratio']:.3f})",
                            "limit": f"≤ {lim_d} mm" if lim_d is not None else "–",
                            "fix": ("" if ok else "Raise volumeFraction or reduce the load. ")
                                   + ("Large-deformation effects are above 10 %: the linear results are not reliable "
                                      "for this load." if big else "")})
    if "buckling" in built:
        bmin = float(lim.get("minBucklingFactor", 2.0))
        worst = min(v["corrected"] for v in built["buckling"].values())
        ok = worst >= bmin
        out.append({"name": "Buckling load factor (linear" + (", corrected for shear locking)" if prob.element == "hex8fi" else ")"), "ok": ok,
                    "value": ", ".join(f"{c} {v['corrected']:.3g}" for c, v in built["buckling"].items()),
                    "limit": f"≥ {bmin:g}",
                    "fix": "" if ok else "Raise volumeFraction or optimizer.minMemberMM so slender members get "
                                         "thicker, or reduce the compressive load."})
    minwall = prob.material.get("minWallMM", 0)
    if thick.size and minwall and not getattr(prob, "process", None):   # with a process, dfm.py checks walls
        tmin = float(np.percentile(thick, 2)) * prob.grid.h
        ok = tmin >= minwall
        out.append({"name": "Thinnest member vs process minimum wall", "ok": ok,
                    "value": f"{tmin:.2f} mm (2nd percentile)", "limit": f"≥ {minwall} mm",
                    "fix": "" if ok else f"Set optimizer.minMemberMM to at least {2 * minwall} mm."})
    if built.get("thermal"):
        out += thermal_checks(prob, built, out)
    return out


POLYMER_E_MPA = 10000.0     # below this E a material is treated as a polymer (softens well below its limit)


def thermal_checks(prob, built, rows):
    """Check rows for temperature cases (0.4.2). Also adds the thermal displacement to the displacement row
    and the thermal share to the fix of a failed safety-factor row."""
    th = built["thermal"]
    cases = {c: built["cases"][c] for c in th["cases"]}
    mat = prob.material
    out = []
    for r in rows:
        if r["name"].startswith("Maximum displacement") and "thermalDisplacementMM" in built:
            r["value"] += (f"; thermal expansion {built['thermalDisplacementMM']:.4g} mm "
                           + ("included" if prob.disp_incl_thermal else "not in the limit"))
        if r["name"].startswith("Safety factor on yield") and not r["ok"]:
            top = max(cases, key=lambda c: cases[c]["thermalStressShare"])
            if cases[top]["thermalStressShare"] > 0.3:
                r["fix"] += (f" Thermal stress is {100 * cases[top]['thermalStressShare']:.0f} % of the peak in '{top}' "
                             f"(the optimizer used the mechanical loads only): make a joint able to slide (hold only "
                             f"the bolt-axis direction there) or raise volumeFraction.")
    # 1. service temperature
    lim = mat.get("maxServiceTempC")
    hot = max(c["temperatureC"] for c in cases.values())
    polymer = mat["E"] < POLYMER_E_MPA or str(mat.get("process", "")).upper() in ("FDM", "SLS")
    table = bool(mat.get("tempDerating"))
    warn, fix = False, ""
    if lim is None:
        warn, fix = True, (f"Material '{mat.get('name', '')}' has no maxServiceTempC, so Anneal cannot check the case "
                           f"temperatures. Add the service limit (°C) from the datasheet (for polymers: HDT at 1.8 MPa).")
    if polymer and not table and hot > 20.0:
        warn = True
        fix = (fix + " " if fix else "") + (
            f"No tempDerating table: room-temperature E and yield are used up to {hot:g} °C. A polymer is softer and "
            f"weaker when warm; add a tempDerating table from the datasheet or a test.")
    ok = lim is None or hot <= float(lim)
    out.append({"name": "Service temperature vs material limit", "ok": ok, "warn": warn and ok,
                "value": ", ".join(f"{c} {r['temperatureC']:g} °C" + (f" (margin {float(lim) - r['temperatureC']:.0f} K)"
                                                                     if lim is not None else "")
                                   for c, r in cases.items()),
                "limit": f"≤ {float(lim):g} °C (maxServiceTempC)" if lim is not None else "no limit in the material",
                "fix": fix})
    # 2. thermal stress share
    share = {c: r["thermalStressShare"] for c, r in cases.items()}
    big = max(share.values()) > 0.5
    out.append({"name": "Thermal stress share", "ok": True, "warn": bool(big),
                "value": ", ".join(f"{c} {100 * s:.0f} %" for c, s in share.items()) + " of the peak stress",
                "limit": "information (warning above 50 %)",
                "fix": "" if not big else "The expansion, not the load, sets the peak stress. The optimizer used the "
                                          "mechanical loads only. Let one joint slide (hold only the bolt-axis direction) "
                                          "before you add material: material held at both ends carries more thermal force."})
    # 3. supports that hold every direction at two or more anchors
    held = [a.name for a in prob.anchors if a.role == "fixed" and sorted(a.dofs) == [0, 1, 2]]
    if len(held) >= 2 and any(r["deltaTC"] != 0 for r in cases.values()):
        out.append({"name": "Held supports and thermal expansion", "ok": True, "warn": True,
                    "value": f"{', '.join(held)} hold x, y and z", "limit": "–",
                    "fix": "Held supports overestimate thermal stress: a real bolted joint slides a little. Hold only the "
                           "bolt-axis direction (anchor dofs) at the anchors where the joint can slide, and compare."})
    return out


def next_volume_fraction(passes, limit, tol=0.01):
    """Bracketed log-log secant search for the lightest volume fraction that meets the limit.
    Returns None to stop."""
    aim = 0.93 * limit
    pts = sorted((p["vf"], p["built"]["maxDisplacementMM"]) for p in passes)
    good = [(v, d) for v, d in pts if d <= limit]
    bad = [(v, d) for v, d in pts if d > limit]
    if good and min(good)[1] >= 0.85 * limit:   # lightest passing design is close to the limit
        return None
    if good and bad:
        vb, db = max(bad)
        vg, dg = min(good)
        if vg - vb < tol:
            return None
        if vb < vg:
            a = np.log(db / dg) / np.log(vg / vb) if db > dg else 2.5
            v = vg * (dg / aim) ** (1 / max(a, 0.5))
            gap = vg - vb
            return float(np.clip(v, vb + 0.15 * gap, vg - 0.15 * gap))
        return float((vb + vg) / 2 + 0.01)
    (v1, d1) = (max(bad) if bad else min(good))
    a = 2.5
    if len(pts) >= 2:
        (va, da), (vc, dc) = pts[0], pts[-1]
        if vc > va and da > dc > 0:
            a = float(np.clip(np.log(da / dc) / np.log(vc / va), 1.0, 4.0))
    v = float(np.clip(v1 * (d1 / aim) ** (1 / a), 0.05, 0.9))
    if bad and v >= 0.9 and max(bad)[0] >= 0.89:
        return None
    if abs(v - v1) < tol:
        return None
    return v


def run(spec_path, out_dir=None, log=print, db_path=None):
    t0 = time.time()
    log(f"Anneal {__version__} — {spec_path}")
    prob = Problem(spec_path, log=log)
    log("Building the design space")
    prob.build()
    g = prob.grid
    out_dir = out_dir or os.path.join(prob.base, "runs", prob.name)
    os.makedirs(out_dir, exist_ok=True)

    fixed, F, info = prob.boundary(prob.active)
    log("  anchor nodes: " + ", ".join(f"{k} {v}" for k, v in info.items()))
    prob.derived["anchorNodes"] = dict(info)
    few = {k: v for k, v in info.items() if v < MIN_ANCHOR_NODES}
    if few:
        log(f"  WARNING: anchor(s) {', '.join(f'{k} ({v} nodes)' for k, v in few.items())} hold fewer than "
            f"{MIN_ANCHOR_NODES} nodes: the support or load acts almost at a point, so stress there is not meaningful.")
    opt = prob.opt
    phys = prob.spec.get("physics", {}) or {}
    prob.D = None
    if phys.get("anisotropic"):
        from .physics import material_D
        prob.D, info = material_D(prob.material, prob.process)
        prob.derived["printAware"] = info
        log(f"  print-aware material: E {info['E']:g} MPa in the layers, Ez {info['Ez']:g} MPa across "
            f"(nuZ {info['nuZ']:g}, Gz {info['Gz']:.4g} MPa" + (f"; assumed {', '.join(info['assumed'])}" if info["assumed"] else "") + ")")
    mill = None
    proc = prob.process or {}
    if proc.get("method") == "machining" and int(proc.get("axes", 3)) == 3 and opt.get("machiningFilter", True):
        from .machining import MillFilter
        mill = lambda: MillFilter(g.shape, proc.get("setups", ["+z"]))
        prob.derived["machiningFilter"] = {"setups": proc.get("setups", ["+z"])}
        log(f"  machining filter on: every empty space stays open to the tool from {', '.join(proc.get('setups', ['+z']))}")
    if opt.get("overhangFilter"):
        raise RuntimeError("optimizer.overhangFilter is not part of Anneal 0.4 (it is still in testing). Remove it "
                           "from the spec; the printability report still shows overhangs and support volume.")
    if int(opt.get("iterations", 80)) < 25:
        log("  WARNING: fewer than 25 iterations leaves the design grey; the exported part will be heavier "
            "than the target. Use 60 or more for a part you will make.")
    # D9: members at least 6 voxels thick unless the user asks for a larger minimum
    min_member = float(opt.get("minMemberMM", max(2 * prob.material.get("minWallMM", 0), 6 * g.h)))
    r_mm = max(min_member / 2, 1.5 * g.h)
    prob.derived.update({"filterRadiusMM": r_mm, "minMemberMM": min_member})

    # the optimizer uses the mechanical loads only (0.4.2): thermal-only cases enter at the as-built check
    F_opt = F if not getattr(prob, "thermal_only", None) else {c: F[c] for c in prob.mech_cases}

    def one_pass(vf, x0=None):
        log(f"Optimizing at volume fraction {vf:.3f} ({len(F_opt)} load case(s): {', '.join(F_opt)})")
        res = simp(g, prob.fill, prob.active, prob.frozen, fixed, F_opt, prob.weights,
                   prob.material["E"], prob.material["nu"], vf,
                   iters=int(opt.get("iterations", 80)) if x0 is None else max(15, int(opt.get("iterations", 80)) * 2 // 5),
                   r_mm=r_mm, x0=x0,
                   p_final=float(opt.get("penalty", 3.0)), move=float(opt.get("move", 0.2)),
                   combine=prob.combine, log=log, beta_max=float(opt.get("sharpness", 4.0)),
                   D=prob.D, mfilter=mill() if mill else None, element=prob.element,
                   gravity=(prob.gravity_coef(), prob.gravity) if prob.gravity else None)
        x = res["x"]
        log("Generating the surface")
        f = output_field(prob, x)
        iso = prob.out_opts.get("isoLevel", "auto")
        level = choose_level(prob, f, x) if iso in (None, "auto") else float(iso)
        lp = prob.spec.get("loadPaths", {})
        prob._load_path_record = None
        if lp.get("guard", True):
            f, level = keep_load_paths(prob, f, level, log=log, margin=float(lp.get("margin", 0.1)),
                                       max_drop=float(lp.get("maxDrop", 0.15)), repair=bool(lp.get("repair", True)))
        edges, detail, up, sm = surface_settings(prob.out_opts)
        if (edges, detail) != ("smooth", "normal"):
            prob.derived["surface"] = f"{edges} edges, {detail} detail (upsample {up}, smoothing {sm})"
        if edges == "sharp":
            try:
                mesh = sharp_clip(prob, surface(g, sharp_field(prob, f, x), level, upsample=up, smooth=sm, log=log), log)
            except Exception as e:   # never lose a run over the finishing step
                log(f"  sharp edges not applied ({e}); smooth surface used")
                prob.derived["sharpEdges"] = f"not applied: {e}"
                mesh = surface(g, f, level, upsample=up, smooth=max(sm, 6), log=log)
        else:
            mesh = surface(g, f, level, upsample=up, smooth=sm, log=log)
        log(f"  {len(mesh.faces):,} triangles, watertight: {mesh.is_watertight}")
        from .finish import finish
        mesh, exact = finish(prob, mesh, log)
        if exact is not None:
            prob.derived["exactFeatures"] = exact
        log("Re-solving the as-built part (voxelized from the exported surface)")
        fill_b = voxel_fill(mesh, g)
        fill_b = np.minimum(np.maximum(fill_b, np.where(prob.frozen, prob.fill, 0)), 1 - prob.void_fill)
        built = evaluate(prob, fill_b, "Optimized (as built)", log)
        thick = member_thickness(g, fill_b)
        n25 = float(np.percentile(thick, 25)) if thick.size else 8.0
        lf = locking_factor(n25, prob.element)
        built["memberVoxelsP25"] = n25
        if getattr(prob, "_load_path_record", None) is not None:
            built["loadPaths"] = prob._load_path_record
        built["lockingFactor"] = lf
        built["maxDisplacementRawMM"] = built["maxDisplacementMM"]
        built["maxDisplacementMM"] = built["maxDisplacementMM"] / lf
        log(f"  thin members (25th percentile) {n25:.1f} voxels -> displacement corrected x{1 / lf:.3f} "
            + ("for shear locking" if prob.element == "hex8fi" else "for discretisation (e9 element)")
            + f": {built['maxDisplacementMM']:.4g} mm")
        return {"vf": vf, "res": res, "x": x, "f": f, "level": level, "mesh": mesh,
                "fill_b": fill_b, "built": built, "thick": thick}

    target = prob.limits.get("maxDisplacementMM")
    minimise_mass = prob.spec.get("objective", {}).get("minimise") == "mass" and target
    max_passes = int(opt.get("massPasses", 5)) if minimise_mass else 1
    passes = []
    vf = prob.vf
    for k in range(max_passes):
        P = one_pass(vf, None if not passes else min(passes, key=lambda q: abs(q['vf'] - vf))['x'])
        passes.append(P)
        d = P["built"]["maxDisplacementMM"]
        if not minimise_mass:
            break
        log(f"  pass {k + 1}: volume fraction {vf:.3f}, displacement {d:.4g} mm vs limit {target} mm, "
            f"mass {P['built']['massG']:.1f} g")
        vf = next_volume_fraction(passes, target)
        if vf is None:
            break
    ok = [p for p in passes if p["built"]["maxDisplacementMM"] <= (target or np.inf)]
    best = min(ok, key=lambda p: p["built"]["massG"]) if (minimise_mass and ok) else \
        (min(passes, key=lambda p: p["built"]["maxDisplacementMM"]) if minimise_mass else passes[-1])
    if minimise_mass:
        prob.derived["massPasses"] = [f"vf {p['vf']:.3f}: {p['built']['maxDisplacementMM']:.3g} mm, "
                                      f"{p['built']['massG']:.1f} g" for p in passes]
        log(f"  chose volume fraction {best['vf']:.3f} ({best['built']['massG']:.1f} g)"
            + ("" if ok else " — no pass met the limit; this is the stiffest"))
    res, x, f, level, mesh, fill_b, built, thick = (best[k] for k in
                                                    ("res", "x", "f", "level", "mesh", "fill_b", "built", "thick"))
    try:
        from .fea import mass_properties, report_lines
        built["massProperties"] = mass_properties(mesh, prob.material["density"])
        if "error" not in built.get("fea", {"error": 1}):
            for line in report_lines(built["fea"], built["massProperties"]):
                log(line)
    except Exception as e:
        log(f"  (FEA study summary not available: {e})")
    if prob.spec.get("impact"):
        log("Impact check on the as-built part (equivalent static)")
        built["impact"] = impact_check(prob, fill_b, built["lockingFactor"], log)
    if phys.get("buckling") or "minBucklingFactor" in prob.limits:
        log("Buckling check on the as-built part")
        built["buckling"] = buckling_check(prob, fill_b, built["lockingFactor"], log)
    prob.vf = best["vf"]
    res["all_history"] = [(f"pass {i + 1}: vf {p['vf']:.3f}", p["res"]["history"]) for i, p in enumerate(passes)] \
        if len(passes) > 1 else [("", res["history"])]
    history_record = [{"volumeFraction": p["vf"], "history": p["res"]["history"]} for p in passes]
    passes = [{"volumeFraction": p["vf"], "maxDisplacementMM": p["built"]["maxDisplacementMM"],
               "massG": p["built"]["massG"]} for p in passes]

    stl = os.path.join(out_dir, f"{prob.name}-optimized.stl")
    mesh.export(stl)          # always written: the viewer and the as-built check use it
    files = [stl]
    for fmt in prob.out_opts.get("formats", ["stl", "3mf"]):
        fmt = str(fmt).lower().lstrip(".")
        if fmt == "stl":
            continue
        if fmt in ("step", "stp"):
            try:
                from .stepout import export_step
                pth = os.path.join(out_dir, f"{prob.name}-optimized.step")
                info = export_step(mesh, pth, int(prob.out_opts.get("stepFaces", 20000)))
                prob.derived["step"] = info
                files.append(pth)
                log(f"  STEP written: faceted solid, {info['faces']:,} faces, volume {info['volumeMM3'] / 1000:.2f} cm3 "
                    f"(mesh {info['meshVolumeMM3'] / 1000:.2f} cm3)")
            except Exception as e:
                log(f"  (STEP not written: {e})")
            continue
        if fmt not in ("3mf", "obj", "ply", "glb", "off"):
            log(f"  output format '{fmt}' is not supported; use stl, 3mf, step, obj, ply, glb or off")
            continue
        try:
            pth = os.path.join(out_dir, f"{prob.name}-optimized.{fmt}")
            mesh.export(pth)
            files.append(pth)
        except Exception as e:  # some formats need optional packages; STL is always written
            log(f"  ({fmt.upper()} not written: {e.__class__.__name__}; STL is complete)")
    prob.derived["isoLevel"] = level
    if phys.get("nonlinear"):
        log("Large-deformation check with CalculiX (as-built STL)")
        from .sidecar import nonlinear_check
        try:
            built["nonlinear"] = nonlinear_check(prob, stl, os.path.join(out_dir, "calculix"), log,
                                                 phys.get("nonlinearMeshMM"))
        except Exception as e:   # the sidecar is optional: report, do not lose the run
            built["nonlinear"] = {"skipped": f"CalculiX check failed: {e}"}
        if "skipped" in built["nonlinear"]:
            log(f"  large-deformation check skipped: {built['nonlinear']['skipped']}")
    original = None
    if prob.mesh is not None and getattr(prob, "keep_model", False):
        log("  (the model holds only the interfaces, so it is not evaluated as a part on its own)")
    elif prob.mesh is not None:
        try:
            orig_fill = prob.space_fill if prob.spec.get("designSpace", "model") == "model" else voxel_fill(prob.mesh, g)
            original = evaluate(prob, orig_fill, "Original model", log)
        except Exception as e:
            log(f"  original model not evaluated: {e}")
    chk = checks(prob, built, thick)
    from .dfm import assess
    dfm_checks, dfm_summary = assess(prob, mesh, fill_b, built, thick)
    chk += dfm_checks
    for c in chk:
        log(f"  [{'WARN' if c.get('warn') else 'PASS' if c['ok'] else 'FAIL'}] {c['name']}: {c['value']} (limit {c['limit']})"
            + (f" — {c['fix']}" if c["fix"] else ""))

    adv = None
    if prob.out_opts.get("advanced"):
        log("Advanced output: graphs and statements")
        from . import advanced
        adv = advanced.write(out_dir, prob, built)
        for line in adv["insights"]:
            log("  - " + line)
    np.save(os.path.join(out_dir, "density.npy"), g.to3d(x).astype(np.float32))
    save_fields(os.path.join(out_dir, "fields-optimized.npz"), g, built)
    save_fields(os.path.join(out_dir, "fields-original.npz"), g, original)
    record = {
        "passes": passes,
        "anneal": __version__, "createdUTC": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0], "platform": platform.platform(),
        "spec": os.path.abspath(spec_path), "specSha256": _sha(spec_path),
        "model": getattr(prob, "model_path", None),
        "modelSha256": _sha(prob.model_path) if getattr(prob, "model_path", None) else None,
        "material": prob.material, "derived": prob.derived,
        "optimizer": {"iterations": len(res["history"]), "seconds": res["seconds"],
                      "amgBuilds": res["fem_builds"], "final": res["history"][-1]},
        "results": {"optimized": {k: v for k, v in built.items() if not k.startswith("_")},
                    "original": {k: v for k, v in original.items() if not k.startswith("_")} if original else None},
        "checks": chk,
        "process": prob.process,
        "solver": provenance.record(prob.element),
        **({"advanced": adv} if adv else {}),
        "dfm": dfm_summary,
        "history": history_record,
        "outputs": {os.path.basename(p): _sha(p) for p in files},
        "totalSeconds": time.time() - t0,
    }
    with open(os.path.join(out_dir, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, default=float)
    shutil.copy(spec_path, os.path.join(out_dir, "spec.json"))
    html = None
    if prob.out_opts.get("report", True):
        view = mesh
        if len(mesh.faces) > 160_000:
            view = surface(g, f, level, upsample=1, smooth=surface_settings(prob.out_opts)[3], log=lambda *a: None)
        html = report.write(out_dir, prob, res, view, built, original, chk, thick, record)
    copy_to = prob.out_opts.get("copyTo")
    if copy_to:
        try:
            os.makedirs(copy_to, exist_ok=True)
            for pth in files:
                shutil.copy(pth, copy_to)
            log(f"  copied {len(files)} file(s) to {copy_to}")
        except OSError as e:
            log(f"  WARNING: could not copy the outputs to {copy_to}: {e}")
    if db_path is not False:
        try:
            from . import db
            db.record_run(out_dir, record, prob.name, db_path)
        except Exception as e:  # the run is complete even if the history database is not writable
            log(f"  (run not added to the history database: {e})")
    log(f"Done in {time.time() - t0:.0f} s." + (f" Report: {html}" if html else f" Files in {out_dir}"))
    return record, html
