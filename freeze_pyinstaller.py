"""
Build script for LMU AI Race Engineer — produces a standalone Windows exe.

Run on Windows from the project root:
    uv run python freeze_pyinstaller.py

Output: dist\\LMU-Race-Engineer\\
  LMU-Race-Engineer.exe   <- double-click to launch
  .env                    ← fill in your API keys before first run
  SETUP.txt               ← quick-start guide

To create a release zip afterwards, run:
    uv run python freeze_pyinstaller.py --release

Requires PyInstaller:
    uv add --dev pyinstaller
"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

APP_NAME = "LMU-Race-Engineer"
ENTRY_POINT = "main.py"
ICON = os.path.join("images", "icon.ico")
DIST_DIR = "dist"
BUILD_DIR = "build"

DATAS = [
    (".env.example", "."),
]

HIDDEN_IMPORTS = [
    # faster-whisper / CTranslate2
    "faster_whisper",
    "ctranslate2",
    "ctranslate2.specs",
    # pynput Windows backend
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    # inputs (gamepad/joystick)
    "inputs",
    # anthropic
    "anthropic",
    "anthropic._base_client",
    "anthropic.resources",
    "httpx",
    "httpcore",
    # elevenlabs
    "elevenlabs",
    "elevenlabs.client",
    # audio / numpy
    "sounddevice",
    "numpy",
    # PySide6
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
]

EXCLUDES = [
    "tkinter",
    "matplotlib",
    "scipy",
    "PIL",
    "IPython",
    "jupyter",
    "pytest",
]

SETUP_TXT = """\
LMU AI Race Engineer — Setup
=============================

FIRST-TIME SETUP
----------------
1. Open the ".env" file in this folder with Notepad.
2. Fill in your API keys:

   ANTHROPIC_API_KEY=sk-ant-...
   ELEVENLABS_API_KEY=...

   (Optional) Change the voice:
   ELEVENLABS_VOICE_ID=onwK4e9ZLuTAKqWW03F9

3. Save the file and close Notepad.
4. Double-click LMU-Race-Engineer.exe to launch.

PUSH-TO-TALK
------------
Default PTT is the SPACE key on your keyboard.
To use a wheel button instead, add to .env:

   PTT_TYPE=joystick
   PTT_JOYSTICK_BUTTON=BTN_TRIGGER

Launch the app once with PTT_TYPE=joystick and press buttons on your wheel —
the log will show the button code so you can set PTT_JOYSTICK_BUTTON correctly.

API KEYS
--------
Anthropic (Claude): https://console.anthropic.com/
ElevenLabs (TTS):   https://elevenlabs.io/app/settings/api-keys

SUPPORT
-------
GitHub: https://github.com/imranaskem/race-engineer
"""


def build() -> None:
    # Generate icon if missing
    if not os.path.exists(ICON):
        print(f"Icon not found at {ICON} — run: uv run python create_icon.py")
        print("Continuing without icon...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",
        "--windowed",     # no console popup; all output goes to the Qt log panel
        "--noconfirm",
        "--distpath", DIST_DIR,
        "--workpath", BUILD_DIR,
        "--collect-all", "PySide6",
    ]

    if os.path.exists(ICON):
        cmd += ["--icon", ICON]

    for src, dst in DATAS:
        cmd += ["--add-data", f"{src}{os.pathsep}{dst}"]

    for imp in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", imp]

    for exc in EXCLUDES:
        cmd += ["--exclude-module", exc]

    cmd.append(ENTRY_POINT)

    print("Running PyInstaller...")
    print()
    subprocess.run(cmd, check=True)

    out_dir = Path(DIST_DIR) / APP_NAME

    # .env — copy from example if not present so users have a file to edit
    env_example = out_dir / ".env.example"
    env_target = out_dir / ".env"
    if env_example.exists() and not env_target.exists():
        shutil.copy(env_example, env_target)

    # SETUP.txt — quick-start guide
    (out_dir / "SETUP.txt").write_text(SETUP_TXT, encoding="utf-8")

    print()
    print(f"Build complete → {out_dir}")
    print()
    print("Users need to:")
    print(f"  1. Edit {out_dir / '.env'}  (add API keys)")
    print(f"  2. Double-click {out_dir / (APP_NAME + '.exe')}")


def create_release_zip() -> None:
    """Zip up the dist folder for GitHub release distribution."""
    out_dir = Path(DIST_DIR) / APP_NAME
    if not out_dir.exists():
        print("Run build first.")
        sys.exit(1)

    # Read version from pyproject.toml if available
    version = "dev"
    try:
        import tomllib
        with open("pyproject.toml", "rb") as f:
            version = tomllib.load(f)["project"]["version"]
    except Exception:
        pass

    zip_name = f"{APP_NAME}-{version}-windows.zip"
    print(f"Creating {zip_name}...")

    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in out_dir.rglob("*"):
            if file.is_file():
                arcname = Path(APP_NAME) / file.relative_to(out_dir)
                zf.write(file, arcname)

    size_mb = os.path.getsize(zip_name) / 1_048_576
    print(f"Release zip: {zip_name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    build()
    if "--release" in sys.argv:
        create_release_zip()
