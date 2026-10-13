# Anneal — notes for Claude Code

Anneal is a personal topology-optimization program, similar to Noyron and inspired by PicoGK. It is
written in Python. It runs on Windows 10/11 and Ubuntu 20.04, from a CLI, a web GUI, or a desktop
window (pywebview).

Pipeline: spec JSON + model (STL or STEP) → voxel grid → SIMP optimization (hex8 FEM, AMG-CG) →
surface (marching cubes) → as-built re-solve → checks, DFM, report.

## Language

The owner wants most explanations in plain technical English (ASD-STE100 / ISO 24495-1): short
sentences, active voice, one instruction per sentence, defined terms. Use the same style in the
README and in user-facing messages.

## Branches and rules

- `master` = 0.3.0 (commit 17a3e31). It changes ONLY by a merge that has full proof (see "Proof").
- `release-0.4` = 0.4.0 work. Commit ada107c is the "0.4.0 preview". It is not verified, and it does
  NOT start on the owner's Windows PC (desktop icon, also as admin).
- `verify-roadmap` = experiments that are not in 0.4 (overhang filter, slicer settings). Do not merge.
- Work on your own branch or worktree. Never push to or rewrite master.
- Commit messages end with:
  `Co-Authored-By: Claude <noreply@anthropic.com>`

## Layout

| Path | What |
|---|---|
| `anneal/fem.py` | Voxel FEM. Elements: `e9` (hex8 + 9 incompatible modes, default) and `hex8fi` (plain hex8, 0.3 results) |
| `anneal/optimize.py` | SIMP + OC, density filter, Heaviside projection, machining filter, self-weight |
| `anneal/problem.py` | Spec parsing, anchors (fixed/load, pressure, holes, bolt access), design space, gravity |
| `anneal/run.py` | The run: passes, as-built evaluate, checks, impact, buckling, outputs, run.json |
| `anneal/export.py` | Iso level, load-path guard, surface, sharp edges (`output.edges`, `output.detail`) |
| `anneal/physics.py` | Anisotropic D, Hill, buckling, impact |
| `anneal/fea.py` | FEA study (reactions, equilibrium, stresses, FOS), ZZ stress error, mass properties |
| `anneal/advanced.py` | `output.advanced`: graphs and statements |
| `anneal/provenance.py` | Solver source hash; `python -m anneal validate` stores the gate result |
| `anneal/finish.py` | Exact geometry with manifold3d (keep features, cut keep-outs) |
| `anneal/machining.py`, `dfm.py` | 3/5-axis machining filter and checks; printability checks |
| `anneal/sidecar.py` | Optional CalculiX + gmsh large-deformation check |
| `anneal/stepout.py` | STEP export (OCP) |
| `anneal/validate.py` | Validation gate V1–V10 |
| `anneal/gui/` | `server.py` (HTTP API), `desktop.py` (pywebview, Windows taskbar icon), `static/` (app.js, viewer.js) |
| `tests/` | pytest. `test_golden.py` runs only with `ANNEAL_GOLDEN=1` (about 3 min per case) |
| `tools/` | `prove_release.py`, `write_verification.py`, `gui_smoke.py` (headless Chromium), `ccx_bracket.py` |

## Commands

```
pip install -e .                      # plus: pip install manifold3d cadquery-ocp (STEP), gmsh (optional)
python -m anneal validate             # gate: must print "GATE: OPEN - 10 of 10"
python -m pytest -q tests/
ANNEAL_GOLDEN=1 python -m pytest -q tests/test_golden.py
python -m anneal run examples/bracket.json
python -m anneal gui                  # web GUI;  the desktop icon uses anneal/gui/desktop.py
python tools/gui_smoke.py             # Playwright, headless Chromium
```

## Proof (needed before anything goes to master)

1. `python -m anneal validate` → 10 of 10.
2. Full pytest passes, golden tests included.
3. Regression: `examples/bracket.json` with `"solver": {"element": "hex8fi"}` gives the same STL,
   density and field SHA-256, mass, displacement and safety factor as 0.3.0 (bit for bit).
4. Physics run (`examples/bracket-pla.json`), interfaces run (`examples/interfaces.json`), CalculiX
   cross-check, GUI smoke test.
5. `tools/prove_release.py` + `tools/write_verification.py` → `VERIFICATION.md`.
6. The app starts on Windows 10/11 (desktop icon and `python -m anneal gui`) and on Ubuntu 20.04.

## Work list (open)

Startup (highest priority)
- [ ] Find why 0.4.0 does not open on Windows. Suspects: `desktop.py` taskbar code
      (SetCurrentProcessExplicitAppUserModelID, WinForms Form.Icon via pythonnet) raising before the
      window opens; the missing `manifold3d` dependency; errors that the windowed launcher hides.
      Make start-up failures visible (log file + message box) and make every optional feature fail soft.

Verification
- [ ] Run the gate, full pytest and golden tests on ada107c; fix failures.
- [ ] Update `tools/prove_release.py` / `write_verification.py`: regression with hex8fi; compare only
      check rows that exist in 0.3.0 and list new rows; add e9 (V3/V7/V10), the feature run and gate count 10.
- [ ] Check "Member thickness in voxels" row: it said 36 % ≥ 3 voxels on a cantilever with ≥ 2 mm members.
- [ ] Test sharp edges with designSpace "model"; pressure together with exactFeatures.

GUI and docs
- [ ] Run and extend `tools/gui_smoke.py` for: solver element, edges/detail, custom smoothing,
      advanced output, pressure unit (N/MPa) on picked faces, own-weight (gravity), machining fields,
      Result step FEA and advanced blocks. Old projects with output.smoothing/upsample must still open.
- [ ] README: e9 element, gravity, pressure, edges/detail, advanced output, machining, FEA study,
      ZZ error, report Assumptions/Not modelled/Verification, provenance, 10-check gate.

Later
- [ ] Bolt preload load case (DeepSeek plan 6.3).
- [ ] Release: merge release-0.4 → master after the proof, tag v0.4.0, build the zip.

## Decisions already made (do not reopen without data)

- Physics in 0.4: anisotropic (print-aware) material, buckling, equivalent-static impact, CalculiX
  large-deformation check. Slicer and overhang filter are NOT in 0.4.
- Keep regions and anchor freeze zones never add material outside the model ("no bubbles").
- The iso-level volume estimate counts voxels above the level. That matches marching cubes within 1 %.
  The suggestion `f*(f>t)` under-counts by 4–20 % and was rejected (test in `tests/test_solver.py`).
- e9 on cube voxels equals the Taylor (1976) incompatible-modes element; it passes the patch test (V10).
