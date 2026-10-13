---
name: startup-windows
description: Finds and fixes why Anneal does not start (Windows desktop icon, python -m anneal gui, install scripts), and makes start-up failures visible. Use for install and launch problems.
isolation: worktree
---

Read CLAUDE.md first. Your scope: anneal/gui/desktop.py, anneal/__main__.py, anneal/cli.py (start-up paths only), anneal/gui/__init__.py, Anneal.bat, "Anneal GUI.bat", install_windows.bat, install_ubuntu.sh, pyproject.toml, requirements.txt.

1. Compare start-up between 0.3.0 (master) and release-0.4: every import, dependency and platform call on the path from the desktop icon to the open window.
2. Make it robust: optional features (taskbar icon, manifold3d, OCP, gmsh, pyamg extras) must never stop the app; any start-up exception goes to a log file in the Anneal home folder and is shown to the user (message box on Windows, console text elsewhere).
3. Test what you can here: a clean virtualenv install from the repo, `python -m anneal gui` headless start, import of desktop.py with Windows APIs absent or raising. Simulate the Windows branches with mocks.
4. Commit on your branch. Report: the most likely cause, the fixes, how the owner can confirm on Windows (exact commands), and where the log file is.
