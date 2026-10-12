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

<h2>Convergence</h2><img class="plot" src="{conv}" alt="Convergence of objective, grey fraction and change">
<p class="note">Chosen pass: {opt['iterations']} iterations in {opt['seconds']:.0f} s, {opt['amgBuilds']} multigrid builds.
The objective rises while the penalty ramps up (expected), then falls. Later passes start from the previous design at full penalty.</p>

<h2>Where the material went</h2><img class="plot" src="{proj}" alt="Average density through the part from three directions">
<p class="note">Dark = material kept through most of the depth; white = removed. Blank areas are outside the design space.</p>

<h2>Derived values</h2><p class="note">Nothing here was typed in: each value is derived from the spec, the material and the model.</p>
<div class="scroll"><table><tr><th>Value</th><th>Setting</th></tr>{derived_rows}</table></div>

<h2>Files</h2><ul>{files}</ul>
<p class="note">Model limits: linear elastic, isotropic, small displacement, static loads. FDM parts are anisotropic;
Z strength can be under half the listed yield. Material values are typical datasheet figures — replace them with
your own coupon data in <code>materials.py</code>.</p>
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
