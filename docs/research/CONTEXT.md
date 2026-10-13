# Research context behind Anneal (digest)

These are the facts and decisions from the research notes in the owner's claude.ai project
"Canned heat" (September–October 2026). Each section names its source note. Use these facts.
Do not re-derive them without new data.

## Reframe: a personal Noyron (personal-system-scope)

- The goal changed from a commercial no-code desktop product to a **single-operator** tool. The
  operator is the author, so automatic feature detection is not critical (picking is a convenience;
  typed coordinates also work). Installer polish, certification provenance and usability studies were
  dropped.
- The input is one spec JSON per part. Each anchor does three jobs: it places geometry, it sets a
  boundary condition and it marks a frozen region.
- Keep these five habits; they separate a personal Noyron from a folder of scripts:
  1. Parameter taxonomy: every number is a specification, derived, interface, process or free value.
  2. Guard rails that raise errors whose messages name the fix.
  3. Input-count diagnostic: if the spec files grow, you are building a configurator.
  4. As-built re-solve.
  5. Test results become code changes, with the test named.
- Library layout that compounds: materials, processes, fasteners, correlations, tests. Nothing goes
  in the library until it is needed twice.
- LLM role: write the spec from a conversation, write new anchor types, find and cite correlations,
  read failures and propose fixes. **It never computes a value at run time.**

## Method: twelve stages (index-and-method)

Design time (once per part family, human-led) is separate from run time (once per part, unattended).
Define (frame the class, requirements vs interfaces, construction narrative) → Structure (blocks and
interface objects, skeleton before skin, classify every number) → Encode (derive numbers from physics,
generate geometry, guard rails, measurement harness) → Prove (reproduce a known part, print and test a
new one, feed results back as code). Diagnostic: model inputs should fall while the valid output range grows.

## Phase 0 solver facts (phase0-spike-results, anneal-application-architecture)

- Partial-volume voxels: a bar 6.4 cells deep has 6.67 % error with binary voxels and solver-tolerance
  error with fill fractions. **Solve partial volumes with penalty 1** (real material in parallel), not
  the SIMP penalty.
- Shear locking of plain hex8: 13.4 % too stiff at 2 elements deep, 1.9 % at 8. (Now removed by e9.)
- CG iterations grow with size → use algebraic multigrid before a GPU. (Done with pyamg.)
- Penalty continuation (1 → 3) is needed. Compliance rises during the ramp; compare against a uniform
  design at equal mass and penalty, not first vs last iteration.
- Grey density is an output, not a defect: it is the input to lattice grading.
- Decision D6: re-solve the as-built geometry. D9: enough elements through the thinnest member.

## Competitors and load paths (competitive-and-loadpath-findings)

- PicoGK and ShapeKernel have no solver (verified by grep). LEAP 71's physics is in proprietary Noyron.
- Intact Solutions' Immersed Method of Moments (in nTop) uses the same idea: a non-conforming grid
  under implicit geometry; about 3 % from mesh FEA. The academic name is the Finite Cell Method.
  Known failure mode: ill-conditioning from badly cut cells (Anneal's E-min floor masks part of it).
- Nobody turns "a bracket holding a 5 kg camera through a hard landing" into a boundary value problem.
  That gap is the most valuable missing piece.
- The optimizer is the load-path finder. To explain results: strain-energy colouring and
  principal-stress streamlines (cheap on a regular grid). U* index later.

## Physics engines (physics-engines-newton-chrono-ppf)

- None replaces the SIMP solver. They feed it (loads) and check it.
- Project Chrono (BSD-3): rigid-body events → joint forces; hex8 FEA; STEP via Chrono::Cascade.
  Use a C++ or Python sidecar. `pip install pychrono` is an unrelated package; use
  `conda install projectchrono::pychrono -c conda-forge`.
- NVIDIA Newton / Warp (Apache-2.0): warp.fem on NanoVDB grids is a possible GPU path. Needs NVIDIA
  Turing+ and driver R580+.
- PPF (ZOZO, Apache-2.0): contact dynamics only, single precision, not production ready.
- Swan (MATLAB): no licence file → read for ideas only.
- Traps: impact peaks depend on contact stiffness and time step; units mm in spec, SI in engines;
  GPU sidecars are not bit-identical; licence-scan every sidecar.

## Roadmap verification results (roadmap-verification, 12 Oct 2026)

- Transversely isotropic D: exact in the isotropic limit; bar tests reproduce Ez and Exy.
- Kuznetsov FDM strength fit: R² 0.956 on 20 rows; use only as a trend through a user calibration point.
- Langelaar 2016 AM (overhang) filter: adjoint matches finite differences; a NaN in the smooth-max
  derivative was fixed by computing in logs; cantilever unsupported voxels 10.5 % → 0 % with no
  stiffness loss; more grey voxels. On the bracket it showed no slicer gain → stays off 0.4.
- Linear buckling: +3.5 % at 4 voxels (hex8fi), CalculiX *BUCKLE agrees to 0.01 %.
- CalculiX sidecar (gmsh tet10): linear cantilever 16.00 mm = theory; NLGEOM 15.61 mm.
- PrusaSlicer CLI has no support-volume line: slice with and without supports.
- Equivalent-static impact F = sqrt(2 E k) matches a time-stepped mass-spring.
- Corrections to sources: Langelaar 2016 is the 3-D filter (Additive Manufacturing 12:60–70);
  Ferrari, Sigmund & Guest 2021 (SMO 63) uses OC by default; licences: Swan none, GCMMA-MMA-Python
  GPL-3.0, OpenRadioss repo deleted.

## Element (e9) references

- Wilson, Taylor, Doherty, Ghaboussi 1973; Taylor, Beresford, Wilson 1976 (patch-test version). On
  cube voxels the Jacobian is constant, so both are the same element; it passes the patch test (V10).
- Abaqus documents the same incompatible-modes idea (C3D8I). Strand7 documents bubble modes for bricks.
- Zienkiewicz & Zhu 1987, Int. J. Numer. Methods Eng. 24:337–357 (error estimator).

## Licence ledger (component-ledger, adapted to the Python build)

- Permissive and linked: numpy, scipy, scikit-image, matplotlib (BSD); pyamg, trimesh, three.js (MIT);
  manifold3d (Apache-2.0); pywebview (BSD); cadquery-ocp (LGPL-2.1 + OCCT exception: put a notice in
  the documentation).
- Never link: CalculiX, Elmer, Code_Aster, gmsh, TetGen (GPL); MMA ports (GPL-3.0); CGAL-dependent code.
  Separate processes and file formats only.
- PicoGK 2.3.0 ships win-x64 and osx-arm64 only, so the Python build keeps its own geometry layer
  (`kernel.py`, `geometry.py`); a PicoGK backend can replace it later.

## Open unknowns that still matter (open-unknowns-register)

1. **Judgement**: is the stated load case the right one? (Largest unknown; not in the code.)
2. Does a generated part behave as predicted? Only answered by making and testing one.
3. Does grey density grade into a better lattice part? Not yet shown.
4. AMG reuse: how many iterations can reuse one hierarchy (N)?
