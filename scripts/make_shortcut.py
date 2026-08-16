"""Create a PlayCache desktop shortcut on Windows.

Generates ``PlayCache.lnk`` on the user's Desktop pointing to ``run.pyw`` in
the project root, with the app icon. Run:

    python scripts/make_shortcut.py

Requires pywin32 (``pip install pywin32``). If pywin32 is not installed, the
script prints instructions instead of failing hard.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "playcache" / "assets" / "app.ico"
TARGET = ROOT / "run.pyw"


def main() -> int:
    if sys.platform != "win32":
        print("This script is Windows-only.")
        return 1
    if not TARGET.is_file():
        print(f"Target not found: {TARGET}")
        return 1
    if not ICON.is_file():
        print(f"Icon not found: {ICON}")
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
        shortcut.SetIconLocation(str(ICON), 0)
        persist = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
        persist.Save(str(lnk_path), True)
    finally:
        pythoncom.CoUninitialize()

    print(f"Created: {lnk_path}")
    print(f"  Target: {TARGET}")
    print(f"  Icon:   {ICON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
