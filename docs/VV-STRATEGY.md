# Anneal — verification and validation strategy

This document says how Anneal proves that its results are correct, what is proved today, and what
to add. It uses the standard terms of computational solid mechanics (ASME V&V 10, Roache, Oberkampf
& Roy). Every new feature must say which of the five levels below it adds evidence to.

`VERIFICATION.md` (at the repository root, made by `tools/prove_release.py`) is the **evidence for
one release**. This file is the **strategy** behind that evidence.

---

## 1. The five levels

| Level | Question | Who answers it | Where in Anneal |
|---|---|---|---|
| 1. Code verification | Does the code solve the equations correctly? | Closed-form solutions, patch tests, convergence order | Gate `validate.py`, `tests/` |
| 2. Optimizer verification | Are the sensitivities right, and does the optimizer find known good layouts? | Finite differences, benchmark problems | `tests/test_solver.py`, V6 |
| 3. Solution verification | How large is the discretisation error **in this run**? | Error estimators, grid refinement | ZZ estimate in the FEA study, "verify finer" (planned) |
| 4. Pipeline verification | Is the exported part the part that was analysed? | As-built re-solve, geometry checks | `run.py` as-built, exact features, STEP volume check |
| 5. Validation | Does the real part behave like the model? | Physical tests with uncertainty | **Not done yet** — the most important gap |

A pass at one level never replaces another level. A perfect solver (level 1) on the wrong load case
or the wrong material values still gives a wrong part (level 5).

---

## 2. Level 1 — code verification

### 2.1 What exists (gate V1–V10, more planned)

| Check | What it proves | Tolerance |
|---|---|---|
| V1 rigid body | No energy in rigid motion; 6 zero modes (e9, hex8fi) | 1e-10 |
| V2 tension | Uniform stress state exact | 1e-8 |
| V3 cantilever | Bending without locking (e9); hex8fi locking table | e9 98–101 % of Timoshenko |
| V4 partial volume | Fill-fraction stiffness exact in parallel layers | 1e-8 |
| V5 determinism | Bit-identical reruns | hash |
| V6 SIMP benchmark | Optimized beats uniform at equal mass | > 20 % |
| V7 buckling | Euler column | e9 within 1 % |
| V8 anisotropy | Transversely isotropic stiffness and Hill | 1e-8 |
| V9 impact | k = EA/L, F = √(2Ek) | 2 % / 1 % |
| V10 patch test | Linear field exact (both elements, isotropic and anisotropic) | 1e-10 |
| V11 torsion | Saint-Venant square bar (planned, 0.4.1) | from measured data |
| V12–V14 thermal | Free bar, held bar, gradient beam (planned, 0.4.2) | see PLAN 4B |

### 2.2 Gaps and what to add

1. **Convergence order (method of manufactured solutions, MMS).** Today the gate checks values at
   a few resolutions. It does not check the *rate* of convergence. MMS proves the rate:
   - Choose a smooth displacement field, for example u = A·sin(πx/L)·cos(πy/L)·(1+z/L) per component.
   - Compute the body force b = −∇·σ(u) analytically (sympy) and integrate it into nodal loads with
     2×2×2 Gauss points.
   - Hold the boundary nodes at the exact u. Solve on 3–4 grids (h, h/2, h/4).
   - The displacement error (L2) must fall as O(h²) and the energy-norm error as O(h). The observed
     order p = log(e₁/e₂)/log 2 must be within ±0.1 of the theory.
   - Do this for e9 and hex8fi, isotropic and anisotropic.
   - This becomes a gate check (number after the thermal checks). It catches errors that a
     single-value test can hide, for example a wrong factor in a rarely used term.
2. **NAFEMS linear benchmarks.** These are industry-standard reference problems with published
   target values. They also measure the effect of voxel stair-steps on curved boundaries.

   | Benchmark | Physics | Target | Use in Anneal |
   |---|---|---|---|
   | LE1 elliptic membrane | plane stress, curved edges | σyy = 92.7 MPa at point D | thin slab (1 voxel deep, plane-stress check); measures stair-step error at a curved edge |
   | LE10 thick plate | 3-D, pressure 1 MPa | σyy = −5.38 MPa at point D | pressure load (0.4) |
   | LE11 cylinder/taper/sphere | thermal, T = √(x²+y²) + z, α = 2.3e-4 | σzz = −105 MPa at point A | thermal stress (0.4.2) |

   Voxels make curved edges into stairs. Expect slow convergence of the stress *at* a curved
   boundary. Test the stress at the target point at three voxel sizes. Accept when the trend
   converges to the target, and record the error at each size. Use the trend as the documented
   accuracy for stress at curved edges. Put these in `tests/benchmarks/` (slow, like the goldens),
   not in the gate.
3. **Cross-code checks.** CalculiX (tet10) on the as-built STL is already used. Add it to the proof
   for every new physics (torque, thermal, pressure). CalculiX is GPL: run it only as a separate
   program.

---

## 3. Level 2 — optimizer verification

| Check | Status | Add |
|---|---|---|
| Sensitivity vs finite differences | Done for self-weight | Every design-dependent term (thermal in T3, any new filter) gets an FD test at three random voxels, relative error < 2e-3 |
| Filter / projection / mill filter adjoints | Done for mill filter (earlier) | Keep one FD test per filter in `tests/` |
| Volume constraint exact | V6 | — |
| Known layouts | Cantilever, MBB (earlier spike) | A 3-D benchmark against a published reference code (for example a Python port of `top3d`, same mesh, penalty, filter): compliance within 2 % at equal settings |
| Determinism | V5 | — |

---

## 4. Level 3 — solution verification (each run)

The question is "how large is the discretisation error in *this* part?". Two tools:

1. **Error estimate (exists).** The FEA study reports the Zienkiewicz-Zhu estimate in the energy
   norm. For voxel elements it falls as O(h) (it halves when h halves — verified in
   `tests/test_solver.py`). It is a stress-resolution indicator; displacement is much more accurate
   than the ZZ number suggests.
2. **Grid refinement (to add — "verify finer").** Re-solve the as-built part at h/2 (and, for a
   full check, h/4). With three grids, compute the observed order p and the Grid Convergence Index
   (Roache): GCI = Fₛ·|ε|/(r^p − 1), with Fₛ = 1.25 for three grids and r = 2. Report the
   extrapolated displacement and peak stress, and the GCI as an error band. Two grids: use the
   theoretical order and Fₛ = 3.
   - Acceptance for the feature: on the cantilever, the extrapolated tip deflection is within 0.5 %
     of the converged value.

Report both in the "Verification" section of the report. A result without an error band is a
point estimate; say so.

---

## 5. Level 4 — pipeline verification

| Step | Risk | Check (exists / to add) |
|---|---|---|
| Model import | wrong units, open mesh | watertight flag (exists); unit sanity (to add: warn if the part is < 1 mm or > 5 m) |
| Voxelization | volume error at coarse voxels | to add: report voxel volume vs mesh volume; warn above 2 % |
| Density → surface | iso level, smoothing changes volume | as-built re-solve (exists) |
| Exact features | Boolean failure | fallback + check row (exists) |
| Sharp edges | clip failure | fallback (exists) |
| STEP export | decimation changes shape | volume check vs mesh (exists); add Hausdorff distance < 0.1 mm |
| Loads on nodes | wrong total force | equilibrium in the FEA study (exists): reactions balance loads to < 1e-6 |

---

## 6. Level 5 — validation with physical tests (the largest gap)

No Anneal part has been made and tested. Until one has, every result is unvalidated. Plan:

### 6.1 Material data first

Datasheet values for printed polymers are not the values of your printer. Before a part test:
- **Coupons:** tensile bars (ASTM D638 type I or IV for polymers; ASTM E8 for metals), printed
  with the same printer, material, layer height, infill and orientation as the part. Print in the
  XY plane and upright (Z) for Ez and the layer strength.
- At least 5 coupons per direction. Record E (slope 0.05–0.25 % strain), yield (0.2 % offset or
  peak for brittle polymers), mean and standard deviation.
- Put the values in the library with `source: "coupon test <date>, n=5, printer, settings"`.

### 6.2 The first validation part

- Choose a simple part with a clear load path: the bracket example, or a cantilever bracket with
  one bolt pattern and one load point.
- Make 3 parts. Measure mass and key dimensions (calipers, ±0.05 mm).
- Fixture: bolt the part as in the spec (same bolts, torque recorded). Load with weights or a load
  frame at the load anchor, in the spec direction.
- Measure displacement at the load point with a dial indicator or a laser (±0.01 mm), at 4–5 load
  steps inside the linear range. Fit the stiffness k = ΔF/Δu.
- Then load to failure (optional, destructive): record the failure load and location.

### 6.3 Comparison with uncertainty

- Prediction: Anneal stiffness with the coupon E, on the as-built geometry (use the measured mass
  to check the geometry).
- Uncertainty of the prediction: from E (coupon standard deviation), geometry (mass difference),
  and discretisation (GCI from section 4).
- Uncertainty of the test: fixture compliance (measure the fixture alone), gauge accuracy, part
  scatter (3 parts).
- **Acceptance:** |k_test − k_model| ≤ √(u_model² + u_test²) at about 95 % confidence (2σ).
  Failure location must match the predicted peak-stress region.
- If it fails: find the cause before changing any number (fixture compliance and support
  modelling are the usual causes; rigid supports overestimate stiffness).

### 6.4 Feeding the result back

- Record each test as `library/tests/<part>-<date>.json`: spec hash, solver hash, material source,
  measured values, uncertainty, verdict.
- Add a regression test that recomputes the prediction from the stored spec and checks it against
  the stored prediction (the model must not drift without a reason).
- A failed validation becomes a code change (a new guard rail, a corrected material value, a
  changed support model) **with the test named in the commit**.

---

## 7. Release gates (summary)

| Release | Must have |
|---|---|
| every release | gate all pass; full pytest; goldens; regression bit-identical for specs without new keys; CalculiX cross-check for new physics; GUI smoke; `VERIFICATION.md` |
| 0.5 | MMS order check in the gate; NAFEMS LE10 benchmark; "verify finer" with GCI; **one validated part (section 6)** |
| 0.6+ | each new physics: a closed-form gate check, a NAFEMS or literature benchmark if one exists, a CalculiX cross-check |

---

## Sources

- ASME V&V 10 and the V&V framework, overview: https://www.simscale.com/blog/verification-and-validation-cae/
- Roache, P. J., Grid Convergence Index and code verification: https://maretec.tecnico.ulisboa.pt/~maretec.daemon/html_files/CFD_workshops/html_files_2006/papers/PJRoache.pdf
- Oberkampf & Roy, *Verification and Validation in Scientific Computing* (Cambridge UP): https://assets.cambridge.org/97805211/13601/frontmatter/9780521113601_frontmatter.htm
- Roy, C. J., Review of code and solution verification procedures: https://www.aoe.vt.edu/content/dam/aoe_vt_edu/people/faculty/cjroy/Publications-Articles/VerificationJournal-Revised.pdf
- Method of manufactured solutions in a finite element code (PyLith): https://pylith.readthedocs.io/en/latest/developer/testing/mmstests.html
- NAFEMS LE1, LE10, LE11 set up and solved (FeenoX): https://www.seamplex.com/feenox/examples/mechanical.html
- NAFEMS LE11 problem definition (Altair OptiStruct verification): https://2021.help.altair.com/2021/hwsolvers/os/topics/solvers/os/nafems_test_problem_le11_r.htm
- NAFEMS LE10 problem definition (Altair OptiStruct verification): https://2021.help.altair.com/2021/hwsolvers/os/topics/solvers/os/nafems_test_problem_le10_r.htm
