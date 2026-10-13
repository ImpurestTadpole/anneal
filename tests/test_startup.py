"""Start-up path: the desktop icon (pythonw -m anneal app), `python -m anneal gui`, and the Windows
calls around the window. The Windows APIs are replaced by mocks that are missing or raise; the app
path must still continue (window, or the browser as fallback), and errors must reach the log."""
import json
import os
import socket
import subprocess
import sys
import textwrap
import time
import types
import urllib.request

import pytest

from anneal.gui import desktop

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "Anneal Projects"
    monkeypatch.setenv("ANNEAL_HOME", str(h))
    return h


@pytest.fixture
def windows(monkeypatch):
    """Pretend to be Windows."""
    monkeypatch.setattr(desktop, "_windows", lambda: True)


def _fake_ctypes(monkeypatch, windll):
    """Give the real ctypes a mock `windll` (or none at all, as on Linux)."""
    import ctypes
    if windll is None:
        monkeypatch.delattr(ctypes, "windll", raising=False)
    else:
        monkeypatch.setattr(ctypes, "windll", windll, raising=False)
    return ctypes


def _raising(*a, **k):
    raise OSError("access denied (mock)")


# ----- taskbar ID --------------------------------------------------------------------------------

def test_app_id_without_windll(windows, monkeypatch):
    _fake_ctypes(monkeypatch, None)            # ctypes has no windll attribute
    assert desktop.set_app_id() is False


def test_app_id_raising(windows, monkeypatch):
    shell32 = types.SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=_raising)
    _fake_ctypes(monkeypatch, types.SimpleNamespace(shell32=shell32))
    assert desktop.set_app_id() is False


def test_app_id_ok(windows, monkeypatch):
    calls = []
    shell32 = types.SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=calls.append)
    _fake_ctypes(monkeypatch, types.SimpleNamespace(shell32=shell32))
    assert desktop.set_app_id() is True
    assert calls == [desktop.APP_ID]


def test_app_id_not_windows():
    if sys.platform.startswith("win"):
        pytest.skip("Linux/macOS branch")
    assert desktop.set_app_id() is False


# ----- window icon (WinForms through pythonnet) --------------------------------------------------

def _fake_dotnet(monkeypatch, icon_cls):
    system = types.ModuleType("System")
    system.Action = lambda f: f
    drawing = types.ModuleType("System.Drawing")
    drawing.Icon = icon_cls
    system.Drawing = drawing
    monkeypatch.setitem(sys.modules, "System", system)
    monkeypatch.setitem(sys.modules, "System.Drawing", drawing)


class _Form:
    def __init__(self):
        self.Icon = None

    def BeginInvoke(self, action):   # the UI thread runs the action
        action()


def test_icon_without_pythonnet(windows, monkeypatch):
    monkeypatch.setitem(sys.modules, "System", None)      # import System -> ImportError
    w = types.SimpleNamespace(native=_Form())
    assert desktop.set_window_icon(w) is False


def test_icon_without_native_form(windows):
    assert desktop.set_window_icon(types.SimpleNamespace()) is False


def test_icon_constructor_raising(windows, monkeypatch):
    def bad_icon(path):
        raise ValueError("Argument 'picture' must be a picture that can be used as a Icon (mock)")
    _fake_dotnet(monkeypatch, bad_icon)
    form = _Form()
    desktop.set_window_icon(types.SimpleNamespace(native=form))   # must not raise
    assert form.Icon is None


def test_icon_ok(windows, monkeypatch):
    _fake_dotnet(monkeypatch, lambda path: ("icon", path))
    form = _Form()
    assert desktop.set_window_icon(types.SimpleNamespace(native=form)) is True
    assert form.Icon == ("icon", desktop.ICON_ICO)


# ----- webview.start() arguments -----------------------------------------------------------------

def _webview_with_start(start):
    return types.SimpleNamespace(start=start)


def test_no_icon_argument_on_windows(windows):
    """pywebview >= 6.2 passes start(icon=...) to System.Drawing.Icon() on Windows; a PNG makes the
    GUI thread fail and the window never opens. On Windows the argument must not be passed."""
    def start(func=None, icon=None):
        pass
    assert desktop.start_kwargs(_webview_with_start(start)) == {}


def test_icon_argument_elsewhere(monkeypatch):
    monkeypatch.setattr(desktop, "_windows", lambda: False)
    def start(func=None, icon=None):
        pass
    def old_start(func=None):
        pass
    assert desktop.start_kwargs(_webview_with_start(start)) == {"icon": desktop.ICON_PNG}
    assert desktop.start_kwargs(_webview_with_start(old_start)) == {}


# ----- the window, with a fake pywebview ---------------------------------------------------------

class _Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, h):
        self.handlers.append(h)
        return self

    def fire(self):
        for h in self.handlers:
            h()


def _fake_webview(monkeypatch, show=True, start_error=None, create_error=None):
    wv = types.ModuleType("webview")
    wv.windows = []
    wv.start_calls = []

    def create_window(*a, **k):
        if create_error:
            raise create_error
        w = types.SimpleNamespace(events=types.SimpleNamespace(shown=_Event()), native=None)
        wv.windows.append(w)
        return w

    def start(func=None, icon=None, **k):
        wv.start_calls.append(dict(icon=icon, **k))
        if start_error:
            raise start_error
        if show:
            for w in wv.windows:
                w.events.shown.fire()

    wv.create_window, wv.start = create_window, start
    monkeypatch.setitem(sys.modules, "webview", wv)
    return wv


def test_window_opens(windows, monkeypatch, home):
    shell32 = types.SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=_raising)
    _fake_ctypes(monkeypatch, types.SimpleNamespace(shell32=shell32))   # taskbar ID fails
    monkeypatch.setitem(sys.modules, "System", None)                    # no pythonnet
    wv = _fake_webview(monkeypatch, show=True)
    assert desktop.open_window("http://127.0.0.1:1/") is True
    assert wv.start_calls == [{"icon": None}]                           # no icon on Windows


def test_window_never_shown_falls_back(windows, monkeypatch, home):
    """The 0.4.0 preview failure: webview.start() returns (or its GUI thread dies) without a window."""
    _fake_webview(monkeypatch, show=False)
    assert desktop.open_window("http://127.0.0.1:1/") is False
    log = (home / desktop.STARTUP_LOG).read_text(encoding="utf-8")
    assert "did not open" in log


def test_window_start_raising_falls_back(windows, monkeypatch, home):
    _fake_webview(monkeypatch, start_error=RuntimeError("WebView2 runtime not found (mock)"))
    assert desktop.open_window("http://127.0.0.1:1/") is False
    assert "WebView2 runtime not found" in (home / desktop.STARTUP_LOG).read_text(encoding="utf-8")


def test_webview_import_raising(monkeypatch, home):
    class Broken(types.ModuleType):
        def __getattr__(self, name):
            raise RuntimeError("Failed to resolve Python.Runtime.Loader (mock)")
    monkeypatch.setitem(sys.modules, "webview", None)   # import webview -> ImportError
    assert desktop.open_window("http://127.0.0.1:1/") is False
    monkeypatch.setitem(sys.modules, "webview", Broken("webview"))
    assert desktop.open_window("http://127.0.0.1:1/") is False


def test_app_falls_back_to_browser_and_server_answers(windows, monkeypatch, home):
    """Full app() path with every Windows API missing and a window that never shows: the server
    still answers and the browser is opened instead."""
    _fake_ctypes(monkeypatch, None)
    monkeypatch.setitem(sys.modules, "System", None)
    _fake_webview(monkeypatch, show=False)
    opened = []

    def fake_browser(url):
        with urllib.request.urlopen(url + "api/state", timeout=5) as r:
            opened.append((url, r.status))
        req = urllib.request.Request(url + "api/quit", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
        return True

    monkeypatch.setattr(desktop.webbrowser, "open", fake_browser)
    monkeypatch.setattr(sys, "stdout", sys.stdout)   # app() may redirect stdout; restore after
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    assert desktop.app(str(home), _free_port()) == 0
    assert opened and opened[0][1] == 200


# ----- reporting ---------------------------------------------------------------------------------

def test_report_shows_message_box(windows, monkeypatch, home):
    boxes = []
    user32 = types.SimpleNamespace(MessageBoxW=lambda h, text, title, flags: boxes.append((title, text)))
    _fake_ctypes(monkeypatch, types.SimpleNamespace(user32=user32))
    try:
        raise ImportError("DLL load failed while importing _multiarray_umath (mock)")
    except ImportError as e:
        path = desktop.report_startup_error(e, force_box=True)
    assert path == str(home / desktop.STARTUP_LOG)
    assert "DLL load failed" in open(path, encoding="utf-8").read()
    assert boxes and boxes[0][0] == "Anneal" and path in boxes[0][1]


def test_report_message_box_raising(windows, monkeypatch, home, capsys):
    _fake_ctypes(monkeypatch, types.SimpleNamespace(user32=types.SimpleNamespace(MessageBoxW=_raising)))
    desktop.report_startup_error(RuntimeError("boom (mock)"), force_box=True)
    assert "boom (mock)" in capsys.readouterr().err   # falls back to the console


def test_report_unwritable_home(monkeypatch, tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("ANNEAL_HOME", str(blocker / "sub"))   # cannot be created
    assert desktop.report_startup_error(RuntimeError("no log (mock)")) is None
    assert "no log (mock)" in capsys.readouterr().err


def test_cli_app_error_is_reported(monkeypatch, home):
    from anneal import cli
    from anneal.gui import server
    reported = []
    monkeypatch.setattr(server, "start_server", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("No free port (mock)")))
    monkeypatch.setattr(desktop, "show_error", lambda title, text, force_box=False: reported.append(text))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    assert cli.main(["app", "--workspace", str(home), "--port", str(_free_port())]) == 1
    assert reported and "No free port" in reported[0]
    assert "No free port" in (home / desktop.STARTUP_LOG).read_text(encoding="utf-8")


# ----- real processes ----------------------------------------------------------------------------

def _env(home, extra_path=None):
    env = dict(os.environ, ANNEAL_HOME=str(home), PYTHONIOENCODING="utf-8")
    env["PYTHONPATH"] = os.pathsep.join(p for p in (extra_path, ROOT, env.get("PYTHONPATH")) if p)
    return env


def _wait_http(url, proc, seconds=60):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if proc.poll() is not None:
            raise AssertionError("server stopped: " + proc.stdout.read())
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                return r.status, json.loads(r.read())
        except Exception:
            time.sleep(0.3)
    raise AssertionError("server did not answer")


def _gui(home, extra_path=None):
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "anneal", "gui", "--no-browser", "--port", str(port),
                             "--workspace", str(home)], cwd=ROOT, env=_env(home, extra_path),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc, f"http://127.0.0.1:{port}/"


def test_gui_headless_server_answers(home):
    proc, url = _gui(home)
    try:
        status, state = _wait_http(url + "api/state", proc)
        assert status == 200
        with urllib.request.urlopen(url, timeout=5) as r:
            assert r.status == 200 and b"<html" in r.read().lower()
    finally:
        proc.kill()
        proc.wait()


def test_gui_starts_with_broken_optional_and_solver_packages(home, tmp_path):
    """Optional packages that raise on import (manifold3d, OCP, gmsh, webview) and a broken pyamg
    must not stop the GUI server."""
    fake = tmp_path / "broken"
    fake.mkdir()
    for name in ("manifold3d", "OCP", "gmsh", "webview", "pyamg"):
        (fake / f"{name}.py").write_text(f"raise ImportError('{name} is broken (mock)')\n")
    proc, url = _gui(home, str(fake))
    try:
        assert _wait_http(url + "api/state", proc)[0] == 200
    finally:
        proc.kill()
        proc.wait()
    assert "pyamg is broken" in (home / desktop.STARTUP_LOG).read_text(encoding="utf-8")


def test_main_reports_import_failure(home, tmp_path):
    """numpy that cannot load (a broken install): `python -m anneal app` writes the log and says
    where it is, instead of exiting without a word."""
    fake = tmp_path / "broken"
    fake.mkdir()
    (fake / "numpy.py").write_text("raise ImportError('DLL load failed (mock)')\n")
    r = subprocess.run([sys.executable, "-m", "anneal", "app"], cwd=ROOT, env=_env(home, str(fake)),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 1
    log = (home / desktop.STARTUP_LOG).read_text(encoding="utf-8")
    assert "DLL load failed (mock)" in log and "Traceback" in log
    assert desktop.STARTUP_LOG in r.stderr


def test_desktop_imports_without_optional_packages():
    """desktop.py uses only the standard library at import time."""
    code = textwrap.dedent("""
        import sys
        for m in ("numpy", "scipy", "pyamg", "trimesh", "webview", "manifold3d", "ctypes"):
            sys.modules[m] = None
        import anneal.gui.desktop as d
        print(d.startup_log_path())
    """)
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=_env(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_crash_while_opening_uses_browser_next_time(windows, monkeypatch, home):
    """If the process stopped while the window opened (the marker file stays), the next start uses
    the browser once and writes the reason to the log; the start after that tries the window again."""
    home.mkdir(parents=True, exist_ok=True)
    (home / desktop.WINDOW_PENDING).write_text("x")
    wv = _fake_webview(monkeypatch, show=True)
    assert desktop.open_window("http://127.0.0.1:1/") is False
    assert wv.start_calls == []
    assert "did not open the last time" in (home / desktop.STARTUP_LOG).read_text(encoding="utf-8")
    assert desktop.open_window("http://127.0.0.1:1/") is True
    assert not (home / desktop.WINDOW_PENDING).exists()
