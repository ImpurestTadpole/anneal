# Anneal — plan: goal, current state, and the work to get there

Read this file with `CLAUDE.md`. `CLAUDE.md` holds the rules and the short work list. This file
holds the goal, the reasons and the full plan. `docs/research/CONTEXT.md` holds the research
facts behind the decisions. `docs/research/deepseek-physics-review.md` is an external review that
this plan answers item by item (section 6).

---

## 1. Goal

**A personal Noyron.** Anneal is a computational-engineering program for one operator (the
owner). The operator gives a part's interfaces (bolt holes, faces, keep-outs), its loads and its
material and process. Anneal then makes a part that the operator can manufacture and trust,
without manual meshing or CAD modelling.

"Trust" means:
- The physics is validated against closed-form answers (the gate) and against an independent
  solver (CalculiX).
- Every number in a result can be traced to an input, a derived value or a cited source.
- A result is reproducible: the same spec and the same solver build give the same file, bit for bit.
- The report states what is not modelled.
- Test results from printed or machined parts go back into the code as changed values, new guard
  rails or new tests.

Platforms: Windows 10/11 (primary) and Ubuntu 20.04+. No GPU is needed.

### What "done" looks like (long term)

1. You open a STEP with the interfaces and pick the holes and faces.
2. You state the loads, or derive them from an event (a drop, an acceleration, a mechanism).
3. You pick a material and a process (FDM, SLS, LPBF or CNC).
4. Anneal returns a part as STL, 3MF and STEP, a report, and a run record.
5. The part passes the strength, stiffness, buckling and manufacturability checks for that process.
6. You make the part and test it. The test result goes into the library and the tests.
7. The second and third part families reuse the library. You add fewer inputs per part as the
   library grows.

### Not goals

- A commercial no-code product for other engineers. That was considered and rejected
  (`docs/research/CONTEXT.md`, "Reframe").
- Certification, GD&T, drawings or tolerancing.
- Real-time performance on very large grids. Accuracy and trust come first.

---

## 2. Where it is now (12 October 2026)

| Version | State | Where |
|---|---|---|
| 0.1.0 | CLI, voxel FEM, SIMP, STL/3MF, report. Gate 6/6. | history |
| 0.2.0 | Desktop app (pywebview), web GUI, feature picking, history database | history |
| 0.3.0 | Material/process library, import, printability (DFM) | **master**, 17a3e31 |
| 0.4.0 preview | All features below. Not verified. **Does not start on Windows.** | **release-0.4**, ada107c |
| experiments | Overhang (AM) filter, slicer comparison | verify-roadmap (do not merge) |

### Features on release-0.4 (0.4.0 preview)

Physics
- e9 element (hex8 with 9 incompatible modes): no shear locking. hex8fi stays as the legacy element.
- Print-aware material (transversely isotropic stiffness, Hill strength).
- Linear buckling (with the as-built part).
- Equivalent-static impact.
- Large deformation through a CalculiX sidecar (optional).
- Self-weight and acceleration loads (follow the design in the optimizer).
- Pressure loads on picked faces.
- FEA study: reactions, equilibrium, URES, von Mises, P1/P3, Tresca, strain energy, FOS distribution,
  Zienkiewicz-Zhu stress error, mass properties.

Geometry and manufacturing
- Feature picking: holes, faces and face outlines. Loads can go on inner bolt holes.
- Keep-outs from picked features, keep regions that never add material, grow from interfaces
  (`keepModel`), bolt-head access.
- Exact geometry finishing with manifold3d.
- Sharp edges with coarse / normal / fine detail.
- STEP export (faceted solid).
- 3-axis milling filter in the optimizer; 3- and 5-axis machinability checks.

Output and trust
- Advanced output: graphs and plain statements about how the part carries the load.
- Report sections: FEA study, Assumptions, Not modelled, Verification.
- Solver provenance: a hash of the solver source; `python -m anneal validate` stores the gate
  result for that hash.
- Validation gate V1–V10. It was 10/10 before the last edits.

### Known problems

1. The preview does not open on the owner's Windows PC (desktop icon, also as admin). The cause is
   unknown (section 4, item S1).
2. The full test suite, the golden tests, the GUI smoke test and the release proof have not run on
   ada107c.
3. The "Member thickness in voxels" check row may give wrong numbers.

---

## 3. How the work is organised

- Branch rules, commands and the proof are in `CLAUDE.md`.
- Three agent roles are defined in `.claude/agents/`: `solver-verifier`, `gui-docs` and
  `startup-windows`. Each one works in its own git worktree (`.claude/settings.json` sets
  `worktree.baseRef` to `head`, so worktrees start from your current branch, not from master).
- Each agent commits on its own branch. A person reviews the branch and merges it into release-0.4.
- Only the full proof moves release-0.4 to master.

File ownership between agents (this prevents merge conflicts):

| Agent | Owns |
|---|---|
| startup-windows | `anneal/gui/desktop.py`, `anneal/gui/__init__.py`, `anneal/__main__.py`, start-up paths in `anneal/cli.py`, `*.bat`, `install_*.sh/.bat`, `pyproject.toml`, `requirements.txt`, `tests/test_startup.py` |
| solver-verifier | `anneal/*.py` except the files above and `anneal/gui/`, `tests/` except GUI and start-up tests, `tools/prove_release.py`, `tools/write_verification.py` |
| gui-docs | `anneal/gui/static/*`, `anneal/gui/server.py`, `tools/gui_smoke.py`, `tests/test_gui.py`, `README.md` |

---

## 4. Plan to release 0.4.0

Do these in order. Each item has an acceptance test. Do not merge to master until all of them pass.

### Stage S — make it start (blocking)

| ID | Work | Acceptance |
|---|---|---|
| S1 | Find why 0.4.0 does not start on Windows. Compare the start-up path with 0.3.0: imports, the new taskbar code (`SetCurrentProcessExplicitAppUserModelID`, WinForms icon via pythonnet), `webview.start(icon=...)`, `manifold3d` and other new dependencies, a `pythonw` launcher that hides errors. | The cause is named with evidence. |
| S2 | Make start-up robust. Optional features never stop the app. A start-up exception goes to `~/Anneal Projects/anneal-startup.log` and to a message box (Windows) or the console. | `tests/test_startup.py` passes with the Windows APIs missing or raising. |
| S3 | Install scripts install every required dependency (`manifold3d`), and optional ones (`cadquery-ocp`, `gmsh`) without stopping when one fails. | A clean virtualenv install from the repo starts `python -m anneal gui`, and the server answers. |
| S4 | Owner check on Windows: the desktop icon and `python -m anneal gui` both open the app. | Owner confirms. |

### Stage V — verify

| ID | Work | Acceptance |
|---|---|---|
| V1 | Gate | `python -m anneal validate` → 10 of 10 |
| V2 | Test suite | `python -m pytest -q tests/` passes |
| V3 | Golden tests | `ANNEAL_GOLDEN=1 pytest tests/test_golden.py` passes for hex8fi and e9 |
| V4 | Regression vs 0.3.0 | Bracket with `solver.element: hex8fi`: STL, density and field SHA-256, mass, displacement and SF are bit-identical to 17a3e31. Old check rows are identical; new rows are listed. |
| V5 | Physics run | `examples/bracket-pla.json` with print-aware material, buckling, impact and CalculiX |
| V6 | Interfaces run | `examples/interfaces.json`: one closed solid, holes exact, no material in bolt access |
| V7 | Feature run | Sharp edges + fine detail + gravity + pressure + advanced output |
| V8 | Machining run | CNC-3axis with the filter: no undercut from the setups; CNC-5axis check |
| V9 | CalculiX cross-check | `tools/ccx_bracket.py`: e9 displacement within 5 % of CalculiX tet10 |
| V10 | GUI smoke | `tools/gui_smoke.py`: every 0.4 control, old projects open, Result step shows FEA and advanced blocks |
| V11 | Proof document | `tools/prove_release.py` + `tools/write_verification.py` → `VERIFICATION.md` |
| V12 | Check-row bug | "Member thickness in voxels" gives the right share on a known part |

### Stage D — documents

| ID | Work | Acceptance |
|---|---|---|
| D1 | README for every 0.4 option, in plain technical English | Every spec key in the code is in the README |
| D2 | `VERIFICATION.md` | From V11 |
| D3 | Changelog for 0.4.0 | In the README or `CHANGELOG.md` |

### Stage R — release

Merge release-0.4 into master. Tag `v0.4.0`. Build the zip. Install it on Windows and on Ubuntu 20.04.

---

## 4A. Plan for release 0.4.1 — torque load

0.4.1 adds one load type: a **torque** (a pure moment) on a load region. Examples: a drive shaft
in a bore, a lever hub, a motor flange. 0.4.1 starts only after 0.4.0 is on master and tagged.

### Scope

In scope:
- A torque per load case on a load anchor, alone or together with a force or a pressure.
- The optimizer, the as-built re-solve, the FEA study, the CalculiX sidecar, the report and the GUI
  all use the torque.
- A new gate check for torsion.
- Fixes from owner feedback on 0.4.0 (bugs only, no new features).

Not in scope (see section 5):
- Bolt preload (tightening torque → axial clamp force). This is a different thing: it is 0.5 item 4.
  The README must say the difference.
- A torque as an impact load. `impact` stays force-only; a spec with an impact on a torque-only
  anchor gives a SpecError that names the fix.
- A rotation limit in the optimizer (`limits.maxRotationDeg` is reported and checked, not optimized).

### Definitions

| Term | Meaning |
|---|---|
| Torque | A pure moment M = [Mx, My, Mz]. Its net force is zero. |
| Node centroid | The mean position of the anchor's nodes on the active voxels. |
| Twist | The rigid rotation of the anchor's nodes that fits their displacement best (least squares), in degrees. |

### Spec (proposed)

```json
{ "name": "hub", "role": "load", "feature": {"bore": {"bolt": "M8", "at": [0,0,0]}},
  "torques": { "drive": [0, 0, 12.5] },
  "loads":   { "drive": [0, 200, 0] } }
```

- `torques`: `{"caseName": [Mx, My, Mz]}` in **N·m**. The solver uses N·mm (× 1000). A
  `torques` case and a `loads` case with the same name add together.
- `limits.maxRotationDeg` (optional): the largest permitted twist of any load anchor.
- A spec without `torques` must give bit-identical results to 0.4.0 (regression).

### How the torque goes onto nodes

For anchor nodes i at positions x_i, with centroid c and r_i = x_i − c:
1. Make the node inertia tensor I = Σ_i (|r_i|² E − r_i r_iᵀ) (E is the 3×3 unit matrix).
2. Solve I ω = M for ω.
3. Nodal force f_i = ω × r_i.
4. Then Σ f_i = ω × Σ r_i = 0 and Σ r_i × f_i = I ω = M exactly, for any node set. It is the
   smallest set of nodal forces (least squares) with these two sums. It matches a rigid hub with a
   linear shear distribution (the usual RBE3 or "spider" model in commercial FEA).
5. The nodes change with the active set (as forces do today), so the rule runs in
   `Problem.boundary()` each time. Guard: if I is near singular (all nodes on one line), give a
   SpecError that tells the user to use a larger region.

Note: a simpler rule, f_i = M × s_i / Σ|s_j|² with s_i normal to the torque axis, is exact only
for a symmetric node set. It gives a wrong moment on a tilted or one-sided region. Do not use it.

The optimizer needs no change: the compliance is linear in the nodal force vector.

### Work items

| ID | Work | Owner (section 3) | Acceptance |
|---|---|---|---|
| T1 | Parse `torques` in `Anchor`; validate shape and units; store per case. Store `limits.maxRotationDeg`. | solver-verifier (`problem.py`) | Clear SpecError for a wrong shape, an empty region, an impact on a torque-only anchor. |
| T2 | Nodal distribution in `Problem.boundary()` (rule above). Add the torque cases to `self.cases`. | solver-verifier (`problem.py`) | Unit test: Σf = 0 and Σ r×f = M to 1e-10 relative, on a bore, a pad and an off-axis box. |
| T3 | Twist in degrees per load anchor and case (least-squares rotation of anchor nodes), in run.json and the result. Check row against `maxRotationDeg`. | solver-verifier (`run.py`) | Rigid-rotation test: an imposed small rotation gives back the same angle. |
| T4 | FEA study: moment reactions at fixed anchors and a moment-equilibrium residual next to the force residual. | solver-verifier (`fea.py`) | Moment equilibrium < 1e-6 relative on the torsion test part. |
| T5 | Gate check V11: torsion of a square bar, θ = T·L / (G · k₁ · a⁴), k₁ = 0.1406 (Saint-Venant). Set the tolerance from measured data at 4, 6, 8 voxels across (as was done for V3 with e9), for e9 and hex8fi. | solver-verifier (`validate.py`, `provenance.py`) | `python -m anneal validate` → "GATE: OPEN - 11 of 11". The provenance hash changes; the gate result is stored again. |
| T6 | CalculiX sidecar: the same rule on the tet10 anchor node set. Cross-check on a torsion bracket. | solver-verifier (`sidecar.py`, `tools/ccx_bracket.py`) | e9 twist within 5 % of CalculiX tet10. |
| T7 | Report: the load table shows torques in N·m; "Assumptions" states the distribution rule; "Not modelled" states that the hub is not a separate rigid body and there is no contact or slip in the bore. | solver-verifier (`report.py`) | Report on the example shows all three. |
| T8 | Advanced output: twist per case and the torque share carried by each support. | solver-verifier (`advanced.py`) | Statements name the support that carries most of the torque. |
| T9 | GUI: a "Torque (N·m)" vector row per case on load anchors, next to Force. A curved-arrow glyph about the axis in the viewer. Old projects open unchanged. | gui-docs (`app.js`, `viewer.js`) | `tools/gui_smoke.py`: set a torque, save, reload, run; the spec holds `torques`. |
| T10 | Example `examples/torque-hub.json` (hub on a bore, fixed on a bolt circle) and a golden test for it. | solver-verifier | Golden test passes for e9 and hex8fi. |
| T11 | README: torque option, units, the rule, the difference from bolt preload. CHANGELOG 0.4.1. | gui-docs | Every new spec key is in the README. |
| T12 | Owner feedback fixes on 0.4.0 (bugs only). | by area | Each fix has a test. |

### Order

1. T1, T2 (with tests) → T5 (the gate must pass before anything else uses the torque).
2. T3, T4, T6, T7, T8 in parallel.
3. T9 after T1 (the spec shape is fixed).
4. T10, T11, then the proof.

### Proof for 0.4.1

The same proof as 0.4.0 (`CLAUDE.md`, "Proof"), with these changes:
- The gate is 11 of 11.
- Regression: `examples/bracket.json` (no torque) gives bit-identical results to **0.4.0** with
  both e9 and hex8fi.
- New runs: `examples/torque-hub.json` and the CalculiX torsion cross-check (T6).
- Branch `release-0.4.1` from tag `v0.4.0`. Merge to master, tag `v0.4.1`.

### Risks

| Risk | What answers it |
|---|---|
| Stress peaks at the bore edge (the torque goes in through few nodes) | The anchor freeze zone keeps material there; the report excludes the anchor zone from the design stress, as for forces; the ZZ indicator shows it. |
| Users enter N·mm instead of N·m | The unit is in the key help, the GUI label and the report; a check row warns when |M| / (|F|·part size) is above 1000. |
| The linear rule is too stiff or too soft compared with a real key or spline | The report states the rule. A key or spline model is not in 0.4.1. |

---

## 4B. Plan for release 0.4.2 — temperature: derating and thermal stress

0.4.2 adds temperature to the as-built check. It is stages T0 and T1 of
`docs/research/thermal-loads.md` (read that file first: physics, traps and sources). 0.4.2 starts
only after 0.4.1 is on master and tagged. Branch `release-0.4.2` from tag `v0.4.1`.

### Scope

In scope:
- **Derating (T0):** material properties at temperature, and a hard stop above the material's
  service limit.
- **Thermal stress (T1):** one uniform temperature per load case. The thermal strain α·ΔT acts in
  the as-built re-solve, the FEA study, the stress, Hill and layer checks, buckling, the CalculiX
  sidecar, the report and the GUI.
- New gate checks for thermal strain.
- Fixes from owner feedback on 0.4.1 (bugs only).

Not in scope (later stages in `thermal-loads.md`):
- A temperature field from heat flow (T2, conduction solve).
- Thermal load inside the optimizer (T3). In 0.4.2 the optimizer uses the mechanical loads only;
  the thermal load enters at the as-built check. The report must say this.
- Temperature-dependent properties inside one part (one temperature per load case only).
- Residual stress and warping from printing.

### Definitions

| Term | Meaning |
|---|---|
| Reference temperature | The temperature at which the part has no thermal stress (assembly). Default 20 °C. |
| Case temperature | The uniform part temperature during one load case. ΔT = case − reference. |
| Thermal strain | ε_th = ΔT·[α, α, α_z, 0, 0, 0] in the build frame (α_z = α if not given). |
| Derating | E and yield at the case temperature, from the material's table, by linear interpolation. |
| Service limit | `maxServiceTempC` of the material. Above it the linear model is not valid. |

### Spec (proposed)

```json
"thermal": {
  "referenceTempC": 20,
  "cases": { "main": 55, "coldStart": -20, "expansionOnly": 70 }
}
```

- Each key of `thermal.cases` is a load case name, and its value is the case temperature in °C.
- A key that is also a mechanical load case: that case runs at that temperature (mechanical +
  thermal together).
- A key with no mechanical loads: a new **thermal-only** load case (expansion only).
- Mechanical load cases without a key run at the reference temperature (no thermal strain, no
  derating) — as in 0.4.1.
- `limits.maxDisplacementMM` checks the **mechanical** displacement by default: the as-built
  solve without the thermal strain. A free part that expands is not "too flexible". The thermal
  displacement is reported separately. `limits.displacementIncludesThermal: true` changes this.
- A spec without `thermal` must give bit-identical results to 0.4.1 (regression).

New material keys (library, import and custom material):

| Key | Unit | Meaning |
|---|---|---|
| `alpha` | 1/K | expansion coefficient (in the layers for printed parts) |
| `alphaZ` | 1/K | expansion across the layers (optional; print-aware runs) |
| `maxServiceTempC` | °C | service limit |
| `tempDerating` | list | `[[tempC, E factor, yield factor], ...]`, factors relative to the listed E and yield; must include the reference temperature with factors 1 |

**Every built-in value needs a cited source** (datasheet or paper) in the material's `source`
field. If no source is found, leave the key out. A thermal case on a material without `alpha` gives
a SpecError that names the missing key and how to add it. Do not invent numbers.

### How the thermal strain goes into the solver

1. Per material, compute once the 24-vector f̂ = Σ_gp Bᵀ D₁ m_α w (D₁ = D for E = 1, m_α the strain
   pattern above, rotated like D for print-aware runs). For e9 the bubble part is zero when ΔT is
   constant in a voxel (checked numerically: |f_b| = 0). Keep a test that proves it.
2. Thermal load of a case: f = Σ_e E_e · ΔT · f̂ scattered over the element dofs (the same
   scatter as `internal_forces`). E_e includes the fill fraction and the derating factor.
3. Displacement: u = K⁻¹ (f_mech + f_th). Mechanical-only displacement for the limit: K⁻¹ f_mech
   (same factorisation/preconditioner, one more right-hand side).
4. Stress: σ = E_e · D₁ (B₀ u − ε_th). Change `FEM.stress` to take an optional ε₀ per element and
   update **every caller**: `run.evaluate`, `fea.study` (and ZZ), Hill, the layer check, buckling.
5. Buckling: the thermal stress is part of the pre-stress of that case (a heated, held part can
   buckle with no mechanical load). `buckling_check` uses the total stress.
6. Impact stays mechanical (unit-load stiffness); it uses the derated E and yield of the case it
   names, if any.
7. FEA study equilibrium: a thermal-only case has zero net applied force. Normalise the equilibrium
   error by Σ|f_i| (sum of absolute nodal forces), not by |Σ f_i|, for all cases.

### Work items

| ID | Work | Owner (section 3) | Acceptance |
|---|---|---|---|
| H1 | Material keys `alpha`, `alphaZ`, `maxServiceTempC`, `tempDerating`: schema, validation, CSV/JSON import (column names and units: 1/K, ppm/K, µm/(m·K), °C, °F), library editor fields. | solver-verifier (`materials.py`); gui-docs (library page) | Import tests for each unit; a bad derating table (missing reference row, factor ≤ 0, unsorted) gives a row-level error. |
| H2 | Sourced values for the built-in materials (PLA-FDM, PETG-FDM, PA12-SLS, AlSi10Mg-LPBF, Ti64-LPBF, 316L-LPBF). Web research; the source goes in the material's `source` text. | solver-verifier | Each value added has a source that a person can open. Missing values stay missing. |
| H3 | Parse `thermal` in `Problem`: reference, case temperatures, thermal-only cases added to `self.cases`; `limits.displacementIncludesThermal`. SpecErrors: unknown material key, case above `maxServiceTempC` (stop the run, name the limit and the fix). | solver-verifier (`problem.py`) | Tests for each error message; a thermal-only case appears in `prob.cases`. |
| H4 | Derating: E and yield per case from the table; used by the as-built check, safety factors, Hill, layer check, impact. | solver-verifier (`run.py`, `physics.py`) | Test: a table with factor 0.5 at the case temperature halves E (displacement doubles) and yield. |
| H5 | Thermal load vector and stress with ε₀ (steps 1–4 above) in `fem.py`; mechanical-only displacement as an extra right-hand side. | solver-verifier (`fem.py`, `run.py`) | Unit tests: e9 bubble thermal load = 0; Σ of thermal nodal forces = 0 for any active set. |
| H6 | Gate checks (numbers after V11 torsion): **V12** free bar, uniform ΔT: end displacement α·ΔT·L to 1e-10 relative and stress < 1e-9·E·α·ΔT, for e9 and hex8fi; **V13** bar on rollers at both ends (x held only), ΔT: σ_x = −E·α·ΔT exactly, σ_y = σ_z = 0; **V14** free beam with a linear ΔT through the depth (per-voxel ΔT through the internal API): curvature κ = α·(ΔT_top − ΔT_bottom)/h; set the tolerance from measured data at 4, 8, 16 layers (midpoint sampling error is O(1/n²)). | solver-verifier (`validate.py`, `provenance.py`) | `python -m anneal validate` → "GATE: OPEN - 14 of 14". Gate result stored again for the new solver hash. |
| H7 | Buckling with thermal pre-stress (step 5). | solver-verifier (`run.py`, `physics.py`) | Test: a column held at both ends, heated: buckling temperature ΔT_cr = π²·I/(α·A·L_eff²) with L_eff = 0.5·L, within the V7 tolerance. |
| H8 | FEA study and report: case temperature and ΔT per case; thermal displacement and mechanical displacement as separate rows; reactions from thermal load; equilibrium normalised by Σ|f| (step 7); "Assumptions": uniform temperature, linear thermal strain, derated values at the case temperature, optimizer used mechanical loads only; "Not modelled": temperature gradients, heat flow, creep, slip in bolted joints (held supports overestimate thermal stress). | solver-verifier (`fea.py`, `report.py`) | Report on the example shows all items. |
| H9 | Check rows: "Service temperature vs material limit" (per case); "Thermal stress share" (thermal part of the peak stress); warning when supports hold all three directions on two or more anchors and ΔT ≠ 0 ("held supports overestimate thermal stress; hold only the bolt-axis direction if the joint can slide"). | solver-verifier (`run.py`) | Rows appear on the example; the warning appears on a doubly clamped bar. |
| H10 | CalculiX sidecar: `*EXPANSION` in the material cards, `*INITIAL CONDITIONS, TYPE=TEMPERATURE` (reference) and `*TEMPERATURE` (case) in the step; engineering-constant orientation for `alphaZ`. Cross-check on a clamped bracket. | solver-verifier (`sidecar.py`, `tools/ccx_bracket.py`) | e9 thermal displacement and peak stress within 5 % of CalculiX tet10 (stress away from supports). |
| H11 | Advanced output: thermal vs mechanical stress share per case; a statement naming the hottest case and its margin to the service limit; material comparison uses the derated values. | solver-verifier (`advanced.py`) | Statements appear on the example. |
| H12 | GUI: "Temperature" fieldset in step 3 (reference temperature; a temperature per load case; "add a thermal-only case"); material `alpha`/`alphaZ`/`maxServiceTempC` fields for custom materials; Result step shows thermal and mechanical displacement separately. Old projects open unchanged. | gui-docs (`app.js`) | `tools/gui_smoke.py`: set case temperatures, save, reload, run; the spec holds `thermal`. |
| H13 | Example `examples/thermal-bracket.json` (metal bracket bolted at two anchors, a mechanical case at 60 °C and a thermal-only cold case) and a golden test (e9 and hex8fi). | solver-verifier | Golden test passes. |
| H14 | README (temperature option, units, what is and is not modelled, the displacement rule) and CHANGELOG 0.4.2. | gui-docs | Every new spec key and material key is in the README. |
| H15 | Owner feedback fixes on 0.4.1 (bugs only). | by area | Each fix has a test. |

### Order

1. H1, H3, H5 with their tests → H6 (the gate must pass before anything else uses the thermal load).
2. H2 (research) in parallel with step 1.
3. H4, H7, H8, H9, H10, H11 in parallel.
4. H12 after H3 (the spec shape is fixed).
5. H13, H14, then the proof.

### Proof for 0.4.2

The same proof as 0.4.0 (`CLAUDE.md`, "Proof"), with these changes:
- The gate is 14 of 14.
- Regression: `examples/bracket.json` and `examples/torque-hub.json` (no `thermal`) give
  bit-identical results to **0.4.1** with e9 and hex8fi.
- New runs: `examples/thermal-bracket.json` and the CalculiX thermal cross-check (H10).
- Merge to master, tag `v0.4.2`.

### Risks

| Risk | What answers it |
|---|---|
| No sourced CTE or derating data for a printed polymer | H2 leaves the value out; the run stops with a message that tells the owner to add a measured or datasheet value. |
| Held supports make thermal stress far too high | H9 warning; the README explains the `dofs` setting for sliding joints. |
| The optimizer ignores the thermal load, so the part can fail the thermal check | The check row fails with the fix "raise volumeFraction or make the joint able to slide"; T3 (later) adds the load to the optimizer. |
| Polymer above its glass transition | H3 stops the run above `maxServiceTempC`. |
| Thermal displacement hides a too-flexible part, or the reverse | The limit uses the mechanical displacement by default; both are reported. |

---

## 5. After 0.4.0 — the road to the goal

Ordered by value to the goal. Each item lists why it matters.

### 0.5 — trust the stress and close the test loop

1. **Print or machine one part and test it.** Write the measured stiffness and failure load next to
   the prediction. Put the result in `library/tests/` and in a regression test. This is the only
   real proof that the tool works; every earlier gate is a proxy for it.
2. **Material calibration from coupons.** Import measured E, Ez, yield and layer strength. Store the
   source of each value. The report says which values are datasheet values and which are measured.
3. **Stress near supports and loads.** Report a stress concentration range from the ZZ indicator
   instead of only excluding anchor zones. Add a "verify finer" run (`anneal run --verify`): an
   as-built-only solve at half the voxel size, with the change shown.
4. **Bolt preload** as a load type (tightening torque → axial clamp force, with a proof-load warning).
   This is not the 0.4.1 torque load: that one is a moment that the part carries.
5. **Fatigue screen**: alternating stress from two load cases versus an endurance limit from the
   library, with the assumptions stated.
6. Small fixes from the external review: `designSpace.minFillFraction`, `resolution.subSamples`,
   `objective.pnorm` (section 6).

### 0.6 — loads from events (the hardest judgement problem)

The largest risk is a correct part for the wrong load case. Anneal must help derive loads.
1. **Load-case advisor**: from an event description (mass, drop height, acceleration, mechanism) to
   load cases, with each assumption visible. The LLM may write the spec; it never computes a value
   at run time.
2. **Mechanism sidecar** (Project Chrono, BSD-3): a rigid-body event → peak joint forces → quasi-static
   load cases, with an equilibrium check.
3. **Modal check**: first natural frequency versus `limits.minFirstModeHz`.

### 0.7 — better shapes for each process

1. **Overhang filter for printing** (prototype on verify-roadmap; it needs continuation of the
   threshold and a proof that it lowers support volume in the slicer).
2. **Lattice / TPMS grading** from the grey density (grey density is the input to grading, not a defect).
3. **Hard minimum member size** and a maximum member size.
4. **Machining**: 5-axis filter in the optimizer, tool-length limits, a stock-from-bar option.

### 0.8 — speed and size

1. Measure where the time goes on a 1-million-voxel part.
2. Reuse the AMG hierarchy for N iterations (find N).
3. Optional GPU path (Warp FEM or similar) only if the CPU path misses the time budget.

### Later

- PicoGK backend for geometry (Windows and macOS arm64 only).
- Thermal loads: derating, thermal stress, conduction, then thermal optimization. Plan and research in `docs/research/thermal-loads.md` (stages T0–T4; T0+T1 first).
- Principal-stress streamlines in the viewer (explain where the material went).

---

## 6. The external physics review (DeepSeek) — status of each item

The review is in `docs/research/deepseek-physics-review.md`. Status on release-0.4:

| Item | Status | Note |
|---|---|---|
| 0.1 regression baseline | Done | `tests/golden/` (hex8fi recorded before e9 existed, plus e9) |
| 0.2 physics harness | Partly | `tests/test_solver.py`, `tests/test_physics.py` |
| 0.3 extensible gate | Done | V1–V10 in `validate.py` |
| 1.1–1.3 element upgrade | Done | e9. Bounds were set from measured data: e9 is 98.7–99.2 % of Timoshenko at 2–8 voxels deep, mesh-independent within 0.6 %. The review's 99.8–100.2 % at 8 deep is **not reachable**: the remaining ~0.7 % is the fully clamped end (no Poisson contraction), which beam theory leaves out. A small factor (`E9_TABLE`, ≤ 1.5 %) stays so the displacement remains conservative. |
| 1.4 re-run V6 | Done | 91.6 % stiffer |
| 2.x buckling | Done | V7: e9 +0.07 % vs Euler without correction |
| 3.x anisotropy | Done | V8; Hill strength added (the review left strength out) |
| 4.1 nodal stress recovery | Done (averaging) | The review's "quadratic patch test to 1 %" cannot pass with constant stress per element. Use SPR if this is needed. |
| 4.2 ZZ estimate | Done | **The review's "indicator drops 5× from nd=2 to nd=4" is wrong** for linear elements: the error is O(h), so it halves. Measured: 0.50 → 0.25 → 0.13. Test in `tests/test_solver.py`. |
| 4.3 replace percentile peak | Open | Do it in 0.5 item 3; calibrate against a notched specimen, not V3 |
| 4.4 `--verify` pass | Open | 0.5 item 3 |
| 5.1 level-set volume | **Rejected with evidence** | Counting voxels above the level matches the marching-cubes volume within 1 %; `f*(f>t)` under-counts by 4–20 %. Test in `tests/test_solver.py`. |
| 5.2 minFill from spec | Open | 0.5 item 6 |
| 5.3 voxel_fill sampling | Open | 0.5 item 6 |
| 5.4 docstring | Open | trivial |
| 5.5 minimum anchor nodes | Done as a warning | A check row warns under 8 nodes; it does not stop the run. |
| 5.6 p-norm | Open | 0.5 item 6 |
| 5.7 load-path repair reporting | Done | Check row "Load paths from every load to a support" |
| 6.1 pressure | Done | On picked faces (area and normal from the face outline). An analytic plate test is still open. |
| 6.2 self-weight | Done | Design-dependent load with the 2 u·dF/dx term; finite-difference test passes; beam test within 1 %. |
| 6.3 preload | Open | 0.5 item 4 |
| 7.1 report sections | Done | Assumptions, Not modelled, Verification |
| 7.2 provenance | Done | Hash of 8 solver files; the GUI compare warning is open |
| 7.3 GUI items | Partly | Machining, solver, pressure, gravity, edges/detail done; buckling tile, verify button, inline min-node warning open |

---

## 7. Requirements

### Owner's machines
- Windows 10/11 x64 (primary). Ubuntu 20.04+ (secondary).
- 4+ CPU cores (8–16 is better: the solver is memory-bandwidth bound). 16 GB RAM (32 GB for fine grids).
- No GPU.

### Software
- Python 3.11 (the Windows and Ubuntu installers use uv to get it).
- Required: numpy, scipy, scikit-image, matplotlib, trimesh, pyamg, manifold3d, pywebview
  (desktop), Edge WebView2 (Windows).
- Optional: cadquery-ocp (STEP import and export), gmsh + CalculiX `ccx` (large deformation,
  cross-check), Playwright + Chromium (GUI smoke test only).

### Licences
All linked code is permissive (BSD, MIT, Apache-2.0, LGPL+OCCT exception for OCP). CalculiX and gmsh
are GPL: run them as separate programs only (the sidecar does this); never import their code.
MMA reference code is GPL-3.0: do not use it; write MMA from Svanberg's paper if it is needed.

---

## 8. Risks and unknowns

| Risk | Kind | What answers it |
|---|---|---|
| A correct part for the wrong load case | judgement — the largest | 0.6 load-case advisor; the report lists assumptions |
| The model and a real part disagree | unmeasured | 0.5 item 1: make one, test one |
| Stress at supports and loads is not meaningful in a linear voxel model | known limit | ZZ indicator, "verify finer", report wording |
| Start-up on Windows | open bug | Stage S |
| Datasheet material values are not the real values (FDM above all) | known | 0.5 item 2: coupon calibration |
| Runs are slow on large parts | measured | 0.8 |

---

## 9. Definitions

| Term | Meaning |
|---|---|
| Gate | `python -m anneal validate`: V1–V10 closed-form checks |
| Golden test | An end-to-end run whose numbers are stored and compared |
| As-built re-solve | The exported surface is voxelized again and solved; all reported results come from it |
| e9 | Hex8 with nine incompatible (bubble) modes, condensed to 24×24 |
| hex8fi | Plain hex8, full 2×2×2 integration (0.3 results) |
| ZZ | Zienkiewicz-Zhu stress error estimate in the energy norm |
| Proof | The list in `CLAUDE.md` → `VERIFICATION.md` |
