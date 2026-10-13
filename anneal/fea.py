"""Study results in the style of a commercial FEA report (SolidWorks Simulation, Ansys).

For a solved part: mesh and solver statistics, and per load case the reaction forces at every
support with an equilibrium check, displacement extremes and where they are, von Mises and
principal stresses, strain energy and the factor-of-safety distribution. Mass properties come from
the exported solid. Units: mm, N, MPa, g.
"""
import numpy as np


def _vm(sig):
    sx, sy, sz, txy, tyz, tzx = sig.T
    return np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3 * (txy ** 2 + tyz ** 2 + tzx ** 2))


def _principal(sig):
    S = np.zeros((len(sig), 3, 3))
    S[:, 0, 0], S[:, 1, 1], S[:, 2, 2] = sig[:, 0], sig[:, 1], sig[:, 2]
    S[:, 0, 1] = S[:, 1, 0] = sig[:, 3]
    S[:, 1, 2] = S[:, 2, 1] = sig[:, 4]
    S[:, 2, 0] = S[:, 0, 2] = sig[:, 5]
    return np.linalg.eigvalsh(S)            # ascending: P3, P2, P1


def study(prob, fem, K, Ee, cases, F_full, U_red, anchor_nodes, keep, label, seconds, yield_mpa, E0):
    g = prob.grid
    used = np.unique(g.element_nodes(fem.act))
    partial = int(((Ee / E0) < 0.999).sum())
    n_cases = len(cases)
    it = fem.cg_iters[-n_cases:] if fem.cg_iters else []
    centres = g.elem_centers(fem.act)
    mat = prob.material
    out = {"label": label, "analysis": "Linear static",
           "material": {k: mat.get(k) for k in ("name", "E", "nu", "density", "yield", "Ez", "zStrengthFactor") if mat.get(k) is not None},
           "mesh": {"elementType": "Hex8: 8-node brick, trilinear, 2x2x2 Gauss points (voxel)",
                    "elements": int(fem.act.size), "partialVoxels": partial, "voxelMM": g.h,
                    "nodes": int(used.size), "dof": int(3 * used.size), "freeDof": int(fem.nfree),
                    "nonzeros": int(fem.nnz)},
           "solver": {"method": "Conjugate gradient with smoothed-aggregation algebraic multigrid (pyamg)",
                      "iterations": {c: int(n) for c, n in zip(cases, it)}, "tolerance": 1e-9,
                      "seconds": float(seconds)},
           "cases": {}}
    worst_res = 0.0
    for c, u_r in zip(cases, U_red):
        f = fem.reduce_load(F_full[c])
        r = K @ u_r - f
        res = float(np.linalg.norm(r) / max(np.linalg.norm(f), 1e-30))
        worst_res = max(worst_res, res)
        u = fem.expand(u_r)
        fint = fem.internal_forces(u, Ee)
        R = (fint - F_full[c]).reshape(-1, 3)
        applied = F_full[c].reshape(-1, 3).sum(0)
        reac = {}
        for a in prob.anchors:
            if a.role == "fixed":
                reac[a.name] = R[anchor_nodes[a.name]].sum(0).tolist()
        tot = np.sum(list(reac.values()), axis=0) if reac else np.zeros(3)
        eq = float(np.linalg.norm(tot + applied) / max(np.linalg.norm(applied), 1e-30))
        U = u.reshape(-1, 3)
        mag = np.linalg.norm(U, axis=1)
        im = int(np.argmax(mag))
        sig = fem.stress(u, Ee * 0 + E0)
        vm = _vm(sig)
        eps = u[fem.edof] @ fem.B0.T
        em = (eps[:, 0] + eps[:, 1] + eps[:, 2]) / 3
        estrn = np.sqrt(2.0 / 3.0 * ((eps[:, 0] - em) ** 2 + (eps[:, 1] - em) ** 2 + (eps[:, 2] - em) ** 2
                                     + 0.5 * (eps[:, 3] ** 2 + eps[:, 4] ** 2 + eps[:, 5] ** 2)))
        P = _principal(sig)
        iv = int(np.argmax(vm))
        design = float(np.percentile(vm[keep], 99.5))
        energy = float(0.5 * F_full[c] @ u)
        vol = Ee / E0 * g.h ** 3
        fos = yield_mpa / np.maximum(vm, 1e-12)
        out["cases"][c] = {
            "appliedN": applied.tolist(), "reactionsN": reac, "reactionTotalN": tot.tolist(),
            "equilibriumError": eq, "relativeResidual": res,
            "uresMaxMM": float(mag[im]), "uresMaxAt": g.node_coords(im).tolist(),
            "uMinMM": U[used].min(0).tolist(), "uMaxMM": U[used].max(0).tolist(),
            "vonMisesMaxMPa": float(vm[iv]), "vonMisesMaxAt": centres[iv].tolist(),
            "vonMisesMaxAtSupportOrLoad": bool(not keep[iv]), "vonMisesDesignMPa": design,
            "p1MaxMPa": float(P[:, 2].max()), "p3MinMPa": float(P[:, 0].min()),
            "trescaMaxMPa": float(((P[:, 2] - P[:, 0]) / 2).max()),
            "strainEnergyNmm": energy, "equivalentStrainMax": float(estrn.max()),
            "fosMin": float(fos.min()), "fosDesign": float(yield_mpa / design) if design > 0 else float("inf"),
            "volumeShareBelowFOS": {k: float(vol[fos < k].sum() / vol.sum()) for k in (1.0, 1.5, 2.0, 3.0)},
        }
    out["solver"]["relativeResidual"] = worst_res
    return out


def mass_properties(mesh, density_g_cm3):
    """Mass, volume, area, centre of gravity and principal moments of a closed mesh."""
    m = mesh.copy()
    m.density = density_g_cm3 * 1e-3                 # g/mm3 -> masses in g, inertia in g mm2
    mp = m.mass_properties
    I = np.asarray(mp["inertia"])
    pm, _ = np.linalg.eigh(I)
    return {"massG": float(mp["mass"]), "volumeCM3": float(mp["volume"] / 1000), "areaMM2": float(m.area),
            "cogMM": np.asarray(mp["center_mass"]).round(3).tolist(),
            "inertiaKgMM2": (I / 1000).round(4).tolist(), "principalMomentsKgMM2": (pm / 1000).round(4).tolist()}


def _v(x, n=4):
    return "(" + ", ".join(f"{t:.{n}g}" for t in x) + ")"


def report_lines(fea, mp=None):
    m, s = fea["mesh"], fea["solver"]
    L = [f"FEA study — {fea['label']}: {fea['analysis'].lower()} (small displacement, linear elastic)",
         f"  Mesh: {m['elements']:,} {m['elementType'].split(':')[0]} elements at {m['voxelMM']:g} mm "
         f"({m['partialVoxels']:,} partly filled), {m['nodes']:,} nodes, {m['dof']:,} DOF ({m['freeDof']:,} free)",
         "  Material: " + ", ".join(f"{k} {v}" for k, v in fea.get("material", {}).items()) + " (MPa, g/cm3)",
         f"  Solver: CG + AMG, relative residual {s['relativeResidual']:.1e} (tolerance {s['tolerance']:.0e}); "
         + ", ".join(f"{c} {n} it" for c, n in s["iterations"].items()) + f"; {s['seconds']:.1f} s"]
    for c, r in fea["cases"].items():
        L.append(f"  Load case '{c}': applied {_v(r['appliedN'])} N")
        for a, R in r["reactionsN"].items():
            L.append(f"    reaction {a}: {_v(R)} N")
        L.append(f"    reaction total {_v(r['reactionTotalN'])} N; equilibrium error {r['equilibriumError']:.1e}")
        L.append(f"    URES max {r['uresMaxMM']:.4g} mm at {_v(r['uresMaxAt'])}; UX {r['uMinMM'][0]:.3g}/{r['uMaxMM'][0]:.3g}, "
                 f"UY {r['uMinMM'][1]:.3g}/{r['uMaxMM'][1]:.3g}, UZ {r['uMinMM'][2]:.3g}/{r['uMaxMM'][2]:.3g} mm")
        L.append(f"    von Mises max {r['vonMisesMaxMPa']:.4g} MPa at {_v(r['vonMisesMaxAt'])}"
                 + (" (at a support or load: local peak)" if r["vonMisesMaxAtSupportOrLoad"] else "")
                 + f"; design value {r['vonMisesDesignMPa']:.4g} MPa (99.5th percentile away from supports and loads)")
        L.append(f"    P1 max {r['p1MaxMPa']:.4g} MPa, P3 min {r['p3MinMPa']:.4g} MPa, Tresca max {r['trescaMaxMPa']:.4g} MPa; "
                 f"ESTRN max {r.get('equivalentStrainMax', float('nan')):.3e}; strain energy {r['strainEnergyNmm']:.4g} N·mm")
        sh = r["volumeShareBelowFOS"]
        L.append(f"    FOS min {r['fosMin']:.3g} (design {r['fosDesign']:.3g}); volume below FOS 1: {100 * sh[1.0]:.2f} %, "
                 f"below 2: {100 * sh[2.0]:.2f} %, below 3: {100 * sh[3.0]:.2f} %")
    if mp:
        L.append(f"  Mass properties (exported solid): {mp['massG']:.4g} g, {mp['volumeCM3']:.4g} cm3, area {mp['areaMM2']:.5g} mm2, "
                 f"CoG {_v(mp['cogMM'])} mm, principal moments {_v(mp['principalMomentsKgMM2'])} kg·mm2")
    return L
