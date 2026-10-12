"""Headless-browser smoke test of the GUI with the 0.4 options.
Usage: python research/gui_smoke.py <workdir>   (writes gui_smoke.json and screenshots)"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from playwright.sync_api import sync_playwright

wd = os.path.abspath(sys.argv[1]); os.makedirs(wd, exist_ok=True)
ws = os.path.join(wd, "workspace"); os.makedirs(ws, exist_ok=True)
port = 8799
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = dict(os.environ, PYTHONPATH=root, ANNEAL_HOME=ws)
srv = subprocess.Popen([sys.executable, "-m", "anneal", "gui", "--workspace", ws, "--port", str(port), "--no-browser"],
                       env=env, stdout=open(os.path.join(wd, "server.log"), "w"), stderr=subprocess.STDOUT)
base = f"http://127.0.0.1:{port}"
out = {"checks": []}


def check(name, ok, detail=""):
    out["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name, detail)


try:
    for _ in range(60):
        try:
            st = json.load(urllib.request.urlopen(base + "/api/state"))
            break
        except Exception:
            time.sleep(0.5)
    check("server answers /api/state", st.get("version"), st.get("version"))
    stl = open(os.path.join(root, "examples", "bracket.stl"), "rb").read()
    req = urllib.request.Request(base + "/api/projects", data=stl, method="POST",
                                 headers={"X-Filename": "bracket.stl", "Content-Type": "application/octet-stream"})
    proj = json.load(urllib.request.urlopen(req))
    pid = proj.get("id") or proj.get("project", {}).get("id")
    check("project created from bracket.stl", pid, str(pid))
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        pg = b.new_page(viewport={"width": 1400, "height": 900})
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(base)
        pg.wait_for_selector(f'[data-open="{pid}"]', timeout=20000)
        pg.click(f'[data-open="{pid}"]')
        pg.wait_for_selector(".stepHead", timeout=20000)
        heads = pg.locator(".stepHead")
        heads.nth(2).click()
        for bind in ("physics.anisotropic", "physics.buckling"):
            loc = pg.locator(f'input[data-bind="{bind}"]')
            check(f"goal step shows {bind}", loc.count() == 1)
            loc.check()
        mb = pg.locator('input[data-bind="limits.minBucklingFactor"]')
        check("goal step shows limits.minBucklingFactor", mb.count() == 1)
        mb.fill("2.5"); mb.dispatch_event("change")
        pg.select_option('select[data-bind="material"]', "__custom")
        pg.wait_for_timeout(300)
        ez = pg.locator('input[data-bind="material.Ez"]')
        check("custom material shows Ez", ez.count() == 1)
        ez.fill("2400"); ez.dispatch_event("change")
        pg.locator(".stepHead").nth(3).click()
        oh = pg.locator('input[data-bind="optimizer.overhangFilter"]')
        check("settings step shows optimizer.overhangFilter", oh.count() == 1)
        oh.check()
        pg.wait_for_timeout(1500)
        pg.screenshot(path=os.path.join(wd, "gui_settings.png"), full_page=True)
        spec = json.load(urllib.request.urlopen(f"{base}/api/projects/{pid}"))["spec"]
        check("options saved to the project spec",
              spec.get("physics", {}).get("anisotropic") is True and spec.get("physics", {}).get("buckling") is True
              and spec.get("optimizer", {}).get("overhangFilter") is True and spec["limits"].get("minBucklingFactor") == 2.5
              and spec["material"].get("Ez") == 2400,
              json.dumps({k: spec.get(k) for k in ("physics", "optimizer", "limits")}))
        pg.click("#navLibrary")
        pg.wait_for_timeout(1200)
        txt = pg.content()
        check("library page loads", "Library" in txt)
        pg.screenshot(path=os.path.join(wd, "gui_library.png"), full_page=True)
        b.close()
    check("no JavaScript errors", not errors, "; ".join(errors[:5]))
    out["specSaved"] = spec
finally:
    srv.terminate()
json.dump(out, open(os.path.join(wd, "gui_smoke.json"), "w"), indent=1)
sys.exit(0 if all(c["ok"] for c in out["checks"]) else 1)
