"""SHUCLAW server: turns your phone into an XInput (Xbox 360-compatible) controller for this PC.

Each connected phone gets its own virtual controller (so two phones = two players, up to four).
Run with --demo to test without the ViGEmBus driver (inputs are just printed).

This file runs on its own in a console (start.bat), and is also used by the windowed
app (SHUCLAW.pyw / SHUCLAW.exe), which shows the live dashboard instead of a console.
"""

import argparse
import asyncio
import json
import re
import socket
import sys
import threading
import time
from pathlib import Path

from aiohttp import web, WSMsgType

PORT = 8765
MAX_PLAYERS = 4  # XInput supports four controllers
# Inside a PyInstaller .exe the files are unpacked to a temp folder
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC = BASE / "static"

# Bit order must match BUTTONS in static/index.html
BUTTON_NAMES = [
    "A", "B", "X", "Y",
    "LEFT_SHOULDER", "RIGHT_SHOULDER",
    "BACK", "START", "GUIDE",
    "LEFT_THUMB", "RIGHT_THUMB",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
]


class Pad:
    """One virtual XInput controller (or a printer, in demo mode)."""

    def __init__(self, demo, on_rumble, quiet=False):
        """on_rumble(large, small) is called (from any thread) when the game changes vibration, 0-255."""
        self.demo = demo
        self.quiet = quiet
        self.buttons = 0
        self.on_rumble = on_rumble
        self.last_rumble = (0, 0)
        if not demo:
            import vgamepad as vg
            self.gp = vg.VX360Gamepad()
            self.bits = [getattr(vg.XUSB_BUTTON, "XUSB_GAMEPAD_" + n) for n in BUTTON_NAMES]
            self.gp.register_notification(callback_function=self._notify)

    def _notify(self, client, target, large_motor, small_motor, led_number, user_data):
        self._rumble(large_motor, small_motor)

    def _rumble(self, large, small):
        if (large, small) != self.last_rumble:
            self.last_rumble = (large, small)
            self.on_rumble(large, small)

    def apply(self, mask, lx, ly, rx, ry, lt, rt):
        if self.demo:
            if not self.quiet:
                pressed = [n for i, n in enumerate(BUTTON_NAMES) if mask >> i & 1]
                print(f"\r  L({lx:+.2f},{ly:+.2f}) R({rx:+.2f},{ry:+.2f}) "
                      f"LT {lt:.1f} RT {rt:.1f}  {' '.join(pressed):<40}", end="", flush=True)
            self._rumble(int(rt * 200), int(lt * 120))  # demo: triggers test the phone's rumble
            return
        changed = mask ^ self.buttons
        for i, bit in enumerate(self.bits):
            if changed >> i & 1:
                if mask >> i & 1:
                    self.gp.press_button(button=bit)
                else:
                    self.gp.release_button(button=bit)
        self.buttons = mask
        self.gp.left_joystick_float(x_value_float=lx, y_value_float=ly)
        self.gp.right_joystick_float(x_value_float=rx, y_value_float=ry)
        self.gp.left_trigger_float(value_float=lt)
        self.gp.right_trigger_float(value_float=rt)
        self.gp.update()

    def reset(self):
        self.apply(0, 0, 0, 0, 0, 0, 0)

    def close(self):
        self.reset()
        if not self.demo:
            self.gp.unregister_notification()
            del self.gp  # unplugs the virtual controller


def clamp(v, lo, hi):
    return max(lo, min(hi, float(v)))


def describe_device(ua):
    """(name, is_app) from a phone's User-Agent."""
    m = re.search(r"SHUCLAW-App \(([^)]*)\)", ua)   # the Android app adds its real model name
    if m and m.group(1).strip():
        return m.group(1).strip(), True
    is_app = "; wv)" in ua
    m = re.search(r"Android [\d.]+; ([^;)]+?)(?: Build/[^;)]*)?[;)]", ua)
    model = m.group(1).strip() if m else ""
    if not model or model == "K":   # Chrome hides the model name these days
        model = "Android phone" if "Android" in ua else "iPhone" if "iPhone" in ua else "Phone"
    return model, is_app


class Player:
    def __init__(self, slot, peer, ua):
        self.slot = slot
        self.peer = peer
        self.device, self.app = describe_device(ua)
        self.since = time.time()
        self.state = [0, 0, 0, 0, 0, 0, 0]
        self.ping = None
        self.rumble = (0, 0)
        self.inputs = 0
        self.rate = 0
        self._last_inputs = 0

    def snapshot(self):
        return {"slot": self.slot, "peer": self.peer, "device": self.device, "app": self.app,
                "since": round(time.time() - self.since), "s": self.state, "ping": self.ping,
                "rumble": list(self.rumble), "rate": self.rate}


class Hub:
    """Who is connected, and the live feed for the dashboard."""

    def __init__(self, demo, port, driver_error=None, quiet=False):
        self.demo = demo
        self.port = port
        self.driver_error = driver_error
        self.quiet = quiet
        self.players = {}       # slot -> Player
        self.dash = set()       # dashboard websockets
        self.dirty = True
        self.started = time.time()
        self.listeners = []     # fn(kind, player) for "join" / "leave" (tray notifications)
        self.on_show = None     # brings the app window forward (second launch)

    def free_slot(self):
        return next((i for i in range(1, MAX_PLAYERS + 1) if i not in self.players), None)

    def info(self):
        ips = local_ips()
        urls = [f"http://{ip}:{self.port}" for ip in ips]
        return {"type": "info", "demo": self.demo, "driver_error": self.driver_error,
                "port": self.port, "host": socket.gethostname(), "max": MAX_PLAYERS,
                "addresses": [{"url": u, "qr": qr_matrix(u)} for u in urls]}

    def state(self):
        return {"type": "state", "uptime": round(time.time() - self.started),
                "players": [p.snapshot() for p in sorted(self.players.values(), key=lambda p: p.slot)]}

    def event(self, kind, player):
        self._send_all({"type": "event", "kind": kind, "slot": player.slot, "device": player.device})
        for fn in self.listeners:
            try:
                fn(kind, player)
            except Exception as e:  # a notification must never break the server
                print(f"[!] listener failed: {e}")

    def _send_all(self, obj):
        text = json.dumps(obj)
        for ws in list(self.dash):
            if not ws.closed:
                asyncio.ensure_future(ws.send_str(text))

    async def run_feed(self):
        """Pushes controller state to the dashboard ~30 times a second."""
        last_tick = 0
        while True:
            if not self.dash:           # no window open: next to no work while you play
                await asyncio.sleep(0.5)
                continue
            await asyncio.sleep(1 / 30)
            now = time.time()
            if now - last_tick >= 1:
                last_tick = now
                for p in self.players.values():
                    p.rate, p._last_inputs = p.inputs - p._last_inputs, p.inputs
                self.dirty = True
            if self.dirty and self.dash:
                self.dirty = False
                self._send_all(self.state())


def qr_matrix(text):
    """QR code as rows of '0'/'1' strings (the dashboard draws it)."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(text)
        qr.make(fit=True)
        return ["".join("1" if c else "0" for c in row) for row in qr.get_matrix()]
    except Exception:
        return None


def is_local(request):
    return request.remote in ("127.0.0.1", "::1")


async def ws_handler(request):
    hub = request.app["hub"]
    ws = web.WebSocketResponse(heartbeat=5)
    await ws.prepare(request)
    peer = request.remote
    loop = asyncio.get_running_loop()

    slot = hub.free_slot()
    if slot is None:
        await ws.send_str(json.dumps({"error": f"All {MAX_PLAYERS} controllers are in use on this PC."}))
        await ws.close()
        return ws
    player = Player(slot, peer, request.headers.get("User-Agent", ""))

    def send_rumble(large, small):
        player.rumble = (large, small)
        hub.dirty = True
        if not ws.closed:
            asyncio.ensure_future(ws.send_str(json.dumps({"r": [large, small]})))

    try:
        pad = Pad(hub.demo, lambda l, s: loop.call_soon_threadsafe(send_rumble, l, s), quiet=hub.quiet)
    except Exception as e:
        print(f"\n[!] Could not create virtual controller: {e}")
        await ws.send_str(json.dumps({"error": "PC could not create a controller. Is ViGEmBus installed?"}))
        await ws.close()
        return ws

    hub.players[slot] = player
    hub.dirty = True
    print(f"\n[+] Player {slot} connected: {player.device} ({peer})  (controllers: {len(hub.players)})")
    hub.event("join", player)
    await ws.send_str(json.dumps({"hello": slot}))
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except ValueError:
                continue
            if isinstance(data, list) and len(data) == 7:
                m, lx, ly, rx, ry, lt, rt = data
                state = [int(m), clamp(lx, -1, 1), clamp(ly, -1, 1), clamp(rx, -1, 1),
                         clamp(ry, -1, 1), clamp(lt, 0, 1), clamp(rt, 0, 1)]
                pad.apply(*state)
                player.state = state
                player.inputs += 1
                hub.dirty = True
            elif isinstance(data, dict) and "p" in data:
                if isinstance(data.get("l"), (int, float)):
                    player.ping = round(data["l"])
                await ws.send_str(msg.data)  # latency ping echo
    finally:
        pad.close()  # release everything so nothing stays "stuck" held down
        hub.players.pop(slot, None)
        hub.dirty = True
        print(f"\n[-] Player {slot} disconnected  (controllers: {len(hub.players)})")
        hub.event("leave", player)
    return ws


async def dash_handler(request):
    """Live feed for the dashboard window. Only this PC may watch."""
    if not is_local(request):
        raise web.HTTPForbidden()
    hub = request.app["hub"]
    ws = web.WebSocketResponse(heartbeat=10)
    await ws.prepare(request)
    hub.dash.add(ws)
    try:
        await ws.send_str(json.dumps(hub.info()))
        await ws.send_str(json.dumps(hub.state()))
        async for msg in ws:
            if msg.type == WSMsgType.TEXT and msg.data == "info":   # addresses may change (USB tethering)
                await ws.send_str(json.dumps(hub.info()))
    finally:
        hub.dash.discard(ws)
    return ws


async def dashboard(request):
    if not is_local(request):
        raise web.HTTPForbidden()
    return web.FileResponse(STATIC / "dashboard.html", headers={"Cache-Control": "no-store"})


async def api_ping(request):
    return web.json_response({"app": "SHUCLAW"})


async def api_show(request):
    """A second launch of the app asks the running one to show its window."""
    if not is_local(request):
        raise web.HTTPForbidden()
    hub = request.app["hub"]
    if hub.on_show:
        hub.on_show()
    return web.json_response({"ok": True})


class Discovery(asyncio.DatagramProtocol):
    """Answers the Android app's "is there a SHUCLAW PC here?" broadcast."""

    def __init__(self, port):
        self.reply = f"SHUCLAW!{socket.gethostname()}|{port}".encode()

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if data == b"SHUCLAW?":
            self.transport.sendto(self.reply, addr)


async def on_startup(app):
    hub = app["hub"]
    app["feed"] = asyncio.ensure_future(hub.run_feed())
    try:
        await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: Discovery(hub.port), local_addr=("0.0.0.0", hub.port + 1))
    except OSError as e:
        print(f"[!] Auto-discovery unavailable ({e}); type the PC address in the app instead.")


async def on_cleanup(app):
    app["feed"].cancel()


async def index(request):
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


def make_app(hub):
    app = web.Application()
    app["hub"] = hub
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/dashboard", dashboard)
    app.router.add_get("/dash", dash_handler)
    app.router.add_get("/api/ping", api_ping)
    app.router.add_post("/api/show", api_show)
    app.router.add_static("/static", STATIC)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def driver_problem():
    """None if the virtual controller driver works, otherwise a short reason."""
    try:
        import vgamepad  # noqa: F401
        return None
    except Exception as e:
        return str(e) or e.__class__.__name__


class BackgroundServer:
    """Runs the server on its own thread (used by the windowed app)."""

    def __init__(self, hub):
        self.hub = hub
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, name="shuclaw-server", daemon=True)

    def start(self, timeout=10):
        self.thread.start()
        self.ready.wait(timeout)
        if self.error:
            raise self.error

    def _run(self):
        asyncio.set_event_loop(self.loop)
        runner = web.AppRunner(make_app(self.hub))
        try:
            self.loop.run_until_complete(runner.setup())
            self.loop.run_until_complete(web.TCPSite(runner, "0.0.0.0", self.hub.port).start())
        except Exception as e:
            self.error = e
            self.ready.set()
            return
        self.runner = runner
        self.ready.set()
        self.loop.run_forever()
        self.loop.run_until_complete(runner.cleanup())   # unplugs every controller

    def stop(self):
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(5)


def local_ips():
    ips, default = set(), None
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:  # the address used for the default route (usually Wi-Fi/Ethernet)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        default = s.getsockname()[0]
        ips.add(default)
        s.close()
    except OSError:
        pass
    return sorted((ip for ip in ips if not ip.startswith(("127.", "169.254."))),
                  key=lambda ip: ip != default)  # default route first (used for the QR code)


def print_banner(demo, port):
    print("=" * 60)
    print("  SHUCLAW is running" + ("  [DEMO MODE - no virtual controller]" if demo else ""))
    print("=" * 60)
    ips = local_ips()
    if not ips:
        print("  No network found. Connect Wi-Fi or turn on USB tethering, then restart.")
    print("  SHUCLAW app: just open it, it finds this PC automatically.")
    print("  Browser instead: open Chrome on the phone and go to one of these:\n")
    for ip in ips:
        print(f"     http://{ip}:{port}")
    print("\n  USB cable: turn on 'USB tethering' on the phone, restart this")
    print("  program, and use the new address that appears above.")
    try:
        import qrcode
        if ips:
            url = f"http://{ips[0]}:{port}"
            print(f"\n  Or scan this QR code ({url}):\n")
            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.print_ascii(invert=True)
    except Exception:   # no qrcode package, or output that can't show block characters
        pass
    print(f"  Dashboard: http://127.0.0.1:{port}/dashboard")
    print("  Press Ctrl+C to stop.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="print inputs instead of creating a controller")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    demo = args.demo
    if not demo:
        problem = driver_problem()
        if problem:
            print(f"[!] vgamepad / ViGEmBus not available ({problem}).")
            print("    Install the driver (see README.md) or run with --demo to test.")
            sys.exit(1)

    hub = Hub(demo, args.port)
    print_banner(demo, args.port)
    web.run_app(make_app(hub), host="0.0.0.0", port=args.port, print=None)


if __name__ == "__main__":
    main()
