# Anneal GUI design

This document specifies the look and the interaction rules of the Anneal GUI
(`anneal/gui/static/`). It applies to the web GUI and to the desktop window (pywebview).

## 1. Brief and direction

The owner asked for "a very 1980s firm feel, with modern touches and sleekness", with nTop
(nTopology) as the model for form and function.

- **1980s firm** means an engineering workstation (Sun, Apollo, SGI, HP instruments, IBM 3270):
  hard rectangular edges, thin rules, a dense grid, uppercase micro-labels, monospace numbers,
  tabular readouts, a status line at the bottom, a key bar, and one amber accent on charcoal or
  on warm "putty" grey. No round "bubble" cards, no toys.
- **Modern** means crisp type (IBM Plex), light depth (1 px highlights and inset wells), short
  transitions (160 ms), keyboard keys, visible focus, inline SVG icons, light and dark themes,
  and WCAG AA contrast for all text.
- **nTop** gives the function: a notebook of ordered blocks on the left, a large viewport in the
  middle with a view cube and an orthographic switch, a panel on the right for display settings,
  and a status/log area at the bottom (see section 7).

## 2. Files

| File | What it holds |
|---|---|
| `style.css` | All tokens (section 3), components, layout. Both themes. |
| `index.html` | Layout: title bar, workbench (notebook, stage, inspector), pages, status line. |
| `ui.js` | Presentation only: theme switch, display panel, orthographic camera, keys, status line, block lamps. It reads `window.__anneal` and clicks existing controls. It does not change the spec. |
| `viewer.js` | 3D view. Visual parts: grid and part colours from CSS tokens, lights, label chips, view cube rotation, orthographic camera. |
| `vendor/plex-*.woff2` | IBM Plex Sans 400/500/600 and IBM Plex Mono 400/500/600, Latin subset (from `@fontsource` 5.1.0). Licence: SIL OFL 1.1, in `vendor/plex-LICENSE.txt`. Bundled so that the desktop app works offline. |

`app.js` is not changed. The existing element IDs, `name`, `data-*` attributes and classes that
`app.js` and `tools/gui_smoke.py` use are all kept.

## 3. Tokens

### 3.1 Colour

All colours are CSS variables on `:root`. The light theme is the default. The dark theme applies when
the system asks for it, or when the user selects it (`data-theme="dark"` on `<html>`). The user's
choice is saved in `localStorage` (`anneal.theme`).

| Token | Light ("putty") | Dark ("charcoal") | Use |
|---|---|---|---|
| `--ground` | `#e7e4dc` | `#17191b` | Panels, page background |
| `--raised` | `#f1efe9` | `#1e2124` | Title bar, block heads, cards, buttons |
| `--surface` | `#fbfaf6` | `#101213` | Inputs, tables, readouts (recessed wells) |
| `--line` | `#cbc6ba` | `#2f3438` | Hairline rules |
| `--line-strong` | `#9f998c` | `#4a5157` | Pane borders, control borders |
| `--ink` | `#1b1c1e` | `#e8e5dc` | Text |
| `--quiet` | `#5b5850` | `#a09d93` | Labels, help text (AA on all grounds) |
| `--accent` | `#f0a000` | `#ffb000` | Active block, selected toggle, primary action, focus |
| `--accent-ink` | `#1b1c1e` | `#17191b` | Text on the accent |
| `--accent-text` | `#8c5200` | `#ffb52e` | Accent used as text (links) |
| `--stage`, `--stage2` | `#d8d5cd` → `#c3bfb5` | `#23272b` → `#121416` | Viewport gradient |
| `--grid-major`, `--grid-minor` | `#8f8a7f`, `#b1aca2` | `#5a6066`, `#33383d` | Floor grid (read by `viewer.js`) |
| `--part-model`, `--part-result` | `#b9bdc0`, `#9fb0bd` | `#aab1b6`, `#93a6b4` | Part colours (read by `viewer.js`) |

Meaning colours do not change their meaning between themes. Only their lightness changes.

| Token | Light | Dark | Meaning |
|---|---|---|---|
| `--hold` | `#0b6f6a` | `#2bb8ad` | Support (teal) |
| `--push` | `#b0380f` | `#ff6a40` | Load (red-orange) |
| `--void` | `#6450ad` | `#a28ff0` | Keep empty (violet) |
| `--solid` | `#2763a6` | `#62a6ff` | Keep as is (blue) |
| `--ok` | `#186a33` | `#5fd38a` | PASS, block ready |
| `--bad` | `#b3261e` | `#ff7468` | FAIL, error |
| `--warn` | `#8f5a00` | `#f5c451` | WARN, needs support |

Rules:

1. Use the amber accent for one thing per area only: the active item or the main action.
2. Do not use the accent for meaning (support, load, pass, fail). Meaning has its own colours.
3. Result fields use **viridis** (perceptually uniform, readable with colour blindness, in grey
   print). The legend shows the same map with tick marks at tenths.

### 3.2 Type

| Role | Font | Size / weight | Case |
|---|---|---|---|
| Body, help | IBM Plex Sans | 13 px / 400, help 12 px | Sentence |
| Micro-label (pane heads, fieldset legends, table heads, keys) | IBM Plex Mono | 10–11 px / 500–600, tracking 0.08–0.12 em | UPPERCASE |
| Block title | IBM Plex Mono | 11.5 px / 600 | UPPERCASE |
| Numbers in inputs, tables, readouts | IBM Plex Mono | 11–12 px; readout value 20 px / 500 | – |
| Page title | IBM Plex Mono | 15 px / 600 | UPPERCASE |
| Wordmark | IBM Plex Mono | 13 px / 600, tracking 0.32 em | `ANNEAL` |

All numbers use tabular figures.

### 3.3 Space, size and shape

- Grid unit: 4 px. Gaps are 4, 6, 8, 10, 12, 16 or 28 px.
- Control height: 26 px (`--ctl`). Primary button: 30 px.
- Corner radius: 2 px (`--r`). Pills and tags are square.
- Rules: 1 px. Pane borders use `--line-strong`; rules inside a pane use `--line`.
- Depth: buttons have a 1 px top highlight and a 1 px drop (`--shadow`). Inputs are wells
  (`--well`, inset shadow). Overlays on the viewport use a 6 px backdrop blur.
- Motion: 160 ms, `cubic-bezier(.2,.6,.2,1)`. Off when the system asks for reduced motion.

## 4. Layout

```
+--------------------------------------------------------------------------------+
| [#] ANNEAL | project  model.stl               PROJECTS HISTORY LIBRARY [/] QUIT |  title bar 40 px
+---------------+-------------------------------------------------+--------------+
| NOTEBOOK  1-6 |  ┌                                  [view cube] ┐ | DISPLAY  Hide|
| [01] MODEL  ■ |                                    ISO FIT ORTHO| COLOUR BY    |
| [02] SUPPORTS■|                                                 | SHAPE        |
|   ...body...  |              3D viewport                        | CAMERA       |
| [03] MATERIAL■|                                                 | REGIONS      |
| [04] OPTIMIZER|  xyz                               [legend]     |              |
| [05] RUN    □ |  └ navigation help                              ┘ |              |
| [06] RESULT □ |                                                 |              |
+---------------+-------------------------------------------------+--------------+
| ■ READY | status message ...        PASS 2 · IT 14/70 [====]  F I O M P D | ver |  status line 26 px
+--------------------------------------------------------------------------------+
```

- Notebook: 330–380 px (310–340 px under 1180 px window width).
- Inspector: 208 px (184 px under 1180 px). Key `P` or the *Hide* button hides it.
- Under 900 px the panes stack: viewport, display panel, notebook.
- The viewport has corner ticks (an instrument screen), the view cube top right, the axis triad
  bottom left, the legend bottom right.

## 5. Components

| Component | Specification |
|---|---|
| Title bar | Square tabs with vertical rules. Active tab: `--ground` fill and a 2 px amber underline. |
| Block (step) | Head: number box `01`–`06`, title in mono uppercase, summary in mono quiet, state lamp. Open block: amber number box and a 3 px amber bar on the left. |
| State lamp | 8 px square. Hollow = to do. Green = ready. Amber, blinking = running. Red = error. Yellow = the result has a failed or warning check. |
| Fieldset | Top rule with the legend as an uppercase micro-label on the rule. |
| Row | Label left (quiet), control right (112–150 px). |
| Input | Recessed well, mono numbers, right-aligned numbers. Focus: amber border and a 2 px amber halo. |
| Button | Square, raised, 1 px border. Role buttons keep a 4 px colour bar on the left (support, load, keep-out, keep). Armed role button: inverted, with the word ARMED in amber. |
| Primary button | Amber fill, mono uppercase, for one main action per view (Choose a model, Optimize, Save). |
| Segmented toggle | Grid of square cells with 1 px gaps. Selected cell: amber. |
| Readout grid (`.figures`) | Instrument panel: cells on `--surface`, label in micro-caps, value in 20 px mono. |
| Check list | `PASS` / `FAIL` / `WARN` in square mono tags with a tint. |
| Progress bar | Recessed, amber with fine 2 px gaps (a segment display). |
| Legend | Blurred panel, title in micro-caps, viridis bar with tenth ticks, mono values. |
| Viewport label | Dark chip, coloured bar, mono text (for example `2,000 N`). |
| Toast / hint | Inverted bar with an amber left edge. |
| Status line | State lamp and word (READY, RUNNING, CHECKING, STOPPED, ERROR), the last message, a pass/iteration meter while a run is active, the key bar, the version. |

## 6. Interaction rules

1. Every control keeps its function and its place in the step order of the notebook.
2. Keys work when the focus is not in a text field, and without Ctrl, Alt or Cmd:
   - `1`–`6` open a notebook block.
   - `F` fit, `I` iso, `T` top, `V` front, `R` right.
   - `O` orthographic or perspective camera. The part keeps its size on the screen.
   - `M` move mode (left drag moves the view).
   - `P` show or hide the display panel.
   - `D` light or dark theme.
   - `Esc` stops picking (from `app.js`).
   The status line shows the keys as buttons; a click does the same as the key.
3. A face of the view cube is a camera button (TOP, BOTTOM, FRONT, BACK, RIGHT, LEFT).
4. The focus ring is always visible for keyboard focus (`:focus-visible`).
5. Hover changes are colour changes only. Nothing moves or grows on hover.
6. The app does not show a state that it does not know. A lamp is green only when the block has
   what it needs (from `app.js`), and amber only while a job runs.

## 7. nTop mapping

| nTop | Anneal | Notes |
|---|---|---|
| Notebook of blocks, top to bottom | Notebook with the six steps: model and design space → supports and loads → material, process and goal → optimizer, load paths and output → check and run → result | The order is the data flow, as in nTop. Blocks show their inputs inline. |
| Block status icon (grey built, blue incomplete, yellow warning, red error) | State lamp on each block head | Same idea, colours from Anneal's tokens: green ready, hollow to do, yellow warning, red error, amber running. |
| Block summary/outputs on the collapsed block | Summary text on each block head (size, supports and loads, material and goal, iterations, run state, mass) | Already in `app.js`; now set in mono. |
| Viewport with view cube, perspective/orthographic | View cube (HTML, turns with the camera), ISO/FIT/ORTHO buttons | Orthographic is useful for checking wall thickness and alignment. |
| Right panel, Display tab | Display panel: colour by, deformation, load case, original ghost, camera, move mode, region key | Holds the view controls that were on top of the viewport, so the viewport is clear. |
| Error log / messages | Status line plus the log in block 5 | The status line shows the last log line during a job. |
| Ribbon of block types | Not adopted | Anneal has a fixed pipeline, not a free graph. |

## 8. Ideas left for later

- A "stale" lamp for the result block when the settings changed after the run (needs a reliable
  comparison of the run spec and the current spec in `app.js`).
- Section planes (clip the part) in the viewport.
- A ruler / measure tool (nTop has one in orthographic view).
- A compact log console under the viewport that the user can open and close.
- Pick highlights in the viewport that follow the selected anchor card.
- Use the theme tokens in the convergence chart of block 5 (it uses `--ink` and `--hold` now, and
  the font of `app.js`).
