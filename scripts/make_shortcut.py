"""Create a PlayCache desktop shortcut (Windows .lnk or Linux .desktop).

Generates a shortcut on the user's Desktop pointing to ``run.pyw`` in the
project root, with the app icon. Run:

    python scripts/make_shortcut.py

- **Windows**: creates ``PlayCache.lnk`` via pywin32 (``pip install pywin32``).
- **Linux**: installs ``PlayCache.desktop`` to
  ``~/.local/share/applications/`` (FreeDesktop standard) so the app appears
  in the application menu. Also copies a copy to the Desktop if writable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON_ICO = ROOT / "playcache" / "assets" / "app.ico"
ICON_PNG = ROOT / "playcache" / "assets" / "app.png"
TARGET = ROOT / "run.pyw"


def _make_windows_shortcut() -> int:
    if not TARGET.is_file():
        print(f"Target not found: {TARGET}")
        return 1
    if not ICON_ICO.is_file():
        print(f"Icon not found: {ICON_ICO}")
        print("Run `python scripts/make_icon.py` first.")
        return 1
    try:
        import pythoncom
        from win32com.shell import shell, shellcon
    except ImportError:
        print("pywin32 is required:  pip install pywin32")
        return 1

    desktop = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOP, None, 0))
    lnk_path = desktop / "PlayCache.lnk"

    pythoncom.CoInitialize()
    try:
        shortcut = pythoncom.CoCreateInstance(
            shell.CLSID_ShellLink,
            None,
            pythoncom.CLSCTX_INPROC_SERVER,
            shell.IID_IShellLink,
        )
        shortcut.SetPath(str(TARGET))
        shortcut.SetWorkingDirectory(str(ROOT))
        shortcut.SetDescription("PlayCache — game catalog")
        shortcut.SetIconLocation(str(ICON_ICO), 0)
        persist = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
        persist.Save(str(lnk_path), True)
    finally:
        pythoncom.CoUninitialize()

    print(f"Created: {lnk_path}")
    print(f"  Target: {TARGET}")
    print(f"  Icon:   {ICON_ICO}")
    return 0


def _make_linux_desktop_entry() -> int:
    if not TARGET.is_file():
        print(f"Target not found: {TARGET}")
        return 1
    icon = ICON_PNG if ICON_PNG.is_file() else ICON_ICO
    if not icon.is_file():
        print(f"Icon not found: {ICON_PNG} or {ICON_ICO}")
        print("Run `python scripts/make_icon.py` first.")
        return 1

    python_exe = sys.executable or "python3"
    desktop_entry = f"""[Desktop Entry]
Type=Application
Name=PlayCache
Comment=Game library cataloguer
Exec={python_exe} {TARGET}
Path={ROOT}
Icon={icon}
Terminal=false
Categories=Game;Utility;
StartupNotify=true
"""
    app_dir = Path.home() / ".local" / "share" / "applications"
    app_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = app_dir / "PlayCache.desktop"
    desktop_path.write_text(desktop_entry, encoding="utf-8")
    os.chmod(desktop_path, 0o755)

    desktop_copy = Path.home() / "Desktop" / "PlayCache.desktop"
    if desktop_copy.parent.is_dir() and os.access(desktop_copy.parent, os.W_OK):
        desktop_copy.write_text(desktop_entry, encoding="utf-8")
        os.chmod(desktop_copy, 0o755)
        print(f"Created: {desktop_copy}")
    else:
        print(f"Created: {desktop_path}")

    print(f"  Target: {python_exe} {TARGET}")
    print(f"  Icon:   {icon}")
    return 0


def main() -> int:
    if sys.platform == "win32":
        return _make_windows_shortcut()
    return _make_linux_desktop_entry()


if __name__ == "__main__":
    sys.exit(main())
