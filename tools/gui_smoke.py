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


def get_project(pid):
    return json.load(urllib.request.urlopen(f"{base}/api/projects/{pid}"))


def open_in_page(pg, pid, step=None):
    pg.goto(base)
    pg.wait_for_selector(f'[data-open="{pid}"]', timeout=20000)
    pg.click(f'[data-open="{pid}"]')
    pg.wait_for_selector(".stepHead", timeout=20000)
    pg.wait_for_timeout(1200)                        # openProject saves at once
    if step is not None and pg.locator(f'.stepHead[data-step="{step}"][aria-expanded="true"]').count() == 0:
        pg.locator(f'.stepHead[data-step="{step}"]').click()
        pg.wait_for_timeout(300)


def torque_checks(pg, pid, stl):
    """0.4.1 torque load (PLAN 4A, T9): torque rows, maxRotationDeg, save and reload, old projects."""
    open_in_page(pg, pid, step=1)
    rows = pg.locator("[data-torque-row]")
    check("load anchor shows a torque row per load case", rows.count() == 2, str(rows.count()))
    i = int(rows.first.get_attribute("data-torque-row"))
    name = get_project(pid)["spec"]["anchors"][i]["name"]
    check("no torques key before a torque is set", "torques" not in get_project(pid)["spec"]["anchors"][i])
    mz = pg.locator(f'input[data-torque="{i}.down.2"]')
    mz.fill("12.5"); mz.dispatch_event("change")
    pg.wait_for_timeout(1000)
    a = get_project(pid)["spec"]["anchors"][i]
    check("a torque goes into the spec as torques (N·m)", a.get("torques") == {"down": [0, 0, 12.5]}, json.dumps(a.get("torques")))
    pg.locator(".stepHead").nth(2).click()
    pg.wait_for_timeout(300)
    mr = pg.locator('input[data-bind="limits.maxRotationDeg"]')
    check("goal step shows limits.maxRotationDeg", mr.count() == 1)
    mr.fill("1.5"); mr.dispatch_event("change")
    pg.wait_for_timeout(1000)
    check("maxRotationDeg saved", get_project(pid)["spec"]["limits"].get("maxRotationDeg") == 1.5)
    open_in_page(pg, pid, step=1)                     # reload the page and open the project again
    a = get_project(pid)["spec"]["anchors"][i]
    v = pg.locator(f'input[data-torque="{i}.down.2"]').input_value()
    check("torque holds after reload", a.get("torques") == {"down": [0, 0, 12.5]} and float(v or 0) == 12.5,
          f"{json.dumps(a.get('torques'))} field={v}")
    check("the anchor keeps its name and forces", a["name"] == name and a.get("loads", {}).get("down") == [0, 0, -2000])
    pg.screenshot(path=os.path.join(wd, "gui_torque.png"), full_page=True)
    mz = pg.locator(f'input[data-torque="{i}.down.2"]')
    mz.fill(""); mz.dispatch_event("change")
    pg.wait_for_timeout(1000)
    check("an empty torque removes the torques key", "torques" not in get_project(pid)["spec"]["anchors"][i])
    # an old (0.4.0) project without torques must open and save without a torques key
    req = urllib.request.Request(base + "/api/projects", data=stl, method="POST",
                                 headers={"X-Filename": "old.stl", "Content-Type": "application/octet-stream"})
    old = json.load(urllib.request.urlopen(req))
    oid = old.get("id") or old.get("project", {}).get("id")
    ex = json.load(open(os.path.join(root, "examples", "bracket.json")))
    ospec = {k: ex[k] for k in ("anchors", "loadCases", "material", "resolution", "designSpace")}
    ospec.update(name=oid, model=old["model"], keepOut=[], keep=[],
                 objective={"minimise": "mass", "volumeFraction": 0.35, "combine": "worst"},
                 limits={"maxDisplacementMM": 0.3, "minSafetyFactor": 2},
                 output={"formats": ["stl"], "smoothing": 10, "upsample": 2})
    ogui = {"anchors": [{} if a["role"] == "fixed" else
                        {"forces": {"down": {"mag": 2000, "dir": "-z"}, "side": {"mag": 600, "dir": "+y"}}}
                        for a in ex["anchors"]], "keepOut": [], "keep": []}
    req = urllib.request.Request(f"{base}/api/projects/{oid}/save", method="POST",
                                 data=json.dumps({"spec": ospec, "gui": ogui}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)
    open_in_page(pg, oid, step=1)
    pg.wait_for_timeout(800)
    sp = get_project(oid)
    check("old project opens and saves without torques",
          not any("torques" in a for a in sp["spec"]["anchors"]) and "maxRotationDeg" not in sp["spec"]["limits"]
          and not any("torques" in m for m in sp["gui"]["anchors"]),
          json.dumps([sorted(a) for a in sp["spec"]["anchors"]]))
    check("old project keeps its anchors", sp["spec"]["anchors"] == ospec["anchors"])


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
        pg.wait_for_timeout(1500)                    # the app writes its default spec
        pr = json.load(urllib.request.urlopen(f"{base}/api/projects/{pid}"))
        ex = json.load(open(os.path.join(root, "examples", "bracket.json")))
        spec0, gui0 = pr["spec"], pr.get("gui") or {}
        spec0["anchors"], spec0["loadCases"] = ex["anchors"], ex["loadCases"]
        gui0["anchors"] = [{} if a["role"] == "fixed" else
                           {"forces": {"down": {"mag": 2000, "dir": "-z"}, "side": {"mag": 600, "dir": "+y"}}}
                           for a in ex["anchors"]]
        gui0.setdefault("keepOut", []); gui0.setdefault("keep", [])
        # server-side feature picks on the display mesh: a bolt hole and the flange's back face
        import io, numpy as np, trimesh
        dm = trimesh.load(io.BytesIO(urllib.request.urlopen(f"{base}/api/projects/{pid}/model.stl").read()), file_type="stl")
        cc = dm.triangles_center
        def api_pick(fi):
            rq = urllib.request.Request(f"{base}/api/projects/{pid}/pick", method="POST", headers={"Content-Type": "application/json"},
                                        data=json.dumps({"face": int(fi), "point": cc[fi].tolist(), "mode": "auto", "resolution": "normal"}).encode())
            return json.load(urllib.request.urlopen(rq))
        hole_f = int(np.argmin(np.abs(np.hypot(cc[:, 1] - 10, cc[:, 2] - 10) - 3.3) + 10 * (np.abs(cc[:, 0] - 5) > 4.5)))
        ph = api_pick(hole_f)
        check("clicking a bolt hole gives a hole", ph["kind"] == "hole" and abs(ph["radius"] - 3.3) < 0.05, ph["label"])
        face_f = int(np.argmax((dm.face_normals[:, 0] < -0.99) * dm.area_faces))
        pf = api_pick(face_f)
        check("clicking a face gives the face and its outline", pf["kind"] == "face" and bool(pf.get("outline")), pf["label"])
        # a keep-out pushed 5 mm out from that face, stored the way the app stores a pick
        gui0["keepOut"] = [{"label": pf["label"], "kind": "face", "faces": pf["faces"], "normal": pf["normal"],
                            "centre": pf["centre"], "base": {"region": pf["region"], "radius": None, "outline": pf["outline"]},
                            "p": {"depth": 5}}]
        req = urllib.request.Request(f"{base}/api/projects/{pid}/save", method="POST",
                                     data=json.dumps({"spec": spec0, "gui": gui0}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req)
        pg.goto(base)                                # open it again with the supports and loads
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
        nl = pg.locator('input[data-bind="physics.nonlinear"]')
        check("goal step shows physics.nonlinear", nl.count() == 1)
        nl.check()
        pg.locator('input[data-bind="gui:impact.on"]').check()
        pg.wait_for_timeout(500)
        sel = pg.locator('select[data-bind="gui:impact.anchor"]')
        check("impact editor lists the load region", sel.count() == 1 and "load-bore" in sel.inner_text())
        ms = pg.locator('input[data-bind="gui:impact.massKg"]')
        ms.fill("0.5"); ms.dispatch_event("change")
        pg.select_option('select[data-bind="material"]', "__custom")
        pg.wait_for_timeout(300)
        ez = pg.locator('input[data-bind="material.Ez"]')
        check("custom material shows Ez", ez.count() == 1)
        ez.fill("2400"); ez.dispatch_event("change")
        pg.locator(".stepHead").nth(3).click()
        check("settings step has no overhang filter option",
              pg.locator('input[data-bind="optimizer.overhangFilter"]').count() == 0)
        pg.wait_for_timeout(1500)
        pg.screenshot(path=os.path.join(wd, "gui_settings.png"), full_page=True)
        spec = json.load(urllib.request.urlopen(f"{base}/api/projects/{pid}"))["spec"]
        ko = (spec.get("keepOut") or [{}])[0]
        check("a face keep-out becomes the exact face outline (prism)", ko.get("type") == "prism" and ko.get("z1") == 5,
              json.dumps({k: ko.get(k) for k in ("type", "z0", "z1")}))
        check("options saved to the project spec",
              spec.get("physics", {}).get("anisotropic") is True and spec.get("physics", {}).get("buckling") is True
              and spec["limits"].get("minBucklingFactor") == 2.5
              and spec["material"].get("Ez") == 2400 and spec.get("physics", {}).get("nonlinear") is True
              and spec.get("impact") == {"impact": {"anchor": "load-bore", "massKg": 0.5, "dropHeightMM": 1000,
                                                    "direction": [0, 0, -1]}},
              json.dumps({k: spec.get(k) for k in ("physics", "impact", "limits")}))
        torque_checks(pg, pid, stl)
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
