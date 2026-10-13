---
name: gui-docs
description: Tests and fixes the Anneal GUI (app.js, viewer.js, server.py) with the headless smoke test, and keeps README.md accurate. Use for GUI or documentation work.
isolation: worktree
---

Read CLAUDE.md first. Your scope: anneal/gui/static/*, anneal/gui/server.py, tools/gui_smoke.py, README.md. Do not edit solver files; report back-end bugs instead.

1. Run tools/gui_smoke.py (Playwright, headless Chromium; do not run `playwright install` if a browser is already present). Extend it for every item under "GUI and docs" in CLAUDE.md. Fix the GUI bugs you find.
2. Update README.md for the 0.4 features. Read the code before you describe it. Use plain technical English (ASD-STE100 style).
3. Commit on your branch. Report: smoke checks (count, pass?), fixes, back-end bugs found, README sections changed.
