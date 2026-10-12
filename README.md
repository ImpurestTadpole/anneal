# Anneal

Anneal makes an existing part lighter and stiffer. You open a model (STL or STEP), click where the
part is held and where it is loaded, and set a goal. Anneal removes the material that does not
carry load, makes a smooth printable surface, solves the new part again to check it, and keeps a
record of every run.

You can use it three ways: the **desktop app** (an icon on your desktop), the **same app in your
browser**, or the **command line** with a spec file. All three write the same files.

```
your-part.step  +  your-part.anneal.json   ──►   your-part-optimized.stl / .3mf  +  report.html
```

It runs on **Windows 10/11** and **Ubuntu 20.04 or newer** (also macOS). It needs no GPU.

---

## 1. Install

### Windows

1. Install **Python 3.11** (or 3.10–3.13) from <https://www.python.org/downloads/windows/>.
   Keep the default options.
2. Unzip Anneal to a folder, for example `C:\Anneal`.
3. Double-click **`install_windows.bat`**. It makes a private environment in `.venv`, installs
   the packages, adds STEP support and the desktop window, puts an **Anneal** icon on the desktop
   and in the Start menu, and runs the solver checks. The last lines must say
   `GATE: OPEN - 6 of 6 checks pass`.

**Updating from 0.1.0:** unzip the new version over the old folder (or into a new folder) and run
`install_windows.bat` again. It is quick the second time; the packages are cached.

### Ubuntu 20.04

Ubuntu 20.04 has Python 3.8, which is too old for current numpy and scipy. The installer gets
Python 3.11 for Anneal only and does not change the system Python.

```bash
cd ~/Anneal
chmod +x install_ubuntu.sh
./install_ubuntu.sh
source .venv/bin/activate
```

### Any system, by hand

```bash
python -m venv .venv
.venv/bin/pip install -e .           # Windows: .venv\Scripts\pip install -e .
.venv/bin/pip install cadquery-ocp   # optional: STEP import
python -m anneal validate
```

---

## 2. Use it

### The app

Open **Anneal** from the desktop or the Start menu (Linux: the applications menu, or `anneal gui`).
On Windows it opens in its own window, drawn by Microsoft Edge WebView2, which is part of
Windows 10/11. Without it, Anneal opens in your browser. Everything stays on your PC: the app is a
small local server at `http://127.0.0.1:8765` and works offline.

1. **Open a part.** Drop an STL, STEP, OBJ or 3MF on the window, or choose one. Each model becomes a
   project in your user folder, in `Anneal Projects\<name>` (for example
   `C:\Users\<you>\Anneal Projects\bracket`). The project folder also holds the spec file, so the
   command line can run the same setup.
2. **Supports and loads.** Click *Add support*, then click a bolt hole or a face on the part.
   A hole becomes a ring around its wall (Anneal measures its diameter); a flat face becomes a thin
   slab on it; *A round patch at the click* selects a spot. Hold Shift to pick several. Then
   *Add load*, click where the force acts, and type the force in newtons and its direction.
   *Add keep-out* keeps a space empty (clearance for a bolt head or a mating part);
   *Add keep-solid* keeps a wall solid. Add load cases if the part sees more than one load.
3. **Material and goal.** Pick the material (or type your own values), then either
   *Lightest part that meets the limits* or *Keep a fixed share of the material*.
4. **Optimizer, load paths and output.** Every setting of the spec file is here, with a short
   explanation: iterations, mass-search passes, smallest member, penalty, move limit, edge
   sharpness; the load-path guard (keep every load connected, required density, largest level drop,
   path repair); output formats (STL, 3MF, OBJ, PLY, GLB), smoothing, surface detail, surface
   level, report, and a folder to copy the results to (for example your slicer's folder).
5. **Check and run.** *Check setup* solves the original part at draft resolution in seconds and
   colours it by displacement or stress, so you can see that supports hold and loads push the way
   you expect. *Optimize* runs the full job with a live chart and log. *Stop* ends it.
6. **Result.** Mass, stiffness per gram, displacement and safety factor against the original; every
   check with its fix; *Displacement*, *Stress* and *Deformed* views; the original as a ghost;
   download buttons; star and notes; *Use this run's settings*.

**History** lists every run on this PC, from the app and from the command line, in a database
(`~/Anneal Projects/anneal.db`, SQLite). Search, filter by project, material, passed or starred,
sort by mass or stiffness, add notes (for example what you printed and how it tested), open a run,
reuse its settings in the current project, or tick two runs to compare them: the table shows the
results side by side and only the settings that differ. If the database is lost, Anneal rebuilds
it from the run folders.

**Quit** (top right) stops Anneal. Opening the icon again while Anneal runs shows the running one.

### On Windows, by drag and drop

1. Drag your model (`.stl`, `.step`, `.obj`, …) onto **`Anneal.bat`**.
   Anneal writes `your-part.anneal.json` next to the model and opens it. It also opens
   `your-part-preview.png`, three views of the part on a mm grid.
2. Edit the anchors in the JSON file (see section 3). Use the preview to read coordinates.
   Save the file.
3. Drag the `.json` file onto **`Anneal.bat`**. When the run finishes, the report opens in
   your browser. The optimized part is in `runs\your-part\`.

### From the command line (Windows or Ubuntu)

```bash
anneal inspect part.step            # sizes, volume, closed or not, preview image
anneal init part.step               # writes part.anneal.json (edit the anchors)
anneal run part.anneal.json --open  # optimize, check, report
anneal validate                     # solver checks
anneal materials                    # material library
anneal gui                          # the app in your browser
anneal app                          # the app in its own window
anneal history                      # past runs from the database
anneal shortcut                     # add the desktop / Start menu icon again
```

### Try the example first

```bash
anneal run examples/bracket.json --open
```

`bracket.step` is a solid wall bracket: a 10 mm flange with four M6 holes, and a solid
100 × 30 × 40 mm arm with a 12 mm load bore. The spec loads the bore 2000 N down and 600 N sideways,
keeps a 12 mm clearance hole through the arm, and asks for the lightest part that deflects
0.30 mm or less.

Result from the command line at `normal` resolution (included in `examples/runs/bracket/`): **405 g → 108 g (−73 %)**,
maximum displacement 0.274 mm (limit 0.30), safety factor 2.73, **1.46× stiffer per gram** than the
solid original. Three passes of the mass search, 24 minutes on a 2-core machine.

---

## 3. The spec file

One JSON file per part. It holds only what you know about the job. Everything else (voxel
size, filter radius, surface level, multigrid settings) is derived, and the report lists it.

```jsonc
{
  "name": "bracket",
  "model": "bracket.step",           // STL, OBJ, PLY, OFF, 3MF, GLB, STEP/STP; path relative to this file
  "designSpace": "model",            // see below
  "material": "AlSi10Mg-LPBF",       // `anneal materials` lists them; or an inline {E, nu, density, yield}
  "resolution": "normal",            // draft | normal | fine | {"voxelMM": 1.2} | {"targetElements": 60000}

  "anchors": [
    { "name": "bolt-1", "role": "fixed", "dofs": "xyz", "freezeMM": 3,
      "region": { "type": "pipe", "from": [0,10,10], "to": [10,10,10], "r": 4.4, "rIn": 2.4 } },
    { "name": "load-bore", "role": "load", "freezeMM": 3,
      "region": { "type": "pipe", "from": [95,15,40], "to": [95,45,40], "r": 7.2, "rIn": 5.0 },
      "loads": { "down": [0,0,-2000], "side": [0,600,0] } }      // newtons, one vector per load case
  ],
  "keepOut": [ { "type": "cylinder", "from": [55,10,30], "to": [55,50,30], "r": 6 } ],
  "keep":    [ ],                                              // regions that must stay solid

  "loadCases": { "down": {"weight": 1}, "side": {"weight": 1} },
  "objective": { "minimise": "mass", "volumeFraction": 0.30, "combine": "worst" },
  "optimizer": { "iterations": 70, "massPasses": 5, "minMemberMM": 6,   // minMemberMM optional (auto)
                 "penalty": 3, "move": 0.2, "sharpness": 4 },
  "limits":    { "maxDisplacementMM": 0.30, "minSafetyFactor": 2.0 },
  "loadPaths": { "guard": true, "margin": 0.1, "maxDrop": 0.15, "repair": true },
  "output":    { "formats": ["stl", "3mf"], "smoothing": 10, "upsample": 2,
                 "isoLevel": "auto", "report": true, "copyTo": "D:/Prints/brackets" }   // copyTo optional
}
```

### Design space

| Value | Meaning |
|---|---|
| `"model"` | Material may stay only inside your existing part. The usual choice for lightening a part. |
| `"hull"` (`{"type":"hull","marginMM":5}`) | The convex hull of the part, optionally grown. Lets material move into gaps and corners. |
| `{"type":"bounds","marginMM":5}` | The part's bounding box plus a margin. |
| `{"type":"box","min":[…],"max":[…]}` | A box you type. No model needed: start from rough points in space. |

### Anchors: where the part is held and loaded

Each anchor does three jobs: it selects the grid nodes where the world acts on the part, it
freezes the material near them (`freezeMM`) so the mounting stays, and, as a feature, it can add
geometry.

- `role`: `"fixed"` (held) or `"load"` (loaded). At least one of each.
- `dofs` (fixed only): which directions are held, `"xyz"` (bolted) or for example `"z"` (resting on a surface).
- `loads` (load only): `{ "caseName": [Fx, Fy, Fz] }` in newtons. The force is spread evenly over
  the selected nodes. Different anchors can share case names.
- `region`: what to select. Types: `box` (min, max), `obox` (center, normal, xdir, size: an oriented
  box, which the app makes when you click a flat face), `sphere` (center, r), `cylinder` (from, to, r),
  `pipe` (from, to, r, rIn). **For a hole that is already in the model, use a `pipe` that
  straddles the hole wall:** `rIn` a little inside the hole radius, `r` a little outside.
- `feature`: geometry that Anneal adds and holds. Use it when you start from rough points:
  - `{"bore": {"at": [x,y,z], "axis": [0,0,1], "bolt": "M5", "depthMM": 10}}` — a boss with a
    clearance hole (ISO 273 medium fit). Bolts M2–M12, or `"d"` for any diameter.
  - `{"boltCircle": {"at": […], "axis": […], "dia": 40, "count": 4, "bolt": "M5"}}`
  - `{"pad": {"at": […], "normal": [1,0,0], "w": 30, "h": 30, "t": 3}}` — a flat mounting pad.

### Objective

- `volumeFraction`: share of the design space that stays (0.03–0.95).
- `"minimise": "mass"` with `limits.maxDisplacementMM`: Anneal searches for the lightest
  volume fraction that meets the displacement limit (up to 5 passes, each later pass
  starts from the previous design). Without it, the volume fraction is used as given.
- `combine`: `"sum"` (weighted total stiffness) or `"worst"` (stiffest worst case, a p-norm).

### Optimizer, load paths and output

| Key | Default | Meaning |
|---|---|---|
| `optimizer.iterations` | 80 | Iterations per pass. 60+ for a part you make; under 25 Anneal warns. |
| `optimizer.massPasses` | 5 | Most passes in the lightest-part search. |
| `optimizer.minMemberMM` | auto | Smallest member (sets the filter radius). Auto: 6 voxels or 2 × the material's minimum wall. |
| `optimizer.penalty` | 3 | SIMP penalty for grey material. |
| `optimizer.move` | 0.2 | Largest density change per iteration. |
| `optimizer.sharpness` | 4 | Heaviside projection strength. 0 turns it off; above 8 can stall. |
| `loadPaths.guard` | true | Before the surface is made, check that every load connects to a support. |
| `loadPaths.margin` | 0.1 | Density the connection needs above the surface level. |
| `loadPaths.maxDrop` | 0.15 | Largest drop of the surface level allowed to reconnect a load. |
| `loadPaths.repair` | true | If still cut, add material along the cheapest path. |
| `output.formats` | stl, 3mf | Also obj, ply, glb. STL is always written. |
| `output.smoothing` | 10 | Taubin smoothing passes on the surface. |
| `output.upsample` | 2 | Surface detail: 1 = voxel size, 2 or 3 = finer (larger files). |
| `output.isoLevel` | auto | Surface level. Auto keeps the optimized volume; a number 0.1–0.9 (lower = thicker). |
| `output.report` | true | Write the HTML report. |
| `output.copyTo` | – | Also copy the part files to this folder. |

### Limits and checks

| Check | How it is measured |
|---|---|
| Maximum displacement | Re-solve of the **exported surface** (not the density field), corrected for shear locking |
| Safety factor | Material yield / peak von Mises stress (99.5th percentile at element centres, away from the support and load points) |
| Members ≥ 6 voxels thick | Skeleton of the as-built part. Thinner members are modelled too stiff, so displacement is scaled up by the measured factor (warning, not failure) |
| Thinnest member vs process | 2nd-percentile member thickness vs the material's minimum wall |

A failed check prints the fix, for example "Raise objective.volumeFraction".

---

## 4. Output (`runs/<name>/`)

| File | Content |
|---|---|
| `<name>-optimized.stl`, `.3mf` | The part, closed and smoothed, in the model's coordinates |
| `report.html` | Key numbers, 3D view (original vs optimized), checks, per-case table, convergence, density views, derived values |
| `run.json` | Run record: versions, input and output SHA-256 hashes, material, every derived value, results, checks |
| `density.npy` | Optimized density field (numpy array, `[i, j, k]` on the grid) |
| `spec.json` | Copy of the spec used |

---

## 5. How it works

```
model ──► voxelize (fill fractions) ──► anchors, keep-outs, frozen regions
      ──► SIMP optimization on the voxel grid (hex8 FEM, multigrid-preconditioned CG,
          density filter, penalty ramp, then Heaviside projection to sharpen the design)
      ──► load-path guard ──► smooth surface (marching cubes + Taubin) ──► voxelize the surface again
      ──► as-built re-solve ──► checks ──► report + run record
```

| Module | Job | CEM layer |
|---|---|---|
| `kernel.py` | Frames and base shapes (box, sphere, cylinder, pipe), fastener table | Shape kernel (ShapeKernel's role) |
| `geometry.py` | STL/STEP import, fill-fraction voxelizer | Geometry kernel (PicoGK's role) |
| `fem.py` | Hex8 voxel FEM, partial volumes, AMG-preconditioned CG, stress | Physics (Anneal.Solve) |
| `optimize.py` | SIMP, density filter, penalty continuation, Heaviside projection, OC, multi-load | Optimizer |
| `problem.py` | Spec → grid, anchors, guard rails with fixes | Engineering model |
| `export.py`, `run.py`, `report.py` | Load-path guard, surface, as-built re-solve, checks, mass search, record | Run harness |
| `materials.py` | Material and process data | Library |
| `pick.py` | Click on the model → hole (fitted cylinder), flat face (oriented slab) or patch | GUI |
| `fields.py` | Displacement and stress at the corners of the displayed mesh | GUI |
| `db.py` | Run history in SQLite, rebuilt from run folders if needed | Record |
| `gui/server.py`, `gui/desktop.py`, `gui/static/` | Local server, desktop window, page (three.js r160, MIT, included) | GUI |
| `validate.py` | 6-check solver gate | Validation |

Design rules carried over from the Phase 0 spike:

- **One grid, no mesh.** Each voxel is a trilinear brick. Partial voxels use their fill fraction
  as stiffness with penalty 1 (V4: binary voxels give 6.67 % error on a bar 6.4 cells deep; fill
  fractions give exact results).
- **Multigrid before GPU.** Smoothed-aggregation AMG (pyamg) with the six rigid-body modes keeps
  CG near 15–30 iterations. The hierarchy is rebuilt only when CG iterations grow.
- **Members at least 6 voxels thick** by default (filter radius = 3 voxels), and a correction
  where they are thinner.
- **Sharpen before you threshold.** After the penalty ramp, a Heaviside projection (sharpness 1 → 4)
  pushes densities toward 0 or 1, so the optimizer sees almost the part that is exported. On the
  draft bracket this gave 9 % better stiffness per gram in the exported part than thresholding a
  grey field.
- **Never cut a load path.** Before the surface is made, every load anchor must connect to a support
  through material clearly above the iso level. If not, the level drops a little (at most 0.15);
  as a last resort, material is added along the cheapest path (Dijkstra). The log says when either happens.
- **Re-solve the as-built part.** The reported numbers come from the exported surface.
- **Deterministic.** The same inputs on the same machine give bit-identical results (V5).

### Validation gate (`anneal validate`)

| Check | Expected |
|---|---|
| V1 rigid-body motion stores no energy | < 1e-10 |
| V2 uniform tension equals FL/(AE) | exact to 1e-8 |
| V3 cantilever vs Timoshenko | 86.9 % (2 deep), 95.7 % (4 deep), 98.3 % (8 deep) |
| V4 partial volume vs binary | binary 6.67 % error, partial exact |
| V5 deterministic reruns | identical SHA-256 |
| V6 SIMP vs uniform at equal mass | about 92 % lower compliance |

Fast tests: `pip install pytest` then `python -m pytest -q` (15 tests, about 40 s).

---

## 6. Limits — read before you print

- Linear elastic, isotropic, small displacement, static loads. No buckling, fatigue, contact,
  thermal or dynamic analysis.
- Stress is an estimate at element centres. Support and load points have high local stress in any
  linear model, so they are left out of the peak. Check critical parts with an independent analysis.
- FDM parts are anisotropic. Z strength can be under half the listed yield.
- Material values are typical datasheet figures. Replace them with your own coupon data in `materials.py`.
- Bolted holes are modelled as fully fixed walls. This is stiffer than a real joint.
- No overhang or support optimization yet. Check printability in your slicer.
- Voxel count sets run time. On a 2-core machine: `draft` about 2 minutes per pass, `normal` about
  10 minutes for the first pass and 4 for each later pass, `fine` about 30. The example bracket with
  the mass search takes about 20–25 minutes at `normal`. Use `draft` to set up a spec, then `normal`.
- Use 60 or more iterations for a part you will make. Under 25, the design stays grey and the
  exported part comes out heavier than the target (Anneal warns you).

## 7. Next steps on the plan

- PicoGK backend for `kernel.py` and `geometry.py` on Windows and macOS (lattice infill, exact offsets).
- Lattice grading from grey density, instead of thresholding it.
- Chrono sidecar for loads from simulated events (drop, landing), as in the method document.
- Overhang constraints, and a minimum-size constraint that holds after thresholding.

Third-party licences: numpy, scipy, scikit-image, matplotlib (BSD-3), pyamg, trimesh, three.js (MIT),
optional pywebview (BSD-3), optional cadquery-ocp / OpenCASCADE (LGPL-2.1 with the OCCT exception).
