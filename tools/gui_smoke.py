"""Headless-browser smoke test of the GUI with the 0.4 options.
Usage: python research/gui_smoke.py <workdir>   (writes gui_smoke.json and screenshots)"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from playwright.sync_api import sync_playwright

wd = os.path.abspath(sys.argv[1]); os.makedirs(wd, exist_ok=True)
ws = os.path.join(wd, "workspace"); os.makedirs(ws, exist_ok=True)
with socket.socket() as _s:                         # a free port: other worktrees may run this test at the same time
    _s.bind(("127.0.0.1", 0)); port = _s.getsockname()[1]
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
        for attempt in range(3):                      # a loaded machine can stall one click; retry it
            try:
                pg.locator(f'.stepHead[data-step="{step}"]').click(timeout=15000)
                break
            except Exception:
                if attempt == 2:
                    raise
                pg.wait_for_timeout(1000)
        pg.wait_for_timeout(300)


def wait_project(pid, ok, timeout=8.0):
    """Poll the saved project until ok(project) is true (the app saves after a short delay)."""
    t = time.time()
    while True:
        p = get_project(pid)
        if ok(p) or time.time() - t > timeout:
            return p
        time.sleep(0.2)


def goal_smoke(pg, pid):
    """0.4.2 goals: percent of the original part, saved in spec.goals; an empty field removes the key."""
    open_in_page(pg, pid, step=2)
    m = pg.locator('input[data-bind="goals.massPct"]')
    check("goal step shows goals.massPct, displacementPct, strainPct",
          m.count() == 1 and pg.locator('input[data-bind="goals.displacementPct"]').count() == 1
          and pg.locator('input[data-bind="goals.strainPct"]').count() == 1)
    m.fill("60"); m.dispatch_event("change")
    sp = wait_project(pid, lambda p: (p["spec"].get("goals") or {}).get("massPct") == 60)["spec"]
    check("goals.massPct saved", (sp.get("goals") or {}).get("massPct") == 60, json.dumps(sp.get("goals")))
    open_in_page(pg, pid, step=2)
    m = pg.locator('input[data-bind="goals.massPct"]')
    check("goals.massPct holds after reload", m.input_value() == "60")
    m.fill(""); m.dispatch_event("change")
    sp = wait_project(pid, lambda p: not (p["spec"].get("goals") or {}).get("massPct"))["spec"]
    check("an empty goal removes it", not (sp.get("goals") or {}).get("massPct"), json.dumps(sp.get("goals")))
    open_in_page(pg, pid, step=0)                     # material change: remove / add / add and remove
    want = {"add": lambda d: isinstance(d, dict) and d.get("keepModel") is True,
            "both": lambda d: isinstance(d, dict) and not d.get("keepModel"),
            "remove": lambda d: d == "model"}
    for v, ok in want.items():
        pg.select_option("#matChange", v)
        d = wait_project(pid, lambda p: ok(p["spec"].get("designSpace")))["spec"].get("designSpace")
        check(f"material change '{v}' sets the design space", ok(d), json.dumps(d))


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
    a = wait_project(pid, lambda p: p["spec"]["anchors"][i].get("torques"))["spec"]["anchors"][i]
    check("a torque goes into the spec as torques (N·m)", a.get("torques") == {"down": [0, 0, 12.5]}, json.dumps(a.get("torques")))
    pg.locator(".stepHead").nth(2).click()
    pg.wait_for_timeout(300)
    mr = pg.locator('input[data-bind="limits.maxRotationDeg"]')
    check("goal step shows limits.maxRotationDeg", mr.count() == 1)
    mr.fill("1.5"); mr.dispatch_event("change")
    lim = wait_project(pid, lambda p: p["spec"]["limits"].get("maxRotationDeg") is not None)["spec"]["limits"]
    check("maxRotationDeg saved", lim.get("maxRotationDeg") == 1.5, json.dumps(lim))
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
    return oid, ospec, ogui


def thermal_checks(pg, pid, oid, ospec, ogui):
    """0.4.2 temperature (PLAN 4B, H12): case temperatures, thermal-only case, displacement rule, material alpha."""
    open_in_page(pg, pid, step=2)
    th = lambda p: p["spec"].get("thermal")
    check("goal step shows the Temperature fieldset", pg.locator("#tempFields").count() == 1)
    check("no thermal key before a temperature is set", th(get_project(pid)) is None)
    rows = pg.locator("input[data-temp-case]")
    check("a temperature field per load case", rows.count() == 2, str(rows.count()))
    f = pg.locator('input[data-temp-case="down"]')
    f.fill("60"); f.dispatch_event("change")
    t = th(wait_project(pid, lambda p: (th(p) or {}).get("cases", {}).get("down") == 60))
    check("a case temperature goes into thermal.cases", t == {"referenceTempC": 20, "cases": {"down": 60}}, json.dumps(t))
    r = pg.locator("#tempRef")
    r.fill("23"); r.dispatch_event("change")
    t = th(wait_project(pid, lambda p: (th(p) or {}).get("referenceTempC") == 23))
    check("the reference temperature is saved", (t or {}).get("referenceTempC") == 23, json.dumps(t))
    pg.locator("#tempAddOnly").click()
    pg.wait_for_selector("[data-thermal-only] input[data-temp-case]", timeout=10000)
    name = pg.locator("[data-thermal-only]").first.get_attribute("data-temp-row")
    f = pg.locator(f'[data-thermal-only] input[data-temp-case="{name}"]')
    f.fill("-20"); f.dispatch_event("change")
    sp = wait_project(pid, lambda p: (th(p) or {}).get("cases", {}).get(name) == -20)["spec"]
    check("a thermal-only case goes into thermal.cases, not loadCases",
          sp.get("thermal", {}).get("cases") == {"down": 60, name: -20} and name not in sp["loadCases"],
          json.dumps({"thermal": sp.get("thermal"), "loadCases": sorted(sp["loadCases"])}))
    pg.locator("#dispInclThermal").check()
    lim = wait_project(pid, lambda p: "displacementIncludesThermal" in p["spec"]["limits"])["spec"]["limits"]
    check("limits.displacementIncludesThermal saved", lim.get("displacementIncludesThermal") is True, json.dumps(lim))
    # custom material: alpha typed in ppm/K is stored in 1/K; service limit; derating table
    if pg.locator('input[data-mat-alpha="alpha"]').count() == 0:
        pg.select_option('select[data-bind="material"]', "__custom")
        pg.wait_for_selector('input[data-mat-alpha="alpha"]', timeout=10000)
    a = pg.locator('input[data-mat-alpha="alpha"]')
    a.fill("68"); a.dispatch_event("change")
    m = wait_project(pid, lambda p: isinstance(p["spec"]["material"], dict) and p["spec"]["material"].get("alpha"))["spec"]["material"]
    check("custom material alpha in ppm/K is saved in 1/K", abs((m.get("alpha") or 0) - 68e-6) < 1e-15, str(m.get("alpha")))
    a = pg.locator('input[data-mat-alpha="alphaZ"]')
    a.fill("9.5e-5"); a.dispatch_event("change")
    ms = pg.locator('input[data-bind="material.maxServiceTempC"]')
    ms.fill("55"); ms.dispatch_event("change")
    dr = pg.locator("input[data-mat-derating]")
    dr.fill("[[20, 1, 1], [60, 0.8, 0.7]]"); dr.dispatch_event("change")
    m = wait_project(pid, lambda p: p["spec"]["material"].get("tempDerating") and p["spec"]["material"].get("maxServiceTempC"))["spec"]["material"]
    check("custom material alphaZ, maxServiceTempC and tempDerating saved",
          m.get("alphaZ") == 9.5e-5 and m.get("maxServiceTempC") == 55 and m.get("tempDerating") == [[20, 1, 1], [60, 0.8, 0.7]],
          json.dumps({k: m.get(k) for k in ("alphaZ", "maxServiceTempC", "tempDerating")}))
    pg.wait_for_timeout(500)
    check("a case above the service limit shows a message", "higher service temperature" in pg.locator("#tempFields").inner_text())
    pg.locator("#tempFields").scroll_into_view_if_needed()
    pg.screenshot(path=os.path.join(wd, "gui_thermal.png"), full_page=True)
    # reload: the spec and the fields hold
    open_in_page(pg, pid, step=2)
    sp = wait_project(pid, lambda p: True)["spec"]
    check("thermal holds after reload", sp.get("thermal") == {"referenceTempC": 23, "cases": {"down": 60, name: -20}}
          and sp["limits"].get("displacementIncludesThermal") is True, json.dumps(sp.get("thermal")))
    v = pg.locator('input[data-temp-case="down"]').input_value()
    vo = pg.locator(f'[data-thermal-only] input[data-temp-case="{name}"]').input_value()
    check("temperature fields hold after reload", float(v or 0) == 60 and float(vo or 0) == -20
          and pg.locator("#dispInclThermal").is_checked() and pg.locator("#tempRef").input_value() == "23", f"{v} {vo}")
    # clear everything: the keys go away
    pg.locator("#dispInclThermal").uncheck()
    pg.locator(f'[data-temp-del="{name}"]').click()
    pg.wait_for_selector("[data-thermal-only]", state="detached", timeout=10000)
    f = pg.locator('input[data-temp-case="down"]')
    f.fill(""); f.dispatch_event("change")
    sp = wait_project(pid, lambda p: "thermal" not in p["spec"] and "displacementIncludesThermal" not in p["spec"]["limits"])["spec"]
    check("empty temperatures remove the thermal key", "thermal" not in sp and "displacementIncludesThermal" not in sp["limits"],
          json.dumps({"thermal": sp.get("thermal"), "limits": sp["limits"]}))
    # an old project (no thermal) opens on the goal step and saves without thermal
    open_in_page(pg, oid, step=2)
    pg.wait_for_timeout(800)
    sp = get_project(oid)
    check("old project opens and saves without thermal",
          "thermal" not in sp["spec"] and "displacementIncludesThermal" not in sp["spec"]["limits"] and "thermal" not in sp["gui"]
          and pg.locator("#tempFields").count() == 1, json.dumps(sorted(sp["spec"])))
    # a spec with a typed thermal block (command line) fills the fields and saves unchanged
    typed = {"referenceTempC": 20, "cases": {"down": 40, "cold": -10}}
    req = urllib.request.Request(f"{base}/api/projects/{oid}/save", method="POST",
                                 data=json.dumps({"spec": dict(ospec, thermal=typed), "gui": ogui}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)
    open_in_page(pg, oid, step=2)
    pg.wait_for_timeout(800)
    sp = get_project(oid)["spec"]
    check("a typed thermal block fills the fields and saves unchanged",
          sp.get("thermal") == typed and pg.locator('input[data-temp-case="down"]').input_value() == "40"
          and pg.locator('[data-thermal-only] input[data-temp-case="cold"]').input_value() == "-10", json.dumps(sp.get("thermal")))


def thermal_result_checks(pg, oid, ospec):
    """0.4.2 Result step: a synthetic run record with the expected back-end keys
    (results.optimized.cases[case].mechanicalDisplacementMM / thermalDisplacementMM). It tests only the GUI."""
    rd = os.path.join(ws, oid, "runs", "20260101-000000")
    os.makedirs(rd, exist_ok=True)
    thermal = {"referenceTempC": 20, "cases": {"down": 60, "cold": -20}}
    cs = {"down": {"complianceNmm": 10.0, "maxDisplacementMM": 0.25, "mechanicalDisplacementMM": 0.21, "thermalDisplacementMM": 0.08},
          "side": {"complianceNmm": 4.0, "maxDisplacementMM": 0.12},
          "cold": {"complianceNmm": 0.0, "maxDisplacementMM": 0.05, "mechanicalDisplacementMM": 0.0, "thermalDisplacementMM": 0.05}}
    rec = {"createdUTC": "2026-01-01T00:00:00Z", "checks": [], "passes": [{"volumeFraction": 0.35, "massG": 20.0, "maxDisplacementMM": 0.25}],
           "totalSeconds": 60, "results": {"original": None, "optimized": {"massG": 20.0, "maxDisplacementMM": 0.25, "safetyFactor": 3.0,
                                                                        "peakStressMPa": 10.0, "cases": cs}}}
    json.dump(rec, open(os.path.join(rd, "run.json"), "w"))
    json.dump(dict(ospec, thermal=thermal), open(os.path.join(rd, "spec.json"), "w"))
    with open(os.path.join(rd, f"{oid}-optimized.stl"), "wb") as fh:
        fh.write(urllib.request.urlopen(f"{base}/api/projects/{oid}/model.stl").read())
    n0 = len(errors)
    open_in_page(pg, oid, step=5)
    pg.wait_for_selector("#thermalBlock", timeout=20000)
    cell = lambda c: [t.strip() for t in pg.locator(f'#thermalBlock tr[data-thermal-case="{c}"] td').all_inner_texts()]
    check("result step shows mechanical and thermal displacement per case",
          cell("down") == ["down", "60 (+40)", "0.21", "0.08"] and cell("cold") == ["cold", "-20 (-40)", "0", "0.05"]
          and cell("side") == ["side", "20", "0.12", "0"], json.dumps([cell("down"), cell("cold"), cell("side")]))
    pg.locator("#thermalBlock").scroll_into_view_if_needed()
    pg.screenshot(path=os.path.join(wd, "gui_thermal_result.png"), full_page=True)
    errors[n0:] = [e for e in errors[n0:] if "Failed to load resource" not in e]   # the synthetic run has no field files


def library_thermal_checks(pg):
    """0.4.2 library editor: alpha (ppm/K or 1/K), alphaZ, maxServiceTempC, tempDerating."""
    pg.click("#navLibrary")
    pg.wait_for_selector("#libMats tbody tr", timeout=20000)    # the library is loaded
    pg.click('[data-lib-new="material"]')
    ed = pg.locator("#libEdit .editor")
    ed.wait_for(timeout=10000)
    check("library editor has alpha, alphaZ, maxServiceTempC and tempDerating fields",
          all(ed.locator(f'[data-f="{k}"]').count() == 1 for k in ("alpha", "alphaZ", "maxServiceTempC", "tempDerating")))
    for k, v in (("name", "Smoke-Al"), ("E", "70000"), ("nu", "0.33"), ("density", "2.7"), ("yield", "200"),
                 ("alpha", "23 ppm/K"), ("maxServiceTempC", "150"), ("tempDerating", "[[20, 1, 1], [150, 0.9, 0.8]]")):
        ed.locator(f'[data-f="{k}"]').fill(v)
    pg.click('[data-lib-save="material"]')
    t = time.time()
    while time.time() - t < 10:
        lib = json.load(urllib.request.urlopen(base + "/api/library"))
        if "Smoke-Al" in lib["materials"]:
            break
        time.sleep(0.3)
    m = lib["materials"].get("Smoke-Al")
    check("library editor saves the material", m is not None)
    sys.path.insert(0, root)
    from anneal import materials as M
    if "alpha" not in M.MAT_KEYS:
        print("SKIP library material keeps alpha: the back end (materials.MAT_KEYS) has no alpha yet")
        return
    check("library material keeps alpha in 1/K, maxServiceTempC and tempDerating",
          m and abs(m.get("alpha", 0) - 23e-6) < 1e-15 and m.get("maxServiceTempC") == 150
          and m.get("tempDerating") == [[20, 1, 1], [150, 0.9, 0.8]], json.dumps(m))


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
        oid, ospec, ogui = torque_checks(pg, pid, stl)
        thermal_checks(pg, pid, oid, ospec, ogui)
        goal_smoke(pg, pid)
        thermal_result_checks(pg, oid, ospec)
        library_thermal_checks(pg)
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
