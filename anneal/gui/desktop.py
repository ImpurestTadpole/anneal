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
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_ICO = os.path.join(HERE, "static", "anneal.ico")
ICON_PNG = os.path.join(HERE, "static", "anneal-256.png")


def _log_to_file(workspace):
    """pythonw has no console: keep messages in a log file inside the projects folder."""
    if sys.stdout is None or not hasattr(sys.stdout, "write") or sys.executable.lower().endswith("pythonw.exe"):
        os.makedirs(workspace, exist_ok=True)
        fh = open(os.path.join(workspace, "anneal-app.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = fh


def app(workspace=None, port=8765):
    from .server import start_server, default_workspace, running_instance
    ws = workspace or default_workspace()
    _log_to_file(ws)
    existing = running_instance(port)
    if existing:   # second click on the icon: show the running Anneal instead of starting another
        webbrowser.open(existing)
        return 0
    srv, url, app_state = start_server(ws, port)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "Anneal app on", url)
    try:
        import webview  # pywebview
    except ImportError:
        webview = None
    if webview is not None:
        try:
            set_app_id()
            window = webview.create_window("Anneal", url, width=1440, height=900, min_size=(960, 640))
            try:
                window.events.shown += lambda: set_window_icon(window)
            except Exception:
                pass
            try:
                webview.start(icon=ICON_PNG)   # the icon argument is used by the GTK and Qt back ends
            except TypeError:                  # older pywebview without the argument
                webview.start()          # returns when the window is closed
            srv.shutdown()
            return 0
        except Exception as e:  # WebView2 missing or blocked: fall back to the browser
            print("Desktop window not available:", e, "- opening the browser instead")
    webbrowser.open(url)
    print("Anneal is running in your browser. Use Quit in the Anneal page to stop it.")
    try:
        while not app_state.stop.wait(1.0):
            pass
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        srv.shutdown()


APP_ID = "Anneal.TopologyOptimizer"


def set_app_id():
    """Windows groups taskbar buttons by AppUserModelID. Without one, the Anneal window is grouped
    under pythonw.exe and shows the Python icon. Must run before the first window opens."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        return True
    except Exception as e:
        print("Could not set the taskbar ID:", e)
        return False


def set_window_icon(window):
    """Give the window (title bar and taskbar button) the Anneal icon. On Windows pywebview draws
    with WinForms: set Form.Icon on the UI thread through pythonnet."""
    if not sys.platform.startswith("win"):
        return False
    try:
        form = getattr(window, "native", None)
        if form is None:
            return False
        from System import Action                 # pythonnet, installed with pywebview on Windows
        from System.Drawing import Icon
        form.Invoke(Action(lambda: setattr(form, "Icon", Icon(ICON_ICO))))
        return True
    except Exception as e:
        print("Could not set the window icon:", e)
        return False


def shortcut():
    if sys.platform.startswith("win"):
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
