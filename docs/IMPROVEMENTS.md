# Anneal — improvement catalogue (research)

Each entry: what it is, why it matters for the goal (a personal Noyron that makes parts you can
trust), what it costs, how to prove it works, and the source. The order is the recommended order.
`docs/PLAN.md` decides which release takes which entry.

Rule for every entry: it must keep the regression (specs without the new key give bit-identical
results) and it must add evidence at one or more levels of `docs/VV-STRATEGY.md`.

---

## A. Trust (highest value)

### A1. Validate one real part
See `docs/VV-STRATEGY.md` section 6. No other entry adds as much trust. Cost: a few days of
printing and testing; a fixture; a dial indicator.

### A2. Stress-based design (stress constraint in the optimizer)
- **What:** today the optimizer minimises compliance and the stress is only checked afterwards. A
  stress constraint makes the optimizer keep the peak stress under a limit.
- **How:** aggregate the local von Mises (or Hill) stress with a p-norm or KS function, with stress
  relaxation for low densities (qp-relaxation), or use an augmented Lagrangian on local constraints
  (PolyStress). Needs a gradient optimizer with more than one constraint: **MMA**. Write MMA from
  Svanberg's papers (1987, 2002), or use pyMOTO's MIT implementation. Do not use the GPL ports.
- **Why:** parts that fail the safety-factor check today need manual volume changes. Thermal loads
  (0.4.2 → T3) are stress-driven by nature.
- **Proof:** the L-bracket benchmark (re-entrant corner): the stress-constrained design rounds the
  corner and meets the limit; FD sensitivity test of the aggregated stress.
- **Cost:** 2–3 weeks (MMA + aggregation + tests).

### A3. "Verify finer" and error bands
Grid refinement of the as-built part with the Grid Convergence Index (`VV-STRATEGY.md` section 4).
Cost: 3–4 days.

### A4. Supports that move (prescribed displacements)
- **What:** an anchor that moves by a given vector or follows a frame that expands
  (`frameAlpha`, `frameOrigin`): u = α_frame·ΔT·(x − x₀).
- **Why:** the main real thermal load on a bolted part is the **expansion mismatch** with the frame.
  Rigid supports model a frame with zero expansion. Also useful for assembly misalignment ("bolt
  holes 0.2 mm off").
- **Proof:** a bar between two anchors on a frame with the same α must have zero stress under ΔT.
- **Cost:** 2–3 days (prescribed dofs in `FEM.solve`: move the known values to the right-hand side).

### A5. Material calibration and uncertainty
Coupon import with mean and standard deviation; report results as a band (E ± σ → displacement band,
yield − 2σ → design yield). Cost: 1 week.

---

## B. Better shapes

### B1. Robust formulation (eroded / intermediate / dilated)
- **What:** optimise three projected designs at once (thresholds η = 0.5 ± Δη) and use the worst.
  This gives a **minimum length scale for both solid and void**, and makes the design tolerant to
  manufacturing errors (over- or under-extrusion, machining tolerance).
- **Why:** printed and machined parts are never exactly the designed size. Today the minimum member
  size comes only from the filter radius, and thin members can still appear after projection.
- **Proof:** the eroded design still meets the displacement limit; measured minimum member size ≥
  the requested size (member-thickness check).
- **Cost:** 1–2 weeks. Triples the solve cost per iteration (three designs), less with reuse.
- **Source:** Wang, Lazarov & Sigmund 2011; analytic relations between Δη and length scale
  (arXiv 2101.08605); min/max member and cavity sizes (arXiv 2003.00263).

### B2. Overhang filter for printing
Langelaar's AM filter (prototype on `verify-roadmap`). Needs threshold continuation and a slicer
comparison that shows less support. Cost: 1 week to finish.

### B3. Maximum member size and lattice grading
Grey density as input to TPMS or strut lattices (graded by density). Needs a dehomogenization step
or a density → lattice-thickness map, and a homogenised stiffness law for the chosen cell
(validated against a full solve of a unit cell). Cost: 3–4 weeks.

### B4. 5-axis machining filter in the optimizer
Extend the 3-axis mill filter to a set of tool directions. Cost: 1 week.

---

## C. Speed and size

### C1. Reuse the AMG hierarchy
SIMP changes the operator a little each iteration. Rebuild the AMG hierarchy only when the CG
iteration count grows by > 60 % (already partly done: `rebuild` flag). Measure N on the bracket and
report it. Cost: 2 days.

### C2. Geometric multigrid on the voxel grid (matrix-free)
- **What:** the grid is regular, so coarse grids are easy (2× coarsening, Galerkin or
  rediscretised). Large-scale topology optimization codes use exactly this (PETSc-based, up to
  billions of voxels, Aage et al.).
- **Why:** AMG setup time grows with size; geometric multigrid has almost no setup and can be
  matrix-free (no stored K).
- **Proof:** same iteration count independent of size on the V3 cantilever (± 20 %); same results
  to solver tolerance.
- **Cost:** 2–3 weeks. Do this before any GPU work.

### C3. GPU (only if C1 and C2 miss the time budget)
Warp FEM or CuPy matrix-free products. Results are not bit-identical; keep the CPU path as the
reference. Cost: 3–5 weeks.

---

## D. Accuracy at the boundary

### D1. Better cut-cell (finite cell) integration
- **What:** partial voxels today use stiffness × fill. The Finite Cell Method integrates the cut
  part of each voxel with adaptive quadrature and gives better stress near curved boundaries.
- **Why:** NAFEMS LE1/LE10 will show the stair-step error (VV-STRATEGY section 2.2). This is the fix
  if the error is too large.
- **Risk:** badly cut cells make the system ill-conditioned; needs stabilisation.
- **Cost:** 2–4 weeks; do it only if the benchmarks show the need.

### D2. Stress concentration at supports and loads
Report a stress-concentration range from the ZZ indicator, and model bolts as a contact-free
bearing (cosine pressure on the hole) instead of all nodes fixed. Cost: 1 week.

---

## E. Loads and judgement (the largest risk is the wrong load case)

### E1. Load-case advisor
A guided list of events per part (service, peak/abuse, drop, assembly, thermal, transport), each
turned into load cases with visible assumptions. The LLM may write the spec from a conversation; it
never computes a value at run time. See `docs/guides/NEW-PART.md` section 4.

### E2. Load-direction robustness
Optimise for a cone of load directions (several cases or a worst-case formulation), because a real
load is never exactly along the stated vector. Cost: 3 days (load cases) to 2 weeks (worst case).

### E3. Events from a mechanism (Chrono sidecar)
Rigid-body simulation → peak joint forces → quasi-static load cases. See
`docs/research/CONTEXT.md`. Cost: 2–3 weeks.

---

## F. Physics extensions

| Entry | Plan |
|---|---|
| Thermal stress, derating | 0.4.2 (`docs/PLAN.md` 4B) |
| Conduction, thermal in the optimizer, heat objective | `docs/research/thermal-loads.md` T2–T4 |
| Torque | 0.4.1 |
| Bolt preload | 0.5 |
| Modal (natural frequency) | 0.6: generalized eigenproblem K φ = ω² M φ with the lumped mass; reuse the buckling eigensolver |
| Fatigue screen | 0.5: alternating stress between two cases vs an endurance limit |
| Large deformation in Anneal itself | not planned; the CalculiX sidecar covers checks |

---

## Sources

- Giraldo-Londoño & Paulino 2021, PolyStress (augmented Lagrangian, local stress constraints): https://paulino.princeton.edu/journal_papers/2021/SMO_21_PolyStress.pdf
- Limiting first principal stress in topology optimization (2022): https://paulino.princeton.edu/journal_papers/2022/SMO_22_LimitingFirstPrincipalStressInTopOpt.pdf
- Stress-constrained topology optimization (NSF repository): https://par.nsf.gov/servlets/purl/10308918
- Large-scale 3-D manufacturing-tolerant stress-constrained topology optimization: https://arxiv.org/pdf/2006.12927
- Analytical relations for minimum length scale in the robust formulation: https://arxiv.org/pdf/2101.08605
- Minimum and maximum member size, cavity size and separation: https://arxiv.org/pdf/2003.00263
- Topology optimization tailored to the deposition nozzle size (large-scale AM): https://arxiv.org/pdf/2105.08115
- Large-scale topology optimization with PETSc (DTU TopOpt group): https://www.topopt.mek.dtu.dk/-/media/subsites/topopt/apps/dokumenter-og-filer-til-apps/petsc-1-.pdf
- Narrow-band topology optimization on a sparsely populated grid (SIGGRAPH): https://history.siggraph.org/?p=198051
- Langelaar 2016, AM filter (Additive Manufacturing 12:60–70); Svanberg 1987, MMA (IJNME 24:359–373) — see `docs/research/CONTEXT.md`.
