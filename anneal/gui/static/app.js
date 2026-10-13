// Anneal GUI. One page; three views: Projects (home), the workbench, History.
import * as THREE from "three";
import { Viewer } from "./viewer.js";

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 3) => {
  if (v === null || v === undefined || Number.isNaN(+v)) return "–";
  if (!Number.isFinite(+v)) return "∞";
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString();
  const s = Number(v).toPrecision(d);
  return s.includes(".") && !s.includes("e") ? s.replace(/\.?0+$/, "") : s;   // 110 stays 110, 0.300 becomes 0.3
};
const clone = o => JSON.parse(JSON.stringify(o));

const STEPS = [
  { key: "model", title: "Model and design space" },
  { key: "anchors", title: "Supports and loads" },
  { key: "goal", title: "Material, process and goal" },
  { key: "settings", title: "Optimizer, load paths and output" },
  { key: "run", title: "Check and run" },
  { key: "result", title: "Result" },
];
const ROLE = {
  fixed: { cls: "hold", css: "--hold", noun: "Support", verb: "Add support" },
  load: { cls: "push", css: "--push", noun: "Load", verb: "Add load" },
  keepOut: { cls: "void", css: "--void", noun: "Keep empty", verb: "Add keep-out" },
  keep: { cls: "solid", css: "--solid", noun: "Keep as is", verb: "Keep a feature" },
};
const DIRS = [["-z", "Down (−Z)"], ["+z", "Up (+Z)"], ["+x", "+X"], ["-x", "−X"], ["+y", "+Y"], ["-y", "−Y"],
  ["into", "Into the surface"], ["out", "Away from the surface"], ["custom", "Custom vector"]];
const FORMATS = ["stl", "3mf", "step", "obj", "ply", "glb"];

const S = {
  page: "home", project: null, spec: null, gui: null, open: 0, arm: null,
  pickMode: "auto", patchR: null, job: null, check: null, runs: [], run: null,
  view: { mode: "shape", deform: 0, case: null, ghost: false }, fields: {}, materials: {}, processes: {}, version: "",
};
let viewer = null;

// ------------------------------------------------------------------ api
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).error || msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  const ct = r.headers.get("Content-Type") || "";
  return ct.includes("json") ? r.json() : r;
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function toast(msg, ms = 3200) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), ms);
}
function status(msg) { $("#status").textContent = msg || ""; }

// ------------------------------------------------------------------ paths
function getp(o, path) { return path.split(".").reduce((a, k) => a == null ? a : a[k], o); }
function setp(o, path, v) {
  const ks = path.split("."); let a = o;
  for (let i = 0; i < ks.length - 1; i++) { if (a[ks[i]] == null) a[ks[i]] = /^\d+$/.test(ks[i + 1]) ? [] : {}; a = a[ks[i]]; }
  if (v === undefined) delete a[ks.at(-1)]; else a[ks.at(-1)] = v;
}

// ------------------------------------------------------------------ spec
function defaultSpec(p) {
  const ext = p.bounds[1].map((v, i) => v - p.bounds[0][i]);
  const diag = Math.hypot(...ext);
  return {
    name: p.id, model: p.model, designSpace: "model", material: "PLA-FDM", resolution: "normal",
    anchors: [], keepOut: [], keep: [], loadCases: { main: { weight: 1 } },
    objective: { minimise: "mass", volumeFraction: 0.35, combine: "worst" },
    optimizer: { iterations: 70, massPasses: 5, penalty: 3, move: 0.2, sharpness: 4 },
    limits: { maxDisplacementMM: +(diag / 500).toPrecision(2), minSafetyFactor: 2 },
    loadPaths: { guard: true, margin: 0.1, maxDrop: 0.15, repair: true },
    output: { formats: ["stl", "3mf"], smoothing: 10, upsample: 2, isoLevel: "auto", report: true, exactFeatures: true },
  };
}
function cases() { return Object.keys(S.spec.loadCases || { main: {} }); }
function vecFor(meta, c) {
  const f = (meta.forces || {})[c] || { mag: 0, dir: "-z" };
  const n = meta.normal || [0, 0, 1];
  const m = +f.mag || 0;
  const d = { "+x": [1, 0, 0], "-x": [-1, 0, 0], "+y": [0, 1, 0], "-y": [0, -1, 0], "+z": [0, 0, 1], "-z": [0, 0, -1],
    into: n.map(v => -v), out: n }[f.dir];
  if (f.dir === "custom") return (f.custom || [0, 0, 0]).map(Number);
  return d.map(v => +(v * m).toFixed(6));
}
function derived(meta, role) {
  // region for keep-out / keep-solid built from the picked feature and its parameters
  const r = clone(meta.base.region), p = meta.p || {};
  if (meta.custom) return meta.region;
  const V = (a, b, s) => a.map((x, i) => x + s * b[i]);
  if (r.type === "pipe") {
    const R = meta.base.radius ?? (r.r + r.rIn) / 2;
    if (role === "keepOut") {
      const ext = +(p.extend ?? 0), ax = meta.normal;
      return { type: "cylinder", from: V(r.from, ax, -ext), to: V(r.to, ax, ext), r: +(R + +(p.clear ?? 0.5)).toFixed(3) };
    }
    return { type: "pipe", from: r.from, to: r.to, rIn: +R.toFixed(3), r: +(R + +(p.wall ?? 2)).toFixed(3) };
  }
  const o = meta.base.outline;
  if (r.type === "obox" && o) {   // the exact face outline, pushed out (keep-out) or into the part (keep)
    const d = role === "keepOut" ? +(p.depth ?? 5) : +(p.wall ?? 2);
    return { type: "prism", origin: o.origin, normal: o.normal, xdir: o.xdir, tris: o.tris,
      z0: role === "keepOut" ? 0 : -d, z1: role === "keepOut" ? d : 0 };
  }
  if (r.type === "obox") {
    if (role === "keepOut") {
      const d = +(p.depth ?? 5);
      return { ...r, center: V(r.center, meta.normal, d / 2), size: [r.size[0], r.size[1], d] };
    }
    const w = +(p.wall ?? 2);
    return { ...r, center: V(r.center, meta.normal, -w / 2), size: [r.size[0], r.size[1], w] };
  }
  return r;
}
function sync() {
  const sp = S.spec, g = S.gui;
  sp.anchors.forEach((a, i) => {
    const m = g.anchors[i] || {};
    if (a.role === "load") {
      a.loads = {};
      for (const c of cases()) a.loads[c] = vecFor(m, c);
    } else delete a.loads;
  });
  sp.keepOut = g.keepOut.map(m => derived(m, "keepOut"));
  sp.keep = g.keep.map(m => derived(m, "keep"));
  const used = new Set(sp.anchors.flatMap(a => a.loads ? Object.keys(a.loads) : []));
  if (used.size) for (const c of Object.keys(sp.loadCases)) if (!used.has(c)) delete sp.loadCases[c];
  syncImpact();
}
const AXIS = { "+x": [1, 0, 0], "-x": [-1, 0, 0], "+y": [0, 1, 0], "-y": [0, -1, 0], "+z": [0, 0, 1], "-z": [0, 0, -1] };
function impactGui() {
  const g = S.gui;
  if (!g.impact) {
    const [name, c] = Object.entries(S.spec.impact || {})[0] || [null, null];
    const dir = c ? (Object.entries(AXIS).find(([, v]) => v.join() === (c.direction || []).join()) || ["-z"])[0] : "-z";
    g.impact = c ? { on: true, name, anchor: c.anchor, massKg: c.massKg, mode: "dropHeightMM" in c ? "height" : "speed",
      value: c.dropHeightMM ?? c.speedMS, dir } : { on: false, name: "impact", massKg: 1, mode: "height", value: 1000, dir: "-z" };
  }
  return g.impact;
}
function syncImpact() {
  const m = impactGui(), loads = S.spec.anchors.filter(a => a.role === "load").map(a => a.name);
  if (!m.on || !loads.length) { delete S.spec.impact; return; }
  if (!loads.includes(m.anchor)) m.anchor = loads[0];
  const c = { anchor: m.anchor, massKg: +m.massKg || 0, direction: AXIS[m.dir] || [0, 0, -1] };
  if (m.mode === "height") c.dropHeightMM = +m.value || 0; else c.speedMS = +m.value || 0;
  S.spec.impact = { [m.name || "impact"]: c };
}
function impactFields() {
  const m = impactGui(), loads = S.spec.anchors.filter(a => a.role === "load").map(a => a.name);
  const head = chk("gui:impact.on", m.on, "Check an impact (equivalent static)",
    "A mass hits a load region. Anneal finds the part's stiffness there and the peak force from the impact energy.", "data-rerender");
  if (!m.on) return head;
  if (!loads.length) return head + `<p class="help">Add a load region first (step 2). The impact hits a load region.</p>`;
  return head + `
    ${row("Region that is hit", `<select data-bind="gui:impact.anchor" data-kind="text">${loads.map(n => `<option ${n === m.anchor ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>`)}
    ${row("Mass, kg", num("gui:impact.massKg", m.massKg, 'min="0.001" step="any"'))}
    ${row("Given as", `<select data-bind="gui:impact.mode" data-kind="text" data-rerender>
      <option value="height" ${m.mode === "height" ? "selected" : ""}>Drop height, mm</option>
      <option value="speed" ${m.mode === "speed" ? "selected" : ""}>Impact speed, m/s</option></select>`)}
    ${row(m.mode === "height" ? "Drop height, mm" : "Impact speed, m/s", num("gui:impact.value", m.value, 'min="0" step="any"'))}
    ${row("Direction the mass moves", `<select data-bind="gui:impact.dir" data-kind="text">${DIRS.filter(([v]) => AXIS[v]).map(([v, t]) => `<option value="${v}" ${m.dir === v ? "selected" : ""}>${t}</option>`).join("")}</select>`)}
    ${row("Minimum safety factor in the impact", num("limits.minImpactSafetyFactor", S.spec.limits.minImpactSafetyFactor, 'min="0" step="0.1" placeholder="1"'))}`;
}
let saveTimer = null;
function save(now = false) {
  if (!S.project) return;
  sync();
  clearTimeout(saveTimer);
  const go = () => post(`/api/projects/${encodeURIComponent(S.project.id)}/save`, { spec: S.spec, gui: S.gui })
    .catch(e => toast("Not saved: " + e.message));
  if (now) return go();
  saveTimer = setTimeout(go, 500);
}

// ------------------------------------------------------------------ navigation
function go(page) {
  if (page === "work" && !S.project) page = "home";
  S.page = page;
  $("#home").hidden = page !== "home";
  $("#workbench").hidden = page !== "work";
  $("#history").hidden = page !== "history";
  $("#library").hidden = page !== "library";
  $("#navHome").classList.toggle("on", page === "home");
  $("#navHistory").classList.toggle("on", page === "history");
  $("#navLibrary").classList.toggle("on", page === "library");
  if (page === "home") loadHome();
  if (page === "history") loadHistory();
  if (page === "library") loadLibrary();
  if (page === "work") viewer?.resize();
  crumb();
}
function crumb() {
  const c = $("#crumb");
  c.innerHTML = S.project && S.page === "work" ? `<b>${esc(S.project.id)}</b> <span class="quiet">${esc(S.project.model)}</span>` : "";
  if (S.project && S.page !== "work") c.innerHTML = `<button class="link" data-go="work">Back to ${esc(S.project.id)}</button>`;
}

async function loadHome() {
  const st = await api("/api/state");
  S.materials = st.materials; S.processes = st.processes; S.version = st.version;
  $("#wsPath").textContent = `Projects are saved in ${st.workspace}`;
  const ul = $("#projectList");
  ul.innerHTML = st.projects.length ? st.projects.map(p => `
    <li><button data-open="${esc(p.id)}"><span><b>${esc(p.id)}</b><br>
      <span class="meta">${p.runs ? `${p.runs} run${p.runs > 1 ? "s" : ""}, last ${fmt(p.best)} g` : "Not run yet"}</span></span>
      <span class="meta">${new Date(p.modified * 1000).toLocaleDateString()}</span></button></li>`).join("")
    : `<li class="quiet">No projects yet. Open a model to start one.</li>`;
}

async function upload(file) {
  if (!file) return;
  toast(`Opening ${file.name}…`, 20000);
  try {
    const p = await api("/api/projects", { method: "POST", headers: { "X-Filename": encodeURIComponent(file.name) }, body: file });
    toast(`Opened ${file.name}`);
    await openProject(p.id, p);
  } catch (e) { toast(e.message, 8000); }
}

async function refreshLib() {
  const st = await api("/api/state");
  S.materials = st.materials; S.processes = st.processes;
}

async function openProject(id, info) {
  await refreshLib();
  const p = info || await api(`/api/projects/${encodeURIComponent(id)}`);
  S.project = p; S.runs = p.runs; S.run = null; S.check = null; S.fields = {}; S.job = null; S.arm = null;
  S.spec = p.spec || defaultSpec(p);
  S.spec.name = p.id;
  const base = defaultSpec(p);
  for (const k of ["loadPaths", "output", "optimizer", "objective", "limits"]) S.spec[k] = { ...base[k], ...(S.spec[k] || {}) };
  S.spec.keepOut ??= []; S.spec.keep ??= []; S.spec.loadCases ??= { main: { weight: 1 } };
  S.gui = p.gui || { anchors: [], keepOut: [], keep: [] };
  while (S.gui.anchors.length < S.spec.anchors.length) S.gui.anchors.push({ label: "Typed region", kind: "custom", faces: [], custom: true });
  for (const k of ["keepOut", "keep"]) {
    while (S.gui[k].length < S.spec[k].length) S.gui[k].push({ label: "Typed region", faces: [], custom: true, region: S.spec[k][S.gui[k].length] });
  }
  S.open = S.spec.anchors.length ? (S.runs.length ? 5 : 4) : 1;
  go("work");
  if (!viewer) viewer = new Viewer($("#viewport"));
  viewer.setResult(null);
  viewer.setModel(await viewer.loadSTL(`/api/projects/${encodeURIComponent(p.id)}/model.stl`));
  viewer.view("iso");
  if (p.hasCheck) S.check = await api(`/api/projects/${encodeURIComponent(p.id)}/check`).catch(() => null);
  if (S.runs.length && S.open === 5) await selectRun(S.runs[0].id);
  save(true);
  render();
}

// ------------------------------------------------------------------ process
function matNow() { return typeof S.spec.material === "string" ? S.materials[S.spec.material] || {} : S.spec.material || {}; }
function procName() {
  const sp = S.spec.process;
  if (sp === "none") return null;
  const n = (sp && typeof sp === "object") ? sp.name : (typeof sp === "string" ? sp : null);
  return n || matNow().process || null;
}
function effProcess() {
  const name = procName();
  if (!name || !S.processes[name]) return null;
  const p = { ...S.processes[name] };
  if (matNow().zStrengthFactor) p.zStrengthFactor = matNow().zStrengthFactor;
  if (S.spec.process && typeof S.spec.process === "object") for (const [k, v] of Object.entries(S.spec.process)) if (k !== "name") p[k] = v;
  p.name = name;
  return p;
}
const AXES = { "+Z": [0, 0, 1], "-Z": [0, 0, -1], "+X": [1, 0, 0], "-X": [-1, 0, 0], "+Y": [0, 1, 0], "-Y": [0, -1, 0] };
function axisName(v) {
  for (const [k, a] of Object.entries(AXES)) if (a.every((x, i) => Math.abs(x - v[i]) < 1e-6)) return k;
  return v.map(x => (+x).toFixed(2)).join(", ");
}
function setProc(key, value) {
  let sp = S.spec.process;
  if (!sp || typeof sp !== "object") sp = S.spec.process = sp && sp !== "none" ? { name: sp } : {};
  if (value === undefined) delete sp[key]; else sp[key] = value;
}

// ------------------------------------------------------------------ panel
function stepSummary(k) {
  const sp = S.spec, p = S.project;
  if (k === "model") { const e = p.bounds[1].map((v, i) => v - p.bounds[0][i]); return e.map(v => fmt(v, 3)).join(" × ") + " mm"; }
  if (k === "anchors") {
    const n = r => sp.anchors.filter(a => a.role === r).length;
    return `${n("fixed")} support${n("fixed") === 1 ? "" : "s"}, ${n("load")} load${n("load") === 1 ? "" : "s"}`;
  }
  if (k === "goal") {
    const m = (typeof sp.material === "string" ? sp.material : "Custom") + (procName() ? `, ${procName()}` : "");
    return sp.objective.minimise === "mass" ? `${m}, lightest within ${sp.limits.maxDisplacementMM ?? "?"} mm` : `${m}, keep ${Math.round(100 * sp.objective.volumeFraction)} %`;
  }
  if (k === "settings") return `${sp.optimizer.iterations} iterations, ${sp.output.formats.map(f => f.toUpperCase()).join(" + ")}`;
  if (k === "run") return S.job?.state === "running" ? (S.job.kind === "check" ? "Checking…" : "Running…") : (S.check ? "Checked" : "Not checked");
  if (k === "result") return S.run ? `${fmt(S.run.record.results.optimized.massG)} g` : (S.runs.length ? `${S.runs.length} run${S.runs.length > 1 ? "s" : ""}` : "No runs yet");
  return "";
}

function render() {
  if (!S.project) return;
  const done = [true, S.spec.anchors.some(a => a.role === "fixed") && S.spec.anchors.some(a => a.role === "load"), true, true, !!S.check || S.runs.length > 0, S.runs.length > 0];
  $("#panel").innerHTML = STEPS.map((s, i) => `
    <section class="step ${S.open === i ? "open" : ""} ${done[i] ? "done" : ""}">
      <button class="stepHead" data-step="${i}" aria-expanded="${S.open === i}">
        <span class="n">${i + 1}</span><span class="t">${s.title}</span><span class="s">${esc(stepSummary(s.key))}</span>
      </button>
      <div class="stepBody">${S.open === i ? BODY[s.key]() : ""}</div>
    </section>`).join("");
  if (S.open === 4) drawChart();
  refreshView();
}

const num = (bind, val, attrs = "") => `<input type="number" data-bind="${bind}" value="${val ?? ""}" ${attrs}>`;
const row = (label, ctrl, help) => `<label class="row"><span>${label}</span>${ctrl}</label>${help ? `<p class="help">${help}</p>` : ""}`;
const chk = (bind, on, label, help, attrs = "") => `<label class="check"><input type="checkbox" data-bind="${bind}" data-kind="bool" ${on ? "checked" : ""} ${attrs}><span>${label}${help ? `<br><span class="quiet">${help}</span>` : ""}</span></label>`;

function processFields() {
  const p = effProcess(), sp = S.spec.process;
  const ov = sp && typeof sp === "object" ? sp : {};
  const sel = sp === "none" ? "__none" : (ov.name || (typeof sp === "string" ? sp : ""));
  const pv = (k, v) => ov[k] !== undefined ? ov[k] : v;
  const b = p ? p.buildDirection : [0, 0, 1];
  const bv = p ? p.buildVolumeMM : [0, 0, 0];
  const matProc = matNow().process;
  return `<fieldset><legend>Process and printability</legend>
    <p class="help">The process sets the printability (DFM) checks of each run. Values you change here apply to this project only.</p>
    ${row("Process", `<select id="procSel">
      <option value="" ${sel === "" ? "selected" : ""}>${matProc ? `From the material (${esc(matProc)})` : "From the material (none set)"}</option>
      ${Object.keys(S.processes).map(k => `<option ${sel === k ? "selected" : ""}>${esc(k)}</option>`).join("")}
      <option value="__none" ${sel === "__none" ? "selected" : ""}>None (no printability checks)</option></select>`)}
    ${p ? `
      ${row("Build direction (up)", `<select id="procDir">${Object.keys(AXES).map(k => `<option ${axisName(b) === k ? "selected" : ""}>${k}</option>`).join("")}
        ${Object.keys(AXES).includes(axisName(b)) ? "" : `<option selected>${axisName(b)}</option>`}</select>`)}
      ${row("Steepest overhang without support, ° from vertical", `<input type="number" data-proc="maxOverhangDeg" value="${p.maxOverhangDeg}" min="0" max="90" step="1">`, "90 means the process needs no support (powder beds).")}
      ${chk("__p.supportsAllowed", p.supportsAllowed !== false, "Supports are allowed", "", 'data-proc-bool="supportsAllowed"')}
      ${row("Closed cavities", `<select data-proc="enclosedVoids">${[["allow", "Allowed"], ["warn", "Warn"], ["fail", "Not allowed (trapped powder)"]].map(([v, t]) => `<option value="${v}" ${p.enclosedVoids === v ? "selected" : ""}>${t}</option>`).join("")}</select>`)}
      ${row("Layer strength factor", `<input type="number" data-proc="zStrengthFactor" value="${p.zStrengthFactor}" min="0.05" max="1" step="0.05">`, "Across-layer strength ÷ in-plane strength. Used for the layer-strength check.")}
      ${row("Minimum wall, mm", `<input type="number" data-proc="minWallMM" value="${p.minWallMM}" min="0" step="0.1">`)}
      ${row("Minimum hole, mm", `<input type="number" data-proc="minHoleMM" value="${p.minHoleMM}" min="0" step="0.1">`)}
      <div class="row wide"><span class="quiet">Build volume x, y, z (mm)</span><div class="xyz">${[0, 1, 2].map(i => `<input type="number" data-proc-vol="${i}" value="${bv[i]}" min="1" step="1">`).join("")}</div></div>
      <div class="btns"><button class="btn" data-view="print">Show printability</button>
        ${Object.keys(ov).some(k => k !== "name") ? `<button class="btn" data-proc-reset>Use the process values again</button>` : ""}</div>` : ""}
  </fieldset>`;
}

const BODY = {
  model() {
    const p = S.project, sp = S.spec;
    const ds = typeof sp.designSpace === "string" ? { type: sp.designSpace } : sp.designSpace;
    const res = typeof sp.resolution === "string" ? sp.resolution : "custom";
    const h = res === "custom" ? sp.resolution.voxelMM : p.voxelMM[res];
    const nvox = p.volumeCM3 * 1000 / Math.pow(h, 3);
    return `
      <p>${esc(p.model)}<br><span class="quiet">${p.faces.toLocaleString()} triangles, ${fmt(p.volumeCM3)} cm³,
        ${p.watertight ? "closed" : "<b style='color:var(--bad)'>not closed</b> (inside and outside can be wrong; repair it in CAD)"}</span></p>
      ${p.notes.length ? `<p class="help">${p.notes.map(esc).join("<br>")}</p>` : ""}
      <fieldset><legend>Design space</legend>
      <p class="help">Where material may go. "Inside the model only" can only remove material. The other spaces
        can also add material, for example to grow a part between bolt-on points you imported.</p>
      ${row("Space", `<select data-bind="designSpace.type" data-kind="ds" data-rerender>
        ${[["model", "Inside the model only"], ["hull", "Convex hull of the model"], ["bounds", "Bounding box of the model"], ["box", "A box I type in"]]
          .map(([v, t]) => `<option value="${v}" ${ds.type === v ? "selected" : ""}>${t}</option>`).join("")}</select>`)}
      ${["hull", "bounds"].includes(ds.type) ? row("Margin around it, mm", num("designSpace.marginMM", ds.marginMM ?? 0, 'min="0" step="0.5"')) : ""}
      ${ds.type !== "model" ? chk("designSpace.keepModel", !!ds.keepModel, "Keep the imported model as it is and grow material around it",
        "Use this when the model holds only the interfaces (bosses, flanges, mounting faces). Mark holes as supports or loads so they stay open.") : ""}
      ${ds.type === "box" ? `
        <div class="row wide"><span class="quiet">Minimum corner x, y, z (mm)</span><div class="xyz">${[0, 1, 2].map(i => num(`designSpace.min.${i}`, (ds.min || p.bounds[0])[i], 'step="any"')).join("")}</div></div>
        <div class="row wide"><span class="quiet">Maximum corner x, y, z (mm)</span><div class="xyz">${[0, 1, 2].map(i => num(`designSpace.max.${i}`, (ds.max || p.bounds[1])[i], 'step="any"')).join("")}</div></div>` : ""}
      </fieldset>
      <fieldset><legend>Resolution</legend>
      ${row("Detail", `<select data-bind="resolution" data-kind="res" data-rerender>
        ${[["draft", "Draft (fast, to test a setup)"], ["normal", "Normal"], ["fine", "Fine (slow)"], ["custom", "Custom voxel size"]]
          .map(([v, t]) => `<option value="${v}" ${res === v ? "selected" : ""}>${t}</option>`).join("")}</select>`)}
      ${res === "custom" ? row("Voxel size, mm", num("resolution.voxelMM", sp.resolution.voxelMM, 'min="0.05" step="0.05"')) : ""}
      <p class="help">Voxels about ${fmt(h)} mm, roughly ${Math.round(nvox).toLocaleString()} in the part.
        Rough time: ${fmt(nvox * 2.1e-4 * sp.optimizer.iterations / 60, 2)} min per pass on a 2-core PC; faster on more cores.</p>
      </fieldset>
      <div class="btns"><label class="btn file">Open another model…<input type="file" id="fileInput2"
        accept=".stl,.step,.stp,.obj,.ply,.off,.3mf,.glb"></label></div>`;
  },

  anchors() {
    const sp = S.spec;
    const armed = r => S.arm && S.arm.role === r && S.arm.index == null ? "armed" : "";
    const rows = sp.anchors.map((a, i) => anchorRow(a, i)).join("");
    const kr = k => S.gui[k].map((m, i) => extraRow(k, m, i)).join("");
    return `
      <p class="help">Click a button, then click a hole, a face or a spot on the part. A hole becomes a ring around its wall;
        a flat face becomes a thin slab on it.</p>
      <div class="btns">
        ${["fixed", "load", "keepOut", "keep"].map(r => `<button class="btn ${ROLE[r].cls} ${armed(r)}" data-arm="${r}">${ROLE[r].verb}</button>`).join("")}
      </div>
      <div class="row"><span>What a click selects</span><select id="pickMode">
        <option value="auto" ${S.pickMode === "auto" ? "selected" : ""}>The whole hole or face</option>
        <option value="patch" ${S.pickMode === "patch" ? "selected" : ""}>A round patch at the click</option></select></div>
      ${S.pickMode === "patch" ? `<div class="row"><span>Patch radius, mm</span><input type="number" id="patchR" value="${S.patchR ?? ""}" placeholder="auto" min="0.1" step="0.5"></div>` : ""}
      <fieldset><legend>Load cases</legend>
        <p class="help">Each case is one way the part is loaded. The weight says how much it counts.</p>
        <div class="cases">${cases().map(c => `<span class="case">
          <input type="text" value="${esc(c)}" data-case-rename="${esc(c)}" aria-label="Case name">
          <input type="number" value="${sp.loadCases[c].weight ?? 1}" data-bind="loadCases.${c}.weight" min="0" step="0.1" aria-label="Weight">
          ${cases().length > 1 ? `<button class="icon" data-case-del="${esc(c)}" title="Remove case">✕</button>` : ""}</span>`).join("")}
          <button class="btn" data-case-add>Add case</button></div>
        ${cases().length > 1 ? `<div class="row"><span>Viewer shows</span><select id="caseShow">${cases().map(c => `<option ${S.view.case === c ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></div>` : ""}
      </fieldset>
      ${rows || `<p class="quiet">No supports or loads yet.</p>`}
      ${kr("keepOut")}${kr("keep")}`;
  },

  goal() {
    const sp = S.spec, mats = S.materials;
    const custom = typeof sp.material !== "string";
    const m = custom ? sp.material : mats[sp.material] || {};
    const mass = sp.objective.minimise === "mass";
    return `
      ${row("Material", `<select data-bind="material" data-kind="mat" data-rerender>
        <optgroup label="Built in">${Object.keys(mats).filter(k => mats[k].builtIn).map(k => `<option ${sp.material === k ? "selected" : ""}>${esc(k)}</option>`).join("")}</optgroup>
        ${Object.keys(mats).some(k => !mats[k].builtIn) ? `<optgroup label="My library">${Object.keys(mats).filter(k => !mats[k].builtIn).map(k => `<option ${sp.material === k ? "selected" : ""}>${esc(k)}</option>`).join("")}</optgroup>` : ""}
        <option value="__custom" ${custom ? "selected" : ""}>Custom (this project only)…</option></select>`)}
      ${custom ? `
        ${row("Young's modulus E, MPa", num("material.E", m.E, 'min="1" step="any"'))}
        ${row("Poisson's ratio", num("material.nu", m.nu, 'min="0" max="0.49" step="0.01"'))}
        ${row("Density, g/cm³", num("material.density", m.density, 'min="0.01" step="any"'))}
        ${row("Yield strength, MPa", num("material.yield", m.yield, 'min="0.1" step="any"'))}
        ${row("Minimum wall, mm", num("material.minWallMM", m.minWallMM, 'min="0" step="0.1"'))}
        ${row("Layer strength factor", num("material.zStrengthFactor", m.zStrengthFactor, 'min="0.05" max="1" step="0.05" placeholder="from process"'), "Strength across layers ÷ strength along them. FDM often 0.4 to 0.6.")}
        ${row("E across the layers (Ez), MPa", num("material.Ez", m.Ez, 'min="1" step="any" placeholder="none"'), "For print-aware runs. From a test or the Z-direction value on the data sheet.")}
        ${row("Poisson's ratio across layers (nuZ)", num("material.nuZ", m.nuZ, 'min="0" max="0.49" step="0.01" placeholder="= nu"'))}
        ${row("Shear modulus between layers (Gz), MPa", num("material.Gz", m.Gz, 'min="1" step="any" placeholder="from Ez"'))}
        <div class="row"><input type="text" id="saveMatName" placeholder="Name for your library"><button class="btn" data-save-mat>Save to my library</button></div>`
        : `<p class="help">E ${fmt(m.E)} MPa, yield ${fmt(m.yield)} MPa, ${m.density} g/cm³, min wall ${m.minWallMM ?? 1} mm${m.zStrengthFactor ? `, layer strength ×${m.zStrengthFactor}` : ""}.
            ${esc(m.note || "")}${m.builtIn ? "" : ` <span class="tag mine">My library${m.source ? ": " + esc(m.source) : ""}</span>`}
            <button class="link" data-go="library">Library</button></p>`}
      ${processFields()}
      ${chk("physics.anisotropic", !!(sp.physics || {}).anisotropic, "Print-aware material (weaker and softer across the layers)",
        "Uses Ez from the material and the process build direction. Strength is checked with the Hill criterion.")}
      <fieldset><legend>Goal</legend>
        <label class="check"><input type="radio" name="goal" value="mass" ${mass ? "checked" : ""} data-goal><span>Lightest part that meets the limits
          <br><span class="quiet">Anneal tries several amounts of material and keeps the lightest that passes.</span></span></label>
        <label class="check"><input type="radio" name="goal" value="volume" ${!mass ? "checked" : ""} data-goal><span>Keep a fixed share of the material</span></label>
        <label class="row"><span>${mass ? "Start with this share" : "Share of the design space to keep"}: <b id="vfOut">${Math.round(sp.objective.volumeFraction * 100)} %</b></span>
          <input type="range" min="0.05" max="0.9" step="0.01" value="${sp.objective.volumeFraction}" data-bind="objective.volumeFraction" data-kind="num" data-live="vfOut"></label>
        ${cases().length > 1 ? row("With several load cases", `<select data-bind="objective.combine">
          <option value="worst" ${sp.objective.combine === "worst" ? "selected" : ""}>Stiffest in the worst case</option>
          <option value="sum" ${sp.objective.combine === "sum" ? "selected" : ""}>Stiffest on weighted average</option></select>`) : ""}
      </fieldset>
      <fieldset><legend>Limits</legend>
        ${row("Maximum displacement, mm", num("limits.maxDisplacementMM", sp.limits.maxDisplacementMM, `min="0" step="any" ${mass ? "required" : ""}`),
          mass ? "Needed for the lightest-part goal." : "Leave empty for no limit.")}
        ${row("Minimum safety factor on yield", num("limits.minSafetyFactor", sp.limits.minSafetyFactor, 'min="0" step="0.1"'))}
        ${chk("physics.buckling", !!(sp.physics || {}).buckling, "Check buckling of the finished part",
          "Linear buckling, corrected for the voxel model. Adds about a minute or more per load case.")}
        ${row("Minimum buckling factor", num("limits.minBucklingFactor", sp.limits.minBucklingFactor, 'min="1" step="0.1" placeholder="2"'), "A value here also turns the buckling check on.")}
        ${chk("physics.nonlinear", !!(sp.physics || {}).nonlinear, "Check large deformation with CalculiX",
          "Optional. Needs CalculiX and gmsh installed. Compares linear and large-deflection results of the finished part.")}
        ${impactFields()}
      </fieldset>`;
  },

  settings() {
    const o = S.spec.optimizer, lp = S.spec.loadPaths, out = S.spec.output;
    return `
      <fieldset><legend>Optimizer</legend>
        ${row("Iterations per pass", num("optimizer.iterations", o.iterations, 'min="10" max="500" step="5" data-kind="int"'), "60 or more for a part you will make. Under 25 the part stays grey and heavy.")}
        ${row("Most passes in the mass search", num("optimizer.massPasses", o.massPasses ?? 5, 'min="1" max="10" data-kind="int"'))}
        ${row("Smallest member, mm", num("optimizer.minMemberMM", o.minMemberMM, 'min="0" step="0.5" placeholder="auto"'), "Empty = 6 voxels, or twice the material's minimum wall if that is larger.")}
        ${row("Penalty", num("optimizer.penalty", o.penalty ?? 3, 'min="1" max="5" step="0.25"'), "How hard grey material is punished. 3 is standard.")}
        ${row("Move limit per iteration", num("optimizer.move", o.move ?? 0.2, 'min="0.02" max="0.5" step="0.01"'))}
        ${row("Edge sharpness", num("optimizer.sharpness", o.sharpness ?? 4, 'min="0" max="16" step="1"'), "Heaviside projection. 0 turns it off; above 8 can stall.")}
      </fieldset>
      <fieldset><legend>Load paths</legend>
        ${chk("loadPaths.guard", lp.guard !== false, "Keep every load connected to a support", "Checks the part before the surface is made.")}
        ${row("Required density above the surface level", num("loadPaths.margin", lp.margin ?? 0.1, 'min="0" max="0.5" step="0.01"'))}
        ${row("Largest surface-level drop to reconnect", num("loadPaths.maxDrop", lp.maxDrop ?? 0.15, 'min="0" max="0.5" step="0.01"'))}
        ${chk("loadPaths.repair", lp.repair !== false, "Add material if a load path is still cut", "Along the cheapest route through the design space.")}
        <p class="help">Supports and loads also keep material around them: set "Keep material around" on each one.</p>
      </fieldset>
      <fieldset><legend>Output</legend>
        <div class="row wide"><span class="quiet">File formats</span><div class="dofs">
          ${FORMATS.map(f => `<label><input type="checkbox" data-format="${f}" ${out.formats.includes(f) ? "checked" : ""} ${f === "stl" ? "disabled" : ""}> ${f.toUpperCase()}</label>`).join("")}</div></div>
        <p class="help">STL is always written. 3MF opens straight in Bambu Studio and other slicers. STEP opens as a
          solid body in SolidWorks, Fusion and FreeCAD (faceted; needs the STEP add-on).</p>
        ${out.formats.includes("step") ? row("STEP faces", num("output.stepFaces", out.stepFaces ?? 20000, 'min="1000" step="1000" data-kind="int"'), "Fewer faces = smaller file. 20 000 keeps the shape within a fraction of a millimetre.") : ""}
        ${row("Smoothing passes", num("output.smoothing", out.smoothing ?? 10, 'min="0" max="60" data-kind="int"'))}
        ${row("Surface detail", `<select data-bind="output.upsample" data-kind="int">
          ${[[1, "Voxel size"], [2, "2× finer"], [3, "3× finer (large files)"]].map(([v, t]) => `<option value="${v}" ${+out.upsample === v ? "selected" : ""}>${t}</option>`).join("")}</select>`)}
        ${row("Surface level", `<input type="text" data-bind="output.isoLevel" data-kind="iso" value="${out.isoLevel ?? "auto"}" placeholder="auto">`,
          "auto keeps the optimized volume. A number from 0.1 to 0.9: lower gives thicker members.")}
        ${chk("output.exactFeatures", !!out.exactFeatures, "Keep exact geometry at supports, loads and kept regions; cut keep-outs exactly",
          "Bolt holes, flanges and faces you picked come out as in the model instead of smoothed.")}
        ${chk("output.report", out.report !== false, "Write an HTML report")}
        ${row("Also copy files to folder", `<input type="text" data-bind="output.copyTo" data-kind="text" value="${esc(out.copyTo || "")}" placeholder="optional">`)}
      </fieldset>
      <details class="log"><summary>Spec file (what the command line uses)</summary><pre>${esc(JSON.stringify((sync(), S.spec), null, 2))}</pre></details>`;
  },

  run() {
    const j = S.job, sp = S.spec;
    const ready = sp.anchors.some(a => a.role === "fixed") && sp.anchors.some(a => a.role === "load");
    const busy = j && j.state === "running";
    const ck = S.check;
    const last = j?.iters?.at(-1);
    const iters = sp.optimizer.iterations;
    return `
      ${!ready ? `<p class="err">Add at least one support and one load first (step 2).</p>` : ""}
      <p class="help">Check setup solves the original part at draft resolution in seconds. Use it to see that supports hold
        and loads push the way you expect before a long run.</p>
      <div class="btns">
        <button class="btn" data-job="check" ${!ready || busy ? "disabled" : ""}>Check setup</button>
        <button class="primary" data-job="run" ${!ready || busy ? "disabled" : ""}>Optimize</button>
        ${busy ? `<button class="btn" data-stop>Stop</button>` : ""}
      </div>
      ${ck && !(busy && j.kind === "check") ? `<div class="figures">
        <div><div class="k">Original mass</div><div class="v">${fmt(ck.massG)} g</div></div>
        <div><div class="k">Original max displacement</div><div class="v">${fmt(ck.maxDisplacementMM)} mm</div></div>
        <div><div class="k">Original safety factor</div><div class="v">${fmt(ck.safetyFactor)}</div></div>
        <div><div class="k">Grid points per anchor</div><div class="d">${Object.entries(ck.anchorNodes || {}).map(([k, v]) => `${esc(k)}: ${v}`).join("<br>")}</div></div>
        </div><p class="help">The view shows how the original part bends. Use Deformed to exaggerate it.</p>` : ""}
      ${j && j.kind === "run" ? `
        <p>${busy ? `Pass ${(j.passes.length || 1)}${j.passes.length ? ` at ${Math.round(j.passes.at(-1).volumeFraction * 100)} % material` : ""},
          iteration ${last ? last.iter : 0} of up to ${iters}` : j.state === "done" ? "Finished." : j.state === "cancelled" ? "Stopped." : ""}</p>
        <div class="progress"><div style="width:${busy && last ? Math.min(100, 100 * last.iter / iters) : j.state === "done" ? 100 : 0}%"></div></div>
        <canvas class="chart" id="chart"></canvas>` : ""}
      ${j?.error ? `<p class="err">${esc(j.error)}</p>` : ""}
      ${j ? `<details class="log" ${j.state === "error" ? "open" : ""}><summary>Log (${j.lines.length} lines)</summary><pre id="logPre">${esc(j.lines.slice(-400).join("\n"))}</pre></details>` : ""}`;
  },

  result() {
    if (!S.runs.length) return `<p class="quiet">No runs yet. Optimize in step 5.</p>`;
    const r = S.run;
    const sel = `<div class="row"><span>Run</span><select id="runSel">${S.runs.map(x => `<option value="${x.id}" ${r && r.id === x.id ? "selected" : ""}>
      ${esc(x.created ? new Date(x.created).toLocaleString() : x.id)}, ${fmt(x.massG)} g${x.ok ? "" : ", check failed"}</option>`).join("")}</select></div>`;
    if (!r) return sel + `<p class="quiet">Loading…</p>`;
    const rec = r.record, o = rec.results.optimized, g = rec.results.original;
    const lim = (r.spec && r.spec.limits) || {};
    let spg = null;
    if (g) {
      const co = Object.values(g.cases).reduce((a, c) => a + c.complianceNmm, 0), cb = Object.values(o.cases).reduce((a, c) => a + c.complianceNmm, 0);
      spg = (co * g.massG) / (cb * o.massG);
    }
    const procNote = rec.process ? `<p class="help">Checked for ${esc(rec.process.name)}, built along ${esc(rec.dfm?.buildDirection || "+Z")}.</p>` : "";
    const files = r.files.filter(f => /-optimized\.(stl|3mf|obj|ply|glb|off)$/.test(f));
    const base = `/api/projects/${encodeURIComponent(S.project.id)}/runs/${r.id}/`;
    const hist = r.hist || {};
    return sel + `
      <div class="figures">
        <div><div class="k">Mass</div><div class="v">${fmt(o.massG)} g</div><div class="d">${g ? `${Math.round(100 * (1 - o.massG / g.massG))} % lighter than ${fmt(g.massG)} g` : ""}</div></div>
        <div><div class="k">Stiffness per gram</div><div class="v">${spg ? fmt(spg) + "×" : "–"}</div><div class="d">vs the original</div></div>
        <div><div class="k">Max displacement</div><div class="v">${fmt(o.maxDisplacementMM)} mm</div><div class="d">${lim.maxDisplacementMM ? `limit ${lim.maxDisplacementMM} mm` : ""}</div></div>
        <div><div class="k">Safety factor</div><div class="v">${fmt(o.safetyFactor)}</div><div class="d">peak ${fmt(o.peakStressMPa)} MPa${lim.minSafetyFactor ? `, need ${lim.minSafetyFactor}` : ""}</div></div>
      </div>
      <ul class="checks">${rec.checks.map(c => `<li><span class="pill ${c.warn ? "warn" : c.ok ? "ok" : "bad"}">${c.warn ? "WARN" : c.ok ? "PASS" : "FAIL"}</span>
        <span>${esc(c.name)}: ${esc(c.value)} <span class="quiet">(${esc(c.limit)})</span>${c.fix ? `<br><span class="fix">${esc(c.fix)}</span>` : ""}</span></li>`).join("")}</ul>
      ${procNote}
      <div class="btns">${files.map(f => `<a class="btn" href="${base}${encodeURIComponent(f)}?download=1">Download ${f.split(".").pop().toUpperCase()}</a>`).join("")}
        ${r.files.includes("report.html") ? `<a class="btn" href="${base}report.html" target="_blank" rel="noopener">Open report</a>` : ""}
        <button class="btn" data-reveal="${esc(r.dir)}">Open folder</button></div>
      <fieldset><legend>Notes</legend>
        <label class="check"><input type="checkbox" data-star ${hist.star ? "checked" : ""}><span>Star this run</span></label>
        <textarea data-note placeholder="What did you change, what did you print, how did it test?" style="min-height:70px">${esc(hist.note || "")}</textarea>
      </fieldset>
      ${rec.dfm && rec.dfm.bestDirection && rec.dfm.bestDirection !== rec.dfm.buildDirection ? `
        <p class="help">Printability: building along ${rec.dfm.bestDirection} instead of ${rec.dfm.buildDirection} gives
          ${fmt(rec.dfm.directions[rec.dfm.bestDirection].overhangMM2)} mm² of overhang instead of ${fmt(rec.dfm.overhangAreaMM2)} mm².</p>
        <div class="btns"><button class="btn" data-best-dir="${rec.dfm.bestDirection}">Build along ${rec.dfm.bestDirection}</button></div>` : ""}
      <div class="btns"><button class="btn" data-reuse>Use this run's settings</button></div>
      <p class="help">Takes material, goal, limits, optimizer, load-path and output settings from this run. Supports and loads stay as they are.</p>
      <p class="help">${rec.passes.length} pass${rec.passes.length > 1 ? "es" : ""}: ${rec.passes.map(p => `${Math.round(100 * p.volumeFraction)} % gives ${fmt(p.massG)} g, ${fmt(p.maxDisplacementMM)} mm`).join("; ")}. ${fmt(rec.totalSeconds / 60, 2)} min.</p>`;
  },
};

function anchorRow(a, i) {
  const m = S.gui.anchors[i] || {}, R = ROLE[a.role];
  const dofs = a.dofs ?? "xyz";
  const forces = a.role === "load" ? cases().map(c => {
    const f = (m.forces || {})[c] || { mag: 0, dir: "-z" };
    return `<div class="force"><span class="cn">${esc(c)}</span>
      <input type="number" data-bind="gui:anchors.${i}.forces.${c}.mag" value="${f.mag}" step="any" aria-label="Force in newtons" title="Force, N">
      <select data-bind="gui:anchors.${i}.forces.${c}.dir" data-rerender>${DIRS.map(([v, t]) => `<option value="${v}" ${f.dir === v ? "selected" : ""}>${t}</option>`).join("")}</select></div>
      ${f.dir === "custom" ? `<div class="xyz">${[0, 1, 2].map(k => `<input type="number" step="any" data-bind="gui:anchors.${i}.forces.${c}.custom.${k}" value="${(f.custom || [0, 0, 0])[k]}" title="F${"xyz"[k]}, N">`).join("")}</div>` : ""}`;
  }).join("") : "";
  return `<div class="anchor ${R.cls}">
    <div class="top"><input type="text" value="${esc(a.name)}" data-rename="${i}" aria-label="Name">
      <span><button class="icon" data-repick="${i}" title="Pick again">Re-pick</button><button class="icon" data-del="${i}" title="Remove">✕</button></span></div>
    <div class="what">${R.noun}: ${esc(m.label || "Region")}</div>
    ${a.role === "fixed" ? `<div class="row"><span>Held in</span><span class="dofs">${"xyz".split("").map(d => `<label><input type="checkbox" data-dof="${i}" value="${d}" ${dofs.includes(d) ? "checked" : ""}> ${d.toUpperCase()}</label>`).join("")}</span></div>` : ""}
    ${a.role === "load" ? `<div class="help">Force in newtons, per load case</div>${forces}` : ""}
    <div class="row"><span>Keep material around, mm</span>${num(`anchors.${i}.freezeMM`, a.freezeMM, 'min="0" step="0.5" placeholder="auto"')}</div>
    ${a.hole ? `<div class="row"><span>Room for the bolt head or nut at each end, mm</span>${num(`anchors.${i}.boltAccessMM`, a.boltAccessMM, 'min="0" step="1" placeholder="0"')}</div>` : ""}
    <details class="log"><summary>Region as numbers</summary><textarea data-region="anchors.${i}">${esc(JSON.stringify(a.region, null, 1))}</textarea></details>
  </div>`;
}

function extraRow(kind, m, i) {
  const R = ROLE[kind], hole = m.base?.region?.type === "pipe", face = m.base?.region?.type === "obox";
  const p = m.p || {};
  let params = "";
  if (!m.custom && kind === "keepOut" && hole) params = row("Clearance around the hole, mm", num(`gui:${kind}.${i}.p.clear`, p.clear ?? 0.5, 'min="0" step="0.1"')) + row("Extend past both ends, mm", num(`gui:${kind}.${i}.p.extend`, p.extend ?? 0, 'min="0" step="0.5"'));
  if (!m.custom && kind === "keepOut" && face) params = row("Depth from the face, mm", num(`gui:${kind}.${i}.p.depth`, p.depth ?? 5, 'min="0.1" step="0.5"'));
  if (!m.custom && kind === "keep" && (hole || face)) params = row("Wall thickness to keep, mm", num(`gui:${kind}.${i}.p.wall`, p.wall ?? 2, 'min="0.1" step="0.5"'));
  return `<div class="anchor ${R.cls}">
    <div class="top"><b style="padding-left:4px">${R.noun}</b><span><button class="icon" data-del-extra="${kind}.${i}" title="Remove">✕</button></span></div>
    <div class="what">${esc(m.label || "Region")}</div>${params}
    <details class="log"><summary>Region as numbers</summary><textarea data-region="${kind}.${i}">${esc(JSON.stringify(S.spec[kind][i], null, 1))}</textarea></details>
  </div>`;
}

// ------------------------------------------------------------------ events
function onInput(el, live) {
  const bind = el.dataset.bind;
  if (!bind) return false;
  const kind = el.dataset.kind || (el.type === "number" || el.type === "range" ? "num" : el.type === "checkbox" ? "bool" : "text");
  let v = el.type === "checkbox" ? el.checked : el.value;
  const isGui = bind.startsWith("gui:");
  const path = isGui ? bind.slice(4) : bind;
  const root = isGui ? S.gui : S.spec;
  if (el.dataset.live) $("#" + el.dataset.live).textContent = Math.round(v * 100) + " %";
  if (live && el.type !== "range") return true;
  if (kind === "ds") {
    const p = S.project;
    if (v === "model") S.spec.designSpace = "model";
    else if (v === "box") S.spec.designSpace = { type: "box", min: p.bounds[0].map(x => +x.toFixed(2)), max: p.bounds[1].map(x => +x.toFixed(2)) };
    else S.spec.designSpace = { type: v, marginMM: 0 };
  } else if (kind === "res") {
    S.spec.resolution = v === "custom" ? { voxelMM: S.project.voxelMM.normal } : v;
  } else if (kind === "mat") {
    S.spec.material = v === "__custom" ? { name: "custom", E: 2000, nu: 0.35, density: 1.2, yield: 40, minWallMM: 1 } : v;
  } else if (kind === "iso") {
    const t = String(v).trim();
    setp(root, path, t === "" || t === "auto" ? "auto" : Math.min(0.9, Math.max(0.1, +t || 0.5)));
  } else if (kind === "bool") setp(root, path, !!v);
  else if (kind === "text") setp(root, path, v === "" ? undefined : v);
  else {
    if (v === "" || v === null) setp(root, path, undefined);
    else setp(root, path, kind === "int" ? Math.round(+v) : +v);
  }
  if (path.startsWith("designSpace.") && typeof S.spec.designSpace === "object" && S.spec.designSpace.type === "model") S.spec.designSpace = "model";
  save();
  if (el.hasAttribute("data-rerender") || ["ds", "res", "mat"].includes(kind)) render();
  else { refreshHeads(); refreshView(); }
  return true;
}
function refreshHeads() {
  document.querySelectorAll(".stepHead").forEach((b, i) => { b.querySelector(".s").textContent = stepSummary(STEPS[i].key); });
}

function uniqueName(base, skip = -1) {
  const names = new Set(S.spec.anchors.filter((_, i) => i !== skip).map(a => a.name));
  let n = base, k = 2; while (names.has(n)) n = `${base}-${k++}`; return n;
}

async function onPick(ev) {
  if (!S.arm) return;
  const hit = viewer.pickAt(ev);
  if (!hit) { status("Missed the part. Click on its surface."); return; }
  let res;
  try {
    const radius = S.pickMode === "patch" ? (S.patchR || null) : null;
    res = await post(`/api/projects/${encodeURIComponent(S.project.id)}/pick`, { ...hit, mode: S.pickMode, radius,
      resolution: typeof S.spec.resolution === "string" ? S.spec.resolution : "normal" });
  } catch (e) { toast(e.message, 6000); return; }
  const { role, index } = S.arm;
  const meta = { label: res.label, kind: res.kind, faces: res.faces, normal: res.normal, centre: res.centre,
    base: { region: res.region, radius: res.radius, outline: res.outline || null } };
  if (role === "fixed" || role === "load") {
    if (index != null) {
      const a = S.spec.anchors[index];
      a.region = res.region;
      if (res.kind === "hole") a.hole = true; else delete a.hole;
      S.gui.anchors[index] = { ...S.gui.anchors[index], ...meta, custom: false };
    } else {
      const n = S.spec.anchors.filter(a => a.role === role).length + 1;
      const name = uniqueName(role === "fixed" ? (res.kind === "hole" ? `bolt-${n}` : `support-${n}`) : `load-${n}`);
      S.spec.anchors.push({ name, role, ...(role === "fixed" ? { dofs: "xyz" } : {}), region: res.region,
        ...(res.kind === "hole" ? { hole: true } : {}) });
      if (role === "load") {
        meta.forces = {};
        for (const c of cases()) meta.forces[c] = { mag: 100, dir: res.kind === "face" ? "into" : "-z" };
      }
      S.gui.anchors.push(meta);
    }
  } else {
    meta.p = {};
    S.gui[role].push(meta);
  }
  toast(`${ROLE[role].noun}: ${res.label}`);
  if (index != null || !ev.shiftKey) disarm();
  save(); render();
}
function arm(role, index = null) {
  S.arm = { role, index };
  $("#viewport").classList.add("picking");
  const h = $("#hint");
  h.hidden = false;
  h.textContent = `${index != null ? "Pick again: " : ""}click a hole, face or spot for the ${ROLE[role].noun.toLowerCase()}. Hold Shift to add several. Esc stops.`;
  render();
}
function disarm() {
  S.arm = null; $("#viewport").classList.remove("picking"); $("#hint").hidden = true; render();
}

function wire() {
  document.addEventListener("click", async ev => {
    const t = ev.target.closest("button, a, [data-open]");
    if (!t) return;
    const d = t.dataset;
    if (d.go) return go(d.go);
    if (t.id === "quit") {
      try { await post("/api/quit", {}); } catch (e) { return toast(e.message, 6000); }
      document.body.innerHTML = `<main class="page"><h1>Anneal stopped</h1><p class="quiet">You can close this window. Open Anneal again from its icon.</p></main>`;
      return;
    }
    if (d.open) return openProject(d.open);
    if (d.step !== undefined) { S.open = S.open === +d.step ? -1 : +d.step; if (S.open === 5 && !S.run && S.runs.length) await selectRun(S.runs[0].id); render(); return; }
    if (d.arm) return S.arm && S.arm.role === d.arm ? disarm() : arm(d.arm);
    if (d.repick !== undefined) return arm(S.spec.anchors[+d.repick].role, +d.repick);
    if (d.del !== undefined) { S.spec.anchors.splice(+d.del, 1); S.gui.anchors.splice(+d.del, 1); save(); return render(); }
    if (d.delExtra) { const [k, i] = d.delExtra.split("."); S.gui[k].splice(+i, 1); save(); return render(); }
    if (d.caseAdd !== undefined) {
      let n = `case-${cases().length + 1}`, k = cases().length + 1; while (S.spec.loadCases[n]) n = `case-${++k}`;
      S.spec.loadCases[n] = { weight: 1 };
      S.gui.anchors.forEach((m, i) => { if (S.spec.anchors[i].role === "load") (m.forces ||= {})[n] = { mag: 0, dir: "-z" }; });
      save(); return render();
    }
    if (d.caseDel) {
      delete S.spec.loadCases[d.caseDel];
      S.gui.anchors.forEach(m => { if (m.forces) delete m.forces[d.caseDel]; });
      if (S.view.case === d.caseDel) S.view.case = null;
      save(); return render();
    }
    if (d.job) return startJob(d.job);
    if (d.stop !== undefined && S.job) { await post(`/api/jobs/${S.job.id}/cancel`, {}); toast("Stopping after this iteration…"); return; }
    if (d.reveal) return post("/api/reveal", { path: d.reveal }).catch(e => toast(e.message));
    if (d.reuse !== undefined) return reuse(S.run.spec);
    if (d.saveMat !== undefined) return saveCustomMaterial();
    if (d.procReset !== undefined) { const n = S.spec.process?.name; S.spec.process = n ? { name: n } : undefined; save(); return render(); }
    if (d.bestDir) { setProc("buildDirection", AXES[d.bestDir]); S.view.mode = "print"; save(); toast(`Build direction set to ${d.bestDir}. Optimize again to update the checks.`); return render(); }
    if (d.libNew) return libEditor(d.libNew, null);
    if (d.libEdit) return libEditor(d.libKind, d.libEdit, false);
    if (d.libCopy) return libEditor(d.libKind, d.libCopy, true);
    if (d.libDel) return libDelete(d.libKind, d.libDel);
    if (d.libSave) return libSave(d.libSave);
    if (d.libCancel !== undefined) { $("#libEdit").innerHTML = ""; return; }
    if (d.impSave !== undefined) return importSave();
    if (d.impCancel !== undefined) { IMPORT = null; $("#libImportBox").innerHTML = ""; return; }
    if (d.view) {
      const entering = d.view === "print" && S.view.mode !== "print";
      S.view.mode = d.view;
      await refreshView();
      if (entering) viewer.view("under");   // overhangs face down: show them
      return;
    }
    if (d.cam) return viewer?.view(d.cam);
    if (d.hstar) return histStar(d.hstar, t);
    if (d.hopen) return histOpen(d.hopen);
    if (d.hreuse) return histReuse(d.hreuse);
  });
  document.addEventListener("change", ev => {
    const el = ev.target;
    if (el.id === "fileInput" || el.id === "fileInput2") return upload(el.files[0]);
    if (el.id === "libImport") return importFile(el.files[0]).finally(() => { el.value = ""; });
    if (el.id === "procSel") {
      S.spec.process = el.value === "__none" ? "none" : (el.value ? { name: el.value } : undefined);
      save(); return render();
    }
    if (el.id === "procDir") {
      setProc("buildDirection", AXES[el.value]); save(); render();
      if (S.view.mode === "print") setTimeout(() => viewer.view("under"), 0);
      return;
    }
    if (el.dataset.proc) {
      const k = el.dataset.proc, v = el.tagName === "SELECT" ? el.value : (el.value === "" ? undefined : +el.value);
      setProc(k, v); save(); refreshHeads(); return refreshView();
    }
    if (el.dataset.procBool) { setProc(el.dataset.procBool, el.checked); save(); return refreshView(); }
    if (el.dataset.procVol !== undefined) {
      const p = effProcess(); const v = [...p.buildVolumeMM]; v[+el.dataset.procVol] = +el.value;
      setProc("buildVolumeMM", v); save(); return;
    }
    if (el.id === "pickMode") { S.pickMode = el.value; return render(); }
    if (el.id === "patchR") { S.patchR = el.value ? +el.value : null; return; }
    if (el.id === "caseShow" || el.id === "caseSel") { S.view.case = el.value; return render(); }
    if (el.id === "runSel") return selectRun(el.value).then(render);
    if (el.id === "ghost") { S.view.ghost = el.checked; return refreshView(); }
    if (el.dataset.rename !== undefined) {
      const i = +el.dataset.rename; S.spec.anchors[i].name = uniqueName(el.value.trim() || "anchor", i); save(); return render();
    }
    if (el.dataset.caseRename) {
      const old = el.dataset.caseRename, nu = el.value.trim().replace(/[^\w.-]/g, "-");
      if (!nu || nu === old || S.spec.loadCases[nu]) { el.value = old; return; }
      S.spec.loadCases[nu] = S.spec.loadCases[old]; delete S.spec.loadCases[old];
      S.gui.anchors.forEach(m => { if (m.forces && m.forces[old]) { m.forces[nu] = m.forces[old]; delete m.forces[old]; } });
      if (S.view.case === old) S.view.case = nu;
      save(); return render();
    }
    if (el.dataset.dof !== undefined) {
      const i = +el.dataset.dof;
      const boxes = [...document.querySelectorAll(`[data-dof="${i}"]`)];
      const v = boxes.filter(b => b.checked).map(b => b.value).join("");
      if (!v) { el.checked = true; toast("A support must hold at least one direction."); return; }
      S.spec.anchors[i].dofs = v; save(); return;
    }
    if (el.dataset.format) {
      const f = el.dataset.format, out = S.spec.output;
      out.formats = el.checked ? [...new Set([...out.formats, f])] : out.formats.filter(x => x !== f);
      if (!out.formats.includes("stl")) out.formats.unshift("stl");
      save(); if (f === "step") render(); return refreshHeads();
    }
    if (el.dataset.goal !== undefined) {
      if (el.value === "mass") S.spec.objective.minimise = "mass"; else delete S.spec.objective.minimise;
      save(); return render();
    }
    if (el.dataset.region) {
      try {
        const reg = JSON.parse(el.value);
        const [k, i] = el.dataset.region.split(".");
        if (k === "anchors") { S.spec.anchors[+i].region = reg; S.gui.anchors[+i].custom = true; }
        else { S.gui[k][+i] = { ...S.gui[k][+i], custom: true, region: reg }; }
        save(); toast("Region updated"); return render();
      } catch { toast("That is not valid JSON. The region did not change."); return; }
    }
    if (el.dataset.star !== undefined) return annotate({ star: el.checked });
    if (el.dataset.note !== undefined) return annotate({ note: el.value });
    if (el.dataset.hnote) return post("/api/history/annotate", { run_dir: el.dataset.hnote, note: el.value }).then(() => toast("Note saved"));
    if (el.dataset.hcmp !== undefined) return renderCompare();
    if (el.closest(".filters")) return loadHistory();
    onInput(el, false);
  });
  document.addEventListener("input", ev => {
    const el = ev.target;
    if (el.id === "deform") { S.view.deform = +el.value; return refreshView(); }
    if (el.id === "hText") return loadHistory();
    if (el.type === "range" && el.dataset.bind) onInput(el, true);
  });
  document.addEventListener("keydown", ev => { if (ev.key === "Escape" && S.arm) disarm(); });
  // picking: a click that did not drag
  const vp = $("#viewport");
  let down = null;
  vp.addEventListener("pointerdown", e => { down = [e.clientX, e.clientY]; });
  vp.addEventListener("dblclick", e => { const h = viewer.pickAt(e); if (h) viewer.orbitAround(h.point); });
  $("#panTool").addEventListener("click", e => {
    const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
    e.currentTarget.setAttribute("aria-pressed", on); viewer.setPanMode(on);
  });
  vp.addEventListener("pointerup", e => {
    if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 5) onPick(e);
    down = null;
  });
  // drag and drop a model anywhere
  const dz = $("#drop");
  for (const t of [document.body]) {
    t.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("over"); });
    t.addEventListener("dragleave", () => dz.classList.remove("over"));
    t.addEventListener("drop", e => { e.preventDefault(); dz.classList.remove("over"); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); });
  }
}

// ------------------------------------------------------------------ jobs
async function startJob(kind) {
  sync();
  if (kind === "run" && S.spec.objective.minimise === "mass" && !S.spec.limits.maxDisplacementMM) {
    toast("The lightest-part goal needs a maximum displacement (step 3)."); S.open = 2; return render();
  }
  try {
    S.job = await post(`/api/projects/${encodeURIComponent(S.project.id)}/${kind}`, { spec: S.spec, gui: S.gui });
    S.job.lines = S.job.lines || []; S.job.iters = S.job.iters || [];
    S.open = 4; render(); poll();
  } catch (e) { toast(e.message, 8000); }
}
async function poll() {
  const j = S.job; if (!j) return;
  try {
    const v = await api(`/api/jobs/${j.id}?since=${j.lines.length}&isince=${j.iters.length}`);
    j.lines.push(...v.lines); j.iters.push(...v.iters); j.passes = v.passes; j.state = v.state; j.error = v.error; j.result = v.result;
  } catch (e) { status(e.message); }
  if (j.state === "running") {
    if (S.open === 4) {
      const pre = $("#logPre"); const stick = pre && pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
      render();
      const p2 = $("#logPre"); if (p2 && stick) p2.scrollTop = p2.scrollHeight;
    } else refreshHeads();
    status(j.lines.at(-1) || "");
    setTimeout(poll, 1000);
    return;
  }
  status("");
  if (j.state === "done" && j.kind === "check") {
    S.check = j.result; delete S.fields.check;
    S.view.mode = "disp"; S.view.deform = 1;
    toast("Setup checked. The colours show how the original part bends.");
  }
  if (j.state === "done" && j.kind === "run") {
    const p = await api(`/api/projects/${encodeURIComponent(S.project.id)}`);
    S.runs = p.runs;
    await selectRun(j.result.run);
    S.open = 5; S.view.mode = "shape"; S.view.deform = 0;
    toast("Optimized. The result is in step 6.");
  }
  if (j.state === "error") toast("The run stopped with an error. See step 5.", 6000);
  render();
}

function drawChart() {
  const c = $("#chart"); const j = S.job;
  if (!c || !j || !j.iters.length) return;
  const dpr = devicePixelRatio || 1, W = c.clientWidth, H = c.clientHeight;
  c.width = W * dpr; c.height = H * dpr;
  const ctx = c.getContext("2d"); ctx.scale(dpr, dpr);
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const it = j.iters, n = it.length, L = 4, R = 4, T = 34, B = 6;
  const firstOf = {};
  it.forEach(r => { if (firstOf[r.pass] === undefined) firstOf[r.pass] = r.obj; });
  const objN = it.map(r => r.obj / firstOf[r.pass]);
  const lo = Math.min(...objN), hi = Math.max(...objN), span = Math.max(hi - lo, 0.05);
  const X = i => L + (W - L - R) * (n > 1 ? i / (n - 1) : 0);
  const Y = f => T + (H - T - B) * (1 - f);
  ctx.strokeStyle = css("--line"); ctx.lineWidth = 1;
  ctx.strokeRect(L - 0.5, T - 0.5, W - L - R + 1, H - T - B + 1);
  for (let i = 1; i < n; i++) if (it[i].pass !== it[i - 1].pass) { ctx.beginPath(); ctx.moveTo(X(i - 0.5), T); ctx.lineTo(X(i - 0.5), H - B); ctx.stroke(); }
  const line = (f, color, w) => {
    ctx.strokeStyle = color; ctx.lineWidth = w; ctx.beginPath();
    it.forEach((r, i) => { const y = Y(f(i)); if (i && r.pass === it[i - 1].pass) ctx.lineTo(X(i), y); else ctx.moveTo(X(i), y); });
    ctx.stroke();
  };
  line(i => (objN[i] - lo) / span * 0.9 + 0.05, css("--ink"), 1.8);
  line(i => it[i].grey, css("--hold"), 1.4);
  ctx.font = "11.5px Segoe UI, system-ui, sans-serif";
  ctx.fillStyle = css("--ink"); ctx.fillText("Objective: falls as the part gets stiffer", L, 12);
  ctx.fillStyle = css("--hold"); ctx.fillText("Grey material: falls as edges sharpen", L, 27);
}

// ------------------------------------------------------------------ results
async function selectRun(rid) {
  const base = `/api/projects/${encodeURIComponent(S.project.id)}/runs/${rid}`;
  const r = await api(base);
  r.spec = await api(base + "/spec.json").catch(() => null);
  const rows = await api(`/api/history?project=${encodeURIComponent(S.project.id)}`).catch(() => []);
  r.hist = rows.find(x => x.run_dir === r.dir) || {};
  S.run = r;
  const geom = await viewer.loadSTL(base + "/" + encodeURIComponent(r.stl));
  viewer.setResult(geom);
  for (const k of Object.keys(S.fields)) if (k.startsWith("run:")) delete S.fields[k];
}
async function annotate(change) {
  if (!S.run) return;
  await post("/api/history/annotate", { run_dir: S.run.dir, ...change });
  S.run.hist = { ...S.run.hist, ...change };
  toast(change.star !== undefined ? (change.star ? "Starred" : "Star removed") : "Note saved");
}
function reuse(spec) {
  if (!spec) return toast("This run has no saved settings.");
  for (const k of ["material", "objective", "limits", "optimizer", "loadPaths", "output", "resolution", "designSpace"]) {
    if (spec[k] !== undefined) S.spec[k] = clone(spec[k]);
  }
  const base = defaultSpec(S.project);
  for (const k of ["loadPaths", "output", "optimizer", "objective", "limits"]) S.spec[k] = { ...base[k], ...S.spec[k] };
  save(); toast("Settings taken from the run. Supports and loads did not change."); S.open = 2; render();
}

// ------------------------------------------------------------------ view
async function getField(key, url) {
  if (S.fields[key]) return S.fields[key];
  const r = await fetch(url);
  if (!r.ok) return null;
  const data = new Float32Array(await r.arrayBuffer());
  S.fields[key] = { data, cases: (r.headers.get("X-Cases") || "").split(",").filter(Boolean), case: r.headers.get("X-Case") };
  return S.fields[key];
}
async function refreshView() {
  if (!viewer || !S.project) return;
  const which = S.open === 5 && S.run ? "result" : "model";
  viewer.show(which, S.view.ghost);
  // overlays
  viewer.clearOverlay();
  const caseNow = S.view.case && cases().includes(S.view.case) ? S.view.case : cases()[0];
  S.spec.anchors.forEach((a, i) => {
    if (which === "model") viewer.region(a.region, ROLE[a.role].css);
    if (a.role === "load") {
      const m = S.gui.anchors[i] || {};
      const v = vecFor(m, caseNow);
      const c = m.centre || regionCentre(a.region);
      if (c) viewer.arrow(c, v, `${fmt(Math.hypot(...v))} N`);
    }
  });
  if (which === "model") for (const k of ["keepOut", "keep"]) (S.spec[k] || []).forEach(r => viewer.region(r, ROLE[k].css));
  // colour
  const mode = S.view.mode;
  let field = null, legend = null;
  const proc = effProcess();
  const bdir = proc ? proc.buildDirection : [0, 0, 1];
  viewer.setPlate(bdir);
  if (mode === "print") {
    viewer.resetShape(which);
    const maxDeg = proc ? proc.maxOverhangDeg : 45;
    const st = viewer.paintOverhang(which, bdir, maxDeg);
    document.querySelectorAll("[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === mode));
    const lg = $("#legend"); lg.hidden = false;
    $("#legendTitle").textContent = `Printability, building along ${axisName(bdir)}`;
    lg.querySelector(".lbar").style.display = "none"; lg.querySelector(".lv").style.display = "none";
    let rows = lg.querySelector(".rows"); if (!rows) { rows = document.createElement("div"); rows.className = "rows"; lg.appendChild(rows); }
    rows.innerHTML = `<div><span class="swatch" style="background:var(--warn)"></span>Needs support (steeper than ${fmt(maxDeg)}° from vertical)</div>
      <div><span class="swatch" style="background:#3b4b57"></span>On the build plate</div>
      <div class="quiet">${proc ? esc(proc.name) : "No process set: FDM-like 45°"}</div>`;
    status(`${which === "model" ? "Original part" : "Optimized part"}: ${fmt(st.needArea)} mm² needs support (${fmt(100 * st.needArea / st.total, 2)} % of the surface).`);
    $("#ghostTool").hidden = which !== "result"; $("#caseTool").hidden = true;
    return;
  }
  { const lg = $("#legend"); lg.querySelector(".lbar").style.display = ""; lg.querySelector(".lv").style.display = ""; const r = lg.querySelector(".rows"); if (r) r.remove(); }
  if (mode !== "shape" || S.view.deform > 0) {
    const pid = encodeURIComponent(S.project.id);
    if (which === "result") field = await getField(`run:${S.run.id}:${caseNow}`, `/api/projects/${pid}/field/optimized?run=${S.run.id}&case=${encodeURIComponent(caseNow)}`);
    else if (S.check) field = await getField(`check:${caseNow}`, `/api/projects/${pid}/field/check?case=${encodeURIComponent(caseNow)}`);
  }
  if (mode === "shape" || !field) {
    const fc = which === "model" ? [
      ...S.spec.anchors.map((a, i) => [S.gui.anchors[i]?.faces || [], new THREE.Color(cssVar(ROLE[a.role].css))]),
      ...S.gui.keepOut.map(m => [m.faces || [], new THREE.Color(cssVar("--void"))]),
      ...S.gui.keep.map(m => [m.faces || [], new THREE.Color(cssVar("--solid"))]),
    ] : [];
    viewer.paintShape(which, fc);
    if (mode !== "shape" && !field) status(which === "model" ? "Run Check setup (step 5) to colour the original part." : "No field for this run.");
  } else {
    legend = viewer.paintField(which, field.data, mode);
  }
  // deformation
  if (field && S.view.deform > 0) {
    let mx = 0; const d = field.data;
    for (let i = 0; i < d.length; i += 4) mx = Math.max(mx, Math.hypot(d[i], d[i + 1], d[i + 2]));
    const auto = mx > 0 ? 0.06 * viewer.size / mx : 0;
    viewer.deform(which, field.data, S.view.deform * auto);
    if (legend) legend.scale = S.view.deform * auto;
  } else viewer.resetShape(which);
  // toolbar
  document.querySelectorAll("[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === mode));
  $("#ghostTool").hidden = which !== "result";
  $("#ghost").checked = S.view.ghost;
  $("#deform").value = S.view.deform;
  const cs = $("#caseSel");
  cs.innerHTML = cases().map(c => `<option ${c === caseNow ? "selected" : ""}>${esc(c)}</option>`).join("");
  $("#caseTool").hidden = cases().length < 2;
  const lg = $("#legend");
  lg.hidden = !legend;
  if (legend) {
    $("#legendTitle").textContent = mode === "disp" ? "Displacement, mm" : "von Mises stress, MPa";
    $("#legendMin").textContent = "0";
    $("#legendMax").textContent = (legend.clipped ? "≥ " : "") + fmt(legend.max);
    const sc = legend.scale ? ` Shape exaggerated ${fmt(legend.scale, 2)}×.` : "";
    status(`${which === "model" ? "Original part (check)" : "Optimized part"}, case ${caseNow}.${sc}${legend.clipped ? ` Peak ${fmt(legend.peak)} MPa at a support or load point.` : ""}`);
  } else if (mode === "shape" && !S.job?.state?.startsWith("run")) status("");
}
function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function regionCentre(r) {
  if (!r) return null;
  if (r.center) return r.center;
  if (r.from) return r.from.map((v, i) => (v + r.to[i]) / 2);
  if (r.min) return r.min.map((v, i) => (v + r.max[i]) / 2);
  return null;
}

// ------------------------------------------------------------------ library
let LIB = null, IMPORT = null;
const MAT_FIELDS = [["E", "Young's modulus E, MPa", "number"], ["nu", "Poisson's ratio", "number"], ["density", "Density, g/cm³", "number"],
  ["yield", "Yield strength, MPa", "number"], ["minWallMM", "Minimum wall, mm", "number"], ["zStrengthFactor", "Layer strength factor (0.05 to 1)", "number"],
  ["Ez", "E across the layers (Ez), MPa", "number"], ["nuZ", "Poisson's ratio across layers (nuZ)", "number"],
  ["Gz", "Shear modulus between layers (Gz), MPa", "number"],
  ["process", "Process", "process"], ["note", "Note or source", "text"]];
const PROC_FIELDS = [["minWallMM", "Minimum wall, mm"], ["minHoleMM", "Minimum hole, mm"], ["maxOverhangDeg", "Steepest overhang without support, °"],
  ["zStrengthFactor", "Layer strength factor"], ["layerMM", "Layer height, mm"]];

async function loadLibrary() {
  LIB = await api("/api/library");
  S.materials = LIB.materials; S.processes = LIB.processes;
  $("#libPath").textContent = LIB.path;
  const ms = LIB.materials, ps = LIB.processes;
  $("#libMats").innerHTML = `<thead><tr><th>Name</th><th class="num">E, MPa</th><th class="num">Poisson</th><th class="num">Density, g/cm³</th>
    <th class="num">Yield, MPa</th><th class="num">Min wall, mm</th><th class="num">Layer factor</th><th>Process</th><th>Source</th><th></th><th></th></tr></thead><tbody>
    ${Object.entries(ms).map(([k, m]) => `<tr><td><b>${esc(k)}</b></td><td class="num">${fmt(m.E)}</td><td class="num">${fmt(m.nu)}</td>
      <td class="num">${fmt(m.density)}</td><td class="num">${fmt(m.yield)}</td><td class="num">${fmt(m.minWallMM ?? 1)}</td>
      <td class="num">${m.zStrengthFactor ? fmt(m.zStrengthFactor) : "–"}</td><td>${esc(m.process || "–")}</td>
      <td class="note" title="${esc(m.note || "")}">${esc(m.source || m.note || "")}</td>
      <td><span class="tag ${m.builtIn ? "" : "mine"}">${m.builtIn ? "Built in" : "Mine"}</span></td>
      <td class="acts">${m.builtIn ? `<button class="btn" data-lib-copy="${esc(k)}" data-lib-kind="material">Copy to edit</button>`
        : `<button class="btn" data-lib-edit="${esc(k)}" data-lib-kind="material">Edit</button><button class="btn" data-lib-del="${esc(k)}" data-lib-kind="material">Remove</button>`}</td></tr>`).join("")}</tbody>`;
  $("#libProcs").innerHTML = `<thead><tr><th>Name</th><th class="num">Min wall, mm</th><th class="num">Min hole, mm</th><th class="num">Overhang, °</th>
    <th>Supports</th><th>Closed cavities</th><th class="num">Layer factor</th><th>Build volume, mm</th><th>Up</th><th>Note</th><th></th><th></th></tr></thead><tbody>
    ${Object.entries(ps).map(([k, p]) => `<tr><td><b>${esc(k)}</b></td><td class="num">${fmt(p.minWallMM)}</td><td class="num">${fmt(p.minHoleMM)}</td>
      <td class="num">${fmt(p.maxOverhangDeg)}</td><td>${p.supportsAllowed === false ? "No" : "Yes"}</td><td>${esc(p.enclosedVoids)}</td>
      <td class="num">${fmt(p.zStrengthFactor)}</td><td>${(p.buildVolumeMM || []).map(v => fmt(v)).join(" × ")}</td><td>${axisName(p.buildDirection || [0, 0, 1])}</td>
      <td class="note" title="${esc(p.note || "")}">${esc(p.note || "")}</td><td><span class="tag ${p.builtIn ? "" : "mine"}">${p.builtIn ? "Built in" : "Mine"}</span></td>
      <td class="acts">${p.builtIn ? `<button class="btn" data-lib-copy="${esc(k)}" data-lib-kind="process">Copy to edit</button>`
        : `<button class="btn" data-lib-edit="${esc(k)}" data-lib-kind="process">Edit</button><button class="btn" data-lib-del="${esc(k)}" data-lib-kind="process">Remove</button>`}</td></tr>`).join("")}</tbody>`;
  const vals = v => v ? Object.entries(v).filter(([k]) => !["note", "source"].includes(k)).map(([k, x]) => `${k} ${Array.isArray(x) ? x.join("×") : x}`).join(", ") : "";
  $("#libLog").innerHTML = `<thead><tr><th>When</th><th>Change</th><th>What</th><th>Name</th><th>From</th><th>Values</th></tr></thead><tbody>
    ${LIB.log.length ? LIB.log.map(e => `<tr><td>${new Date(e.time).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}</td>
      <td>${esc(e.action)}</td><td>${esc(e.kind)}</td><td>${esc(e.name)}</td><td>${esc(e.source || "")}</td>
      <td class="note" title="${esc(vals(e.before))}">${e.action === "removed" ? `<span class="quiet">was</span> ${esc(vals(e.before))}` : esc(vals(e.after))}</td></tr>`).join("")
      : `<tr><td colspan="6" class="quiet">No changes yet. Materials you add or import are listed here with their source.</td></tr>`}</tbody>`;
}

function libEditor(kind, name, copy) {
  const isMat = kind === "material";
  const src = name ? (isMat ? LIB.materials[name] : LIB.processes[name]) : (isMat ? { nu: 0.35, process: "FDM" } : { ...LIB.processes.FDM });
  const nm = name ? (copy ? `${name} (mine)` : name) : "";
  const procOpts = v => `<select data-f="process"><option value="">None</option>${Object.keys(LIB.processes).map(k => `<option ${v === k ? "selected" : ""}>${esc(k)}</option>`).join("")}</select>`;
  const fields = isMat ? MAT_FIELDS.map(([k, t, ty]) => `<label class="row"><span>${t}</span>${ty === "process" ? procOpts(src.process)
      : `<input type="${ty === "number" ? "number" : "text"}" step="any" data-f="${k}" value="${esc(src[k] ?? "")}">`}</label>`).join("")
    : PROC_FIELDS.map(([k, t]) => `<label class="row"><span>${t}</span><input type="number" step="any" data-f="${k}" value="${src[k] ?? ""}"></label>`).join("") + `
      <label class="row"><span>Supports allowed</span><select data-f="supportsAllowed"><option value="true" ${src.supportsAllowed !== false ? "selected" : ""}>Yes</option><option value="false" ${src.supportsAllowed === false ? "selected" : ""}>No</option></select></label>
      <label class="row"><span>Closed cavities</span><select data-f="enclosedVoids">${["allow", "warn", "fail"].map(v => `<option ${src.enclosedVoids === v ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label class="row"><span>Build direction (up)</span><select data-f="buildDirection">${Object.keys(AXES).map(k => `<option ${axisName(src.buildDirection || [0, 0, 1]) === k ? "selected" : ""}>${k}</option>`).join("")}</select></label>
      <div class="row wide"><span class="quiet">Build volume x, y, z (mm)</span><div class="xyz">${[0, 1, 2].map(i => `<input type="number" data-fv="${i}" value="${(src.buildVolumeMM || [256, 256, 256])[i]}">`).join("")}</div></div>
      <label class="row wide"><span>Note</span><input type="text" data-f="note" value="${esc(src.note || "")}"></label>`;
  $("#libEdit").innerHTML = `<div class="editor" data-kind="${kind}" data-orig="${esc(name && !copy ? name : "")}">
    <h2>${name && !copy ? "Edit" : "New"} ${isMat ? "material" : "process"}</h2>
    <label class="row"><span>Name</span><input type="text" data-f="name" value="${esc(nm)}" required></label>
    <div class="grid2">${fields}</div>
    ${isMat ? `<p class="help">E, Poisson's ratio, density and yield are needed. Layer strength factor is optional; without it the process value is used.</p>` : ""}
    <div class="btns"><button class="primary" data-lib-save="${kind}">Save</button><button class="btn" data-lib-cancel>Cancel</button></div></div>`;
  $("#libEdit").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function libSave(kind) {
  const box = $("#libEdit .editor");
  const get = k => box.querySelector(`[data-f="${k}"]`)?.value ?? "";
  const name = get("name").trim();
  const values = {};
  box.querySelectorAll("[data-f]").forEach(el => { if (el.dataset.f !== "name" && el.value !== "") values[el.dataset.f] = el.value; });
  try {
    if (kind === "material") {
      await post("/api/library/materials", { name, values, rename_from: box.dataset.orig || null });
    } else {
      values.buildDirection = AXES[values.buildDirection];
      values.buildVolumeMM = [...box.querySelectorAll("[data-fv]")].map(el => +el.value);
      values.supportsAllowed = values.supportsAllowed !== "false";
      await post("/api/library/processes", { name, values });
    }
    $("#libEdit").innerHTML = "";
    toast(`Saved ${name}`);
    loadLibrary();
  } catch (e) { toast(e.message, 8000); }
}

async function libDelete(kind, name) {
  try {
    await post(`/api/library/${kind === "material" ? "materials" : "processes"}/remove`, { name });
    toast(`Removed ${name}. The change history keeps its values.`); loadLibrary();
  } catch (e) { toast(e.message, 6000); }
}

async function importFile(file) {
  if (!file) return;
  try {
    IMPORT = await api("/api/library/import", { method: "POST", headers: { "X-Filename": encodeURIComponent(file.name) }, body: file });
  } catch (e) { return toast(e.message, 8000); }
  const n = Object.keys(IMPORT.materials).length;
  const errs = IMPORT.problems.filter(p => !p.startsWith("Note:")), notes = IMPORT.problems.filter(p => p.startsWith("Note:"));
  $("#libImportBox").innerHTML = `<div class="editor" style="max-width:none"><h2>Import from ${esc(IMPORT.source)}</h2>
    <p>${n} material${n === 1 ? "" : "s"} read${errs.length ? `, ${errs.length} row${errs.length === 1 ? "" : "s"} skipped` : ""}. Check the values, then save.</p>
    ${n ? `<div class="scroll"><table class="hist"><thead><tr><th>Name</th><th class="num">E, MPa</th><th class="num">Poisson</th><th class="num">Density</th>
      <th class="num">Yield, MPa</th><th class="num">Layer factor</th><th>Process</th><th></th></tr></thead><tbody>
      ${Object.entries(IMPORT.materials).map(([k, m]) => `<tr><td><b>${esc(k)}</b></td><td class="num">${fmt(m.E)}</td><td class="num">${fmt(m.nu)}</td>
        <td class="num">${fmt(m.density)}</td><td class="num">${fmt(m.yield)}</td><td class="num">${m.zStrengthFactor ? fmt(m.zStrengthFactor) : "–"}</td>
        <td>${esc(m.process || "–")}</td><td>${IMPORT.exists.includes(k) ? `<span class="tag">replaces yours</span>` : ""}</td></tr>`).join("")}</tbody></table></div>` : ""}
    <ul class="problems">${errs.map(p => `<li class="err">${esc(p)}</li>`).join("")}${notes.map(p => `<li class="note">${esc(p.slice(6))}</li>`).join("")}</ul>
    ${n ? `${IMPORT.exists.length ? `<label class="check"><input type="checkbox" id="impOverwrite" checked><span>Replace materials with the same name</span></label>` : ""}
      <div class="btns"><button class="primary" data-imp-save>Save ${n} to my library</button><button class="btn" data-imp-cancel>Cancel</button></div>`
      : `<div class="btns"><button class="btn" data-imp-cancel>Close</button></div>`}</div>`;
}

async function importSave() {
  if (!IMPORT) return;
  const ow = $("#impOverwrite") ? $("#impOverwrite").checked : true;
  try {
    const r = await post("/api/library/import/save", { materials: IMPORT.materials, overwrite: ow, source: IMPORT.source });
    toast(`${r.added.length} added, ${r.replaced.length} replaced, ${r.skipped.length} kept`);
    IMPORT = null; $("#libImportBox").innerHTML = ""; loadLibrary();
  } catch (e) { toast(e.message, 8000); }
}

async function saveCustomMaterial() {
  const name = ($("#saveMatName").value || "").trim();
  if (!name) return toast("Type a name for the material first.");
  const values = { ...S.spec.material }; delete values.name;
  try {
    await post("/api/library/materials", { name, values, source: `project ${S.project.id}` });
    await refreshLib();
    S.spec.material = name; save(); render();
    toast(`Saved ${name} to your library. This project now uses it by name.`);
  } catch (e) { toast(e.message, 8000); }
}

// ------------------------------------------------------------------ history
let HIST = [];
async function loadHistory() {
  const q = new URLSearchParams({ text: $("#hText").value, project: $("#hProject").value, material: $("#hMaterial").value,
    ok: $("#hOk").checked ? "1" : "", star: $("#hStar").checked ? "1" : "", order: $("#hOrder").value });
  HIST = await api("/api/history?" + q);
  const st = await api("/api/state");
  const fill = (sel, vals, label) => {
    const cur = sel.value;
    sel.innerHTML = `<option value="">${label}</option>` + [...new Set(vals)].filter(Boolean).sort().map(v => `<option ${v === cur ? "selected" : ""}>${esc(v)}</option>`).join("");
  };
  const all = await api("/api/history");
  fill($("#hProject"), all.map(r => r.project), "All projects");
  fill($("#hMaterial"), all.map(r => r.material), "All materials");
  const ws = st.workspace;
  $("#histTable").innerHTML = `<thead><tr><th></th><th>Compare</th><th>Date</th><th>Project</th><th>Material</th><th>Goal</th>
    <th class="num">Original, g</th><th class="num">Optimized, g</th><th class="num">Lighter</th><th class="num">Max disp., mm</th>
    <th class="num">Safety factor</th><th class="num">Stiffness / g</th><th>Checks</th><th class="num">Minutes</th><th>Note</th><th></th></tr></thead><tbody>
    ${HIST.map(r => {
      const inWs = r.run_dir.startsWith(ws);
      return `<tr>
      <td><button class="star ${r.star ? "on" : ""}" data-hstar="${esc(r.run_dir)}" title="Star">${r.star ? "★" : "☆"}</button></td>
      <td><input type="checkbox" data-hcmp value="${esc(r.run_dir)}" aria-label="Compare"></td>
      <td>${r.created ? new Date(r.created).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : ""}</td><td>${esc(r.project)}</td><td>${esc(r.material)}</td>
      <td>${r.goal === "mass" ? "Lightest" : `Keep ${Math.round(100 * (r.volume_fraction || 0))} %`}</td>
      <td class="num">${fmt(r.original_mass_g)}</td><td class="num">${fmt(r.mass_g)}</td>
      <td class="num">${r.original_mass_g ? Math.round(100 * (1 - r.mass_g / r.original_mass_g)) + " %" : "–"}</td>
      <td class="num">${fmt(r.max_disp_mm)}${r.disp_limit_mm ? ` / ${r.disp_limit_mm}` : ""}</td>
      <td class="num">${fmt(r.safety_factor)}</td><td class="num">${r.stiffness_per_gram ? fmt(r.stiffness_per_gram) + "×" : "–"}</td>
      <td><span class="pill ${r.all_ok ? "ok" : "bad"}" style="display:inline-block;padding:0 7px">${r.all_ok ? "PASS" : "FAIL"}</span></td>
      <td class="num">${fmt((r.seconds || 0) / 60, 2)}</td>
      <td><input type="text" data-hnote="${esc(r.run_dir)}" value="${esc(r.note)}" placeholder="Add a note" class="note"></td>
      <td class="acts">${inWs ? `<button class="btn" data-hopen="${esc(r.run_dir)}">Open</button> ` : ""}
        <button class="btn" data-hreuse="${esc(r.run_dir)}" ${S.project ? "" : "disabled title='Open a project first'"}>Use settings</button>
        <button class="btn" data-reveal="${esc(r.run_dir)}">Folder</button></td></tr>`;
    }).join("") || `<tr><td colspan="16" class="quiet">No runs match. Runs appear here when they finish.</td></tr>`}</tbody>`;
  renderCompare();
}
async function histStar(dir, btn) {
  const on = !btn.classList.contains("on");
  await post("/api/history/annotate", { run_dir: dir, star: on });
  btn.classList.toggle("on", on); btn.textContent = on ? "★" : "☆";
}
async function histOpen(dir) {
  const r = HIST.find(x => x.run_dir === dir);
  await openProject(r.project);
  const rid = dir.split(/[\\/]/).pop();
  await selectRun(rid); S.open = 5; render();
}
function histReuse(dir) {
  const r = HIST.find(x => x.run_dir === dir);
  if (!S.project) return toast("Open a project first.");
  go("work"); reuse(JSON.parse(r.spec_json || "{}"));
}
function flat(o, p = "", out = {}) {
  if (o && typeof o === "object" && !Array.isArray(o)) for (const [k, v] of Object.entries(o)) flat(v, p ? `${p}.${k}` : k, out);
  else out[p] = Array.isArray(o) ? JSON.stringify(o) : o;
  return out;
}
function renderCompare() {
  const sel = [...document.querySelectorAll("[data-hcmp]:checked")].map(b => HIST.find(r => r.run_dir === b.value));
  const box = $("#compare");
  if (sel.length !== 2) { box.innerHTML = sel.length > 2 ? `<p class="quiet">Select exactly two runs to compare.</p>` : ""; return; }
  const [a, b] = sel;
  const res = [["Optimized mass, g", "mass_g"], ["Max displacement, mm", "max_disp_mm"], ["Safety factor", "safety_factor"],
    ["Stiffness per gram", "stiffness_per_gram"], ["Share of material kept", "volume_fraction"], ["Voxel size, mm", "voxel_mm"], ["Minutes", "seconds"]];
  const sa = flat(JSON.parse(a.spec_json || "{}")), sb = flat(JSON.parse(b.spec_json || "{}"));
  const keys = [...new Set([...Object.keys(sa), ...Object.keys(sb)])].filter(k => !k.startsWith("anchors") && k !== "name").sort();
  const diffs = keys.filter(k => JSON.stringify(sa[k]) !== JSON.stringify(sb[k]));
  const anchorsSame = JSON.stringify(JSON.parse(a.spec_json || "{}").anchors) === JSON.stringify(JSON.parse(b.spec_json || "{}").anchors);
  box.innerHTML = `<h2>Compare</h2><table><tr><th></th><th>${esc(a.project)}, ${new Date(a.created).toLocaleString()}</th><th>${esc(b.project)}, ${new Date(b.created).toLocaleString()}</th></tr>
    ${res.map(([t, k]) => `<tr><td>${t}</td><td>${fmt(k === "seconds" ? a[k] / 60 : a[k])}</td><td>${fmt(k === "seconds" ? b[k] / 60 : b[k])}</td></tr>`).join("")}
    <tr><th colspan="3">Settings that differ</th></tr>
    ${diffs.length ? diffs.map(k => `<tr class="diff"><td>${esc(k)}</td><td><code>${esc(sa[k] ?? "–")}</code></td><td><code>${esc(sb[k] ?? "–")}</code></td></tr>`).join("") : `<tr><td colspan="3" class="quiet">No setting differs.</td></tr>`}
    <tr><td>Supports and loads</td><td colspan="2">${anchorsSame ? "Same" : "Different"}</td></tr></table>`;
}

// ------------------------------------------------------------------ start
wire();
go("home");
window.__anneal = { S, get viewer() { return viewer; } };   // for tests and debugging
