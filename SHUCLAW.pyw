"""Double-click this to start SHUCLAW. No console window.

The first run (and any run after requirements.txt changes) sets up Python's packages in
%LOCALAPPDATA%\\SHUCLAW\\venv while a small setup window shows progress, then starts the app.
"""

import hashlib
import os
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
APPDIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SHUCLAW"
# A short path on purpose: the controller driver library fails to load from long paths
VENV = APPDIR / "venv"
VPYW = VENV / "Scripts" / "pythonw.exe"
VPY = VENV / "Scripts" / "python.exe"
MARKER = VENV / "shuclaw-requirements.sha1"
REQS = HERE / "requirements.txt"
NO_WINDOW = 0x08000000   # CREATE_NO_WINDOW: keep pip's console hidden


def in_venv():
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def reqs_hash():
    return hashlib.sha1(REQS.read_bytes()).hexdigest()


def needs_setup():
    return not VPYW.exists() or not MARKER.exists() or MARKER.read_text().strip() != reqs_hash()


def setup(status):
    """Creates the venv and installs requirements. status(text) updates the setup window."""
    APPDIR.mkdir(parents=True, exist_ok=True)
    log = open(APPDIR / "setup.log", "a", encoding="utf-8")
    run = lambda args: subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW, check=True)
    if not VPY.exists():
        status("Creating SHUCLAW's private Python environment…")
        base = Path(sys.executable)
        python = base.with_name("python.exe") if base.name.lower() == "pythonw.exe" else base
        run([str(python), "-m", "venv", str(VENV)])
    status("Updating pip…")
    run([str(VPY), "-m", "pip", "install", "--upgrade", "pip"])
    status("Installing SHUCLAW's parts (this takes a minute)…\nIf a driver installer opens, accept it.")
    run([str(VPY), "-m", "pip", "install", "-r", str(REQS)])
    MARKER.write_text(reqs_hash())


def setup_with_window():
    """Runs setup() with a small progress window. Returns True on success."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("SHUCLAW setup")
    root.configure(bg="#0b0d18")
    root.resizable(False, False)
    w, h = 460, 190
    root.geometry(f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 3}")
    tk.Label(root, text="SHUCLAW", fg="#ffffff", bg="#0b0d18", font=("Segoe UI Black", 20)).pack(pady=(22, 4))
    msg = tk.Label(root, text="Getting ready…", fg="#9aa0bd", bg="#0b0d18", font=("Segoe UI", 10), justify="center")
    msg.pack(pady=(0, 14))
    style = ttk.Style(root)
    style.theme_use("default")
    style.configure("S.Horizontal.TProgressbar", troughcolor="#1a1d2e", background="#8a6bff", bordercolor="#0b0d18", thickness=8)
    bar = ttk.Progressbar(root, mode="indeterminate", length=360, style="S.Horizontal.TProgressbar")
    bar.pack()
    bar.start(12)
    result = {}

    def work():
        try:
            setup(lambda t: root.after(0, msg.config, {"text": t}))
            result["ok"] = True
        except Exception as e:
            result["error"] = e
        root.after(0, root.destroy)

    threading.Thread(target=work, daemon=True).start()
    root.mainloop()
    if "error" in result:
        from tkinter import messagebox
        messagebox.showerror("SHUCLAW setup", "Setup failed. Check your internet connection and try again.\n\n"
                             f"Details: {result['error']}\nLog: {APPDIR / 'setup.log'}")
        return False
    return True


def main():
    if in_venv() or getattr(sys, "frozen", False):
        sys.path.insert(0, str(HERE))
        os.chdir(HERE)
        import shuclaw_app
        shuclaw_app.main()
        return
    if needs_setup() and not setup_with_window():
        return
    # restart inside the private environment, still without a console
    subprocess.Popen([str(VPYW), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=str(HERE))


if __name__ == "__main__":
    main()
