# Anneal documentation — index

| File | For | What it holds |
|---|---|---|
| `../CLAUDE.md` | agents (always loaded) | rules, branches, commands, proof, short work list |
| `PLAN.md` | everyone | goal, current state, release plans (0.4.0, 0.4.1 torque, 0.4.2 temperature, 0.4.3 project files), road to 0.5–0.8, external review status, requirements, risks |
| `VV-STRATEGY.md` | everyone | how results are proved: code, optimizer, solution and pipeline verification, physical validation, release gates |
| `IMPROVEMENTS.md` | planning | researched improvements, ranked, with cost, proof and sources |
| `guides/NEW-PART.md` | operator | how to make a new part: framing, interfaces, design space, load-case checklist, run, read, make, test, record; thermal parts; spec template |
| `guides/DEVELOPER.md` | agents, developer | invariants, data flow, recipes for load types, material keys, check rows, gate checks, GUI controls |
| `guides/THERMAL-IMPLEMENTATION.md` | agent building 0.4.2 | code-level steps for derating and thermal stress |
| `research/thermal-loads.md` | planning | thermal physics, literature traps, staged plan T0–T4 |
| `research/CONTEXT.md` | background | digest of the research behind the decisions |
| `research/deepseek-physics-review.md` | background | external physics review (status in `PLAN.md` section 6) |
| `GUI.md` | everyone | screenshots of the app and the logo |
| `../VERIFICATION.md` | release | evidence for one release (made by `tools/prove_release.py`) |
| `../README.md` | users | install, options, every spec key |

Base truth: the `master` branch. Plans and unreleased work: `release-*` branches.
