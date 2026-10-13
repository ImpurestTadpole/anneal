# Anneal: remediation plan for the physics review

An execution plan for a code agent. Items are ordered by dependency and by leverage. Each item has: **files**, **symbols**, **change**, **test**, **acceptance**, **risk / rollback**.

Conventions: all work on a branch, one PR per phase. The validation gate (`python -m anneal validate`) must be green before merging any phase. Each phase extends `validate.py` with new checks *first* (red), then makes them pass.

---

## Phase 0 — Groundwork

### 0.1 Freeze the current behaviour as a regression baseline

- **Files:** new `tests/golden/`, new `tests/conftest.py`, new `tests/test_golden.py`
- **Change:**
  - Add a pytest suite that runs `anneal run` on two fixed specs (`tests/golden/cantilever.anneal.json`, `tests/golden/plate_hole.anneal.json`) and asserts `run.json` fields to a tolerance: `optimized.massG ±1%`, `optimized.maxDisplacementMM ±2%`, `optimized.safetyFactor ±3%`, `optimizer.iterations ±10%`, `optimizer.amgBuilds ±1`.
  - Generate goldens *now*, on the current solver, before touching `fem.py`.
- **Acceptance:** `pytest tests/test_golden.py` passes on `main`.
- **Rationale:** every later phase must be provably not a regression on the parts that were already correct.

### 0.2 Add a physics-behaviour harness

- **Files:** new `tests/physics.py`
- **Change:** helpers that a check can call:
  - `tension_bar(nd, L, ny, nz, h, nu, E)` → uniform end traction, returns tip `u_x`
  - `cantilever(nd, b, d, L, P, nu, E)` → returns tip `u_z`, tip `θ_z`, and centroid `σ_xx` profile
  - `patch_test(poly_order)` → linear/quadratic displacement field prescribed on all boundary nodes, interior recovered by the solver; returns L2 error
- **Acceptance:** the harness itself is covered by `validate.py` (`tension_bar` must match `FL/AE` to `1e-12`).
- **Rationale:** the element change is the highest-risk item; without a rigid patch test and a displacement-based cantilever reference, "no locking" is unverifiable.

### 0.3 Make the validation gate extensible and CI-runnable

- **Files:** `validate.py`
- **Change:** convert `CHECKS` to a list of `(id, name, fn, weight)` and add a `--json` output; assert in `tests/test_validate.py` that `run_all()` returns `True`. Add V7 (patch test) and V8 (rigid-body patch on a distorted-but-hex grid) as *expected-to-fail* placeholders that Phase 1 will turn green.
- **Acceptance:** `python -m anneal validate` returns 0; `python -m anneal validate --json` emits a machine-readable report.

---

## Phase 1 — Element upgrade (highest leverage)

**Goal:** remove shear locking at the element level so `run.py` can delete the `LOCKING` table and the `lockingFactor` correction, and so stress and displacement are simultaneously correct.

### 1.1 Choose and justify the element

- **Files:** `fem.py`, new `docs/element.md`
- **Change:** implement **incompatible-modes hex8 (Wilson/E9, Taylor–Beresford–Wilson)** as the default; keep the existing full-integration hex8 behind `FEM(grid, active, fixed, nu, element="hex8fi")`. Rationale for E9 over the alternatives:
  - B-bar fixes volumetric locking, not shear locking. Not sufficient here.
  - 1-point + hourglass is cheaper but has a stabilization parameter to tune and is less accurate for bending-dominated members.
  - Incompatible modes: same 24-node connectivity and assembly, `ke` stays 24×24 after static condensation, and the centroid `B0` recovery remains valid.
- **Change:** `hex8_matrices(nu, h, element="e9")` returns `(ke24, B0, D)` as today. Add `hex8_incompatible(nu, h)` returning `(ke24, B0, D, T_cond)` where `T_cond` is the 24×24 (or 24×27→24×24) condensation operator if the agent needs to recover internal strains for stress. Document in `docs/element.md`:
  - Number of incompatible modes used (9 for Taylor–Beresford–Wilson with the *enhanced* version that passes the patch test; 3 for the original Wilson which does not pass the patch test — must use the enhanced version).
  - Static condensation formula: `ke = ke_aa - ke_ab @ inv(ke_bb) @ ke_ba`.
  - Why `B0` at centroid is still the right place for stress recovery (for linear elasticity, the E9 element's centroid strain is a superconvergent point).
- **Risk / rollback:** if the enhanced 9-mode version does not pass the patch test, fall back to 1-point + Flanagan–Belytschko hourglass; keep both behind the `element=` kwarg.

### 1.2 Wire it through

- **Files:** `fem.py`
- **Change:**
  - `FEM.__init__` accepts `element="e9"` and stores it.
  - `self.B0` and `self.D` semantics unchanged; `self.ke` is the 24×24 condensed matrix.
  - Add `FEM.element_strain(u_e)` and `FEM.element_stress(u_e)` that apply `T_cond` internally, so `stress()`, `von_mises()`, and `element_energy()` are unchanged at the call site.
- **Test:** `tests/physics.py::cantilever` with `nd ∈ {2,4,8,16}` must converge to the Timoshenko reference with *no* dependence on `nd` at `nd ≥ 4` (see 1.3).
- **Acceptance:** all existing `validate.py` checks pass; V2 tolerance tightens to `1e-10`.

### 1.3 Tighten V3 and delete the correction

- **Files:** `validate.py`, `run.py`, `export.py`, `report.py`
- **Change:**
  - `check_cantilever` bounds become: `nd=2 → [0.96, 1.02]`, `nd=4 → [0.99, 1.01]`, `nd=8 → [0.998, 1.002]`.
  - Remove `LOCKING` table and `locking_factor()` from `run.py`. `built["maxDisplacementMM"]` is now the raw value; `built["lockingFactor"] = 1.0` and `built["maxDisplacementRawMM"]` is deleted (or set equal) for record compatibility.
  - `checks()`: remove the "Members ≥ 6 voxels thick" warning check entirely (it existed only to justify the correction) *or* repurpose it as informational.
  - `report.py`: drop the "corrected for shear locking" language and the derivation line.
- **Acceptance:** goldens change by ≤5% on the plate with thin members (expected — that is the fix); goldens on the stubby cantilever change by ≤1%.
- **Rationale:** this is the single biggest accuracy win and it removes the non-conservative stress/displacement mismatch identified in the review.

### 1.4 Re-run V6 and update the reference

- **Files:** `optimize.py::benchmark_cantilever`
- **Change:** the "stiffer than uniform by X%" number will change with the element. Record the new baseline; the check becomes `stiffer_pct > 20` (currently passes with margin) and `|vol_err| < 1e-3`.
- **Acceptance:** V6 green.

---

## Phase 2 — Buckling

**Goal:** catch the failure mode SIMP loves to create — slender compression members — before it reaches the printer.

### 2.1 Geometric stiffness

- **Files:** `fem.py`
- **Change:** add `FEM.geometric_stiffness(u_full, sig_centroid)` returning a sparse `Kg` on the same free-DOF index set. Standard hex8 `Kg` from the centroid stress: `Kg_e = ∫ B_g^T σ B_g dV` with `B_g` the 3×24 shape-gradient matrix (`[dN/dx; dN/dy; dN/dz]`). Integrate with the same 2×2×2 Gauss rule.
- **Test:** `tests/physics.py::euler_column` — a straight column, `L/r` from 20 to 120, solver buckling load within 5% of `π²EI/(kL)²` for the first mode.
- **Acceptance:** `euler_column` passes at `L/r ≥ 20` for both `element="e9"` and `element="hex8fi"`.

### 2.2 Buckling eigenvalue solve

- **Files:** `fem.py`
- **Change:** `FEM.buckling(K, Kg, n_modes=4, sigma=1e-3)` returning `(λ, φ)` using `scipy.sparse.linalg.eigsh(K, k=n_modes, M=-Kg, sigma=sigma, which="LM")` on the free-DOF reduced system. `-Kg` is symmetric indefinite; use `sigma` to shift into the positive spectrum. Fall back to `lobpcg` if `eigsh` fails.
- **Acceptance:** `euler_column` returns the first eigenvalue within 5% of theory on a uniform column, and the mode shape has one half-wave (check by `argmax |φ|` position).

### 2.3 Wire into `run.py`

- **Files:** `run.py`, `problem.py`, `report.py`, `materials.py`, `optimize.py`
- **Change:**
  - Add spec field `limits.minBucklingFactor` (default `None` → skip). Add library field `bucklingSafetyFactor` per material if desired.
  - In `evaluate()`: after solving, build `Kg` from the peak-stress field *or* from the per-case displacement, and return `res["bucklingFactor"] = λ_min` and `res["bucklingMode"] = φ_min` (reduced to element-wise |φ| for reporting).
  - In `checks()`: if the limit is set, add check "Buckling safety factor (linearized)" with value `λ_min` and limit `minBucklingFactor`.
  - In `report.py`: add a tile and a projection panel of the first buckling mode shape.
- **Acceptance:** on a test part that is intentionally a slender compressive strut (add `tests/golden/strut.anneal.json`), the check fires with a factor < 1 and the fix message names `minMemberMM` and `volumeFraction`.
- **Risk / rollback:** buckling on the *optimized* shape uses the as-built re-solve — this is correct but the re-solve uses `voxel_fill` on the smoothed mesh, which can have a slightly different member topology than the density field. That is the right thing: the check is on the part you will print. Document it.

### 2.4 Add to `simplify`? No.

- **Decision:** do *not* add a buckling constraint inside the SIMP loop in this phase. That is a research-grade extension (eigenvalue constraints in OC need an MMA-class optimizer). Add it to the roadmap in `docs/element.md` but ship the post-hoc check first. Buckling-sensitive parts are caught by an iterative mass pass: if `λ_min < limit`, the volume-fraction search in `run.py::next_volume_fraction` already raises `vf` on the next pass — extend the stop criterion to also require `λ_min ≥ limit`.

---

## Phase 3 — Anisotropy for FDM

**Goal:** stop reporting isotropic displacement for a material whose `zStrengthFactor` is 0.5.

### 3.1 Transversely isotropic D matrix

- **Files:** `fem.py`
- **Change:** `elasticity_D_iso(nu)` stays. Add `elasticity_D_transversely_iso(E1, E2, G12, nu12, nu23, axis)`. Build the 6×6 stiffness in the local material frame (axis 3 = build direction) then rotate with the standard Bond matrix `T(axis) D_local T(axis)^T`. Provide `elasticity_D(material, axis)` dispatcher.
- **Test:** `tests/physics.py::iso_reduces_to_iso` — with `E1 = E2`, `ν12 = ν23`, `G12 = E/(2(1+ν))`, the rotated D reproduces the isotropic D for every axis in `{+X, +Y, +Z, oblique}` to `1e-12`.
- **Acceptance:** test green; `fem.hex8_matrices` accepts an optional `D=` matrix and uses it as-is.

### 3.2 Material schema extension

- **Files:** `materials.py`
- **Change:** add fields `E2`, `G12` (and derived defaults) plus `anisotropyAxis` (or read `process.buildDirection`). Validation: `E1 ≥ E2 > 0`, `|ν12| < 0.5`, `G12 > 0`; if any of `E2/G12` are absent, treat as isotropic (back-compat).
- **Acceptance:** existing library loads; `validate_material` accepts both shapes; `library.json` written by the app round-trips.

### 3.3 Use the anisotropic D in solve

- **Files:** `run.py::evaluate`, `optimize.py::simp`, `problem.py`
- **Change:**
  - `Problem` builds `self.D_mat = elasticity_D(self.material, axis=bdir)` once.
  - `FEM` accepts `D_mat` and uses it in `assemble` / `stress` via the element `ke` from `hex8_matrices(nu=None, D=D_mat, h)`.
  - `simp` uses the same D for the sensitivity; the element energy is unaffected by the change of D (it is `u^T ke u`), so the derivative formula is unchanged.
- **Acceptance:** goldens on a *isotropic* material are unchanged to 1e-12 (back-compat). A new golden `tests/golden/fdm_bracket.anneal.json` with `E2 = 0.5·E1` produces a measurably larger `maxDisplacementMM` than the isotropic run, in the direction predicted by the build direction.

### 3.4 Report the direction and the two bounds

- **Files:** `report.py`, `run.py`
- **Change:**
  - Report tile: "Build direction used for stiffness: `+Z`".
  - For FDM materials, run a second *isotropic* solve with `E = min(E1, E2)` and report both displacements as a bracket. This is cheap (one extra solve) and honest.
  - In the notes section, state explicitly: "FEA used transversely isotropic material with `E1=..., E2=..., G12=...`; reported displacement bracket is `[upper, lower]`."
- **Acceptance:** the report shows the bracket for FDM goldens and a single number for isotropic ones.

---

## Phase 4 — Stress recovery

**Goal:** move the reported peak stress off "99.5th percentile at element centroids, anchor neighbourhoods excluded" and onto a defensible extrapolation.

### 4.1 Nodal stress recovery

- **Files:** `fem.py`
- **Change:** `FEM.nodal_stress(u_full, D)` — extrapolate centroid stresses to the 8 nodes with the standard `N(ξ,η,ζ)` interpolation matrix evaluated at the corner nodes, then average over elements sharing each node.
- **Test:** `patch_test(poly_order=2)` — quadratic displacement on a cube; recovered nodal stress must be within `1%` of the analytic field everywhere.
- **Acceptance:** `test_patch_stress_quadratic` green.

### 4.2 Zienkiewicz–Zhu error estimate

- **Files:** new `recovery.py`
- **Change:** SPR patch recovery on the element patches (weighted least-squares fit of the stress field on each patch), returning `σ*` (recovered), and `‖σ_h - σ*‖_E` per element.
- **Acceptance:** the error indicator peaks near the support and load anchors of the cantilever and near the hole in the plate; the global indicator decreases by ≥5× from `nd=2` to `nd=4`.

### 4.3 Replace the percentile heuristic

- **Files:** `run.py::evaluate`
- **Change:**
  - `peakStressMPa` becomes `max(σ_vm_nodal) * safety_margin` where `safety_margin = 1 + c·η_local` with `η_local` the ZZ error at the peak element and `c` from the validation gate (calibrate so that V3's cantilever matches the analytic peak to within 5%).
  - Remove `maxStressAtAnchorsMPa` and the "excluded anchors" prose. Instead report a separate "stress concentration factor near anchor `X`: 3.2" derived from the ZZ indicator and a user-visible range.
  - `safetyFactor` uses the corrected peak; keep the raw in `safetyFactorRaw` for traceability.
- **Acceptance:** goldens shift on the plate by ≤10% (expected); the check `Safety factor` is now conservative at all tested `nd`.

### 4.4 Optional: adaptive refinement

- **Files:** new `refine.py`
- **Change:** a helper that runs `evaluate` on the as-built mesh, marks the top 5% of elements by ZZ indicator, and returns a recommended voxel size `h/2` for a `--verify` pass. Do *not* wire it into `anneal run` yet; expose it as `anneal run --verify` (a second, finer, as-built-only solve). This gives the user a "sharper answer" button without touching the optimizer.
- **Acceptance:** on the plate golden, `--verify` reduces the reported peak stress and displacement by a factor consistent with the ZZ indicator, and completes in <2× the base run's wall time.

---

## Phase 5 — Smaller correctness fixes

Bundle these into one PR; each is independently reviewable but small.

### 5.1 Level-set volume

- **Files:** `export.py::choose_level`
- **Change:** `v = float((f * (f > t)).sum())`; keep the 0.3–0.7 clamp and log it in `report.py`.
- **Test:** `tests/test_export.py::test_choose_level_matches_target` — synthetic field, target within 0.1 voxel-volume.
- **Acceptance:** goldens shift by ≤0.5% on binary SIMP fields; by more on grey fields (the fix matters exactly there).

### 5.2 `MIN_FILL` from the spec

- **Files:** `problem.py`, `cli.py`, `app.js`
- **Change:** `designSpace.minFillFraction` (default 0.05). Thread through `Problem.build`. Document in `docs/`.
- **Acceptance:** existing specs unchanged; setting it to 0.01 keeps small features.

### 5.3 `voxel_fill` sampling

- **Files:** `geometry.py`
- **Change:** `s = 3` → `s = 4` when `h > 0.4 mm` (or expose as `spec.resolution.subSamples`). Update the docstring.
- **Acceptance:** goldens unchanged (they use `h ≤ 0.3`); a new coarse-mesh golden shows a smaller mass error against analytic volume.

### 5.4 Hex8 Jacobian docstring

- **Files:** `fem.py::hex8_matrices`
- **Change:** one-line docstring fix; no behaviour change.

### 5.5 Minimum anchor nodes

- **Files:** `problem.py::boundary`
- **Change:** after `sel = a.nodes(...)`, require `sel.size >= 8` for `role == "fixed"` and `sel.size >= 1` for `role == "load"`. Error message names the anchor, the region bounds, and the fix ("enlarge the region by at least `2·h` in every direction", "raise `freezeMM`").
- **Test:** `tests/test_problem.py::test_hinge_anchor_rejected`.
- **Acceptance:** test green; existing specs unaffected.

### 5.6 p-norm exponent

- **Files:** `problem.py`, `app.js`
- **Change:** `objective.pnorm` (default 4, range 2–16). Wire through `optimize.simp`.
- **Acceptance:** goldens with one load case unchanged; multi-case golden at `pnorm=8` (old default) unchanged.

### 5.7 `keep_load_paths` reporting

- **Files:** `run.py`, `report.py`
- **Change:** if repair fired, add a `checks` entry "Load-path repair: added material along N voxel paths" with `ok: true, warn: true`. Add the number of added voxels to `derived`.
- **Acceptance:** on a spec designed to break connectivity, the warning appears.

---

## Phase 6 — New load types

Add one at a time, each with its own golden.

### 6.1 Pressure

- **Files:** `problem.py::Anchor`, `fem.py`, `app.js` (picker UI)
- **Change:** `role: "pressure"`, `region` + `magnitudeMPa` + `direction` (surface normal or fixed vector). During `boundary()`, integrate `p · n` over the surface faces of the design space that lie inside the region. The mesh is `prob.mesh` (or the design-space boundary for `box`).
- **Test:** `tests/physics.py::pressure_plate` — a clamped circular plate under uniform pressure matches the analytic deflection to 5%.
- **Acceptance:** golden `tests/golden/pressure_plate.anneal.json` runs and matches theory.

### 6.2 Self-weight / inertial

- **Files:** `problem.py`, `fem.py`
- **Change:** `role: "gravity"`, `region`, `acceleration` (mm/s²) or `direction` + `g`. Body force per element = `ρ · a · V_e · φ_e`. Note: this is a *follower* of density, so it enters `F` as `F_e(x) ∝ φ · x` and the SIMP sensitivity gains an extra term. Derive it: `∂c/∂x = -u^T ∂K/∂x u + 2 u^T ∂F/∂x` (the second term is usually neglected; do **not** neglect it for gravity-dominated parts). Document.
- **Acceptance:** `tests/physics.py::self_weight_beam` matches `q L^4 / (8EI)` to 5% for a distributed load from density.

### 6.3 Preload (bolted joints)

- **Files:** `problem.py`, `kernel.FASTENERS`
- **Change:** `role: "preload"`, `bolt: "M5"`, `torqueNm`. Convert to axial preload `F = T / (K·d)` with `K = 0.2`. Apply as an inward pressure on the bolt-wall region. Warn if the resulting preload exceeds 70% of the bolt's proof load (look up in a small table; skip if not present).
- **Acceptance:** `tests/golden/bolted_flange.anneal.json` produces a bolt-wall stress that is compressive at the interface and tensile in the shank, with the right sign.

---

## Phase 7 — Report and UX polish

### 7.1 Report sections

- **Files:** `report.py`
- **Change:**
  - New "Assumptions" section listing: element (`e9`), material model (isotropic / transversely isotropic + axis), peak-stress method (SPR + ZZ), load types used.
  - New "Not modelled" section: thermal, contact, fatigue, plasticity, creep, dynamic, residual stress. Same list as the review, one line each.
  - "Verification" section: the current `validate.py` numbers (rigid body, tension, cantilever ratios per `nd`, patch test, determinism hash) with the sha256 of `fem.py` at the moment of the run. This makes a report self-auditing.

### 7.2 Solver provenance

- **Files:** `run.py`, `record`
- **Change:** add `"solver": {"element": "e9", "recovery": "spr", "sourceSha256": <hash of fem.py>}` to `run.json`. The GUI history view shows it. This means two runs are only comparable if the hash matches; `renderCompare` in `app.js` warns otherwise.

### 7.3 GUI

- **Files:** `app.js`, `index.html`, `style.css`
- **Change:**
  - Buckling factor tile (when computed).
  - Displacement bracket display for anisotropic materials.
  - A "verify (finer)" button on the Result step that runs `--verify` and shows the delta.
  - Anchor editor: minimum-node warning surfaced inline (not just in the log).

---

## Execution order and parallelism

```
Phase 0  (blocking, ~1 day)
   │
   ├── Phase 1 (element)  ─── blocks Phase 4 (recovery tolerance depends on element)
   │
   ├── Phase 2 (buckling) ─── depends on 1.1 for accurate geometric stiffness
   │
   ├── Phase 3 (anisotropy) ─ independent of 1/2 if elasticity_D is added as a matrix
   │
   └── Phase 5 (small fixes) ─ can start in parallel with 1, merge after
```

Recommended merge order: **0 → 1 → 2 → 3 → 4 → 5 → 6 → 7**. Phases 3 and 5 can be developed in parallel by a second agent.

## Stop-the-line conditions

Any of these halts the merge:

1. `python -m anneal validate` is not green.
2. `tests/test_golden.py` fails, and the change in goldens is not explained in the PR body with the physical reason.
3. The patch test (V7) or rigid-body patch (V8) fails.
4. The determinism check (V5) changes hash for the same input.
5. `fem.py` or `optimize.py` is modified without a corresponding new or updated check in `validate.py`.

## What is deliberately *not* in this plan

- Buckling *constraints* inside SIMP (needs MMA). Post-hoc check + volume-pass iteration is the phase-2 deliverable.
- Contact, plasticity, fatigue, thermal. Out of scope; the report says so.
- A full anisotropic strength criterion (Tsai–Wu / Hill) — only the transversely isotropic *stiffness* is added, with the existing layer-strength check kept for the strength part. Flag this in `docs/element.md` as future work.
- Adaptive remeshing *inside* the optimization loop. Only the `--verify` pass is in scope.

## Acceptance for the whole plan

After all phases:

- `python -m anneal validate` green with V1–V9 (V7/V8 patch tests, V9 anisotropy-reduces-to-isotropy).
- Cantilever at `nd ≥ 4` matches Timoshenko to 1% with **no** empirical correction factor anywhere in the source.
- Euler column buckling matches theory to 5% at `L/r ≥ 20`.
- The FDM bracket golden shows a displacement bracket whose width is within 15% of the analytic transversely-isotropic beam.
- A quadratic-displacement patch test recovers nodal stress to 1% and the ZZ indicator drops 5× from `nd=2` to `nd=4`.
- The report on any run contains a "Verification" section keyed to the source hash, and a "Not modelled" section listing the assumptions the user must accept.