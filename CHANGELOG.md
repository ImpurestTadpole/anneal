# Changelog

## 0.4.2

- Default surface: sharp edges and exact geometry (`output.edges: "sharp"`, `output.exactFeatures: true`). Set `"edges": "smooth"` and `"exactFeatures": false` for the 0.4.0 surface. `examples/bracket.json` and the golden tests pin the 0.4.0 surface, so they still compare with earlier releases.

- GUI: "Material change" (remove only, add only, add and remove) in step 1. It sets the design space.

- Goals: `goals.massPct`, `goals.displacementPct`, `goals.strainPct` set the result as a percent of the original part. Each goal has a check row. GUI: "Goals, % of the original part" in step 3.
- Fix: the run no longer stops when exact geometry cuts off a support or load; it uses the smooth surface and says why.

New: temperature. The as-built check includes material derating and thermal stress.

- Spec: `thermal: {"referenceTempC": 20, "cases": {"caseName": tempC}}`. Temperatures in °C. A case
  name that is also a mechanical load case runs at that temperature. A new name is a thermal-only
  case (expansion only). Mechanical cases without a temperature run at the reference temperature.
  A spec without `thermal` gives the same results as 0.4.1.
- Spec: `limits.displacementIncludesThermal` (default false). By default `maxDisplacementMM`
  checks the mechanical displacement. The thermal displacement is reported separately.
- Material keys: `alpha` (1/K), `alphaZ` (1/K, across the layers), `maxServiceTempC` (°C),
  `tempDerating` (`[[tempC, E factor, yield factor], ...]`). A built-in value is added only with a
  source. A thermal case on a material without `alpha` stops with an error that names the key. A
  case above `maxServiceTempC` stops the run.
- Physics: one uniform temperature per load case; linear thermal strain α·ΔT (alphaZ across the
  layers in print-aware runs); derated E and yield at the case temperature; thermal stress in the
  as-built re-solve, FEA study, safety factor, Hill and layer checks, buckling and CalculiX check.
  The optimizer uses the mechanical loads only.
- Checks: "Service temperature vs material limit", "Thermal stress share", and a warning when
  held supports overestimate thermal stress.
- Gate: V12–V14 (free bar, bar on rollers, beam with a linear ΔT). The gate is 14 of 14.
- App: a "Temperature" fieldset in step 3 (reference temperature, a temperature per load case,
  *Add a thermal-only case*, the displacement check box); alpha (1/K or ppm/K), alphaZ, service
  limit and derating table for custom materials and in the library editor; a "Temperature and
  displacement" table in the result (case temperature, ΔT, mechanical and thermal displacement).
  Old projects open and save without a `thermal` key.
- App fix: the project spec and `gui.json` are written atomically. Before, a read during a save
  could get a half-written file (HTTP 400).
- `tools/gui_smoke.py`: checks for case temperatures, a thermal-only case, save and reload, the
  material keys, the result table, an old project without `thermal`, and a typed `thermal` block.
  The test uses a free port.
- README: section "Temperature: thermal stress and derating", the material temperature keys, the
  new check rows and gate checks.

Not in 0.4.2: temperature from heat flow (gradients), the thermal load inside the optimizer,
property changes inside one part, creep, residual stress from printing, moving supports.

## 0.4.1

New: torque load (a pure moment) on a load region.

- Spec: `torques: {"caseName": [Mx, My, Mz]}` on a load anchor, in N·m. A torque and a force with
  the same case name act together. A spec without `torques` gives the same results as 0.4.0.
- Spec: `limits.maxRotationDeg` (optional). Anneal reports the twist of each load region in degrees
  and checks it against this limit. The optimizer does not use the limit.
- Distribution: a rigid-hub rule with a linear shear distribution. The node forces add up to zero
  and give exactly the torque about the centre of the region's nodes.
- App: a "Torque" row (Mx, My, Mz in N·m) per load case on each load region, a field for the
  maximum twist, a curved-arrow glyph about the torque axis in the viewer, and a "Twist of load
  regions" table in the result when the run has twist values.
- Old projects open and save without a `torques` key.
- `tools/gui_smoke.py`: checks for the torque row, save and reload, `maxRotationDeg`, and an old
  project without torques.
- README: section "Torque on a load region", with the difference from bolt preload.

Not in 0.4.1: bolt preload, a torque as an impact load, a rotation limit in the optimizer.
