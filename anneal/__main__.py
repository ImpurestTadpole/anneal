"""python -m anneal ...  (the desktop icon runs: pythonw -m anneal app)

If Anneal cannot even be imported (a package is missing or broken), the error goes to
~/Anneal Projects/anneal-startup.log and to a message box (Windows) or the console. pythonw has no
console, so without this the desktop icon would do nothing at all.
"""
import sys


def _start():
    try:
        from .cli import main
    except Exception as e:
        try:
            from .gui.desktop import report_startup_error
        except Exception:   # last resort: plain text on the console, if there is one
            import traceback
            traceback.print_exc()
            return 1
        report_startup_error(e, "Anneal could not load its packages", force_box="app" in sys.argv[1:])
        return 1
    return main()


sys.exit(_start())
