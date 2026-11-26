"""SHUCLAW desktop app: the server runs in the background with a tray icon, plus a dashboard window.

Started by SHUCLAW.pyw (or SHUCLAW.exe). No console window.

Two processes, so that SHUCLAW costs almost nothing while you play:
  * the main process: the controller server and the tray icon (as light as the console version);
  * the window process (--window): the dashboard. Minimising or closing it ends that process
    completely, so its browser engine stops using RAM, CPU and GPU. The tray icon opens it again.
Quit from the tray icon. Log file: %LOCALAPPDATA%\\SHUCLAW\\shuclaw.log
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APPDIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SHUCLAW"
TITLE = "SHUCLAW"
WINDOW_TITLE = "SHUCLAW Control Deck"


def setup_logging():
    """Without a console, print() output goes to a log file instead of nowhere."""
    windowless = (sys.stdout is None or getattr(sys, "frozen", False)
                  or Path(sys.executable).name.lower() == "pythonw.exe")
    if not windowless:
        return
    APPDIR.mkdir(parents=True, exist_ok=True)
    log = open(APPDIR / "shuclaw.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log


def message_box(text, error=True):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10 if error else 0x40)
    except Exception:
        print(text)


def ask_running_app_to_show(port):
    """True if SHUCLAW is already running (it is asked to open its window)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            if json.load(r).get("app") != "SHUCLAW":
                return False
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/show", data=b"", method="POST")
        urllib.request.urlopen(req, timeout=2).close()
        return True
    except Exception:
        return False


def make_icon(size=256):
    """The app icon, drawn in code: a gamepad on a neon gradient tile."""
    from PIL import Image, ImageDraw, ImageFilter
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    grad = Image.new("RGBA", (s, s))
    px = grad.load()
    a, b = (91, 43, 255), (0, 194, 255)
    for y in range(s):
        for x in range(s):
            t = (x + y) / (2 * s - 2)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=s * 0.24, fill=255)
    img.paste(grad, (0, 0), mask)

    pad = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(pad)
    w = (255, 255, 255, 255)
    d.rounded_rectangle((s * .14, s * .30, s * .86, s * .62), radius=s * .16, fill=w)   # body
    d.ellipse((s * .12, s * .40, s * .40, s * .80), fill=w)                             # grips
    d.ellipse((s * .60, s * .40, s * .88, s * .80), fill=w)
    ink = (40, 30, 120, 255)
    cx, cy, arm = s * .32, s * .47, s * .055                                            # d-pad
    d.rectangle((cx - arm * 2.2, cy - arm * .7, cx + arm * 2.2, cy + arm * .7), fill=ink)
    d.rectangle((cx - arm * .7, cy - arm * 2.2, cx + arm * .7, cy + arm * 2.2), fill=ink)
    r = s * .042                                                                        # buttons
    for bx, by in ((.66, .41), (.74, .49), (.58, .49), (.66, .57)):
        d.ellipse((s * bx - r, s * by - r, s * bx + r, s * by + r), fill=ink)
    shadow = pad.split()[3].filter(ImageFilter.GaussianBlur(s * .02))
    img.paste((20, 10, 60, 120), (0, int(s * .02)), shadow)
    img.alpha_composite(pad)
    return img


# ======================= window process =======================

def run_window(url):
    """The dashboard window. Minimise or close = this process ends and frees everything."""
    import webview

    class Api:
        """Called from the dashboard page (window buttons)."""

        def minimize(self):
            window.destroy()

        def hide(self):
            window.destroy()

        def open_url(self, link):
            if str(link).startswith("https://"):
                webbrowser.open(link)

    window = webview.create_window(
        WINDOW_TITLE, url, js_api=Api(), width=1240, height=800, min_size=(980, 660),
        frameless=True, easy_drag=False, background_color="#04050b",
    )
    window.events.minimized += lambda: window.destroy()   # Win+Down, taskbar click: off to the tray
    webview.start(private_mode=False, storage_path=str(APPDIR / "webview"))


def focus_window():
    """Brings an open dashboard window to the front. False if there is none."""
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, WINDOW_TITLE)
        if not hwnd:
            return False
        u.ShowWindow(hwnd, 9)   # SW_RESTORE
        u.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


class WindowProcess:
    """Starts the window process on demand and notices when it goes away."""

    def __init__(self, url, port, on_closed):
        self.url = url
        self.port = port
        self.on_closed = on_closed
        self.proc = None
        self.lock = threading.Lock()

    def command(self):
        args = ["--window", self.url, "--port", str(self.port)]
        if getattr(sys, "frozen", False):                         # SHUCLAW.exe
            return [sys.executable, *args]
        script = Path(sys.argv[0]).resolve()                      # SHUCLAW.pyw or shuclaw_app.py
        return [sys.executable, str(script), *args]

    def open(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                focus_window()
                return
            started = time.time()
            try:
                self.proc = proc = subprocess.Popen(self.command(), cwd=str(Path(__file__).resolve().parent))
            except Exception as e:
                print(f"[!] Could not open the window ({e}); using the browser instead.")
                webbrowser.open(self.url)
                return
        threading.Thread(target=self._watch, args=(proc, started), daemon=True).start()

    def _watch(self, proc, started):
        code = proc.wait()
        if code != 0 and time.time() - started < 5:   # no window engine on this PC
            print(f"[!] Window process failed (exit {code}); using the browser instead.")
            webbrowser.open(self.url)
            return
        self.on_closed()

    def is_open(self):
        return bool(self.proc and self.proc.poll() is None)

    def close(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()


# ======================= main (background) process =======================

class Tray:
    """System tray icon: open the window, see how many controllers are connected, quit."""

    def __init__(self, hub, max_players, on_open, on_quit):
        self.icon = None
        try:
            import pystray
        except Exception as e:
            print(f"[!] Tray icon unavailable: {e}")
            return
        count = lambda item: f"{len(hub.players)} of {max_players} controllers connected"
        menu = pystray.Menu(
            pystray.MenuItem("Open SHUCLAW", lambda: on_open(), default=True),
            pystray.MenuItem(count, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit SHUCLAW", lambda: on_quit()),
        )
        self.icon = pystray.Icon("SHUCLAW", make_icon(64), "SHUCLAW", menu)

    def notify(self, text):
        if self.icon:
            try:
                self.icon.notify(text, TITLE)
            except Exception:
                pass

    def refresh(self):
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass


def arg_value(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    setup_logging()
    url = arg_value("--window")
    if url:
        run_window(url)
        return

    import server   # only the background process runs the server
    port = int(arg_value("--port", server.PORT))
    if ask_running_app_to_show(port):
        return   # already running: its window was opened

    print("\n===== SHUCLAW started =====")
    problem = server.driver_problem()
    demo = "--demo" in sys.argv or problem is not None
    hub = server.Hub(demo, port, driver_error=problem, quiet=True)
    srv = server.BackgroundServer(hub)
    try:
        srv.start()
    except OSError as e:
        message_box(f"SHUCLAW could not start: port {port} is already in use by another program.\n\n{e}")
        return
    print(f"Server on port {port}" + (f" (preview mode: {problem})" if problem else ""))
    dash_url = f"http://127.0.0.1:{port}/dashboard"

    stop = threading.Event()
    told = {"tray": False}

    def on_window_closed():
        if stop.is_set():
            return
        if tray.icon is None:   # no tray to come back from: closing the window quits
            quit_app()
            return
        if not told["tray"]:
            told["tray"] = True
            tray.notify("Still running in the tray, controllers stay connected. Right-click the icon to quit.")

    window = WindowProcess(dash_url, port, on_window_closed)

    def quit_app():
        stop.set()
        window.close()
        tray.stop()

    tray = Tray(hub, server.MAX_PLAYERS, window.open, quit_app)

    def on_player(kind, player):
        tray.refresh()
        if not window.is_open():
            tray.notify(f"Player {player.slot} {'connected' if kind == 'join' else 'disconnected'}: {player.device}")

    hub.listeners.append(on_player)
    hub.on_show = window.open

    window.open()
    try:
        if tray.icon:
            tray.icon.run()       # blocks until Quit
        else:
            stop.wait()
    finally:
        stop.set()
        window.close()
        srv.stop()                # unplugs every virtual controller


if __name__ == "__main__":
    main()
