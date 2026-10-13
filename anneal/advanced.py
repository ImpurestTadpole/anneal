"""Advanced output (output.advanced: true): graphs and plain statements about how the part works.

Graphs (PNG files in the run folder, also shown in the report and the app):
  stress.png     von Mises stress by volume, with the yield stress and the allowable stress
  fos.png        share of the part below each factor of safety
  energy.png     how concentrated the load path is: share of strain energy against share of volume
  reactions.png  force taken by each support, per load case
  materials.png  the same geometry in every library material: displacement, safety factor, mass
Statements: what carries the load, where it is weakest, how much margin it has, and how far the
numbers can be trusted.

The material comparison keeps the geometry and the loads. In a linear model with the same Poisson
ratio, stress does not depend on E and displacement scales with 1/E; Poisson ratios differ a little
between materials, so the comparison is an estimate (a few per cent). It does not re-optimize."""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, QUIET, GRID, ACC, BAD, OK = "#1f2328", "#6b7280", "#e5e7eb", "#2563eb", "#b91c1c", "#15803d"


def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=QUIET, labelsize=8)
    ax.xaxis.label.set_color(QUIET)
    ax.yaxis.label.set_color(QUIET)
    ax.grid(color=GRID, lw=0.6)


def _save(fig, path):
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


def _data(prob, built):
    F = built["_fields"]
    fill = np.asarray(F["fill"], float)
    act = fill > 0
    vol = fill[act] * prob.grid.h ** 3
    vm = {c: np.asarray(v, float)[act] for c, v in F["vm"].items()}
    se = {c: np.asarray(v, float)[act] for c, v in F["se"].items()}
    return vol, vm, se


def stress_png(prob, built, path):
    vol, vm, _ = _data(prob, built)
    Y = prob.material["yield"]
    sf_lim = float(prob.limits.get("minSafetyFactor", 0) or 0)
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    top = max(max(float(np.percentile(v, 99.9)) for v in vm.values()), Y * 1.05)
    bins = np.linspace(0, top, 60)
    for c, v in vm.items():
        ax.hist(np.minimum(v, top), bins=bins, weights=vol / vol.sum() * 100, histtype="step", lw=1.4, label=c)
    ax.axvline(Y, color=BAD, lw=1.2)
    ax.text(Y, ax.get_ylim()[1] * 0.92, " yield", color=BAD, fontsize=8)
    if sf_lim > 0:
        ax.axvline(Y / sf_lim, color=QUIET, lw=1, ls="--")
        ax.text(Y / sf_lim, ax.get_ylim()[1] * 0.78, f" allowable (yield / {sf_lim:g})", color=QUIET, fontsize=8)
    ax.set_yscale("log")
    ax.set_xlabel("von Mises stress, MPa")
    ax.set_ylabel("share of part volume, %")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    return _save(fig, path)


def fos_png(prob, built, path):
    vol, vm, _ = _data(prob, built)
    Y = prob.material["yield"]
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    k = np.linspace(0, 10, 201)
    for c, v in vm.items():
        fos = Y / np.maximum(v, 1e-12)
        share = [(vol[fos < t]).sum() / vol.sum() * 100 for t in k]
        ax.plot(k, share, lw=1.5, label=c)
    lim = float(prob.limits.get("minSafetyFactor", 0) or 0)
    if lim:
        ax.axvline(lim, color=BAD, lw=1)
        ax.text(lim, 2, f" limit {lim:g}", color=BAD, fontsize=8)
    ax.set_xlabel("factor of safety (yield / von Mises)")
    ax.set_ylabel("share of volume below it, %")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    return _save(fig, path)


def energy_curve(vol, se):
    """Sorted from most to least loaded: cumulative volume share vs cumulative energy share."""
    dens = se / np.maximum(vol, 1e-30)
    o = np.argsort(-dens)
    cv = np.concatenate([[0], np.cumsum(vol[o])]) / vol.sum()
    ce = np.concatenate([[0], np.cumsum(se[o])]) / max(se.sum(), 1e-300)
    return cv, ce


def energy_png(prob, built, path):
    vol, _, se = _data(prob, built)
    fig, ax = plt.subplots(figsize=(4.6, 3.2))
    for c, e in se.items():
        cv, ce = energy_curve(vol, e)
        ax.plot(cv * 100, ce * 100, lw=1.5, label=c)
    ax.plot([0, 100], [0, 100], color=QUIET, lw=0.8, ls="--")
    ax.text(55, 45, "evenly loaded", color=QUIET, fontsize=8, rotation=35)
    ax.set_xlabel("share of volume, most loaded first, %")
    ax.set_ylabel("share of strain energy, %")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    return _save(fig, path)


def reactions_png(prob, built, path):
    fea = built.get("fea") or {}
    cases = fea.get("cases") or {}
    sup = [a.name for a in prob.anchors if a.role == "fixed"]
    if not cases or not sup:
        return None
    fig, ax = plt.subplots(figsize=(6.4, 0.5 + 0.45 * len(sup) * len(cases)))
    y, labels = 0, []
    for c, r in cases.items():
        for s in sup:
            R = np.asarray(r["reactionsN"].get(s, [0, 0, 0]))
            left = 0.0
            for k, col in zip(range(3), ("#2563eb", "#16a34a", "#d97706")):
                ax.barh(y, abs(R[k]), left=left, color=col, height=0.6, label="xyz"[k].upper() if y == 0 else None)
                left += abs(R[k])
            ax.text(left, y, f"  |R| {np.linalg.norm(R):.4g} N", va="center", fontsize=8, color=INK)
            labels.append(f"{s} · {c}")
            y += 1
    ax.set_yticks(range(len(labels)), labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("support reaction, |component| stacked, N")
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="lower right")
    _style(ax)
    return _save(fig, path)


def material_table(prob, built):
    from .materials import all_materials
    m0 = prob.material
    vcm3 = built["volumeCM3"]
    peak = built["peakStressMPa"]
    rows = []
    for name, m in all_materials().items():
        try:
            E, Y, rho = float(m["E"]), float(m["yield"]), float(m["density"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({"name": name, "displacementMM": built["maxDisplacementMM"] * m0["E"] / E,
                     "safetyFactor": Y / peak if peak > 0 else float("inf"), "massG": vcm3 * rho,
                     "current": name == m0.get("name")})
    return sorted(rows, key=lambda r: r["massG"])


def materials_png(prob, built, path):
    rows = material_table(prob, built)
    if not rows:
        return None
    lim_d = prob.limits.get("maxDisplacementMM")
    lim_s = float(prob.limits.get("minSafetyFactor", 0) or 0)
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 0.6 + 0.32 * len(rows)), gridspec_kw={"wspace": 0.9})
    names = [r["name"] + (" (this run)" if r["current"] else "") for r in rows]
    yy = np.arange(len(rows))
    a.barh(yy, [r["displacementMM"] for r in rows],
           color=[OK if lim_d is None or r["displacementMM"] <= lim_d else BAD for r in rows])
    a.set_yticks(yy, names, fontsize=8)
    a.invert_yaxis()
    a.set_xscale("log")
    a.set_xlabel("max displacement, mm (log)")
    if lim_d:
        a.axvline(lim_d, color=INK, lw=1, ls="--")
    b.barh(yy, [min(r["safetyFactor"], 50) for r in rows],
           color=[OK if r["safetyFactor"] >= max(lim_s, 1) else BAD for r in rows])
    b.set_yticks(yy, [f"{r['massG']:.4g} g" for r in rows], fontsize=8)
    b.invert_yaxis()
    b.set_xscale("log")
    b.set_xlabel("safety factor (log); labels: mass")
    if lim_s:
        b.axvline(lim_s, color=INK, lw=1, ls="--")
    for ax in (a, b):
        _style(ax)
    return _save(fig, path)


def insights(prob, built):
    """Plain statements about how the part carries the load."""
    vol, vm, se = _data(prob, built)
    Y = prob.material["yield"]
    out = []
    lim_d = prob.limits.get("maxDisplacementMM")
    worst = max(prob.cases, key=lambda c: built["cases"][c]["maxDisplacementMM"])
    d = built["maxDisplacementMM"]
    out.append(f"Stiffness: load case '{worst}' bends the part most, {d:.3g} mm"
               + (f", which is {100 * d / lim_d:.0f} % of the {lim_d:g} mm limit." if lim_d else "."))
    for c, e in se.items():
        cv, ce = energy_curve(vol, e)
        v50 = float(np.interp(0.5, ce, cv))
        v90 = float(np.interp(0.9, ce, cv))
        out.append(f"Load path, '{c}': {100 * v50:.0f} % of the material stores half of the strain energy and "
                   f"{100 * v90:.0f} % stores 90 %. " + ("The load goes through a few members: those members decide "
                   "stiffness and life, so keep them free of notches." if v50 < 0.1 else
                   "The load is spread over much of the part." if v50 > 0.25 else
                   "The load is carried by a clear set of members."))
    sf = built["safetyFactor"]
    out.append(f"Strength: safety factor {sf:.2f} on yield ({Y:g} MPa) at the 99.5th-percentile stress "
               f"{built['peakStressMPa']:.4g} MPa. " + ("It yields before the design load: add material or use a "
               "stronger material." if sf < 1 else "Margin is small; a stress raiser or a higher load could make it "
               "yield." if sf < 1.5 else "Static strength is not the limit; stiffness or buckling may be."))
    for c, v in vm.items():
        share = float(vol[v > Y].sum() / vol.sum())
        if share > 0:
            out.append(f"'{c}': {100 * share:.2f} % of the volume is above yield in the linear model. Small local "
                       f"zones at supports and loads are usual; spread over a member they are not.")
    fea = built.get("fea") or {}
    for c, r in (fea.get("cases") or {}).items():
        if "zzRelativeError" in r:
            z = r["zzRelativeError"]
            out.append(f"Stress resolution, '{c}': estimated error {100 * z:.0f} % in the energy norm "
                       f"(Zienkiewicz-Zhu). " + ("Stress values are reliable to a few per cent." if z < 0.1 else
                       "Stress values are an estimate; peaks can be higher. Use resolution 'fine' for sharper "
                       "stresses." if z < 0.3 else "Stress is coarse at this resolution: members are only a few voxels "
                       "thick. Displacement is still good; use resolution 'fine' for stress."))
        R = r.get("reactionsN") or {}
        if len(R) > 1:
            mags = {k: float(np.linalg.norm(v)) for k, v in R.items()}
            tot = sum(mags.values())
            k = max(mags, key=mags.get)
            if tot > 0:
                out.append(f"Supports, '{c}': '{k}' takes {100 * mags[k] / tot:.0f} % of the support force "
                           f"({mags[k]:.4g} N). Size its bolts or bearing for that force.")
    if "buckling" in built:
        b = min(v["corrected"] for v in built["buckling"].values())
        out.append(f"Buckling: the lowest load factor is {b:.3g}. " + ("Slender members buckle before the "
                   "design load." if b < 1 else "Check thin compressed members." if b < 3 else "Buckling is not critical."))
    rows = material_table(prob, built)
    good = [r for r in rows if (lim_d is None or r["displacementMM"] <= lim_d)
            and r["safetyFactor"] >= max(float(prob.limits.get("minSafetyFactor", 0) or 0), 1)]
    if good:
        out.append(f"Materials: with this geometry, the lightest library material that meets the limits is "
                   f"{good[0]['name']} ({good[0]['massG']:.4g} g). A different material changes the best shape, so "
                   f"re-optimize in that material before you make it.")
    return out


def write(out_dir, prob, built):
    files = {}
    for key, fn in (("stress", stress_png), ("fos", fos_png), ("energy", energy_png),
                    ("reactions", reactions_png), ("materials", materials_png)):
        try:
            p = fn(prob, built, os.path.join(out_dir, f"{key}.png"))
            if p:
                files[key] = os.path.basename(p)
        except Exception as e:      # a graph is extra information: never lose a run over it
            files[key + "Error"] = str(e)
    try:
        text = insights(prob, built)
    except Exception as e:
        text = [f"(statements not available: {e})"]
    return {"graphs": files, "insights": text, "materials": material_table(prob, built)}
