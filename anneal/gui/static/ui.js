// Presentation layer of the workbench: theme, display panel, orthographic camera, keyboard keys,
// the status line and the state lamps of the notebook blocks. It only reads the app state
// (window.__anneal, set by app.js) and clicks existing controls; it never changes the spec.
const $ = s => document.querySelector(s);
const app = () => window.__anneal || {};
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

// ---------------------------------------------------------------- theme
function effectiveTheme() {
  const t = document.documentElement.dataset.theme;
  if (t === "light" || t === "dark") return t;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function repaint() {
  const v = app().viewer;
  if (v && v.applyTheme) v.applyTheme();
  $("#tools [data-view].on")?.click();          // the app paints the part again with the new colours
}
function toggleTheme() {
  const next = effectiveTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  store.set("anneal.theme", next);
  repaint();
}
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => { if (!document.documentElement.dataset.theme) repaint(); });

// ---------------------------------------------------------------- display panel and camera
function setInspector(show) {
  $("#workbench").classList.toggle("noInspector", !show);
  store.set("anneal.inspector", show ? "1" : "0");
}
function toggleOrtho() {
  const v = app().viewer; if (!v || !v.setOrtho) return;
  v.setOrtho(!v.isOrtho);
  $("#orthoTool").setAttribute("aria-pressed", String(v.isOrtho));
}
const cam = name => $(`#tools [data-cam="${name}"], #viewcube [data-cam="${name}"]`)?.click();

// ---------------------------------------------------------------- keys
const onWorkbench = () => !$("#workbench").hidden;
const KEYS = {
  f: () => onWorkbench() && cam("fit"),
  i: () => onWorkbench() && cam("iso"),
  t: () => onWorkbench() && cam("top"),
  v: () => onWorkbench() && cam("front"),
  r: () => onWorkbench() && cam("right"),
  o: () => onWorkbench() && toggleOrtho(),
  m: () => onWorkbench() && $("#panTool").click(),
  p: () => onWorkbench() && setInspector($("#workbench").classList.contains("noInspector")),
  d: () => toggleTheme(),
};
document.addEventListener("keydown", ev => {
  if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.repeat) return;
  const el = ev.target;
  if (el.closest && el.closest("input, select, textarea, [contenteditable]")) return;
  const k = ev.key.toLowerCase();
  if (/^[1-6]$/.test(k) && onWorkbench()) {
    const h = document.querySelectorAll(".stepHead")[+k - 1];
    if (h && h.getAttribute("aria-expanded") !== "true") h.click();
    ev.preventDefault(); return;
  }
  if (KEYS[k]) { KEYS[k](); ev.preventDefault(); }
});
document.addEventListener("click", ev => {
  const b = ev.target.closest("button"); if (!b) return;
  if (b.dataset.key && KEYS[b.dataset.key]) return KEYS[b.dataset.key]();
  if (b.id === "themeTool") return toggleTheme();
  if (b.id === "orthoTool") return toggleOrtho();
  if (b.id === "inspClose") return setInspector(false);
});

// ---------------------------------------------------------------- block lamps and status line
function lamps() {
  const { S } = app(); if (!S || !S.project) return;
  const steps = document.querySelectorAll("#panel .step");
  if (steps.length < 6) return;
  const j = S.job, running = j && j.state === "running";
  steps[4].classList.toggle("is-running", !!running);
  steps[4].classList.toggle("is-error", !!j && j.state === "error");
  const checks = S.run?.record?.checks || [];
  steps[5].classList.toggle("is-warn", !!S.run && checks.some(c => !c.ok || c.warn));
}
new MutationObserver(lamps).observe($("#panel"), { childList: true });

function statusLine() {
  const { S } = app(); if (!S) return;
  const line = $("#statusline"), j = S.job;
  const running = j && j.state === "running";
  line.classList.toggle("busy", !!running);
  line.classList.toggle("error", !!j && j.state === "error");
  $("#sysState").textContent = running ? (j.kind === "check" ? "CHECKING" : "RUNNING")
    : j && j.state === "error" ? "ERROR" : j && j.state === "cancelled" ? "STOPPED" : "READY";
  const meter = $("#meter");
  if (running && j.kind === "run" && S.spec) {
    const last = (j.iters || []).at(-1), n = S.spec.optimizer?.iterations || 1;
    const pass = (j.passes || []).length || 1;
    $("#meterText").textContent = `PASS ${pass} · IT ${last ? last.iter : 0}/${n}`;
    $("#meterBar").style.width = `${Math.min(100, 100 * (last ? last.iter : 0) / n)}%`;
    meter.hidden = false;
  } else meter.hidden = true;
  if (S.version) $("#ver").textContent = `ANNEAL ${S.version}`;
  $("#status").style.visibility = onWorkbench() ? "" : "hidden";   // viewport messages belong to the workbench
  lamps();
}
setInterval(statusLine, 500);

// ---------------------------------------------------------------- start
if (store.get("anneal.inspector") === "0") setInspector(false);
statusLine();
