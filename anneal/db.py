"""Run history database (SQLite, one file: <workspace>/anneal.db).

Every finished run is recorded here, from the GUI and from the command line, with its
settings, its results and where its files are. The files stay the source of truth: if the
database is lost, `index_workspace` rebuilds it from the run.json files.
"""
import json
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_dir      TEXT PRIMARY KEY,         -- absolute folder of the run
    project      TEXT,
    created      TEXT,                     -- UTC ISO time
    model        TEXT,
    material     TEXT,
    resolution   TEXT,
    voxel_mm     REAL,
    volume_fraction REAL,
    goal         TEXT,                     -- 'mass' or 'volume'
    load_cases   TEXT,
    original_mass_g REAL,
    mass_g       REAL,
    max_disp_mm  REAL,
    disp_limit_mm REAL,
    safety_factor REAL,
    min_sf       REAL,
    stiffness_per_gram REAL,
    all_ok       INTEGER,
    seconds      REAL,
    anneal_version TEXT,
    spec_json    TEXT,
    star         INTEGER DEFAULT 0,
    note         TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS runs_project ON runs(project);
CREATE INDEX IF NOT EXISTS runs_created ON runs(created);
"""

_lock = threading.Lock()


def default_path():
    from .paths import home
    return os.path.join(home(), "anneal.db")


def connect(path=None):
    path = path or default_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def row_from_record(run_dir, rec, project=None):
    spec = {}
    sp = os.path.join(run_dir, "spec.json")
    if os.path.isfile(sp):
        with open(sp, encoding="utf-8") as fh:
            spec = json.load(fh)
    opt = rec["results"]["optimized"]
    orig = rec["results"].get("original") or {}
    lim = spec.get("limits", {})
    spg = None
    if orig:
        co = sum(c["complianceNmm"] for c in orig["cases"].values())
        cb = sum(c["complianceNmm"] for c in opt["cases"].values())
        if cb > 0 and opt["massG"] > 0:
            spg = (co * orig["massG"]) / (cb * opt["massG"])
    res = spec.get("resolution", "normal")
    return {
        "run_dir": os.path.abspath(run_dir),
        "project": project or spec.get("name") or os.path.basename(os.path.dirname(os.path.dirname(run_dir))),
        "created": rec.get("createdUTC"),
        "model": os.path.basename(rec.get("model") or "") or None,
        "material": rec["material"].get("name", "inline"),
        "resolution": res if isinstance(res, str) else json.dumps(res),
        "voxel_mm": rec["derived"].get("voxelMM"),
        "volume_fraction": _chosen_vf(rec),
        "goal": "mass" if spec.get("objective", {}).get("minimise") == "mass" else "volume",
        "load_cases": ",".join(sorted(opt["cases"])),
        "original_mass_g": orig.get("massG"),
        "mass_g": opt["massG"],
        "max_disp_mm": opt["maxDisplacementMM"],
        "disp_limit_mm": lim.get("maxDisplacementMM"),
        "safety_factor": opt["safetyFactor"] if opt["safetyFactor"] != float("inf") else None,
        "min_sf": lim.get("minSafetyFactor"),
        "stiffness_per_gram": spg,
        "all_ok": int(all(c["ok"] for c in rec.get("checks", []))),
        "seconds": rec.get("totalSeconds"),
        "anneal_version": rec.get("anneal"),
        "spec_json": json.dumps(spec),
    }


def _chosen_vf(rec):
    passes = rec.get("passes") or []
    m = rec["results"]["optimized"]["massG"]
    for p in passes:
        if abs(p.get("massG", -1) - m) < 1e-6:
            return p.get("volumeFraction")
    return passes[-1]["volumeFraction"] if passes else None


def record_run(run_dir, rec, project=None, path=None):
    row = row_from_record(run_dir, rec, project)
    cols = list(row)
    with _lock:
        con = connect(path)
        try:
            old = con.execute("SELECT star, note FROM runs WHERE run_dir=?", (row["run_dir"],)).fetchone()
            con.execute(f"INSERT OR REPLACE INTO runs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [row[c] for c in cols])
            if old:
                con.execute("UPDATE runs SET star=?, note=? WHERE run_dir=?", (old["star"], old["note"], row["run_dir"]))
            con.commit()
        finally:
            con.close()
    return row


def index_workspace(ws, path=None):
    """Add every run.json under the workspace that the database does not know yet."""
    added = 0
    con = connect(path)
    try:
        known = {r[0] for r in con.execute("SELECT run_dir FROM runs")}
        stale = [d for d in known if not os.path.isfile(os.path.join(d, "run.json"))]
        for d in stale:
            con.execute("DELETE FROM runs WHERE run_dir=?", (d,))
        con.commit()
    finally:
        con.close()
    if not os.path.isdir(ws):
        return added
    for proj in os.listdir(ws):
        rd = os.path.join(ws, proj, "runs")
        if not os.path.isdir(rd):
            continue
        for r in os.listdir(rd):
            d = os.path.abspath(os.path.join(rd, r))
            rec_p = os.path.join(d, "run.json")
            if d in known or not os.path.isfile(rec_p):
                continue
            try:
                with open(rec_p, encoding="utf-8") as fh:
                    record_run(d, json.load(fh), proj, path)
                added += 1
            except Exception:
                continue
    return added


def query(path=None, project=None, material=None, ok=None, star=None, text=None, order="created DESC", limit=500):
    allowed = {"created", "mass_g", "max_disp_mm", "safety_factor", "stiffness_per_gram", "project", "seconds"}
    col, _, direction = order.partition(" ")
    if col not in allowed:
        col = "created"
    direction = "ASC" if direction.upper() == "ASC" else "DESC"
    where, args = [], []
    if project:
        where.append("project=?")
        args.append(project)
    if material:
        where.append("material=?")
        args.append(material)
    if ok is not None:
        where.append("all_ok=?")
        args.append(int(ok))
    if star:
        where.append("star=1")
    if text:
        where.append("(project LIKE ? OR note LIKE ? OR model LIKE ?)")
        args += [f"%{text}%"] * 3
    sql = "SELECT * FROM runs" + (" WHERE " + " AND ".join(where) if where else "") + \
          f" ORDER BY {col} {direction} LIMIT {int(limit)}"
    con = connect(path)
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def annotate(run_dir, star=None, note=None, path=None):
    with _lock:
        con = connect(path)
        try:
            if star is not None:
                con.execute("UPDATE runs SET star=? WHERE run_dir=?", (int(bool(star)), run_dir))
            if note is not None:
                con.execute("UPDATE runs SET note=? WHERE run_dir=?", (str(note)[:2000], run_dir))
            con.commit()
        finally:
            con.close()


def forget(run_dir, path=None):
    with _lock:
        con = connect(path)
        try:
            con.execute("DELETE FROM runs WHERE run_dir=?", (run_dir,))
            con.commit()
        finally:
            con.close()
