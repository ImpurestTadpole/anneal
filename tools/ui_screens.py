"""Screenshots of the GUI for design review (docs/ui/screenshots/).

Usage: python tools/ui_screens.py <out_dir> <workspace_dir> [prefix]

The first call fills <workspace_dir> with the bracket example, a "Check setup" result and one short
draft optimization run. Later calls reuse it, so "before" and "after" screenshots show the same data.
Each page is shot at 1280x800 and 1920x1080, in the light and the dark theme.
Needs Playwright with Chromium (PLAYWRIGHT_BROWSERS_PATH); it does not install a browser.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

out = os.path.abspath(sys.argv[1]); os.makedirs(out, exist_ok=True)
ws = os.path.abspath(sys.argv[2]); os.makedirs(ws, exist_ok=True)
prefix = sys.argv[3] if len(sys.argv) > 3 else ""
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
port = 8797
base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PYTHONPATH=root, ANNEAL_HOME=ws)
srv = subprocess.Popen([sys.executable, "-m", "anneal", "gui", "--workspace", ws, "--port", str(port), "--no-browser"],
                       env=env, stdout=open(os.path.join(out, "server.log"), "w"), stderr=subprocess.STDOUT)


def get(path):
    return json.load(urllib.request.urlopen(base + path))


def post(path, body, raw=False, headers=None):
    data = body if raw else json.dumps(body).encode()
    h = headers or {"Content-Type": "application/json"}
    return json.load(urllib.request.urlopen(urllib.request.Request(base + path, data=data, method="POST", headers=h)))


def wait_job(job):
    while True:
        j = get(f"/api/jobs/{job['id']}")
        if j["state"] != "running":
            return j
        time.sleep(1)


def prepare():
    st = get("/api/state")
    if any(p["id"] == "bracket" and p.get("runs") for p in st["projects"]):
        return
    stl = open(os.path.join(root, "examples", "bracket.stl"), "rb").read()
    p = post("/api/projects", stl, raw=True, headers={"X-Filename": "bracket.stl", "Content-Type": "application/octet-stream"})
    ex = json.load(open(os.path.join(root, "examples", "bracket.json")))
    spec = {"name": p["id"], "model": p["model"], "designSpace": "model", "material": "PLA-FDM", "resolution": "draft",
            "anchors": ex["anchors"], "keepOut": [], "keep": [], "loadCases": ex["loadCases"],
            "objective": {"volumeFraction": 0.35, "combine": "worst"},
            "optimizer": {"iterations": 25, "massPasses": 1, "penalty": 3, "move": 0.2, "sharpness": 4},
            "limits": {"maxDisplacementMM": 0.6, "minSafetyFactor": 2},
            "loadPaths": {"guard": True, "margin": 0.1, "maxDrop": 0.15, "repair": True},
            "output": {"formats": ["stl"], "edges": "smooth", "detail": "coarse", "isoLevel": "auto", "report": False,
                       "exactFeatures": False}}
    gui = {"anchors": [{} if a["role"] == "fixed" else
                       {"label": "Hole Ø10.0 mm", "forces": {"down": {"mag": 2000, "dir": "-z"}, "side": {"mag": 600, "dir": "+y"}}}
                       for a in ex["anchors"]], "keepOut": [], "keep": []}
    post(f"/api/projects/{p['id']}/save", {"spec": spec, "gui": gui})
    print("check:", wait_job(post(f"/api/projects/{p['id']}/check", {"spec": spec, "gui": gui}))["state"])
    print("run:", wait_job(post(f"/api/projects/{p['id']}/run", {"spec": spec, "gui": gui}))["state"])


def open_project(pg):
    pg.goto(base)
    pg.wait_for_selector('[data-open="bracket"]', timeout=20000)
    pg.click('[data-open="bracket"]')
    pg.wait_for_selector(".stepHead", timeout=20000)
    pg.wait_for_timeout(1500)


def step(pg, i):
    h = pg.locator(".stepHead").nth(i)
    if h.get_attribute("aria-expanded") != "true":
        h.click()
    pg.wait_for_timeout(1500)


try:
    for _ in range(60):
        try:
            get("/api/state"); break
        except Exception:
            time.sleep(0.5)
    prepare()
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        for scheme in ("light", "dark"):
            for (w, h) in ((1280, 800), (1920, 1080)):
                ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, device_scale_factor=1)
                pg = ctx.new_page()
                tag = f"{w}x{h}-{scheme}"
                shot = lambda name: pg.screenshot(path=os.path.join(out, f"{prefix}{name}-{tag}.png"))
                pg.goto(base); pg.wait_for_selector('[data-open="bracket"]', timeout=20000); pg.wait_for_timeout(600)
                shot("home")
                open_project(pg)
                step(pg, 1)
                shot("setup")
                step(pg, 4)
                shot("run")
                step(pg, 5)
                pg.wait_for_timeout(1500)
                pg.evaluate("document.querySelector('#tools [data-view=stress]').click()"); pg.wait_for_timeout(2000)
                shot("result")
                pg.click("#navHistory"); pg.wait_for_timeout(1200)
                shot("history")
                pg.click("#navLibrary"); pg.wait_for_timeout(1200)
                shot("library")
                ctx.close()
        b.close()
finally:
    srv.terminate()
