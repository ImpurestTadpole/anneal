"""Desktop mode and shortcuts.

`anneal app` opens Anneal in its own window. It uses pywebview, which on Windows 10/11
draws with Microsoft Edge WebView2 (already part of Windows). Without pywebview it opens
your browser instead. `anneal shortcut` puts an Anneal icon on the desktop and in the
Start menu (Windows) or the applications menu (Linux).
"""
import os
import subprocess
import sys
import time
import traceback
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_ICO = os.path.join(HERE, "static", "anneal.ico")
ICON_PNG = os.path.join(HERE, "static", "anneal-256.png")
APP_ID = "Anneal.TopologyOptimizer"
STARTUP_LOG = "anneal-startup.log"


def _windows():
    """True on Windows. One place, so tests can simulate the Windows branches."""
    return sys.platform.startswith("win")


# ---------------------------------------------------------------------------------------------
# Start-up errors: write them to a log file and show them. Only the standard library is used here,
# so this works even when numpy, scipy or pywebview cannot be imported.

def anneal_home():
    """The Anneal home folder (ANNEAL_HOME, or ~/Anneal Projects)."""
    return os.environ.get("ANNEAL_HOME") or os.path.join(os.path.expanduser("~"), "Anneal Projects")


def startup_log_path():
    return os.path.join(anneal_home(), STARTUP_LOG)


def log_startup(message):
    """Append one message to the start-up log. Never raises. Returns the log path, or None."""
    path = startup_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message.rstrip()}\n")
        return path
    except Exception:
        return None


def has_console():
    """True when stderr goes somewhere a person can read (not pythonw)."""
    if sys.stderr is None or not hasattr(sys.stderr, "write"):
        return False
    return not os.path.basename(sys.executable).lower().startswith("pythonw")


def show_error(title, text, force_box=False):
    """Show an error. Windows: a message box when there is no console (or force_box). Elsewhere, or
    when the box fails: text on stderr. Never raises."""
    shown = False
    if _windows() and (force_box or not has_console()):
        try:
            import ctypes
            MB_OK, MB_ICONERROR, MB_SETFOREGROUND = 0x0, 0x10, 0x10000
            ctypes.windll.user32.MessageBoxW(None, str(text), str(title), MB_OK | MB_ICONERROR | MB_SETFOREGROUND)
            shown = True
        except Exception:
            shown = False
    for stream in (sys.stderr, sys.__stderr__):
        if stream is None or not hasattr(stream, "write"):
            continue
        try:
            stream.write(f"\n{title}\n{text}\n")
            stream.flush()
            shown = True
            break
        except Exception:
            continue
    return shown


def report_startup_error(exc=None, what="Anneal could not start", force_box=False):
    """Write the traceback of the current (or given) exception to the start-up log and show a short
    message with the log path. Never raises. Returns the log path, or None."""
    try:
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        else:
            tb = traceback.format_exc()
    except Exception:
        tb = repr(exc)
    path = log_startup(f"{what}.\n{tb}")
    last = (tb.strip().splitlines() or [what])[-1]
    text = f"{what}.\n\n{last}\n\n"
    text += (f"The full report is in:\n{path}" if path else "The report could not be written to a file.")
    text += "\n\nTo see more, run \"Anneal GUI.bat\" (Windows) or: python -m anneal app"
    show_error("Anneal", text, force_box=force_box)
    return path


def _log_to_file(workspace):
    """pythonw has no console: keep messages in a log file inside the projects folder."""
    if sys.stdout is None or not hasattr(sys.stdout, "write") or not has_console():
        try:
            os.makedirs(workspace, exist_ok=True)
            fh = open(os.path.join(workspace, "anneal-app.log"), "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = fh
        except Exception:   # no log file: drop the messages, but never stop the app for this
            sys.stdout = sys.stderr = open(os.devnull, "w")


def _note(msg):
    """A message for the app log (stdout) that never raises."""
    try:
        print(msg)
    except Exception:
        pass


# ---------------------------------------------------------------------------------------------
# The desktop window

def app(workspace=None, port=8765):
    """Open Anneal in its own window. Every optional part (pywebview, taskbar ID, window icon) can
    fail: Anneal then opens in the browser instead. Errors go to the start-up log."""
    from .server import start_server, default_workspace, running_instance
    ws = workspace or default_workspace()
    _log_to_file(ws)
    existing = running_instance(port)
    if existing:   # second click on the icon: show the running Anneal instead of starting another
        webbrowser.open(existing)
        return 0
    srv, url, app_state = start_server(ws, port)
    _note(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Anneal app on {url}")
    if os.environ.get("ANNEAL_NO_WINDOW"):
        _note("ANNEAL_NO_WINDOW is set: the desktop window is not used.")
    elif open_window(url):
        srv.shutdown()
        return 0
    try:
        webbrowser.open(url)
    except Exception as e:
        _note(f"Could not open the browser: {e}. Open {url} yourself.")
    _note("Anneal is running in your browser. Use Quit in the Anneal page to stop it.")
    try:
        while not app_state.stop.wait(1.0):
            pass
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        srv.shutdown()


WINDOW_PENDING = "anneal-window.pending"


def _pending_path():
    return os.path.join(anneal_home(), WINDOW_PENDING)


def _clear_pending():
    try:
        os.remove(_pending_path())
    except OSError:
        pass


def open_window(url):
    """Show `url` in a pywebview window and return when it is closed. Returns True when the window
    was shown, False when the caller must use the browser instead. Never raises.

    A marker file is written before the window opens and removed when it shows. If the process
    stops while the window opens (an error on the GUI thread can end the process with no Python
    exception), the marker stays: the next start writes this to the start-up log and uses the
    browser once, so the second click on the icon always opens Anneal."""
    if os.path.exists(_pending_path()):
        _clear_pending()
        log_startup("The desktop window did not open the last time (the process stopped while the "
                    "window opened). This time the browser is used. The next start tries the window again. "
                    "To see the error, run \"Anneal GUI.bat\" (Windows) or: python -m anneal app")
        _note("The desktop window failed the last time - opening the browser instead")
        return False
    try:
        import webview  # pywebview
    except Exception as e:   # not installed, or a broken install (pythonnet, WebView2 loader)
        _note(f"Desktop window not available ({type(e).__name__}: {e}). Opening the browser instead.")
        return False
    shown = {"ok": False}
    try:
        with open(_pending_path(), "w", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    except OSError:
        pass
    try:
        set_app_id()
        window = webview.create_window("Anneal", url, width=1440, height=900, min_size=(960, 640))
        try:
            window.events.shown += lambda: _on_shown(window, shown)
        except Exception as e:
            shown["ok"] = None     # cannot tell if the window opened: trust webview.start()
            _clear_pending()
            _note(f"Could not watch the window: {e}")
        kwargs = start_kwargs(webview)
        _note(f"Opening the desktop window (pywebview {_dist_version('webview') or '?'}, start{tuple(kwargs)})")
        webview.start(**kwargs)   # returns when the window is closed
    except Exception as e:  # WebView2 missing or blocked, GUI back end missing
        _clear_pending()
        log_startup(f"Desktop window failed, the browser is used instead.\n{traceback.format_exc()}")
        _note(f"Desktop window not available: {e} - opening the browser instead")
        return False
    _clear_pending()
    if shown["ok"] is False:
        log_startup("The desktop window did not open (webview.start returned without showing it). "
                    "The browser is used instead. See anneal-app.log in the same folder.")
        _note("The desktop window did not open - opening the browser instead")
        return False
    _note("The desktop window is closed.")
    return True


def _on_shown(window, shown):
    shown["ok"] = True
    _clear_pending()
    set_window_icon(window)


def start_kwargs(webview):
    """Arguments for webview.start(). The icon argument is given only on Linux/macOS (GTK, Qt).
    On Windows, pywebview 6.2 and newer passes it to System.Drawing.Icon(), which accepts only
    .ico files: a PNG raises ArgumentException on the GUI thread and the window never opens. On
    Windows the icon is set after the window opens instead (set_window_icon)."""
    if _windows():
        return {}
    if not os.path.isfile(ICON_PNG):
        return {}
    try:
        import inspect
        if "icon" in inspect.signature(webview.start).parameters:
            return {"icon": ICON_PNG}
    except Exception:
        pass
    return {}


def set_app_id():
    """Windows groups taskbar buttons by AppUserModelID. Without one, the Anneal window is grouped
    under pythonw.exe and shows the Python icon. Must run before the first window opens. Optional:
    a failure is logged and ignored."""
    if not _windows():
        return False
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        return True
    except Exception as e:   # also a missing windll/shell32 or an OSError from the call
        _note(f"Could not set the taskbar ID: {e}")
        return False


def set_window_icon(window):
    """Give the window (title bar and taskbar button) the Anneal icon. On Windows pywebview draws
    with WinForms: set Form.Icon on the UI thread through pythonnet. Optional: a failure is logged
    and ignored."""
    if not _windows():
        return False
    try:
        form = getattr(window, "native", None)
        if form is None or not os.path.isfile(ICON_ICO):
            return False
        from System import Action                 # pythonnet, installed with pywebview on Windows
        from System.Drawing import Icon

        def apply():
            try:
                form.Icon = Icon(ICON_ICO)
            except BaseException as e:   # a .NET exception here must not reach the GUI thread
                _note(f"Could not set the window icon: {e}")
        form.BeginInvoke(Action(apply))           # do not block; the UI thread runs it later
        return True
    except Exception as e:
        _note(f"Could not set the window icon: {e}")
        return False


def doctor():
    """`anneal doctor`: print what the start-up path needs and what is installed. Optional parts
    show "not installed"; they never stop Anneal."""
    import importlib
    import platform
    print(f"Python      {sys.version.split()[0]}  {sys.executable}")
    print(f"System      {platform.platform()}")
    try:
        from .. import __version__
        print(f"Anneal      {__version__}  {os.path.dirname(HERE)}")
    except Exception as e:
        print(f"Anneal      cannot import: {e}")
    print(f"Home        {anneal_home()}")
    print(f"Logs        {startup_log_path()}")
    print(f"            {os.path.join(anneal_home(), 'anneal-app.log')}")
    bad = 0
    rows = [("numpy", True), ("scipy", True), ("pyamg", True), ("trimesh", True), ("skimage", True),
            ("matplotlib", True), ("manifold3d", True), ("OCP", False), ("gmsh", False), ("webview", False)]
    if _windows():
        rows.append(("clr", False))     # pythonnet, used by pywebview on Windows
    for name, required in rows:
        try:
            importlib.import_module(name)
            state = f"ok {_dist_version(name)}".strip()
        except Exception as e:
            state = f"{'MISSING' if required else 'not installed (optional)'}: {type(e).__name__}: {e}"
            bad += required
        print(f"  {name:11s} {state}")
    try:
        import webview
        print(f"  start(icon=...) passed: {'icon' in start_kwargs(webview)}")
    except Exception:
        pass
    if _windows():
        print(f"  WebView2    {_webview2_version() or 'not found (the browser is used instead)'}")
        print(f"  taskbar ID  {'ok' if set_app_id() else 'failed (optional)'}")
    print("Result:", "OK" if not bad else f"{bad} required package(s) missing: run the installer again")
    return 0 if not bad else 1


def _dist_version(module):
    dist = {"skimage": "scikit-image", "OCP": "cadquery-ocp", "webview": "pywebview", "clr": "pythonnet"}.get(module, module)
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:
        return ""


def _webview2_version():
    """Version of the Microsoft Edge WebView2 runtime, from the registry, or None."""
    try:
        import winreg
    except Exception:
        return None
    key = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for root, path in ((winreg.HKEY_LOCAL_MACHINE, key), (winreg.HKEY_CURRENT_USER, key.replace("WOW6432Node\\", ""))):
        try:
            with winreg.OpenKey(root, path) as k:
                return winreg.QueryValueEx(k, "pv")[0]
        except Exception:
            continue
    return None


def shortcut():
    if _windows():
        return _shortcut_windows()
    if sys.platform.startswith("linux"):
        return _shortcut_linux()
    print("Shortcuts are made on Windows and Linux. On macOS run: python -m anneal app")
    return 1


def _shortcut_windows():
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(exe):
        exe = sys.executable
    workdir = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
    q = lambda v: str(v).replace("'", "''")   # PowerShell single-quote escape (names like O'Neil)
    exe, workdir, icon = q(exe), q(workdir), q(ICON_ICO)
    targets = []
    ps = []
    for folder in ("Desktop", "Programs"):
        ps.append(
            f"$f = [Environment]::GetFolderPath('{'Desktop' if folder == 'Desktop' else 'Programs'}');"
            f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $f 'Anneal.lnk'));"
            f"$s.TargetPath = '{exe}'; $s.Arguments = '-m anneal app'; $s.WorkingDirectory = '{workdir}';"
            f"$s.IconLocation = '{icon},0'; $s.Description = 'Anneal - optimize parts'; $s.Save();"
            f"Write-Output (Join-Path $f 'Anneal.lnk')")
    for cmd in ps:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                           capture_output=True, text=True)
        if r.returncode == 0:
            targets.append(r.stdout.strip())
        else:
            print("Could not make a shortcut:", r.stderr.strip())
    for t in targets:
        print("Shortcut:", t)
    return 0 if targets else 1


def _shortcut_linux():
    apps = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
    os.makedirs(apps, exist_ok=True)
    path = os.path.join(apps, "anneal.desktop")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[Desktop Entry]\nType=Application\nName=Anneal\nComment=Optimize parts\n"
                 f"Exec=\"{sys.executable}\" -m anneal app\nIcon={ICON_PNG}\nTerminal=false\n"
                 "Categories=Graphics;Engineering;\n")
    os.chmod(path, 0o755)
    desk = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(desk):
        import shutil
        shutil.copy(path, os.path.join(desk, "anneal.desktop"))
        os.chmod(os.path.join(desk, "anneal.desktop"), 0o755)
    print("Shortcut:", path)
    return 0
