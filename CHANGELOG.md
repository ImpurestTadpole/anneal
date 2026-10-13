# Changelog

## 0.4.1

New: torque load (a pure moment) on a load region.

- Spec: `torques: {"caseName": [Mx, My, Mz]}` on a load anchor, in N·m. A torque and a force with
  the same case name act together. A spec without `torques` gives the same results as 0.4.0.
- Spec: `limits.maxRotationDeg` (optional). Anneal reports the twist of each load region in degrees
  and checks it against this limit. The optimizer does not use the limit.
- Distribution: a rigid-hub rule with a linear shear distribution. The node forces add up to zero
  and give exactly the torque about the centre of the region's nodes.
- App: a "Torque" row (Mx, My, Mz in N·m) per load case on each load region, a field for the
  maximum twist, a curved-arrow glyph about the torque axis in the viewer, and a "Twist of load
  regions" table in the result when the run has twist values.
- Old projects open and save without a `torques` key.
- `tools/gui_smoke.py`: checks for the torque row, save and reload, `maxRotationDeg`, and an old
  project without torques.
- README: section "Torque on a load region", with the difference from bolt preload.

Not in 0.4.1: bolt preload, a torque as an impact load, a rotation limit in the optimizer.
