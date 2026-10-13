# How to make a new part with Anneal

This guide is for the operator (the person who uses Anneal to make a part). It goes from "I need
a part" to "the part is made, tested and recorded". Follow the steps in order. Do not skip step 4:
most bad parts come from a wrong load case, not from the solver.

Words used here: **anchor** = a region where the part is held (support) or loaded; **load case** =
one set of loads that act at the same time; **design space** = where material may go.

---

## 1. Frame the part

Write four lines before you open Anneal:

1. **Function:** what the part does. Example: "holds a 1.2 kg camera on a drone arm".
2. **Interfaces:** what it bolts to and what bolts to it (bolt sizes, faces, shafts).
3. **Environment:** temperature range, outdoor/UV, chemicals, vibration, how long it must last.
4. **Process:** how it is made (FDM, SLS, LPBF, CNC 3-axis or 5-axis) and with what material.

If the environment includes heat, read section 9 first. A PLA part does not survive in a hot car.

---

## 2. Make the interface model

- Model **only the interfaces** in CAD: bolt bosses, mounting faces, shaft bores, the clearance
  zones. Save as STEP (preferred) or STL, in **millimetres**.
- Alternative: use an existing part as the model and let Anneal remove material from it.
- Check that the model is closed (the GUI shows "closed" or "not closed").

## 3. Choose the design space

| You want | Design space | Notes |
|---|---|---|
| Make an existing part lighter | `"model"` (inside the model only) | Anneal can only remove material |
| Grow a part between interfaces | `"bounds"` or `"box"`, with `designSpace.keepModel: true` | Anneal adds material; the interfaces stay exact |
| Fill around the model | `"hull"` with a margin | |

Add **keep-outs** for every space that must stay empty: other parts, wires, tool access, bolt heads
(`boltAccessMM` on hole anchors). A missing keep-out is the second most common error.

---

## 4. State the load cases (the most important step)

Anneal makes the best part **for the loads you give it**. It cannot know a load you did not state.
Go through this list for every part and write down each event that can happen:

| Event | Question | Typical load case |
|---|---|---|
| Normal service | What acts every day? | Weight × 1 g, working forces |
| Peak service | What is the largest force in normal use? | Measured or estimated maximum |
| Abuse / misuse | What happens if someone leans on it, drops a tool on it, over-tightens it? | A larger force in the worst direction |
| Drop / impact | Can it fall, or be hit? | `impact` (mass and drop height or speed) |
| Acceleration | Vehicle, drone crash, vibration | `gravity` with N g in each direction |
| Assembly | Bolt tightening, press fits, misaligned holes | Torque (0.4.1); preload (later) |
| Thermal | Heat or cold, mismatch with the frame | `thermal` (0.4.2) — see section 9 |
| Transport | Packed loose? | Usually covered by drop |

Rules:
- **Direction:** a real load is never exactly along one axis. Add a second case with the load
  turned 10–20°, or a side component of 20–30 % of the main load.
- **Supports:** a bolted face that can slide is not fully held. Hold only the directions that are
  really held (`dofs`). Fully held supports make the part look stiffer than it is, and make thermal
  stress far too high.
- **Units:** forces in N, torques in N·m, pressures in MPa, lengths in mm, temperatures in °C.
- **Safety factor:** set `limits.minSafetyFactor`. Typical: 1.5 for metal with known loads, 2–3 for
  printed polymers or unsure loads, 3–4 if a failure can hurt a person.
- Write the reason for each load case in the project notes. You will need it when a test fails.

---

## 5. Material and process

- Choose a library material. **Check its source.** Datasheet values for printed polymers are often
  too high for your printer.
- Better: test 5 coupons per direction and import the values (`anneal materials import`). See
  `docs/VV-STRATEGY.md` section 6.1.
- For FDM: turn on `physics.anisotropic` (print-aware) and set the build direction. The layers are
  the weak direction.
- For CNC: choose 3- or 5-axis, the setups, the smallest tool and the reach.

---

## 6. Run

1. **Check setup** (seconds): the original part at draft resolution. Look at the displacement: does
   the part move the way you expect? If a load pushes the wrong way, fix it now.
2. **Draft run**: `resolution: "draft"`, 30–40 iterations. Check the shape makes sense.
3. **Normal run**: the part you will judge. Turn on what you need: buckling, impact, advanced output.
4. **Fine check** (when available, "verify finer"): the error band of the result.

## 7. Read the result

Read the checks first. For each FAIL the row says the fix. Then read:
- **FEA study:** reactions must balance the loads (equilibrium error < 1e-6). If not, stop: the
  setup is wrong.
- **Stress error (ZZ):** above 30 % the stress values are coarse. Use a finer resolution before you
  trust the safety factor. Displacement is still good.
- **Warnings:** few nodes on an anchor (point load), thin members, load-path repair, layer strength.
- **How the part works** (advanced output): where the energy goes, which support carries most.
  If a support carries far more than you expected, check the support model.

## 8. Check, make, test, record

1. Independent check: the CalculiX cross-check (`physics.nonlinear`, or `tools/ccx_bracket.py`).
   Displacements within about 5 % mean the setup is consistent.
2. Make the part. Weigh it: the mass must be within a few per cent of the predicted mass.
3. Test it the way `docs/VV-STRATEGY.md` section 6 says (stiffness at 4–5 load steps, then to failure
   if you can spare a part).
4. Record the result in `library/tests/`. If the test and the model disagree, find the cause before
   you change any value.
5. Save the spec as the start of a **part family**: the next similar part starts from it. Put a
   material or a fastener in the library only when you need it the second time.

---

## 9. Parts with temperature (0.4.2 and later)

Read `docs/research/thermal-loads.md` for the physics. Operator rules:

1. **Service limit first.** Find the highest temperature the part sees (sun on a dark part, a car
   interior, a motor). If it is near the material's glass transition (PLA about 55–60 °C, PETG about
   80 °C), choose another material. Anneal stops the run above `maxServiceTempC`.
2. **Reference temperature** = the temperature at assembly (usually 20 °C).
3. **One load case per temperature that matters:** the hottest service case with its mechanical
   loads, and the coldest. A free part that only expands carries no stress; stress comes from
   supports that stop the expansion.
4. **Mismatch with the frame.** Anneal's supports do not expand. A part bolted at two places to a
   frame that also expands sees only the **difference**. Until moving supports exist
   (`docs/IMPROVEMENTS.md` A4), approximate with an effective temperature change:
   ΔT_eff = ΔT · (α_part − α_frame) / α_part. This is exact for the distance between two supports and
   approximate elsewhere. Write this in the project notes.
5. **Sliding joints.** Slotted holes or a single locating bolt let the part expand. Hold only the
   directions that are really held, or the thermal stress will be far too high.
6. **The optimizer does not see the thermal load in 0.4.2.** The thermal stress is checked on the
   result. If the check fails, raise the volume fraction, change the supports, or change the material.

---

## 10. Spec template

A complete spec with the keys most parts need (JSON with comments for reading only; remove the
comments in a real file):

```jsonc
{
  "name": "camera-mount",
  "model": "camera-mount-interfaces.step",
  "designSpace": { "type": "bounds", "marginMM": 5, "keepModel": true },
  "material": "PETG-FDM",
  "process": { "name": "FDM", "buildDirection": [0, 0, 1] },
  "physics": { "anisotropic": true, "buckling": true },
  "resolution": "normal",
  "solver": { "element": "e9" },
  "anchors": [
    { "name": "arm-bolts", "role": "fixed", "dofs": "xyz", "hole": true, "boltAccessMM": 12,
      "region": { "type": "pipe", "from": [0, 0, 0], "to": [0, 0, 6], "r": 5.5, "rIn": 1.7 } },
    { "name": "camera-face", "role": "load", "freezeMM": 2,
      "region": { "type": "box", "min": [60, -15, 30], "max": [62, 15, 50] },
      "loads": { "service": [0, 0, -12], "crash": [0, -60, -120] } }
  ],
  "gravity": { "crash": [0, 0, -10] },
  "keepOut": [ { "type": "cylinder", "from": [30, -20, 20], "to": [30, 20, 20], "r": 8 } ],
  "loadCases": { "service": { "weight": 1 }, "crash": { "weight": 1 } },
  "objective": { "minimise": "mass", "volumeFraction": 0.3, "combine": "worst" },
  "limits": { "maxDisplacementMM": 0.5, "minSafetyFactor": 2.5 },
  "output": { "formats": ["stl", "3mf", "step"], "edges": "smooth", "detail": "normal",
              "exactFeatures": true, "advanced": true }
}
```

The README lists every key with its meaning and default.
