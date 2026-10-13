"""Material and process library.

Built-in values are TYPICAL datasheet figures, not your machine's data. Your own materials and
processes live in <projects folder>/library.json (default ~/Anneal Projects/library.json), so
updates of Anneal never overwrite them. Add them in the app (Library page), with
`anneal materials import file.csv|json`, or `anneal materials add ...`.

Units inside Anneal: E and yield in MPa, density in g/cm3, lengths in mm, angles in degrees.
"""
import csv
import io
import json
import os
import re

from .paths import home

# ---------------------------------------------------------------- built-in data
MATERIALS = {
    "Ti64-LPBF":     {"E": 110000.0, "nu": 0.31, "density": 4.43, "yield": 880.0, "minWallMM": 0.5, "process": "LPBF",
                      "note": "Ti-6Al-4V, laser powder bed, stress relieved"},
    "AlSi10Mg-LPBF": {"E": 70000.0,  "nu": 0.33, "density": 2.67, "yield": 230.0, "minWallMM": 0.6, "process": "LPBF",
                      "note": "AlSi10Mg, laser powder bed, as built"},
    "316L-LPBF":     {"E": 190000.0, "nu": 0.30, "density": 7.95, "yield": 470.0, "minWallMM": 0.5, "process": "LPBF",
                      "note": "316L stainless, laser powder bed"},
    "PA12-SLS":      {"E": 1700.0,   "nu": 0.39, "density": 1.01, "yield": 48.0,  "minWallMM": 0.8, "process": "SLS",
                      "note": "Nylon 12, selective laser sintering"},
    "PLA-FDM":       {"E": 3500.0,   "nu": 0.36, "density": 1.24, "yield": 50.0,  "minWallMM": 1.0, "process": "FDM",
                      "note": "PLA, FDM. Layer (Z) strength often under half of this"},
    "PETG-FDM":      {"E": 2000.0,   "nu": 0.38, "density": 1.27, "yield": 45.0,  "minWallMM": 1.0, "process": "FDM",
                      "note": "PETG, FDM. Layer (Z) strength lower than in-plane"},
}

# maxOverhangDeg: steepest overhang printed without support, measured from vertical
#   (a vertical wall is 0, a flat ceiling is 90). 90 means the process needs no support.
# enclosedVoids: 'allow' | 'warn' | 'fail' (powder processes trap powder in closed cavities).
# zStrengthFactor: strength along the build direction / in-plane strength (1 = isotropic).
PROCESSES = {
    "FDM":  {"minWallMM": 0.8, "minHoleMM": 2.0, "maxOverhangDeg": 45.0, "supportsAllowed": True,
             "enclosedVoids": "allow", "buildVolumeMM": [256.0, 256.0, 256.0], "buildDirection": [0.0, 0.0, 1.0],
             "zStrengthFactor": 0.5, "layerMM": 0.2,
             "note": "Fused filament. Build volume of a Bambu X1/P1; set your printer's."},
    "SLS":  {"minWallMM": 0.8, "minHoleMM": 1.5, "maxOverhangDeg": 90.0, "supportsAllowed": False,
             "enclosedVoids": "fail", "buildVolumeMM": [300.0, 300.0, 300.0], "buildDirection": [0.0, 0.0, 1.0],
             "zStrengthFactor": 0.9, "layerMM": 0.1,
             "note": "Powder bed fusion of polymer. Self-supporting; closed cavities trap powder."},
    "LPBF": {"minWallMM": 0.4, "minHoleMM": 1.0, "maxOverhangDeg": 45.0, "supportsAllowed": True,
             "enclosedVoids": "fail", "buildVolumeMM": [250.0, 250.0, 325.0], "buildDirection": [0.0, 0.0, 1.0],
             "zStrengthFactor": 0.9, "layerMM": 0.06,
             "note": "Laser powder bed fusion of metal. Build volume of an EOS M290."},
    "CNC-3axis": {"method": "machining", "axes": 3, "setups": ["+z"], "toolDiameterMM": 6.0,
                  "maxDepthToDiameter": 4.0, "minWallMM": 1.0, "minHoleMM": 2.0, "enclosedVoids": "fail",
                  "buildVolumeMM": [500.0, 400.0, 300.0],
                  "note": "3-axis milling. setups: the sides the tool comes from (add \"-z\" for a second setup, "
                          "flipped). The optimizer keeps every empty space open to a setup."},
    "CNC-5axis": {"method": "machining", "axes": 5, "fixture": "-z", "toolDiameterMM": 6.0,
                  "maxDepthToDiameter": 6.0, "minWallMM": 1.0, "minHoleMM": 2.0, "enclosedVoids": "fail",
                  "buildVolumeMM": [500.0, 400.0, 300.0],
                  "note": "5-axis milling: the tool may come from any side except the fixture side."},
}
# Machining keys: method "machining"; axes 3 or 5; setups (3-axis) list of "+z", "-z", "+x" ...;
# fixture (5-axis) the clamped side; toolDiameterMM the smallest cutter; maxDepthToDiameter tool reach.

# Ez, nuZ, Gz (optional): stiffness across the layers for print-aware runs (spec physics.anisotropic).
MAT_KEYS = ["E", "nu", "density", "yield", "minWallMM", "process", "zStrengthFactor", "Ez", "nuZ", "Gz",
            "note", "source"]
PROC_KEYS = ["minWallMM", "minHoleMM", "maxOverhangDeg", "supportsAllowed", "enclosedVoids", "buildVolumeMM",
             "buildDirection", "zStrengthFactor", "layerMM", "note", "method", "axes", "setups", "fixture",
             "toolDiameterMM", "maxDepthToDiameter"]


class LibraryError(ValueError):
    pass


# ---------------------------------------------------------------- user library
def library_path():
    return os.path.join(home(), "library.json")


def load_user():
    p = library_path()
    if not os.path.isfile(p):
        return {"materials": {}, "processes": {}}
    with open(p, encoding="utf-8") as fh:
        try:
            lib = json.load(fh)
        except json.JSONDecodeError as e:
            raise LibraryError(f"{p} is not valid JSON (line {e.lineno}). Fix it or delete it to start a new library.") from None
    lib.setdefault("materials", {})
    lib.setdefault("processes", {})
    return lib


def save_user(lib):
    os.makedirs(home(), exist_ok=True)
    p = library_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"anneal": "library", "version": 1, "materials": lib["materials"], "processes": lib["processes"],
                   "log": lib.get("log", [])[-2000:]}, fh, indent=2)
    os.replace(tmp, p)


def log_change(lib, action, kind, name, source="", before=None, after=None):
    """Library history: what changed, when, from where, and the values before and after."""
    import time
    lib.setdefault("log", []).append({"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "action": action,
                                      "kind": kind, "name": name, "source": source, "before": before, "after": after})


def library_log(limit=500):
    return list(reversed(load_user().get("log", [])))[:limit]


def all_materials():
    out = {k: {**v, "builtIn": True} for k, v in MATERIALS.items()}
    for k, v in load_user()["materials"].items():
        out[k] = {**v, "builtIn": False}
    return out


def all_processes():
    out = {k: {**v, "builtIn": True} for k, v in PROCESSES.items()}
    for k, v in load_user()["processes"].items():
        base = PROCESSES.get(v.get("base", ""), {})
        out[k] = {**base, **v, "builtIn": False}
    return out


def get_material(name_or_dict):
    """Material dict from a library name or an inline dict with E, nu, density, yield."""
    if isinstance(name_or_dict, dict):
        m = validate_material(dict(name_or_dict), where="Inline material")
        m.setdefault("name", "inline")
        return m
    lib = all_materials()
    if name_or_dict not in lib:
        raise ValueError(f"Unknown material '{name_or_dict}'. Use one of: {', '.join(lib)}; add it to your library "
                         f"(anneal materials import / add); or give an inline dict with E, nu, density and yield.")
    m = {k: v for k, v in lib[name_or_dict].items() if k != "builtIn"}
    m["name"] = name_or_dict
    m.setdefault("minWallMM", 1.0)
    return m


def get_process(spec_process, material):
    """Process for a run: library profile (named in the spec or by the material), then the
    material's own overrides (zStrengthFactor), then values typed in the spec."""
    procs = all_processes()
    name, over = None, {}
    if spec_process in ("none", "None"):
        return None                      # printability checks switched off
    if isinstance(spec_process, str):
        name = spec_process
    elif isinstance(spec_process, dict):
        over = {k: v for k, v in spec_process.items() if k != "name"}
        name = spec_process.get("name")
    name = name or material.get("process")
    if name and name not in procs:
        raise ValueError(f"Unknown process '{name}'. Use one of: {', '.join(procs)}, or add it to your library.")
    p = {k: v for k, v in procs.get(name, {}).items() if k != "builtIn"} if name else {}
    if "zStrengthFactor" in material and p.get("method") != "machining":   # layers exist only in printed parts
        p["zStrengthFactor"] = material["zStrengthFactor"]
    p.update(over)
    p["name"] = name or "none"
    return validate_process(p, where=f"Process '{p['name']}'") if name or over else None


# ---------------------------------------------------------------- validation
def _num(v, what, where):
    try:
        return float(v)
    except (TypeError, ValueError):
        raise LibraryError(f"{where}: {what} must be a number, not {v!r}.") from None


def validate_material(m, where="Material"):
    need = ["E", "nu", "density", "yield"]
    missing = [k for k in need if m.get(k) in (None, "")]
    if missing:
        raise LibraryError(f"{where}: {', '.join(missing)} missing. Give E (MPa), nu, density (g/cm3) and yield (MPa).")
    for k in need + ["minWallMM", "zStrengthFactor", "Ez", "nuZ", "Gz"]:
        if m.get(k) not in (None, ""):
            m[k] = _num(m[k], k, where)
        else:
            m.pop(k, None)
    checks = [("E", 1.0, 1.0e6, "MPa (PLA is about 3500, steel 200000). Check the units: GPa × 1000 = MPa"),
              ("nu", 0.0, 0.499, "(Poisson's ratio is between 0 and 0.5; most solids 0.25 to 0.4)"),
              ("density", 0.05, 25.0, "g/cm3 (PLA 1.24, aluminium 2.7). kg/m3 ÷ 1000 = g/cm3"),
              ("yield", 0.1, 5000.0, "MPa. psi × 0.006895 = MPa"),
              ("minWallMM", 0.0, 50.0, "mm"),
              ("zStrengthFactor", 0.05, 1.0, "(layer strength / in-plane strength, 0.05 to 1)"),
              ("Ez", 1.0, 1.0e6, "MPa (modulus across the layers). GPa × 1000 = MPa"),
              ("nuZ", 0.0, 0.499, "(Poisson's ratio for load across the layers, usually 0.2 to 0.4)"),
              ("Gz", 1.0, 1.0e6, "MPa (shear modulus between layers)")]
    for k, lo, hi, hint in checks:
        if k in m and not lo <= m[k] <= hi:
            raise LibraryError(f"{where}: {k} = {m[k]:g} is outside {lo:g} to {hi:g} {hint}.")
    for k in ("process", "note", "source", "name"):
        if k in m and m[k] is not None:
            m[k] = str(m[k])
    return m


def validate_process(p, where="Process"):
    for k in ("minWallMM", "minHoleMM", "maxOverhangDeg", "zStrengthFactor", "layerMM"):
        if p.get(k) not in (None, ""):
            p[k] = _num(p[k], k, where)
    if "maxOverhangDeg" in p and not 0 <= p["maxOverhangDeg"] <= 90:
        raise LibraryError(f"{where}: maxOverhangDeg must be 0 to 90 (0 = vertical walls only, 90 = no support needed).")
    if "zStrengthFactor" in p and not 0.05 <= p["zStrengthFactor"] <= 1:
        raise LibraryError(f"{where}: zStrengthFactor must be 0.05 to 1.")
    if p.get("enclosedVoids", "allow") not in ("allow", "warn", "fail"):
        raise LibraryError(f"{where}: enclosedVoids must be allow, warn or fail.")
    for k in ("buildVolumeMM", "buildDirection"):
        if k in p:
            v = p[k]
            if not isinstance(v, (list, tuple)) or len(v) != 3:
                raise LibraryError(f"{where}: {k} must be three numbers.")
            p[k] = [_num(x, k, where) for x in v]
    if "buildDirection" in p and sum(x * x for x in p["buildDirection"]) < 1e-12:
        raise LibraryError(f"{where}: buildDirection cannot be zero. Use for example [0, 0, 1] (build up along +Z).")
    for k in ("toolDiameterMM", "maxDepthToDiameter"):
        if p.get(k) not in (None, ""):
            p[k] = _num(p[k], k, where)
            if p[k] <= 0:
                raise LibraryError(f"{where}: {k} must be more than 0.")
    if p.get("method", "additive") not in ("additive", "machining"):
        raise LibraryError(f"{where}: method must be additive or machining.")
    if p.get("method") == "machining":
        p["axes"] = int(p.get("axes", 3))
        if p["axes"] not in (3, 5):
            raise LibraryError(f"{where}: axes must be 3 or 5.")
        ok = {"+x", "-x", "+y", "-y", "+z", "-z"}
        if p["axes"] == 3:
            st = p.get("setups") or ["+z"]
            if isinstance(st, str):
                st = [t.strip() for t in st.replace(",", " ").split()]
            if not st or any(t.lower() not in ok for t in st):
                raise LibraryError(f"{where}: setups must be a list of +x, -x, +y, -y, +z, -z (the sides the tool comes from).")
            p["setups"] = [t.lower() for t in st]
        if str(p.get("fixture", "-z")).lower() not in ok:
            raise LibraryError(f"{where}: fixture must be one of +x, -x, +y, -y, +z, -z.")
    if "supportsAllowed" in p:
        p["supportsAllowed"] = str(p["supportsAllowed"]).lower() not in ("false", "0", "no")
    return p


# ---------------------------------------------------------------- import
UNIT = {  # unit -> (quantity, factor to Anneal units)
    "gpa": ("stress", 1000.0), "mpa": ("stress", 1.0), "kpa": ("stress", 1e-3), "pa": ("stress", 1e-6),
    "n/mm2": ("stress", 1.0), "n/mm^2": ("stress", 1.0), "psi": ("stress", 0.00689476), "ksi": ("stress", 6.89476),
    "msi": ("stress", 6894.76),
    "g/cm3": ("density", 1.0), "g/cm^3": ("density", 1.0), "g/cc": ("density", 1.0), "g/ml": ("density", 1.0),
    "kg/m3": ("density", 1e-3), "kg/m^3": ("density", 1e-3), "lb/in3": ("density", 27.6799), "lb/in^3": ("density", 27.6799),
    "lb/ft3": ("density", 0.0160185),
    "mm": ("length", 1.0), "um": ("length", 1e-3), "µm": ("length", 1e-3), "in": ("length", 25.4), "cm": ("length", 10.0),
}
FIELD_WORDS = [  # (field, words that identify a column), first match wins
    ("Ez", [r"\bz\b.*modulus", r"modulus.*\bz\b", r"vertical.*modulus", r"modulus.*(vertical|xz|zx)"]),
    ("yieldZ", [r"\bz\b.*(yield|strength)", r"(yield|strength).*\bz\b", r"layer.*(strength|adhesion)", r"interlayer",
                r"vertical.*strength", r"strength.*(vertical|xz|zx)"]),
    ("name", [r"^name$", r"material", r"^grade$", r"product", r"^filament$"]),
    ("E", [r"young", r"tensile modulus", r"elastic modulus", r"modulus of elasticity", r"^e$", r"^e[\s_(\[]",
           r"^modulus", r"flexural modulus"]),
    ("nu", [r"poisson", r"^nu$", r"^ν$", r"^nu[\s_(\[]"]),
    ("density", [r"density", r"^rho$", r"^ρ$", r"^rho[\s_(\[]"]),
    ("yield", [r"yield", r"tensile strength", r"^uts", r"ultimate", r"^strength", r"^sy$", r"^fy$"]),
    ("minWallMM", [r"min.*wall", r"wall"]),
    ("process", [r"process", r"technology", r"method"]),
    ("zStrengthFactor", [r"z.?factor", r"anisotrop"]),
    ("note", [r"note", r"comment", r"description", r"source", r"supplier", r"brand"]),
]


def _field_and_unit(header):
    h = header.strip().lower().replace("³", "3").replace("²", "2")
    unit = None
    m = re.search(r"[\[(]\s*([^\])]+?)\s*[\])]", h)
    if m:
        unit = m.group(1).replace(" ", "")
        h = (h[:m.start()] + h[m.end():]).strip()
    else:
        m = re.search(r"[_\s]((?:gpa|mpa|kpa|pa|psi|ksi|msi|g/cm3|g/cc|kg/m3|lb/in3|mm|in))$", h)
        if m:
            unit = m.group(1)
            h = h[:m.start()].strip()
    h = h.replace("_", " ").strip()
    for field, pats in FIELD_WORDS:
        if any(re.search(p, h) for p in pats):
            return field, unit, h
    return None, unit, h


def _value(raw, unit, field):
    """Number in Anneal units from a cell (unit from the header or written in the cell)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        num, cell_unit = float(raw), None
    else:
        s = str(raw).strip()
        if s == "":
            return None
        if re.match(r"^[-+]?\d+,\d{1,2}(?!\d)", s) or re.match(r"^[-+]?\d+,\d{4,}", s):
            s = s.replace(",", ".", 1)                 # decimal comma: 1,24 or 0,3600
        else:
            s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)  # thousands: 70,000
        m = re.match(r"^([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(.*)$", s)
        if not m:
            raise LibraryError(f"'{raw}' is not a number")
        num, cell_unit = float(m.group(1)), (m.group(2).strip().lower().replace(" ", "").replace("³", "3") or None)
    u = (cell_unit or unit or "").lower()
    if u:
        if u not in UNIT:
            raise LibraryError(f"unit '{u}' is not known (use GPa, MPa, psi, ksi, g/cm3, kg/m3, lb/in3, mm or in)")
        q, f = UNIT[u]
        want = {"E": "stress", "Ez": "stress", "Gz": "stress", "yield": "stress", "yieldZ": "stress", "density": "density", "minWallMM": "length"}.get(field)
        if want and q != want:
            raise LibraryError(f"unit '{u}' does not fit {field}")
        return num * f
    # no unit: decide only where it is safe
    if field in ("E", "Ez"):
        if num >= 500:
            return num            # MPa
        raise LibraryError(f"E = {num:g} has no unit. Write GPa or MPa in the header, for example 'E (GPa)'")
    if field == "density":
        return num / 1000 if num > 50 else num       # kg/m3 if large, else g/cm3
    return num


def _material_from_fields(fields, where):
    m = {}
    for k in ("E", "nu", "density", "yield", "minWallMM", "zStrengthFactor", "Ez"):
        if fields.get(k) is not None:
            m[k] = fields[k]
    for k in ("process", "note"):
        if fields.get(k):
            m[k] = str(fields[k]).strip()
    if fields.get("yieldZ") is not None and fields.get("yield"):
        m["zStrengthFactor"] = round(min(1.0, fields["yieldZ"] / fields["yield"]), 3)
    if m.get("process") and m["process"].upper() in ("FDM", "FFF"):
        m["process"] = "FDM"
    elif m.get("process") and m["process"].upper() in ("SLS", "MJF", "HP MJF"):
        m["process"] = "SLS"
    elif m.get("process") and m["process"].upper() in ("LPBF", "SLM", "DMLS", "L-PBF"):
        m["process"] = "LPBF"
    return validate_material(m, where)


def parse_import(filename, data):
    """Read materials from CSV or JSON. Returns (materials: dict name -> values, problems: list of str).
    Rows with problems are skipped; every problem names the row and the fix. Lines that start with
    'Note:' are advice, not errors."""
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".json" or text.lstrip().startswith(("{", "[")):
        out, problems = _parse_json(text)
    else:
        out, problems = _parse_csv(text)
    for name, m in out.items():
        if m["E"] < 200:
            problems.append(f"Note: '{name}' is flexible (E {m['E']:g} MPa). Anneal's linear model is not valid for "
                            f"rubber-like materials such as TPU; use the results only as a rough guide.")
        if not m.get("process"):
            problems.append(f"Note: '{name}' has no process (FDM, SLS or LPBF). Printability checks will use the "
                            f"process you choose for each project.")
    return out, problems


def _parse_csv(text):
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        return {}, ["The file needs a header row and at least one material row."]
    header = rows[0]
    cols = [_field_and_unit(h) for h in header]
    found = {f for f, _, _ in cols if f}
    problems = []
    if "name" not in found:
        return {}, ["No name column found. Add a column called 'name' (or 'material')."]
    unknown = [h for (f, _, _), h in zip(cols, header) if not f and h.strip()]
    if unknown:
        problems.append(f"Columns not used: {', '.join(unknown)}")
    out = {}
    for i, r in enumerate(rows[1:], start=2):
        fields, err = {}, None
        for j, ((f, unit, _), cell) in enumerate(zip(cols, r)):
            if not f or f in fields:
                continue
            try:
                fields[f] = cell.strip() if f in ("name", "process", "note") else _value(cell, unit, f)
            except LibraryError as e:
                err = f"Row {i}, column '{header[j]}': {e}"
                break
        name = (fields.get("name") or "").strip()
        if err:
            problems.append(err)
            continue
        if not name:
            problems.append(f"Row {i}: no name. Skipped.")
            continue
        try:
            m = _material_from_fields(fields, f"Row {i} ({name})")
        except LibraryError as e:
            problems.append(str(e))
            continue
        if name in out:
            problems.append(f"Row {i}: '{name}' appears twice; the later row is used.")
        out[name] = m
    return out, problems


def _parse_json(text):
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return {}, [f"Not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}."]
    if isinstance(obj, dict) and "materials" in obj:
        obj = obj["materials"]
    if isinstance(obj, dict) and ("name" in obj and any(k in obj for k in ("E", "density", "yield"))):
        obj = [obj]
    items = list(obj.items()) if isinstance(obj, dict) else [(o.get("name"), o) for o in obj if isinstance(o, dict)]
    out, problems = {}, []
    for name, vals in items:
        if not name or not isinstance(vals, dict):
            problems.append(f"An entry has no name or no values: {str(vals)[:60]}")
            continue
        fields = {}
        try:
            for key, raw in vals.items():
                f, unit, _ = _field_and_unit(key)
                if key in MAT_KEYS:
                    f = key
                if not f or f == "name":
                    continue
                fields[f] = raw if f in ("process", "note") else _value(raw, unit, f)
            out[str(name)] = _material_from_fields(fields, f"'{name}'")
        except LibraryError as e:
            problems.append(f"'{name}': {e}")
    return out, problems


def add_materials(new, overwrite=True, source=""):
    """Save materials to the user library. Returns (added, replaced, skipped) name lists."""
    lib = load_user()
    added, replaced, skipped = [], [], []
    for name, m in new.items():
        if name in MATERIALS and not overwrite:
            skipped.append(name)
            continue
        before = lib["materials"].get(name)
        if before is not None:
            if not overwrite:
                skipped.append(name)
                continue
            replaced.append(name)
        else:
            added.append(name)
        lib["materials"][name] = {k: v for k, v in m.items() if k in MAT_KEYS}
        if source and "source" not in lib["materials"][name]:
            lib["materials"][name]["source"] = source
        log_change(lib, "replaced" if before is not None else "added", "material", name, source, before,
                   lib["materials"][name])
    save_user(lib)
    return added, replaced, skipped


def remove_material(name):
    lib = load_user()
    if name not in lib["materials"]:
        raise LibraryError(f"'{name}' is not in your library" + (" (built-in materials cannot be removed)." if name in MATERIALS else "."))
    log_change(lib, "removed", "material", name, before=lib["materials"].pop(name))
    save_user(lib)


def save_process(name, p):
    if not name or not str(name).strip():
        raise LibraryError("A process needs a name.")
    p = validate_process({k: v for k, v in p.items() if k in PROC_KEYS + ["base"]}, f"Process '{name}'")
    lib = load_user()
    nm = str(name).strip()
    before = lib["processes"].get(nm)
    lib["processes"][nm] = p
    log_change(lib, "replaced" if before else "added", "process", nm, before=before, after=p)
    save_user(lib)


def remove_process(name):
    lib = load_user()
    if name not in lib["processes"]:
        raise LibraryError(f"'{name}' is not in your library" + (" (built-in processes cannot be removed)." if name in PROCESSES else "."))
    log_change(lib, "removed", "process", name, before=lib["processes"].pop(name))
    save_user(lib)


def export_library():
    lib = load_user()
    return {"anneal": "library", "version": 1, "materials": lib["materials"], "processes": lib["processes"]}
