# Developer guide — how to change Anneal safely

For Claude Code agents and for the owner. Read `CLAUDE.md` first (rules, branches, proof).
This guide says **where** each kind of change goes and **what proof** it needs.

## 1. Invariants (never break these)

1. **Regression:** a spec that does not use a new key gives bit-identical results to the previous
   release (STL, density and field SHA-256, mass, displacement, safety factor). New check rows may be
   added; old rows must not change.
2. **As-built:** every reported number comes from the re-solve of the exported surface, not from
   the optimizer's density field.
3. **Gate:** `python -m anneal validate` passes. A change to a file in `provenance.SOLVER_FILES`
   changes the solver hash; run the gate again so the result is stored for the new hash.
4. **Determinism:** same spec + same solver hash → same output files.
5. **No silent defaults for physics data.** A material value without a source is not added. A
   missing value gives a `SpecError` that names the key and the fix.
6. **Licences:** permissive only in the Python process. GPL tools (CalculiX, gmsh) run as separate
   programs.
7. **Messages:** every error and every failed check names the fix, in plain technical English.

## 2. Data flow (where things happen)

```
spec JSON ──► problem.Problem(spec)          parse, validate, SpecError
              Problem.build()                grid, fill, frozen, keep, voids
              Problem.boundary(active)       fixed dofs, nodal load vectors per case
          ──► optimize.simp(...)             SIMP + OC; filters; design-dependent loads
          ──► export.output_field / choose_level / keep_load_paths / surface (+ sharp edges)
          ──► finish.finish                  exact features (manifold3d)
          ──► run.evaluate (as-built)        FEM solve, stress, checks data, fea.study
              impact_check, buckling_check, sidecar.nonlinear_check
          ──► run.checks, dfm.assess         check rows (name, ok, warn, value, limit, fix)
          ──► outputs: STL/3MF/STEP, run.json, report.html, advanced graphs, history DB
```

## 3. Recipes

### 3.1 Add a load type (example: torque in 0.4.1, thermal in 0.4.2)

1. **Spec:** parse in `problem.Anchor` (anchor-level) or `problem.Problem` (part-level). Validate
   shape and units; add `SpecError` messages that name the fix. New case names go into
   `Problem.cases`.
2. **Nodal loads:** add to the load vector in `Problem.boundary()` (fixed loads) or to the
   design-dependent path (like `Problem.body_loads` for self-weight) if the load depends on the design.
3. **Optimizer:** fixed loads need no change. A design-dependent load needs the term
   2·u_eᵀ·∂f_e/∂x_e in the sensitivity (see `optimize.simp`, gravity) and a finite-difference test.
4. **As-built:** add the load in `run.evaluate` (and `buckling_check` if it changes the pre-stress).
5. **Stress:** if the load has an eigenstrain (thermal), stress = E·D(B·u − ε₀) in every place that
   computes stress (`fem.stress` callers, `fea.study`, Hill, layer check).
6. **Gate:** a closed-form check in `validate.py` (append to `CHECKS`), tolerance set from measured
   data at several resolutions, for e9 and hex8fi.
7. **Cross-check:** the same load in `sidecar.py` (CalculiX deck) and a run in the proof.
8. **Report, FEA study, advanced output, GUI, README, example, golden test.**

### 3.2 Add a material key

`materials.MAT_KEYS`, `validate_material` (range checks), import column names and units in
`FIELD_WORDS` / `UNIT`, the custom-material fields and library editor in `app.js`, README table.
Built-in values need a source in the material's `source` text.

### 3.3 Add a check row

In `run.checks()` (physics) or `dfm.py` (manufacturing): append
`{"name", "ok", "warn", "value", "limit", "fix"}`. Add the row only when its input exists, so old
specs keep their exact check list. Add a test that makes the row PASS and one that makes it FAIL/WARN.

### 3.4 Add a gate check

A function in `validate.py` that returns `(name, ok, detail)`; append it to `CHECKS`. It must run
in seconds. Use a closed-form answer; set the tolerance from measured data and write the measured
numbers in the docstring. Update `docs/VV-STRATEGY.md` section 2.1.

### 3.5 Add a GUI control

`app.js`: a `row()`/`chk()`/`num()` with `data-bind="path.in.spec"` (or `gui:` for GUI-only state that
`sync()` turns into spec keys). Empty number fields delete the key. Add the control to
`tools/gui_smoke.py`: set it, save, reload, check the saved spec. Old projects must open unchanged.

### 3.6 Add an output format or report section

`run.py` output loop (formats) or `report.py` (`_fea_section`, `_advanced_section`, `_assumptions`).
A new physics option must add its assumption to "Assumptions" and its limits to "Not modelled".

## 4. Tests to write for every change

| Change | Tests |
|---|---|
| New physics | gate check, unit tests of the load vector, FD sensitivity (if design-dependent), golden, CalculiX in the proof |
| New spec key | SpecError tests, regression (spec without the key unchanged) |
| New check row | PASS and FAIL/WARN cases |
| GUI | smoke test step |
| Bug fix | a test that failed before the fix |

## 5. Before you ask for a merge

```
python -m anneal validate
python -m pytest -q tests/
ANNEAL_GOLDEN=1 python -m pytest -q tests/test_golden.py      # when solver files changed
python tools/gui_smoke.py                                        # when GUI files changed
```
Then write in the commit or merge message: what changed, which proof level it adds to
(`docs/VV-STRATEGY.md`), and any number that moved and why.
