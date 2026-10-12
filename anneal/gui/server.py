"""Local web GUI for Anneal: python -m anneal gui

A small standard-library HTTP server bound to 127.0.0.1. It serves one page (static/)
and a JSON API. Work lives in a workspace folder, one subfolder per project:

    <workspace>/<project>/model.<ext>        the model you opened
    <workspace>/<project>/display.stl        the mesh the viewer draws (same face order as picking)
    <workspace>/<project>/<project>.anneal.json   the spec (also usable from the command line)
    <workspace>/<project>/gui.json           viewer state (picked faces, labels)
    <workspace>/<project>/check/             last "Check setup" result
    <workspace>/<project>/runs/<time>/       each optimization run
"""
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

import numpy as np
import trimesh

from .. import __version__
from .. import db
from ..materials import MATERIALS
from ..kernel import FASTENERS

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MODEL_EXT = (".stl", ".obj", ".ply", ".off", ".3mf", ".glb", ".step", ".stp")
RES_TARGET = {"draft": 15000, "normal": 40000, "fine": 90000}
ITER_RE = re.compile(r"^\s*it\s+(\d+)\s+p\s+([\d.]+)\s+b\s+([\d.]+)\s+obj\s+([\d.eE+-]+)\s+vol\s+([\d.]+)"
                     r"\s+change\s+([\d.]+)\s+grey\s+([\d.]+)")
PASS_RE = re.compile(r"Optimizing at volume fraction ([\d.]+)")


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, kind, project, fn):
        self.id = f"{kind}-{int(time.time() * 1000)}"
        self.kind, self.project = kind, project
        self.state, self.error, self.result = "running", None, None
        self.lines, self.iters, self.passes = [], [], []
        self.cancel = False
        self.started = time.time()
        self.thread = threading.Thread(target=self._run, args=(fn,), daemon=True)
        self.thread.start()

    def log(self, *parts):
        if self.cancel:
            raise Cancelled()
        line = " ".join(str(p) for p in parts)
        self.lines.append(line)
        m = PASS_RE.search(line)
        if m:
            self.passes.append({"volumeFraction": float(m.group(1)), "startIter": len(self.iters)})
        m = ITER_RE.match(line)
        if m:
            it, p, b, obj, vol, ch, grey = m.groups()
            self.iters.append({"pass": max(len(self.passes) - 1, 0), "iter": int(it), "p": float(p),
                               "beta": float(b), "obj": float(obj), "vol": float(vol),
                               "change": float(ch), "grey": float(grey)})

    def _run(self, fn):
        try:
            self.result = fn(self.log)
            self.state = "done"
        except Cancelled:
            self.state = "cancelled"
            self.lines.append("Stopped.")
        except Exception as e:  # shown to the user with the fix the core already wrote
            self.state = "error"
            self.error = str(e)
            self.lines.append("ERROR: " + str(e))
            self.lines.append(traceback.format_exc(limit=3))

    def view(self, since=0, isince=0):
        return {"id": self.id, "kind": self.kind, "project": self.project, "state": self.state,
                "error": self.error, "result": self.result, "lines": self.lines[since:],
                "nLines": len(self.lines), "iters": self.iters[isince:], "nIters": len(self.iters),
                "passes": self.passes, "seconds": time.time() - self.started}


class App:
    def __init__(self, workspace):
        self.ws = os.path.abspath(workspace)
        os.makedirs(self.ws, exist_ok=True)
        self.db = os.path.join(self.ws, "anneal.db")
        threading.Thread(target=lambda: db.index_workspace(self.ws, self.db), daemon=True).start()
        self.jobs = {}
        self.stop = threading.Event()
        self.meshes = {}
        self.lock = threading.Lock()

    # ------------------------------------------------------------ projects
    def pdir(self, pid):
        pid = re.sub(r"[^A-Za-z0-9._ -]", "", pid or "")
        d = os.path.join(self.ws, pid)
        if not pid or not os.path.isdir(d) or os.path.dirname(os.path.abspath(d)) != self.ws:
            raise FileNotFoundError(f"No project named '{pid}' in {self.ws}.")
        return d

    def mesh(self, pid, path=None):
        path = path or os.path.join(self.pdir(pid), "display.stl")
        key = (path, os.path.getmtime(path))
        if key not in self.meshes:
            self.meshes[key] = trimesh.load(path, force="mesh")
        return self.meshes[key]

    def new_project(self, filename, data):
        from ..geometry import load_mesh
        base, ext = os.path.splitext(os.path.basename(filename))
        ext = ext.lower()
        if ext not in MODEL_EXT:
            raise ValueError(f"Anneal reads {', '.join(MODEL_EXT)} files, not '{ext}'.")
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.") or "part"
        pid, k = stem, 2
        while os.path.exists(os.path.join(self.ws, pid)):
            pid, k = f"{stem}-{k}", k + 1
        d = os.path.join(self.ws, pid)
        os.makedirs(d)
        model = os.path.join(d, stem + ext)
        with open(model, "wb") as fh:
            fh.write(data)
        notes = []
        try:
            mesh = load_mesh(model, log=lambda *a: notes.append(" ".join(map(str, a))))
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        mesh.export(os.path.join(d, "display.stl"))
        info = {"model": os.path.basename(model), "notes": notes}
        with open(os.path.join(d, "project.json"), "w", encoding="utf-8") as fh:
            json.dump(info, fh, indent=2)
        return self.project(pid)

    def project(self, pid):
        d = self.pdir(pid)
        with open(os.path.join(d, "project.json"), encoding="utf-8") as fh:
            info = json.load(fh)
        m = self.mesh(pid)
        vol = abs(float(m.volume))
        out = {"id": pid, "name": pid, "model": info["model"], "notes": info.get("notes", []),
               "faces": int(len(m.faces)), "watertight": bool(m.is_watertight),
               "bounds": m.bounds.tolist(), "volumeCM3": vol / 1000,
               "voxelMM": {k: round((vol / n) ** (1 / 3), 3) for k, n in RES_TARGET.items()},
               "spec": None, "gui": None, "runs": self.runs(pid), "hasCheck": os.path.isfile(os.path.join(d, "check", "summary.json"))}
        sp = os.path.join(d, f"{pid}.anneal.json")
        if os.path.isfile(sp):
            with open(sp, encoding="utf-8") as fh:
                out["spec"] = json.load(fh)
        gp = os.path.join(d, "gui.json")
        if os.path.isfile(gp):
            with open(gp, encoding="utf-8") as fh:
                out["gui"] = json.load(fh)
        return out

    def projects(self):
        out = []
        for name in sorted(os.listdir(self.ws)):
            d = os.path.join(self.ws, name)
            if os.path.isfile(os.path.join(d, "project.json")):
                runs = self.runs(name)
                out.append({"id": name, "runs": len(runs), "modified": os.path.getmtime(d),
                            "best": runs[0]["massG"] if runs else None})
        out.sort(key=lambda p: -p["modified"])
        return out

    def runs(self, pid):
        rd = os.path.join(self.ws, pid, "runs")
        out = []
        if not os.path.isdir(rd):
            return out
        for r in sorted(os.listdir(rd), reverse=True):
            rec = os.path.join(rd, r, "run.json")
            if not os.path.isfile(rec):
                continue
            with open(rec, encoding="utf-8") as fh:
                j = json.load(fh)
            opt = j["results"]["optimized"]
            out.append({"id": r, "massG": opt["massG"], "maxDisplacementMM": opt["maxDisplacementMM"],
                        "safetyFactor": opt["safetyFactor"], "ok": all(c["ok"] for c in j["checks"]),
                        "created": j.get("createdUTC")})
        return out

    def save(self, pid, body):
        d = self.pdir(pid)
        spec = body.get("spec")
        if spec is not None:
            spec["name"] = pid
            with open(os.path.join(d, f"{pid}.anneal.json"), "w", encoding="utf-8") as fh:
                json.dump(spec, fh, indent=2)
        if body.get("gui") is not None:
            with open(os.path.join(d, "gui.json"), "w", encoding="utf-8") as fh:
                json.dump(body["gui"], fh)
        return {"saved": True}

    def pick(self, pid, body):
        from ..pick import pick
        m = self.mesh(pid)
        vol = abs(float(m.volume))
        h = (vol / RES_TARGET.get(body.get("resolution", "normal"), 40000)) ** (1 / 3)
        return pick(m, body["face"], body["point"], pad=0.75 * h, mode=body.get("mode", "auto"),
                    patch_r=body.get("radius"))

    # ---------------------------------------------------------------- jobs
    def start(self, kind, pid, body):
        with self.lock:
            busy = [j for j in self.jobs.values() if j.state == "running"]
            if busy:
                raise RuntimeError("A run is already going. Wait for it to finish, or stop it first.")
            d = self.pdir(pid)
            self.save(pid, body)
            spec_path = os.path.join(d, f"{pid}.anneal.json")
            if kind == "check":
                fn = lambda log: self._check(pid, d, spec_path, log)
            else:
                fn = lambda log: self._optimize(pid, d, spec_path, log)
            job = Job(kind, pid, fn)
            self.jobs[job.id] = job
            return job.view()

    def _check(self, pid, d, spec_path, log):
        from ..problem import Problem
        from ..geometry import voxel_fill
        from ..run import evaluate, save_fields
        with open(spec_path, encoding="utf-8") as fh:
            spec = json.load(fh)
        spec["resolution"] = "draft"
        log("Checking the setup on the original part (draft resolution)")
        prob = Problem(spec_path, spec=spec, log=log)   # paths resolve next to the spec file
        prob.build()
        _, _, info = prob.boundary(prob.active)
        log("  anchor nodes: " + ", ".join(f"{k} {v}" for k, v in info.items()))
        dtype = spec.get("designSpace", "model")
        fill = prob.space_fill if dtype == "model" else voxel_fill(prob.mesh, prob.grid)
        res = evaluate(prob, fill, "Original model", log)
        cd = os.path.join(d, "check")
        os.makedirs(cd, exist_ok=True)
        save_fields(os.path.join(cd, "fields.npz"), prob.grid, res)
        summary = {k: v for k, v in res.items() if not k.startswith("_")}
        summary["anchorNodes"] = info
        summary["voxelMM"] = prob.grid.h
        summary["material"] = prob.material
        with open(os.path.join(cd, "summary.json"), "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, default=float)
        log(f"Original part: {res['massG']:.1f} g, max displacement {res['maxDisplacementMM']:.4g} mm, "
            f"safety factor {res['safetyFactor']:.2f}")
        return summary

    def _optimize(self, pid, d, spec_path, log):
        from ..run import run
        out = os.path.join(d, "runs", time.strftime("%Y%m%d-%H%M%S"))
        record, html = run(spec_path, out, log=log, db_path=self.db)
        return {"run": os.path.basename(out), "record": record}

    # ------------------------------------------------------------- history
    def history(self, q):
        db.index_workspace(self.ws, self.db)   # pick up runs made from the command line
        ok = q.get("ok")
        return db.query(self.db, project=q.get("project") or None, material=q.get("material") or None,
                        ok=None if ok in (None, "") else ok == "1", star=q.get("star") == "1",
                        text=q.get("text") or None, order=q.get("order", "created DESC"))

    def reveal(self, path):
        known = {r["run_dir"] for r in db.query(self.db, limit=100000)}
        path = os.path.abspath(path)
        if path not in known and not path.startswith(self.ws):
            raise ValueError("Anneal only opens folders of its own projects and runs.")
        if not os.path.isdir(path):
            raise FileNotFoundError(f"The folder {path} no longer exists.")
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: Windows only
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"opened": path}

    # --------------------------------------------------------------- files
    def run_dir(self, pid, rid):
        rid = re.sub(r"[^0-9A-Za-z_-]", "", rid)
        rd = os.path.join(self.pdir(pid), "runs", rid)
        if not os.path.isdir(rd):
            raise FileNotFoundError(f"No run '{rid}' in project '{pid}'.")
        return rd

    def run_files(self, pid, rid):
        rd = self.run_dir(pid, rid)
        with open(os.path.join(rd, "run.json"), encoding="utf-8") as fh:
            rec = json.load(fh)
        files = sorted(os.listdir(rd))
        stl = next((f for f in files if f.endswith("-optimized.stl")), None)
        return rec, stl, files

    def field(self, pid, which, rid, case):
        from ..fields import corner_values
        d = self.pdir(pid)
        if which == "check":
            return corner_values(self.mesh(pid), os.path.join(d, "check", "fields.npz"), case)
        rd = self.run_dir(pid, rid)
        if which == "original":
            return corner_values(self.mesh(pid), os.path.join(rd, "fields-original.npz"), case)
        _, stl, _ = self.run_files(pid, rid)
        return corner_values(self.mesh(pid, os.path.join(rd, stl)), os.path.join(rd, "fields-optimized.npz"), case)


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        server_version = f"Anneal/{__version__}"

        def log_message(self, fmt, *args):  # quiet console
            pass

        def _send(self, code, body, ctype="application/json", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, default=float).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path, download=None):
            if not os.path.isfile(path):
                return self._send(404, {"error": "File not found."})
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if path.endswith(".js"):
                ctype = "text/javascript"
            with open(path, "rb") as fh:
                data = fh.read()
            extra = {"Content-Disposition": f'attachment; filename="{download}"'} if download else None
            self._send(200, data, ctype, extra)

        def _body(self):
            n = int(self.headers.get("Content-Length", 0))
            return self.rfile.read(n) if n else b""

        def _json(self):
            b = self._body()
            return json.loads(b) if b else {}

        def _route(self, method):
            u = urlparse(self.path)
            parts = [unquote(p) for p in u.path.strip("/").split("/") if p]
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if method == "GET" and not parts:
                    return self._file(os.path.join(STATIC, "index.html"))
                if parts[0] == "static":
                    p = os.path.normpath(os.path.join(STATIC, *parts[1:]))
                    if not p.startswith(STATIC):
                        return self._send(403, {"error": "Forbidden"})
                    return self._file(p)
                if parts[0] != "api":
                    return self._send(404, {"error": "Not found"})
                a = parts[1:]
                if method == "GET" and a == ["state"]:
                    return self._send(200, {"version": __version__, "workspace": app.ws,
                                            "materials": MATERIALS, "fasteners": list(FASTENERS),
                                            "projects": app.projects()})
                if method == "POST" and a == ["projects"]:
                    name = unquote(self.headers.get("X-Filename", "model.stl"))
                    return self._send(200, app.new_project(name, self._body()))
                if a[0] == "projects" and len(a) >= 2:
                    pid = a[1]
                    rest = a[2:]
                    if method == "GET" and not rest:
                        return self._send(200, app.project(pid))
                    if method == "GET" and rest == ["model.stl"]:
                        return self._file(os.path.join(app.pdir(pid), "display.stl"))
                    if method == "POST" and rest == ["save"]:
                        return self._send(200, app.save(pid, self._json()))
                    if method == "POST" and rest == ["pick"]:
                        return self._send(200, app.pick(pid, self._json()))
                    if method == "POST" and rest in (["check"], ["run"]):
                        return self._send(200, app.start(rest[0], pid, self._json()))
                    if method == "GET" and rest == ["check"]:
                        p = os.path.join(app.pdir(pid), "check", "summary.json")
                        with open(p, encoding="utf-8") as fh:
                            return self._send(200, json.load(fh))
                    if method == "GET" and rest and rest[0] == "field":
                        data, cases, case = app.field(pid, rest[1], q.get("run", ""), q.get("case", ""))
                        return self._send(200, data, "application/octet-stream",
                                          {"X-Cases": ",".join(cases), "X-Case": case})
                    if method == "GET" and len(rest) >= 2 and rest[0] == "runs":
                        rid = rest[1]
                        if len(rest) == 2:
                            rec, stl, files = app.run_files(pid, rid)
                            return self._send(200, {"id": rid, "record": rec, "stl": stl, "files": files,
                                                    "dir": os.path.abspath(app.run_dir(pid, rid))})
                        fname = os.path.basename(rest[2])
                        p = os.path.join(app.run_dir(pid, rid), fname)
                        dl = fname if q.get("download") else None
                        return self._file(p, dl)
                if method == "GET" and a == ["history"]:
                    return self._send(200, app.history(q))
                if method == "POST" and a == ["history", "annotate"]:
                    b = self._json()
                    db.annotate(b["run_dir"], b.get("star"), b.get("note"), app.db)
                    return self._send(200, {"saved": True})
                if method == "POST" and a == ["history", "forget"]:
                    db.forget(self._json()["run_dir"], app.db)
                    return self._send(200, {"forgotten": True})
                if method == "POST" and a == ["quit"]:
                    if any(j.state == "running" for j in app.jobs.values()):
                        return self._send(400, {"error": "A run is going. Stop it first, then quit."})
                    threading.Timer(0.3, app.stop.set).start()
                    return self._send(200, {"stopping": True})
                if method == "POST" and a == ["reveal"]:
                    return self._send(200, app.reveal(self._json()["path"]))
                if a[0] == "jobs" and len(a) >= 2:
                    job = app.jobs.get(a[1])
                    if not job:
                        return self._send(404, {"error": "No such job."})
                    if method == "POST" and a[2:] == ["cancel"]:
                        job.cancel = True
                        return self._send(200, {"cancelling": True})
                    return self._send(200, job.view(int(q.get("since", 0)), int(q.get("isince", 0))))
                return self._send(404, {"error": f"No route for {method} {u.path}"})
            except FileNotFoundError as e:
                return self._send(404, {"error": str(e)})
            except (ValueError, RuntimeError, KeyError) as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                traceback.print_exc()
                return self._send(500, {"error": f"{e.__class__.__name__}: {e}"})

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    return H


def default_workspace():
    return os.path.join(os.path.expanduser("~"), "Anneal Projects")


def running_instance(port=8765):
    """URL of an Anneal server that is already running on this PC, or None."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=0.8) as r:
            if r.headers.get("Server", "").startswith("Anneal/"):
                return f"http://127.0.0.1:{port}/"
    except Exception:
        return None
    return None


def start_server(workspace=None, port=8765):
    """Start the server in a background thread. Returns (server, url, app)."""
    app = App(workspace or default_workspace())
    srv = None
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), make_handler(app))
            break
        except OSError:
            continue
    if srv is None:
        raise RuntimeError(f"No free port between {port} and {port + 19}. Close other Anneal windows and try again.")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/", app


def serve(workspace=None, port=8765, open_browser=True):
    """Browser mode: serve until Ctrl+C or Quit in the window."""
    url = running_instance(port)
    if url:
        print(f"Anneal is already running: {url}")
        if open_browser:
            webbrowser.open(url)
        return
    srv, url, app = start_server(workspace, port)
    print(f"Anneal {__version__} GUI: {url}")
    print(f"Projects folder: {app.ws}")
    print("Keep this window open while you use Anneal. Close it (or press Ctrl+C) to stop.")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        while not app.stop.wait(1.0):
            pass
        print("Anneal stopped.")
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        srv.server_close()
