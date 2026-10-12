"""Material and process library.

Values are TYPICAL datasheet figures, not your machine's data. Replace them with
measured values from your own coupons; the run record stores which entry was used.
Units: E and yield in MPa, density in g/cm3, minWallMM in mm.
"""

MATERIALS = {
    "Ti64-LPBF":     {"E": 110000.0, "nu": 0.31, "density": 4.43, "yield": 880.0, "minWallMM": 0.5,
                      "note": "Ti-6Al-4V, laser powder bed, stress relieved"},
    "AlSi10Mg-LPBF": {"E": 70000.0,  "nu": 0.33, "density": 2.67, "yield": 230.0, "minWallMM": 0.6,
                      "note": "AlSi10Mg, laser powder bed, as built"},
    "316L-LPBF":     {"E": 190000.0, "nu": 0.30, "density": 7.95, "yield": 470.0, "minWallMM": 0.5,
                      "note": "316L stainless, laser powder bed"},
    "PA12-SLS":      {"E": 1700.0,   "nu": 0.39, "density": 1.01, "yield": 48.0,  "minWallMM": 0.8,
                      "note": "Nylon 12, selective laser sintering"},
    "PLA-FDM":       {"E": 3500.0,   "nu": 0.36, "density": 1.24, "yield": 50.0,  "minWallMM": 1.0,
                      "note": "PLA, FDM. Anisotropic: Z strength can be under half of this"},
    "PETG-FDM":      {"E": 2000.0,   "nu": 0.38, "density": 1.27, "yield": 45.0,  "minWallMM": 1.0,
                      "note": "PETG, FDM. Anisotropic"},
}


def get_material(name_or_dict):
    """Return a material dict. Accepts a library name or an inline dict with E, nu, density, yield."""
    if isinstance(name_or_dict, dict):
        need = ["E", "nu", "density", "yield"]
        missing = [k for k in need if k not in name_or_dict]
        if missing:
            raise ValueError(f"Inline material is missing {missing}. Give E (MPa), nu, density (g/cm3) "
                             f"and yield (MPa), or use one of: {', '.join(MATERIALS)}")
        m = {"minWallMM": 1.0, "note": "inline material"}
        m.update(name_or_dict)
        return m
    if name_or_dict not in MATERIALS:
        raise ValueError(f"Unknown material '{name_or_dict}'. Use one of: {', '.join(MATERIALS)}, "
                         f"or give an inline dict with E, nu, density and yield.")
    m = dict(MATERIALS[name_or_dict])
    m["name"] = name_or_dict
    return m
