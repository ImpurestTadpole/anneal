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


def nodal_stress(fem, sig, Ee):
    """Recovered (smoothed) nodal stress: the stiffness-weighted average of the element-centre stresses
    around each node (partly filled voxels count less). Returns (nnode, 6) and the node weights."""
    nn = fem.grid.nnode
    w = np.repeat(np.asarray(Ee, float), 8)
    idx = fem.edof[:, 0::3].ravel() // 3
    W = np.bincount(idx, weights=w, minlength=nn)
    S = np.stack([np.bincount(idx, weights=w * np.repeat(sig[:, k], 8), minlength=nn) for k in range(6)], 1)
    return S / np.maximum(W, 1e-300)[:, None], W


def zz_error(fem, sig, Ee, E0):
    """Zienkiewicz-Zhu (1987) error estimate in the energy norm. The recovered stress sigma* is the
    trilinear field through the nodal averages; per element, eta_e^2 = integral of
    (sigma* - sigma_h)^T C^-1 (sigma* - sigma_h) over the voxel (2x2x2 Gauss points). Returns the
    element indicators eta_e (N mm)^0.5, the global relative error eta / sqrt(U + eta^2) and sigma* at
    the nodes."""
    from .fem import _dN, LOCAL
    Sn, _ = nodal_stress(fem, sig, Ee)
    nodes = fem.edof[:, 0::3] // 3                 # (ne, 8)
    Dinv = np.linalg.inv(fem.D)
    scale = np.asarray(Ee, float) / E0             # local modulus share: C = scale E0 D
    g = 1 / np.sqrt(3)
    h3 = fem.grid.h ** 3
    eta2 = np.zeros(len(sig))
    s = 2 * LOCAL - 1
    for xi in (-g, g):
        for et in (-g, g):
            for ze in (-g, g):
                N = (1 + s[:, 0] * xi) * (1 + s[:, 1] * et) * (1 + s[:, 2] * ze) / 8
                d = np.einsum("a,eak->ek", N, Sn[nodes]) - sig
                eta2 += np.einsum("ek,kl,el->e", d, Dinv, d) / (E0 * np.maximum(scale, 1e-9)) * h3 / 8
    U2 = np.einsum("ek,kl,el->e", sig, Dinv, sig) / (E0 * np.maximum(scale, 1e-9)) * h3   # 2 x strain energy
    rel = float(np.sqrt(eta2.sum() / max(U2.sum() + eta2.sum(), 1e-300)))
    return np.sqrt(eta2), rel, Sn


def study(prob, fem, K, Ee, cases, F_full, U_red, anchor_nodes, keep, label, seconds, yield_mpa, E0, thermal=None):
    """thermal (optional, 0.4.2): {case: dict from run._thermal_setup/_thermal_solve}. Such a case uses its own
    (derated) K, Ee, E and yield, the stress E D (B u - eps0), and F_full[c] holds the mechanical plus thermal
    nodal loads. Without it the numbers are exactly those of the earlier versions."""
    g = prob.grid
    used = np.unique(g.element_nodes(fem.act))
    partial = int(((Ee / E0) < 0.999).sum())
    n_cases = len(cases)
    it = fem.cg_iters[-n_cases:] if fem.cg_iters else []
    centres = g.elem_centers(fem.act)
    mat = prob.material
    out = {"label": label, "analysis": "Linear static",
           "material": {k: mat.get(k) for k in ("name", "E", "nu", "density", "yield", "Ez", "zStrengthFactor") if mat.get(k) is not None},
           "mesh": {"elementType": ("Hex8-E9: 8-node brick with 9 incompatible modes (Wilson-Taylor), 2x2x2 Gauss points (voxel)"
                                   if getattr(fem, "element", "hex8fi") == "e9" else
                                   "Hex8: 8-node brick, trilinear, 2x2x2 Gauss points (voxel)"),
                    "elements": int(fem.act.size), "partialVoxels": partial, "voxelMM": g.h,
                    "nodes": int(used.size), "dof": int(3 * used.size), "freeDof": int(fem.nfree),
                    "nonzeros": int(fem.nnz)},
           "solver": {"method": "Conjugate gradient with smoothed-aggregation algebraic multigrid (pyamg)",
                      "iterations": {c: int(n) for c, n in zip(cases, it)}, "tolerance": 1e-9,
                      "seconds": float(seconds)},
           "cases": {}}
    worst_res = 0.0
    base = (K, Ee, E0, yield_mpa)
    for c, u_r in zip(cases, U_red):
        tc = (thermal or {}).get(c)
        K, Ee, E0, yield_mpa = base if tc is None else (tc["K"], tc["Ee"], tc["E"], tc["yield"])
        eps0 = None if tc is None else tc["eps0"]
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
        sig = fem.stress(u, Ee * 0 + E0, eps0)
        vm = _vm(sig)
        eps = u[fem.edof] @ fem.B0.T
        if eps0 is not None:              # elastic (mechanical) strain: total minus thermal
            eps = eps - eps0
        em = (eps[:, 0] + eps[:, 1] + eps[:, 2]) / 3
        estrn = np.sqrt(2.0 / 3.0 * ((eps[:, 0] - em) ** 2 + (eps[:, 1] - em) ** 2 + (eps[:, 2] - em) ** 2
                                     + 0.5 * (eps[:, 3] ** 2 + eps[:, 4] ** 2 + eps[:, 5] ** 2)))
        P = _principal(sig)
        iv = int(np.argmax(vm))
        design = float(np.percentile(vm[keep], 99.5))
        energy = float(0.5 * F_full[c] @ u)
        if tc is not None:
            energy = float(0.5 * (Ee * fem.element_energy_thermal(u, tc["fhat"], tc["m"], tc["dT"])).sum())
        vol = Ee / E0 * g.h ** 3
        fos = yield_mpa / np.maximum(vm, 1e-12)
        # stress recovery and error estimate use the stress in the material at its local stiffness
        sig_l = sig * (np.asarray(Ee) / E0)[:, None]
        eta, rel, Sn = zz_error(fem, sig_l, Ee, E0)
        vm_n = _vm(nodal_stress(fem, sig, Ee)[0][used])
        ie = int(np.argmax(eta))
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
            "vonMisesNodalMaxMPa": float(vm_n.max()),
            "zzRelativeError": rel, "zzMaxAt": centres[ie].tolist(),
            "zzMaxAtSupportOrLoad": bool(not keep[ie]),
            "zzShareTop5pct": float(np.sort(eta ** 2)[::-1][:max(1, len(eta) // 20)].sum() / max((eta ** 2).sum(), 1e-300)),
        }
        if tc is not None:     # temperature of the case; reactions of the thermal load alone (total - mechanical)
            um = fem.expand(tc["u_mech"])
            Rm = (fem.internal_forces(um, Ee) - (F_full[c] - tc["f_th"])).reshape(-1, 3)
            reac_th = {a: (np.asarray(R_) - Rm[anchor_nodes[a]].sum(0)).tolist() for a, R_ in reac.items()}
            out["cases"][c].update({
                "temperatureC": tc["tempC"], "deltaTC": tc["dT"], "deratingE": tc["fE"], "deratingYield": tc["fY"],
                "EMPa": tc["E"], "yieldMPa": tc["yield"],
                "uresMechanicalMaxMM": float(np.linalg.norm(um.reshape(-1, 3), axis=1).max()),
                "uresThermalMaxMM": float(np.linalg.norm((u - um).reshape(-1, 3), axis=1).max()),
                "reactionsThermalN": reac_th, "thermalNodalForceAbsSumN": float(np.abs(tc["f_th"]).sum())})
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
        if "temperatureC" in r:
            L.append(f"    temperature {r['temperatureC']:g} °C (ΔT {r['deltaTC']:+g} K), E {r['EMPa']:.4g} MPa, yield "
                     f"{r['yieldMPa']:.4g} MPa (derating {r['deratingE']:.3g} / {r['deratingYield']:.3g}); URES "
                     f"mechanical {r['uresMechanicalMaxMM']:.4g} mm, thermal {r['uresThermalMaxMM']:.4g} mm")
            for a, R in r["reactionsThermalN"].items():
                L.append(f"    reaction {a} from the thermal load: {_v(R)} N")
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
        if "zzRelativeError" in r:
            L.append(f"    Stress error estimate (Zienkiewicz-Zhu, energy norm) {100 * r['zzRelativeError']:.1f} %; largest at "
                     f"{_v(r['zzMaxAt'])}" + (" (a support or load)" if r["zzMaxAtSupportOrLoad"] else "")
                     + f"; nodal (averaged) von Mises max {r['vonMisesNodalMaxMPa']:.4g} MPa")
        sh = r["volumeShareBelowFOS"]
        L.append(f"    FOS min {r['fosMin']:.3g} (design {r['fosDesign']:.3g}); volume below FOS 1: {100 * sh[1.0]:.2f} %, "
                 f"below 2: {100 * sh[2.0]:.2f} %, below 3: {100 * sh[3.0]:.2f} %")
    if mp:
        L.append(f"  Mass properties (exported solid): {mp['massG']:.4g} g, {mp['volumeCM3']:.4g} cm3, area {mp['areaMM2']:.5g} mm2, "
                 f"CoG {_v(mp['cogMM'])} mm, principal moments {_v(mp['principalMomentsKgMM2'])} kg·mm2")
    return L
