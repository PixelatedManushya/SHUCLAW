# SHUCLAW: your Android phone as a PC game controller

Your PC sees the phone as a standard **XInput (Xbox 360-compatible) controller**, so any game with
controller support works. Works over **USB cable** or **Wi-Fi**.

Two phones = two players.

**Download:** get `SHUCLAW-x.y.apk` for your phone from the
[latest release](https://github.com/PixelatedManushya/SHUCLAW/releases/latest), and this repository
(green **Code** button → Download ZIP) for the PC side.

SHUCLAW is an independent project and is not affiliated with or endorsed by Microsoft or Xbox.

## One-time setup (PC)

1. Install **Python 3** from python.org (tick "Add Python to PATH").
2. Install the **ViGEmBus driver** (creates the virtual controller), from the official page only:
   https://github.com/nefarius/ViGEmBus/releases → download `ViGEmBus_..._x64_x86_arm64.exe` → install → restart the PC.
   (Installing the `vgamepad` package may also open this same installer automatically. Just accept it.)
3. Double-click **`start.bat`**. The first run installs what it needs.
   When Windows Firewall asks, tick **both Private and Public** and click Allow
   (USB tethering often shows up as a "Public" network).

## Install the Android app (recommended)

1. Copy **`SHUCLAW.apk`** to your phone (USB file transfer, Google Drive, or WhatsApp to yourself).
2. Tap it on the phone. Android will ask to allow installing from that app ("Install unknown apps"): allow it once, then tap Install.
   Play Protect may say it doesn't recognise the developer. Tap "Install anyway" (it's your own app).
3. Open SHUCLAW. It finds your PC automatically (start.bat must be running). USB connections show in green.
   It remembers the PC next time; ⚙ → **Change PC** to switch.

The app gives crisp native vibration (⚙ → Button vibration: Off / Light / Medium / Strong) and **game rumble**:
when the game vibrates the controller (gunshots, engines, hits) your phone vibrates too.
Tip: run `start.bat --demo` and hold RT on the phone to feel a test rumble.

To build the app yourself (needs JDK 17 and the Android SDK): in `android/`, run `gradlew assembleDebug`.
The APK lands in `android/app/build/outputs/apk/debug/`. The controller screen is `static/index.html`,
shared by the app and the browser version.

## Connect with a USB cable (lowest lag)

1. Plug the phone into the PC.
2. On the phone: **Settings → Network & internet → Hotspot & tethering → USB tethering → ON**.
3. Close and re-run `start.bat`. A new address appears (often `192.168.x.x`).
4. Open **Chrome** on the phone and type that address, e.g. `http://192.168.42.10:8765`.

## Connect over Wi-Fi

Phone and PC on the same Wi-Fi → run `start.bat` → scan the QR code or type the address shown.

## Using it

- Tap **Tap to start**: it goes full screen and locks to landscape.
- **Sticks float**: put your left thumb anywhere in the lower-left area, or your right thumb in the
  lower-middle-right area, and the stick appears under it. Drag past the edge and it follows your thumb.
- **Quick tap** on a stick area = L3 / R3 (stick click).
- Slide your thumb between A/B/X/Y without lifting.
- D-pad supports diagonals.
- ⚙ (bottom centre): button size, stick size, dead zone, vibration, show stick areas.
- Tip: in Chrome, ⋮ → **Add to Home screen** to launch it like an app.

## Test without the driver

`start.bat --demo` prints the inputs in the window instead of creating a controller.
To check the controller in Windows: press Win+R → `joy.cpl`.

## Troubleshooting

- **Page won't load**: the firewall blocked it. Windows Security → Firewall → Allow an app → allow
  `python.exe` on Public and Private. Make sure the phone uses `http://`, not `https://`.
- **Game ignores it**: the game must support controllers. In Steam: Settings → Controller, check controller support is enabled.

## License

MIT, see [LICENSE](LICENSE). Uses [vgamepad](https://github.com/yannbouteiller/vgamepad) and the
[ViGEmBus](https://github.com/nefarius/ViGEmBus) driver (installed separately, not included).
- **Buttons stuck**: lifting all fingers or leaving the page releases everything; disconnecting does too.
