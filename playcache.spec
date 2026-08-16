# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PlayCache.

Builds a portable one-directory bundle:

    Windows: dist/PlayCache/PlayCache.exe + DLLs → zip for distribution
    Linux:   dist/PlayCache/PlayCache    + libs  → AppImage wrapper

Usage:
    pip install pyinstaller
    pyinstaller playcache.spec --noconfirm
"""

import sys
from pathlib import Path

block_cipher = None

# Data files to bundle alongside the executable
datas = [
    ("config.example.ini", "."),
    ("playcache/assets/app.ico", "playcache/assets"),
    ("playcache/assets/app.png", "playcache/assets"),
]

# Hidden imports that PyInstaller can't always auto-detect
hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
]

a = Analysis(
    ["run.pyw"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest", "pydoc"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PlayCache",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app — no console window
    disable_windowed_traceback=False,
    icon="playcache/assets/app.ico" if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PlayCache",
)
