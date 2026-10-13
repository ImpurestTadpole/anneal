# Thermal — implementation instructions for 0.4.2

For the agent that builds release 0.4.2. The **what** and the acceptance tests are in
`docs/PLAN.md` section 4B (work items H1–H15). The physics and sources are in
`docs/research/thermal-loads.md`. This file is the **how**: code-level steps, in order.
Operator rules for thermal parts are in `docs/guides/NEW-PART.md` section 9.

Start from tag `v0.4.1` on a branch `release-0.4.2`. Follow `docs/guides/DEVELOPER.md` (invariants).

---

## Step 1 — material keys (H1, H2)

`anneal/materials.py`:
- Add `"alpha", "alphaZ", "maxServiceTempC", "tempDerating"` to `MAT_KEYS`.
- `validate_material`: alpha in (0, 1e-3) 1/K; alphaZ the same; maxServiceTempC in (−273, 3000);
  tempDerating a list of `[tempC, Efactor, yieldFactor]`, sorted by temperature, factors in (0, 2],
  and one row at 20 °C (or at the spec reference) with factors 1.
- Import: units `1/K`, `1/°C`, `ppm/K` (×1e-6), `µm/(m·K)` and `um/m/K` (×1e-6), `°C`, `°F`
  (→ °C). Column words: "CTE", "thermal expansion", "alpha" → alpha; "CTE Z", "alpha z" → alphaZ;
  "max service", "HDT", "glass transition" → maxServiceTempC (note: HDT and Tg are *not* the
  same thing; store the column name in `source` so the owner sees which one it was).
- H2: research the built-in values on the web. Put the URL and the document name in `source`.
  **No value without a source.**

## Step 2 — spec (H3)

`anneal/problem.py`, in `Problem.__init__` after the gravity block:
```python
th = spec.get("thermal") or {}
self.t_ref = float(th.get("referenceTempC", 20.0))
self.t_case = {str(c): float(t) for c, t in (th.get("cases") or {}).items()}
```
- Add the thermal case names to `cases` (the same way as gravity cases).
- If `self.t_case` is not empty and the material has no `alpha`: `SpecError` naming the key, the
  material, and "add alpha (1/K) to the material in the library or the spec".
- If any case temperature > `maxServiceTempC`: `SpecError` with the case, the temperature, the limit
  and "choose a material with a higher service temperature".
- `self.limits.get("displacementIncludesThermal", False)` → store.

## Step 3 — derating (H4)

New helper in `physics.py`:
```python
def derate(material, temp_c):
    """(E factor, yield factor) at temp_c by linear interpolation of tempDerating; (1, 1) if absent."""
```
In `run.evaluate`, use per case: `E_case = E0 * fE`, `Y_case = Y * fY`. Evaluate today assembles one
K for all cases. With derating, cases at different temperatures have different K: group the cases
by temperature, assemble one K per group (usually one or two groups). Cases without a thermal entry
use (1, 1) and the existing K, so the regression holds.

## Step 4 — thermal load and stress (H5)

`anneal/fem.py`:
```python
def thermal_vector(self, alpha, alpha_z=None):
    """24-vector f̂ = Σ_gp Bᵀ D₁ m w for a unit temperature rise (E = 1).
    m = [α, α, α_z, 0, 0, 0] in the build frame, rotated like D (physics.frame)."""
```
- Compute with the same Gauss loop as `_hex8_full` (use the corner B matrices, not B₀).
- For e9, assert in a test that the bubble part Σ Biᵀ D m w is zero (it is, for constant ΔT).
- Thermal nodal load: `np.bincount(edof.ravel(), weights=(Ee[:,None]*dT_e[:,None]*fhat).ravel())`
  where `Ee` already holds fill × E × derating.
- Stress with an eigenstrain:
```python
def stress(self, u_full, E_material, eps0=None):
    eps = u_full[self.edof] @ self.B0.T
    if eps0 is not None:
        eps = eps - eps0          # eps0: (n, 6) or (6,)
    return (eps @ self.D.T) * E_material...
```
  Callers to update: `run.evaluate` (von Mises, layer, Hill), `fea.study` (stress, ESTRN uses total
  strain minus ε₀ for mechanical strain — state which in the report), `run.impact_check` (no ε₀),
  `physics.buckling` pre-stress (H7).
- Mechanical-only displacement (for the limit): solve one more right-hand side with f_mech only
  (`fem.solve` accepts a list; reuse the same preconditioner).

## Step 5 — gate checks (H6)

`anneal/validate.py`. Use a direct per-voxel ΔT array through the internal API (the spec allows only
a uniform ΔT; the gradient check proves the general path for later stages).
- **V12 free bar:** 20×4×4 voxels, held only against rigid motion (3-2-1 constraints). ΔT = 50,
  α = 1e-5. End displacement = α·ΔT·L to 1e-10 relative; max |σ| < 1e-9·E·α·ΔT.
- **V13 rollers:** the same bar, x held on both end faces (plus minimal y/z). σx = −E·α·ΔT, σy = σz = 0,
  to 1e-10 relative.
- **V14 gradient beam:** free beam 40×4×8 voxels (8 layers through the depth), ΔT linear through the
  depth (voxel centre values). Curvature κ = α·(ΔT_top − ΔT_bottom)/h. Measure at 4, 8 and 16 layers
  and set the tolerance from the data (the midpoint sampling error is O(1/n²)).
- Run each for e9 and hex8fi. Store the measured numbers in the docstrings.

## Step 6 — buckling with thermal pre-stress (H7)

`physics.buckling(fem, K, u, Ee)` builds K_σ from the element stress. Pass the total stress
(mechanical + thermal) of the case. Test: a column clamped at both ends (axially held), heated, no
mechanical load: ΔT_cr = π²·I/(α·A·(0.5·L)²).

## Step 7 — CalculiX (H10)

`anneal/sidecar.py`, in the material cards and the step:
```
*MATERIAL, NAME=MAT
*ELASTIC
 210000., 0.3
*EXPANSION, ZERO=20.
 1.2E-5
*INITIAL CONDITIONS, TYPE=TEMPERATURE
 NALL, 20.
*STEP
*STATIC
*TEMPERATURE
 NALL, 70.
...
*END STEP
```
- Define `*NSET, NSET=NALL` explicitly (ccx 2.21 does not predefine it — a known trap from 0.4).
- For `alphaZ`: `*EXPANSION, TYPE=ORTHO` with three values in the `*ORIENTATION` frame already used
  for the engineering constants.
- Cross-check: the clamped bracket of H13, e9 vs tet10, displacement and stress away from supports
  within 5 %.

## Step 8 — benchmark (optional, recommended)

NAFEMS LE11 (cylinder/taper/sphere, T = √(x²+y²) + z, α = 2.3e-4, E = 210 GPa, ν = 0.3; target
σzz = −105 MPa at point A). It needs a temperature field, so it uses the internal per-voxel ΔT API.
Get the geometry from the NAFEMS publication or a public input file (for example the FeenoX
examples). Put it in `tests/benchmarks/` and record the error at three voxel sizes
(`docs/VV-STRATEGY.md` section 2.2).

## Step 9 — report, GUI, README (H8, H9, H11, H12, H14)

- Report "Assumptions": uniform temperature per case; linear thermal strain; derated E and yield at
  the case temperature; **the optimizer used the mechanical loads only**.
- "Not modelled": temperature gradients and heat flow, creep and relaxation at temperature, slip in
  bolted joints, expansion of the frame (link to the ΔT_eff rule in `NEW-PART.md` section 9).
- Check rows: "Service temperature vs material limit", "Thermal stress share", and the held-supports
  warning.
- GUI fieldset "Temperature" in step 3; Result step shows mechanical and thermal displacement apart.

## Step 10 — proof

As in `docs/PLAN.md` 4B "Proof for 0.4.2". The gate becomes 14 of 14. The regression against 0.4.1
must be bit-identical for specs without `thermal`.
