"""Self-contained HTML report for one run (opens in any browser; the 3D view needs internet for three.js)."""
import base64
import html as H
import io
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, QUIET, GRID, ACCENT, ORIG = "#1f2328", "#6b7280", "#e5e7eb", "#2563eb", "#9ca3af"


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=QUIET, labelsize=8)
    ax.yaxis.label.set_color(QUIET)
    ax.xaxis.label.set_color(QUIET)
    ax.grid(axis="y", color=GRID, lw=0.6)


def convergence_png(passes):
    """passes: list of (label, history). Draws all passes end to end."""
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.6, 2.9), gridspec_kw={"wspace": 0.32})
    x0 = 0
    first = passes[0][1][0]["objective"]
    for k, (label, hist) in enumerate(passes):
        it = np.arange(len(hist)) + x0 + 1
        col = ACCENT if k == len(passes) - 1 else ORIG
        a.plot(it, [h["objective"] / hist[0]["objective"] for h in hist], color=col, lw=1.6)
        b.plot(it, [h["grey"] for h in hist], color=col, lw=1.6)
        b.plot(it, [h["change"] for h in hist], color=col, lw=1.0, ls=":")
        ramp = next((i for i, h in enumerate(hist) if h["p"] >= hist[-1]["p"]), 0)
        if ramp > 0:
            a.axvline(x0 + ramp + 1, color=QUIET, lw=0.7, ls="--")
            a.annotate("full penalty", (x0 + ramp + 1, 1.0), xytext=(3, 0), textcoords="offset points",
                       fontsize=7, color=QUIET)
        if len(passes) > 1:
            a.annotate(label, (x0 + 1, 0.0), xycoords=("data", "axes fraction"), xytext=(2, 3),
                       textcoords="offset points", fontsize=7, color=QUIET)
            if k:
                for ax in (a, b):
                    ax.axvline(x0 + 0.5, color=GRID, lw=1.2)
        x0 += len(hist)
    a.set_xlabel("iteration (all passes)")
    a.set_ylabel("objective / pass start")
    a.set_title("Objective per pass" + (" (blue = chosen)" if len(passes) > 1 else ""), fontsize=9, color=INK, loc="left")
    b.set_xlabel("iteration (all passes)")
    b.set_ylim(0, 1)
    b.set_title("Grey fraction (solid) and largest change (dotted)", fontsize=9, color=INK, loc="left")
    for ax in (a, b):
        _style(ax)
    return _png(fig)


def projections_png(grid, x, fill):
    d = grid.to3d(x * fill)
    m = grid.to3d(fill > 0).astype(float)

    def avg(axis):  # average density through the part along the view direction
        n = m.sum(axis=axis)
        return np.where(n > 0, d.sum(axis=axis) / np.maximum(n, 1), np.nan).T
    names = [("top view (average along z)", avg(2), "x (mm)", "y (mm)", 0, 1),
             ("front view (average along y)", avg(1), "x (mm)", "z (mm)", 0, 2),
             ("side view (average along x)", avg(0), "y (mm)", "z (mm)", 1, 2)]
    fig, axs = plt.subplots(1, 3, figsize=(10, 3.2))
    o, h, n = grid.origin, grid.h, np.array(grid.shape)
    for ax, (t, img, xl, yl, i0, i1) in zip(axs, names):
        ext = [o[i0], o[i0] + h * n[i0], o[i1], o[i1] + h * n[i1]]
        ax.imshow(img, origin="lower", extent=ext, cmap="Blues", vmin=0, vmax=1, aspect="equal")
        ax.set_title(t, fontsize=9, color=INK, loc="left")
        ax.set_xlabel(xl)
        ax.set_ylabel(yl)
        ax.tick_params(colors=QUIET, labelsize=7)
        for s in ax.spines.values():
            s.set_color(GRID)
    return _png(fig)


def _f(v, d=3):
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.{d}g}"
    return str(v)


def _v3(x):
    return "(" + ", ".join(f"{t:.4g}" for t in x) + ")"


def _fea_section(built):
    fea = built.get("fea") or {}
    if not fea or "error" in fea:
        return ""
    m, s = fea["mesh"], fea["solver"]
    head = (f"<p class='note'>{H.escape(fea['analysis'])}, small displacement, linear elastic. Mesh: {m['elements']:,} "
            f"{H.escape(m['elementType'])} at {m['voxelMM']:g} mm ({m['partialVoxels']:,} partly filled), {m['nodes']:,} nodes, "
            f"{m['dof']:,} DOF. Solver: {H.escape(s['method'])}, relative residual {s['relativeResidual']:.1e}, "
            f"{s['seconds']:.1f} s.</p>")
    rows = []
    for c, r in fea["cases"].items():
        reac = "<br>".join(f"{H.escape(a)}: {_v3(R)} N" for a, R in r["reactionsN"].items())
        if "reactionsThermalN" in r:
            reac += "<br><span class='note'>from the thermal load: " + "; ".join(
                f"{H.escape(a)} {_v3(R)} N" for a, R in r["reactionsThermalN"].items()) + "</span>"
        sh = r["volumeShareBelowFOS"]
        zz = f"{100 * r['zzRelativeError']:.1f} %" if "zzRelativeError" in r else "–"
        rows.append(f"<tr><td>{H.escape(c)}</td><td>{_v3(r['appliedN'])} N</td><td>{reac}<br><span class='note'>"
                    f"equilibrium error {r['equilibriumError']:.1e}</span></td>"
                    f"<td>{r['uresMaxMM']:.4g} mm<br><span class='note'>at {_v3(r['uresMaxAt'])}</span></td>"
                    f"<td>{r['vonMisesDesignMPa']:.4g} MPa<br><span class='note'>max {r['vonMisesMaxMPa']:.4g} at "
                    f"{_v3(r['vonMisesMaxAt'])}{' (support/load)' if r['vonMisesMaxAtSupportOrLoad'] else ''}</span></td>"
                    f"<td>{r['p1MaxMPa']:.4g} / {r['p3MinMPa']:.4g} MPa</td>"
                    f"<td>{r['fosDesign']:.3g}<br><span class='note'>below 1: {100 * sh[1.0]:.2f} %, below 2: {100 * sh[2.0]:.1f} %</span></td>"
                    f"<td>{r['strainEnergyNmm']:.4g} N·mm</td><td>{zz}</td></tr>")
    mp = built.get("massProperties")
    mp_html = "" if not mp else (f"<p class='note'>Mass properties of the exported solid: {mp['massG']:.4g} g, "
                                 f"{mp['volumeCM3']:.4g} cm³, surface {mp['areaMM2']:.5g} mm², centre of gravity "
                                 f"{_v3(mp['cogMM'])} mm, principal moments {_v3(mp['principalMomentsKgMM2'])} kg·mm².</p>")
    return (f"<h2>FEA study (as built)</h2>{head}<div class='scroll'><table><tr><th>Load case</th><th>Applied</th>"
            f"<th>Reactions</th><th>URES max</th><th>von Mises (design)</th><th>P1 max / P3 min</th><th>FOS</th>"
            f"<th>Strain energy</th><th>Stress error (ZZ)</th></tr>{''.join(rows)}</table></div>{mp_html}"
            f"<p class='note'>Design von Mises: 99.5th percentile away from supports and loads. URES: resultant "
            f"displacement. Stress error: Zienkiewicz-Zhu estimate in the energy norm; it halves when the voxel size halves.</p>")


def _thermal_section(prob, built):
    """Temperature per load case: derating, mechanical and thermal displacement, stress shares (0.4.2)."""
    th = built.get("thermal")
    if not th:
        return ""
    rows = []
    for c in prob.cases:
        r = built["cases"][c]
        if "temperatureC" not in r:
            rows.append(f"<tr><td>{H.escape(c)}</td><td>{th['referenceTempC']:g} °C (reference)</td><td>0</td><td>1 / 1</td>"
                        f"<td>{_f(r['maxDisplacementMM'])}</td><td>0</td><td>{_f(r['peakStressMPa'])}</td><td>0 %</td></tr>")
            continue
        rows.append(f"<tr><td>{H.escape(c)}{' (thermal only)' if r['thermalOnly'] else ''}</td><td>{r['temperatureC']:g} °C</td>"
                    f"<td>{r['deltaTC']:+g} K</td><td>{r['deratingE']:.3g} / {r['deratingYield']:.3g}<br><span class='note'>"
                    f"E {r['EMPa']:.4g}, yield {r['yieldMPa']:.4g} MPa</span></td>"
                    f"<td>{_f(r['mechanicalDisplacementMM'])}</td><td>{_f(r['thermalDisplacementMM'])}<br><span class='note'>"
                    f"total {_f(r['totalDisplacementMM'])}</span></td>"
                    f"<td>{_f(r['peakStressMPa'])}<br><span class='note'>mechanical {_f(r['peakStressMechanicalMPa'])}, "
                    f"thermal {_f(r['peakStressThermalMPa'])}</span></td><td>{100 * r['thermalStressShare']:.0f} %</td></tr>")
    lim = ("the mechanical displacement (the thermal expansion of a free part is not a lack of stiffness)"
           if th["displacementLimitUses"] == "mechanical" else "the total displacement (limits.displacementIncludesThermal)")
    return (f"<h2>Temperature</h2><p class='note'>Reference (stress-free) temperature {th['referenceTempC']:g} °C; "
            f"expansion coefficient {th['alpha']:.4g} 1/K. The displacement limit checks {lim}.</p>"
            f"<div class='scroll'><table><tr><th>Load case</th><th>Temperature</th><th>ΔT</th><th>Derating E / yield</th>"
            f"<th>Mechanical displacement, mm</th><th>Thermal displacement, mm</th><th>Peak stress, MPa</th>"
            f"<th>Thermal stress share</th></tr>{''.join(rows)}</table></div>"
            f"<p class='note'>Mechanical: the loads alone at the case temperature. Thermal: the expansion alone. Peak stress "
            f"(total) is the 99.5th percentile of mechanical plus thermal stress; the share is thermal / (mechanical + "
            f"thermal) of those percentiles. The optimizer used the mechanical loads only.</p>")


def _advanced_section(out_dir, adv):
    if not adv:
        return ""
    titles = {"stress": "Stress distribution", "fos": "Factor of safety", "energy": "Load path concentration",
              "reactions": "Support reactions", "materials": "Same geometry in other materials"}
    imgs = []
    for k, t in titles.items():
        f = adv["graphs"].get(k)
        if f and os.path.exists(os.path.join(out_dir, f)):
            with open(os.path.join(out_dir, f), "rb") as fh:
                b = base64.b64encode(fh.read()).decode()
            imgs.append(f"<h3 style='font-size:14px;margin:18px 0 6px'>{t}</h3><img class='plot' "
                        f"src='data:image/png;base64,{b}' alt='{t}'>")
    li = "".join(f"<li>{H.escape(t)}</li>" for t in adv["insights"])
    mats = "".join(f"<tr><td>{H.escape(r['name'])}{' (this run)' if r['current'] else ''}"
                   f"{(' — ' + H.escape(r['note'])) if r.get('note') else ''}</td><td>{r['massG']:.4g}</td>"
                   f"<td>{r['displacementMM']:.4g}</td><td>{r['safetyFactor']:.3g}</td></tr>" for r in adv.get("materials", []))
    return (f"<h2>How the part works</h2><ul>{li}</ul>{''.join(imgs)}"
            + (f"<div class='scroll'><table><tr><th>Material</th><th>Mass, g</th><th>Max displacement, mm</th>"
               f"<th>Safety factor</th></tr>{mats}</table></div><p class='note'>Same geometry and loads; displacement "
               f"scales with 1/E and stress is unchanged (linear model). Not re-optimized.</p>" if mats else ""))


def _assumptions(prob, built, record):
    el = getattr(prob, "element", "hex8fi")
    aniso = getattr(prob, "D", None) is not None
    ass = [("Analysis", "linear static, small displacement, linear elastic material up to yield"),
           ("Element", "hex8 with 9 incompatible modes (e9): no shear locking" if el == "e9" else
            "plain hex8 (hex8fi): displacement corrected for shear locking"),
           ("Material", "transversely isotropic (print-aware), Hill strength" if aniso else "isotropic, von Mises strength"),
           ("Supports", "rigid: the held faces cannot move in the held directions (bolts and seats are not modelled)"),
           ("Loads", "each load spread in equal parts over the nodes of its region"
            + ("; pressures as the equivalent force on the picked face" if any(a.pressure for a in prob.anchors) else "")
            + ("; self-weight from the as-built geometry" if getattr(prob, "gravity", None) else "")),
           ("Geometry", "the exported surface, voxelized again at the run's voxel size (as-built re-solve)")]
    nm = ["contact and friction between parts", "bolt preload", "plasticity, creep and fracture", "fatigue",
          "temperature and thermal stress", "residual stress from manufacture", "dynamic response (except the "
          "equivalent-static impact check)"]
    if not aniso and prob.process and prob.process.get("method") != "machining":
        nm.append("layer anisotropy (turn on physics.anisotropic for FDM)")
    if "nonlinear" not in built:
        nm.append("large deformation (physics.nonlinear runs CalculiX)")
    th = built.get("thermal")
    if th:                 # 0.4.2: what the temperature option assumes and leaves out
        table = bool(prob.material.get("tempDerating"))
        ass += [("Temperature", f"one uniform temperature per load case; thermal strain α·ΔT, linear, from the "
                                f"reference {th['referenceTempC']:g} °C" + (" (α across the layers from alphaZ)"
                                                                          if prob.material.get("alphaZ") and aniso else "")),
                ("Material at temperature", "E and yield derated at the case temperature (tempDerating, linear "
                                            "interpolation)" if table else "no tempDerating table: the listed (room-"
                                            "temperature) E and yield are used at every case temperature"),
                ("Optimizer", "used the mechanical loads only; the thermal load enters at the as-built check"),
                ("Displacement limit", "mechanical displacement; thermal expansion reported separately"
                 if th["displacementLimitUses"] == "mechanical" else "total displacement (mechanical plus thermal)"),
                ("Strain (ESTRN)", "elastic strain: total strain minus thermal strain")]
        nm = [t for t in nm if t != "temperature and thermal stress"]
        nm += ["temperature gradients and heat flow (one uniform temperature per load case)",
               "creep and stress relaxation at temperature (a service limit such as HDT is a short-term value)",
               "slip in bolted joints: supports held in all directions overestimate the thermal stress",
               "expansion of the frame the part is fixed to (use the difference of expansion; docs/guides/NEW-PART.md "
               "section 9)", "properties that change with temperature inside one part"]
    sol = record.get("solver") or {}
    val = sol.get("validation") or {}
    gate = ("passed the validation gate on " + str(val.get("createdUTC")) if val.get("passed") else
            "FAILED the validation gate" if val.get("passed") is False else
            "has not been validated on this computer (run: python -m anneal validate)")
    eqs = [r.get("equilibriumError") for r in ((built.get("fea") or {}).get("cases") or {}).values()]
    ver = [f"Solver build {str(sol.get('solverSha256', ''))[:12]} (Anneal {sol.get('anneal', '')}, element {el}) {gate}.",
           "Results come from re-solving the exported surface, not the optimizer's density field."]
    if eqs and all(e is not None for e in eqs):
        ver.append(f"Equilibrium: reactions balance the applied loads to {max(eqs):.1e} (relative).")
    if th and getattr(prob, "thermal_only", None):
        ver.append("Thermal-only cases have no net applied force; their equilibrium error is relative to the sum of "
                   "the absolute nodal forces.")
    tr = "".join(f"<tr><td>{H.escape(a)}</td><td>{H.escape(b)}</td></tr>" for a, b in ass)
    return (f"<h2>Assumptions</h2><div class='scroll'><table>{tr}</table></div>"
            f"<h2>Not modelled</h2><ul>{''.join(f'<li>{H.escape(t)}</li>' for t in nm)}</ul>"
            f"<h2>Verification</h2><ul>{''.join(f'<li>{H.escape(t)}</li>' for t in ver)}</ul>"
            f"<p class='note'>Material values in the library are typical datasheet figures; replace them with your own "
            f"coupon data. Check critical parts with an independent analysis or a test.</p>")


def write(out_dir, prob, res, mesh, built, original, chk, thick, record):
    stl_b64 = base64.b64encode(mesh.export(file_type="stl")).decode()
    orig_b64 = ""
    if prob.mesh is not None and len(prob.mesh.faces) < 400_000:
        orig_b64 = base64.b64encode(prob.mesh.export(file_type="stl")).decode()
    all_ok = all(c["ok"] for c in chk)

    tiles = []
    if original:
        dm = 100 * (1 - built["massG"] / original["massG"])
        sign = "−" if dm >= 0 else "+"
        tiles.append(("Mass", f"{built['massG']:.1f} g", f"{sign}{abs(dm):.0f} % vs original {original['massG']:.1f} g"))
        cs_o = sum(original["cases"][c]["complianceNmm"] * prob.weights[c] for c in prob.cases)
        cs_b = sum(built["cases"][c]["complianceNmm"] * prob.weights[c] for c in prob.cases)
        spec_gain = (cs_o * original["massG"]) / (cs_b * built["massG"])
        tiles.append(("Stiffness per gram", f"{spec_gain:.2f} ×", "vs the original part"))
    else:
        tiles.append(("Mass", f"{built['massG']:.1f} g", prob.material.get("name", "")))
    tiles.append(("Max displacement", f"{built['maxDisplacementMM']:.3g} mm",
                  f"original {original['maxDisplacementMM']:.3g} mm" if original else "worst load case"))
    tiles.append(("Safety factor", f"{built['safetyFactor']:.2f}",
                  f"yield {prob.material['yield']:.0f} MPa, peak {built['peakStressMPa']:.0f} MPa"))

    rows = []
    for c in prob.cases:
        b = built["cases"][c]
        o = original["cases"][c] if original else None
        rows.append(f"<tr><td>{H.escape(c)}</td>"
                    f"<td>{_f(o['maxDisplacementMM']) if o else '–'}</td><td>{_f(b['maxDisplacementMM'])}</td>"
                    f"<td>{_f(o['peakStressMPa']) if o else '–'}</td><td>{_f(b['peakStressMPa'])}</td>"
                    f"<td>{_f(o['complianceNmm']) if o else '–'}</td><td>{_f(b['complianceNmm'])}</td></tr>")
    chk_rows = "".join(
        f"<tr><td><span class='pill {'warn' if c.get('warn') else 'ok' if c['ok'] else 'bad'}'>{'WARN' if c.get('warn') else 'PASS' if c['ok'] else 'FAIL'}</span></td>"
        f"<td>{H.escape(c['name'])}</td><td>{H.escape(c['value'])}</td><td>{H.escape(c['limit'])}</td>"
        f"<td>{H.escape(c['fix'])}</td></tr>" for c in chk) or "<tr><td colspan=5>No limits given in the spec.</td></tr>"
    d = prob.derived
    derived_rows = "".join(f"<tr><td>{H.escape(k)}</td><td>{H.escape(_f(v, 4) if not isinstance(v, list) else ' × '.join(map(str, v)))}</td></tr>"
                           for k, v in d.items())
    opt = record["optimizer"]
    conv = convergence_png(res.get("all_history") or [("", res["history"])])
    proj = projections_png(prob.grid, res["x"], prob.fill)
    files = "".join(f"<li><code>{H.escape(k)}</code></li>" for k in list(record["outputs"]) + ["run.json", "density.npy", "spec.json"])
    tile_html = "".join(f"<div class='tile'><div class='k'>{H.escape(a)}</div><div class='v'>{H.escape(b)}</div>"
                        f"<div class='s'>{H.escape(c)}</div></div>" for a, b, c in tiles)
    verdict = ("All checks pass." if all_ok else "Some checks fail — see the fixes below before you print.") if chk else \
        "No limits were given, so nothing was checked against a target."

    fea_html = _thermal_section(prob, built) + _fea_section(built)
    adv_html = _advanced_section(out_dir, record.get("advanced"))
    notes_html = _assumptions(prob, built, record)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{H.escape(prob.name)} — Anneal report</title>
<style>
:root{{--bg:#fbfbfa;--card:#ffffff;--ink:#1f2328;--quiet:#6b7280;--line:#e5e7eb;--accent:#2563eb;--ok:#15803d;--bad:#b91c1c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111315;--card:#181b1f;--ink:#e6e7e9;--quiet:#9aa1ab;--line:#2a2f36;--accent:#60a5fa;--ok:#4ade80;--bad:#f87171}}
img.plot{{filter:invert(.88) hue-rotate(180deg)}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:32px 16px 64px}}h1{{font-size:26px;margin:0 0 4px}}h2{{font-size:17px;margin:36px 0 10px}}
.sub{{color:var(--quiet);margin:0 0 20px}}.verdict{{font-weight:600;margin:0 0 18px;color:{'var(--ok)' if all_ok and chk else 'var(--bad)' if chk else 'var(--quiet)'}}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
.k{{color:var(--quiet);font-size:13px}}.v{{font-size:24px;font-weight:650;margin:2px 0}}.s{{color:var(--quiet);font-size:12.5px}}
#view{{height:440px;background:var(--card);border:1px solid var(--line);border-radius:10px;position:relative;overflow:hidden}}
#view .bar{{position:absolute;top:10px;left:10px;display:flex;gap:6px;z-index:2}}
button{{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:4px 10px;cursor:pointer}}
button.on{{border-color:var(--accent);color:var(--accent)}}#msg{{position:absolute;inset:0;display:grid;place-items:center;color:var(--quiet);font-size:13px}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13.5px;background:var(--card);border:1px solid var(--line);border-radius:10px}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--quiet);font-weight:500}}
.pill{{font-size:11.5px;font-weight:650;padding:2px 7px;border-radius:99px}}.ok{{color:var(--ok);border:1px solid var(--ok)}}.bad{{color:var(--bad);border:1px solid var(--bad)}}.warn{{color:#b45309;border:1px solid #b45309}}
img.plot{{width:100%;height:auto}}code{{font-size:12.5px}}.note{{color:var(--quiet);font-size:13px}}ul{{margin:6px 0}}
</style></head><body><main>
<h1>{H.escape(prob.name)}</h1>
<p class="sub">{H.escape(prob.material.get('name', 'material'))} · {len(prob.cases)} load case(s) · volume target {prob.vf:.0%} of the design space · {H.escape(record['createdUTC'])}</p>
<p class="verdict">{verdict}</p>
<div class="tiles">{tile_html}</div>

<h2>Part</h2>
<div id="view"><div class="bar"><button id="bOpt" class="on">Optimized</button>{'<button id="bOrig">Original</button><button id="bBoth">Both</button>' if orig_b64 else ''}</div>
<div id="msg">Loading 3D view… (needs an internet connection for three.js)</div></div>
<p class="note">Drag to turn, scroll to zoom. The exported files hold the full-resolution surface.</p>

<h2>Checks</h2><div class="scroll"><table><tr><th></th><th>Check</th><th>Result</th><th>Limit</th><th>Fix</th></tr>{chk_rows}</table></div>

<h2>Original vs optimized, per load case</h2>
<div class="scroll"><table><tr><th>Load case</th><th>Max displacement, original (mm)</th><th>optimized (mm)</th>
<th>Peak stress, original (MPa)</th><th>optimized (MPa)</th><th>Compliance, original (N·mm)</th><th>optimized (N·mm)</th></tr>{''.join(rows)}</table></div>
<p class="note">Optimized values come from re-solving the exported surface, not the density field (as-built check).
Peak stress is the 99.5th percentile at element centres, away from support and load points, where point
supports make stress unbounded in any linear model. Treat it as an estimate and check critical parts with an
independent analysis.</p>

{fea_html}
{adv_html}
<h2>Convergence</h2><img class="plot" src="{conv}" alt="Convergence of objective, grey fraction and change">
<p class="note">Chosen pass: {opt['iterations']} iterations in {opt['seconds']:.0f} s, {opt['amgBuilds']} multigrid builds.
The objective rises while the penalty ramps up (expected), then falls. Later passes start from the previous design at full penalty.</p>

<h2>Where the material went</h2><img class="plot" src="{proj}" alt="Average density through the part from three directions">
<p class="note">Dark = material kept through most of the depth; white = removed. Blank areas are outside the design space.</p>

<h2>Derived values</h2><p class="note">Nothing here was typed in: each value is derived from the spec, the material and the model.</p>
<div class="scroll"><table><tr><th>Value</th><th>Setting</th></tr>{derived_rows}</table></div>

<h2>Files</h2><ul>{files}</ul>
{notes_html}
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
(function(){{
 var OPT="{stl_b64}", ORIG="{orig_b64}";
 var box=document.getElementById('view'), msg=document.getElementById('msg');
 if(!window.THREE){{msg.textContent='3D view unavailable offline. Open the STL file in your slicer or CAD tool.';return;}}
 msg.remove();
 function bytes(b){{var s=atob(b),a=new Uint8Array(s.length);for(var i=0;i<s.length;i++)a[i]=s.charCodeAt(i);return a.buffer;}}
 var dark=matchMedia('(prefers-color-scheme: dark)').matches;
 var r=new THREE.WebGLRenderer({{antialias:true,alpha:true}});r.setPixelRatio(devicePixelRatio);box.appendChild(r.domElement);
 var sc=new THREE.Scene(),cam=new THREE.PerspectiveCamera(35,1,0.1,1e6);
 sc.add(new THREE.HemisphereLight(0xffffff,dark?0x222222:0x888888,1.0));var dl=new THREE.DirectionalLight(0xffffff,0.7);dl.position.set(1,2,3);sc.add(dl);
 var L=new THREE.STLLoader();
 var gO=L.parse(bytes(OPT)); gO.computeVertexNormals();
 var mO=new THREE.Mesh(gO,new THREE.MeshStandardMaterial({{color:dark?0x60a5fa:0x2563eb,metalness:0.2,roughness:0.55}}));sc.add(mO);
 var mR=null;if(ORIG){{var gR=L.parse(bytes(ORIG));gR.computeVertexNormals();
 mR=new THREE.Mesh(gR,new THREE.MeshStandardMaterial({{color:0x9ca3af,transparent:true,opacity:0.28,depthWrite:false}}));mR.visible=false;sc.add(mR);}}
 gO.computeBoundingBox();var bb=gO.boundingBox,c=new THREE.Vector3();bb.getCenter(c);var sz=bb.getSize(new THREE.Vector3()).length();
 cam.position.set(c.x+sz*0.9,c.y-sz*1.1,c.z+sz*0.8);cam.up.set(0,0,1);
 var ctl=new THREE.OrbitControls(cam,r.domElement);ctl.target.copy(c);ctl.update();
 function fit(){{var w=box.clientWidth,h=box.clientHeight;r.setSize(w,h);cam.aspect=w/h;cam.updateProjectionMatrix();}}
 addEventListener('resize',fit);fit();
 (function loop(){{requestAnimationFrame(loop);r.render(sc,cam);}})();
 function mode(o,g,id){{mO.visible=o;if(mR)mR.visible=g;document.querySelectorAll('#view button').forEach(function(b){{b.classList.toggle('on',b.id===id);}});}}
 document.getElementById('bOpt').onclick=function(){{mode(true,false,'bOpt');}};
 if(mR){{document.getElementById('bOrig').onclick=function(){{mR.material.opacity=1;mR.material.depthWrite=true;mode(false,true,'bOrig');}};
 document.getElementById('bBoth').onclick=function(){{mR.material.opacity=0.28;mR.material.depthWrite=false;mode(true,true,'bBoth');}};}}
}})();
</script></body></html>"""
    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return path
