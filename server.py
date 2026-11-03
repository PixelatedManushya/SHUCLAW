"""SHUCLAW server: turns your phone into an XInput (Xbox 360-compatible) controller for this PC.

Each connected phone gets its own virtual controller (so two phones = two players).
Run with --demo to test without the ViGEmBus driver (inputs are just printed).
"""

import argparse
import asyncio
import json
import socket
import sys
from pathlib import Path

from aiohttp import web, WSMsgType

PORT = 8765
STATIC = Path(__file__).parent / "static"
CONNECTED = {"count": 0}

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

    def __init__(self, demo, on_rumble):
        """on_rumble(large, small) is called (from any thread) when the game changes vibration, 0-255."""
        self.demo = demo
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


async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=5)
    await ws.prepare(request)
    peer = request.remote
    demo = request.app["demo"]
    loop = asyncio.get_running_loop()

    def send_rumble(large, small):
        if not ws.closed:
            asyncio.ensure_future(ws.send_str(json.dumps({"r": [large, small]})))

    try:
        pad = Pad(demo, lambda l, s: loop.call_soon_threadsafe(send_rumble, l, s))
    except Exception as e:
        print(f"\n[!] Could not create virtual controller: {e}")
        await ws.send_str(json.dumps({"error": "PC could not create a controller. Is ViGEmBus installed?"}))
        await ws.close()
        return ws

    CONNECTED["count"] += 1
    print(f"\n[+] Phone connected from {peer}  (controllers: {CONNECTED['count']})")
    await ws.send_str(json.dumps({"hello": CONNECTED["count"]}))
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            if isinstance(data, list) and len(data) == 7:
                m, lx, ly, rx, ry, lt, rt = data
                pad.apply(int(m), clamp(lx, -1, 1), clamp(ly, -1, 1), clamp(rx, -1, 1),
                          clamp(ry, -1, 1), clamp(lt, 0, 1), clamp(rt, 0, 1))
            elif isinstance(data, dict) and "p" in data:
                await ws.send_str(msg.data)  # latency ping echo
    finally:
        pad.close()  # release everything so nothing stays "stuck" held down
        CONNECTED["count"] -= 1
        print(f"\n[-] Phone {peer} disconnected  (controllers: {CONNECTED['count']})")
    return ws


class Discovery(asyncio.DatagramProtocol):
    """Answers the Android app's "is there a SHUCLAW PC here?" broadcast."""

    def __init__(self, port):
        self.reply = f"SHUCLAW!{socket.gethostname()}|{port}".encode()

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if data == b"SHUCLAW?":
            self.transport.sendto(self.reply, addr)


def discovery_starter(port):
    async def start(app):
        try:
            await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: Discovery(port), local_addr=("0.0.0.0", port + 1))
        except OSError as e:
            print(f"[!] Auto-discovery unavailable ({e}); type the PC address in the app instead.")
    return start


async def index(request):
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


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
    except ImportError:
        pass
    print("  Press Ctrl+C to stop.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="print inputs instead of creating a controller")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    demo = args.demo
    if not demo:
        try:
            import vgamepad  # noqa: F401
        except Exception as e:
            print(f"[!] vgamepad / ViGEmBus not available ({e}).")
            print("    Install the driver (see README.md) or run with --demo to test.")
            sys.exit(1)

    app = web.Application()
    app["demo"] = demo
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/static", STATIC)
    app.on_startup.append(discovery_starter(args.port))
    print_banner(demo, args.port)
    web.run_app(app, host="0.0.0.0", port=args.port, print=None)


if __name__ == "__main__":
    main()
