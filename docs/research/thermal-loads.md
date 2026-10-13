# Thermal loads in Anneal — research and plan

Status: research, 12 October 2026. Nothing here is implemented. Stages T0 + T1 are planned as
release 0.4.2 (`docs/PLAN.md` section 4B).
Base truth: `master` (0.3.0, 17a3e31) has no thermal code. Every thermal stage below builds on
`release-0.4`. It reuses the e9 element and the design-dependent load path that 0.4 added for self-weight.

## 1. What "thermal load" can mean (three different problems)

| # | Problem | Example | What Anneal must compute |
|---|---|---|---|
| A | **Thermal stress from a known temperature change** | A PLA bracket bolted to a steel frame, in a car that reaches 50 °C; an aluminium part clamped at both ends and heated | Thermal strain α ΔT → load vector → displacement and stress |
| B | **Temperature field from heat flow, then stress** | A motor mount: heat enters at the motor face and leaves at the frame | A conduction solve for T(x), then problem A |
| C | **Shape for heat flow** (heat sink, heat spreader) | A part that must carry heat away | Thermal compliance as the objective |

Do them in this order. A gives most of the value for the owner's parts. A is also needed by B and C.
Residual stress and warping from printing is a fourth, different problem (process simulation,
inherent-strain method). It is out of scope here.

## 2. The physics on the voxel grid

### 2.1 Thermal strain and load (problem A)

- Thermal strain in Voigt form: ε_th = α ΔT · m, with m = [1, 1, 1, 0, 0, 0].
  For print-aware materials, α has two values: α (in the layers) and α_z (across the layers),
  so ε_th = ΔT · [α, α, α_z, 0, 0, 0] in the build frame, then rotated like D.
- Stress: σ = D (B u − ε_th). Note the minus. The stress output in `fem.stress`, `fea.py`, the
  Hill check and the layer check all need this change.
- Element load (equivalent nodal forces): f_e = ∫ Bᵀ D ε_th dV. With one ΔT per voxel this is
  f_e = ΔT_e · E_e · (Σ_gp Bᵀ D₁ m_α w), where D₁ is D for E = 1. That is a fixed 24-vector per
  material times ΔT_e and the local modulus, so it costs almost nothing.
- **e9 element:** the incompatible modes also take part of the thermal load:
  f_a − K_ab K_bb⁻¹ f_b. For a constant ΔT in a voxel, f_b = 0 exactly (the bubble gradients
  integrate to zero). This was checked numerically on the e9 code: |f_b| = 0.0. So with ΔT constant
  per voxel, no extra condensation term is needed. Keep a test for this. If ΔT is ever made
  trilinear inside a voxel, f_b is no longer zero, and the condensation must be added.
- A free body with a uniform ΔT must expand by α ΔT L with **zero stress**. A body held on all sides
  must have σ = −E α ΔT / (1 − 2ν) (hydrostatic). These two facts are the first validation checks.

### 2.2 Thermal load inside the optimizer (SIMP)

- The thermal load depends on the design: f_e(x) = E(x) · ΔT_e · f̂. The sensitivity has the same
  form that 0.4 already uses for self-weight:
  ∂c/∂x_e = 2 u_eᵀ ∂f_e/∂x_e − u_eᵀ ∂K_e/∂x_e u_e.
  So `optimize.simp` needs a second design-dependent load term, not a new method.
- **Known traps from the literature:**
  1. With SIMP, E(x) = x^p E₀ makes the thermal load scale like the stiffness. At low density the
     ratio of load to stiffness stays finite, and grey material can look attractive. The usual fix is
     a separate interpolation for the "thermal stress coefficient" β(x) = E(x) α(x), or RAMP for E
     (Gao & Zhang 2010).
  2. With thermal loads, adding material can *raise* compliance. The volume constraint may then be
     inactive. The OC update in Anneal assumes an active volume constraint (equality bisection). It
     must allow "use less than the volume limit" when the thermal part dominates.
  3. Compliance is a weak objective for thermal problems. A stiffer part also generates larger
     thermal forces. Stress-based formulations work better (Deaton & Grandhi; Pedersen & Pedersen).
     For Anneal: first add the thermal load to the **as-built check** (stress and safety factor),
     and add it to the optimizer later, with the trap 1 and 2 fixes and a stress check.

### 2.3 Steady heat conduction (problem B)

- Equation: −∇·(k ∇T) = Q. Boundary conditions:
  - fixed temperature on an anchor region (a motor face at 80 °C);
  - heat flux into a region (W/mm²);
  - convection h (T − T∞) on picked faces.
- Element: scalar hex8, 8 × 8 conductivity matrix (k_e = k ∫ ∇Nᵀ ∇N dV), with the same
  connectivity, partial-volume scaling (k × fill) and assembly code as the mechanics. The system is a
  Poisson problem. pyamg is ideal for it (faster than elasticity).
- **Convection on the optimized surface is the hard part.** In topology optimization the surface
  moves with the design, so convection is a design-dependent boundary condition. Start with
  convection only on fixed, picked faces. Treat convection on the free surface later, with a
  smoothed-surface (density-gradient) method.
- One-way coupling: T changes the stress, the stress does not change T. Solve T first, then
  mechanics.
- In the optimizer: if k depends on the design, T depends on the design. Then the mechanical
  compliance needs an adjoint for T: solve K_th λ = −∂c/∂T, then
  ∂c/∂x_e += λ_eᵀ (∂K_th,e/∂x_e) T_e. This is one extra solve per iteration (cheap with AMG).

### 2.4 Heat-flow shape (problem C)

The objective is thermal compliance Qᵀ T (as low as possible) at a given volume. This is the
classic heat-conduction topology problem (Gersborg-Hansen, Bendsøe & Sigmund 2006). It is the same
SIMP loop with the scalar operator. A combined objective (stiffness + heat flow) is a weighted sum
of normalized compliances, as Anneal already does for several load cases.

## 3. Material data needed

New material keys (each value needs a source in the library, like every other number):

| Key | Unit | Meaning |
|---|---|---|
| `alpha` | 1/K | thermal expansion coefficient (in the layers) |
| `alphaZ` | 1/K | expansion across the layers (print-aware runs) |
| `k` | W/(m·K) | thermal conductivity |
| `maxServiceTempC` | °C | above this, do not use the part (for polymers, below the glass transition) |
| `yieldAtTemp` | table | yield (and E) against temperature, for derating |

Approximate values to start from (typical; replace with sourced or measured values before use):

| Material | α, 10⁻⁶/K | k, W/(m·K) | Note |
|---|---|---|---|
| PLA (FDM) | ~70 | ~0.13 | glass transition ~55–60 °C: stiffness and strength fall sharply above it |
| PETG (FDM) | ~60–70 | ~0.2 | glass transition ~80 °C |
| PA12 (SLS) | ~80–110 | ~0.2–0.3 | |
| AlSi10Mg (LPBF) | ~20–21 | ~100–150 | as built; depends on direction and heat treatment |
| Ti-6Al-4V (LPBF) | ~9 | ~7 | |
| 316L (LPBF) | ~16 | ~15 | |

**For polymer parts, the derating matters more than the thermal stress.** A PLA part at 50 °C has
lost a large part of its stiffness. The first useful check is "the service temperature is below the
material limit, with derated E and yield", even before any thermal strain.

## 4. Spec (proposed)

```jsonc
"thermal": {
  "referenceTempC": 20,                       // stress-free temperature (assembly)
  "cases": {
    "hotDay": { "uniformTempC": 55 },         // stage T1: one temperature everywhere
    "motorOn": {                              // stage T2: conduction solve
      "anchors": [
        { "anchor": "motorFace", "tempC": 80 },
        { "anchor": "frameBolts", "convection": { "hWm2K": 25, "ambientC": 30 } }
      ]
    }
  },
  "combineWith": { "main": "hotDay" }         // mechanical load case "main" runs at "hotDay"
}
```

A thermal case is attached to mechanical load cases. The stress of a load case is then mechanical
plus thermal. A thermal case with no mechanical case is also a load case on its own (expansion only).

## 5. Staged plan (after 0.4.1 torque)

| Stage | Work | Acceptance |
|---|---|---|
| **T0 — derating** | `maxServiceTempC` and the yield/E table in the library. Check row "Service temperature vs material limit". Derated E and yield in the as-built check. | Library import reads the new columns. A PLA case at 60 °C fails with a fix message. |
| **T1 — thermal stress, analysis only** | `alpha`, `alphaZ`; uniform ΔT per case; `σ = D(Bu − ε_th)` everywhere stress is used; thermal load vector; as-built check, report and FEA study include thermal stress. Optimizer unchanged (mechanical loads only). | Gate checks (numbering after V11 torque): **free bar** expands α ΔT L with stress < 1e-10 E α ΔT; **fully held block** σ = −E α ΔT/(1−2ν) exactly; **bi-material strip** curvature vs Timoshenko (1925) within 2 %; e9 bubble thermal load = 0 test. CalculiX cross-check with `*EXPANSION` and `*TEMPERATURE` within 5 %. |
| **T2 — conduction solve** | Scalar hex8 conduction on the voxel grid with AMG; fixed T, flux and convection on picked anchors; T field in the viewer and the report; T per voxel feeds T1. | Checks: 1-D slab gives a linear T exactly; patch test for the scalar element; hollow cylinder vs ln(r) solution within 1 %; energy balance (heat in = heat out) to solver tolerance; CalculiX `*HEAT TRANSFER` cross-check. |
| **T3 — thermal load in the optimizer** | Design-dependent thermal load (reuse the self-weight path); β(x) interpolation; OC with an inactive volume constraint allowed; adjoint for T when k depends on the design. | Finite-difference sensitivity test (as for self-weight); a clamped-beam benchmark where the optimizer must not add material that only raises thermal force; as-built stress check passes. |
| **T4 — heat-flow objective** | Thermal compliance objective; combined stiffness + heat objective. | The 2-D/3-D "volume-to-point" benchmark gives the known branching layout; compliance is below a uniform design at equal mass. |

T0 and T1 are about one week together and give most of the value. T2 is about one week. T3 and T4
are research-grade; do them only when a real part needs them (the rule from the personal-scope plan:
"no thermal until a part needs it").

## 6. Risks

- **Material data**: CTE and conductivity of printed polymers vary with direction, fill and
  temperature. Without sourced values the thermal stress is only a rough estimate. Say so in the report.
- **Contact and slip**: real bolted joints slip under thermal expansion; Anneal's rigid supports do
  not. Fully held supports overestimate thermal stress. The report must state this, and an option
  could hold only the bolt-axis directions.
- **Polymers above the glass transition**: the linear model is wrong there. T0 must stop such a run,
  not only warn.
- **Optimizer behaviour with thermal loads**: section 2.2 traps 1–3. Keep thermal in the check only
  until T3 is validated.

## Sources

- Gao, T., Zhang, W. (2010). Topology optimization involving thermo-elastic stress loads. Struct.
  Multidisc. Optim. 42:725–738. https://pure.nwpu.edu.cn/en/publications/topology-optimization-involving-thermo-elastic-stress-loads/
- Deaton, J. D., Grandhi, R. V. Stress-based design of thermal structures via topology optimization
  (thesis and papers). https://corescholar.libraries.wright.edu/etd_all/1362
- Stress-constrained thermo-elastic topology optimization (Univ. Wisconsin, 2017).
  https://ersl.wisc.edu/publications/2017/StressConstrained.pdf
- Stress-constrained thermo-elastic topology optimization with varying temperature fields (level set).
  https://arxiv.org/pdf/2203.15117
- Kambampati et al. (2020), level-set topology optimization of thermoelastic structures (OpenMDAO).
  https://openmdao.org/pubs/kambampati_topology_2020.pdf
- Gersborg-Hansen, A., Bendsøe, M. P., Sigmund, O. (2006). Topology optimization of heat conduction
  problems using the finite volume method. https://orbit.dtu.dk/en/publications/topology-optimization-of-heat-conduction-problems-using-the-finit/
- CalculiX: thermal expansion from a temperature field. https://calculix.discourse.group/t/calculate-thermal-expansion-from-a-temperature-field/3909
- CalculiX manual (`*INITIAL CONDITIONS`, `*TEMPERATURE`). https://web.mit.edu/calculix_v2.7/CalculiX/ccx_2.7/doc/ccx/node150.html
- FreeCAD FEM initial temperature constraint (CalculiX front end). https://wiki.freecad.org/FEM_ConstraintInitialTemperature/en
