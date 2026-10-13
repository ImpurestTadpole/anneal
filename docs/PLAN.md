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
4. **Bolt preload** as a load type (torque → axial force, with a proof-load warning).
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
- Thermal (steady conduction) when a part needs it.
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
