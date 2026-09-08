"""Smoke tests for the GUI entry points.

Runs ``run.py`` and ``run.pyw`` with ``--version`` in a subprocess so
import-time breakage (a missing PySide6 module, a bad import in
``playcache.gui``) fails CI instead of appearing only at launch.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _assert_version_output(script: Path, cwd: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(script), "--version"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(cwd),
    )
    assert result.returncode == 0, result.stderr
    assert "PlayCache" in result.stdout + result.stderr


def test_run_py_version(tmp_path: Path) -> None:
    _assert_version_output(ROOT / "run.py", tmp_path)


def test_run_pyw_version(tmp_path: Path) -> None:
    _assert_version_output(ROOT / "run.pyw", tmp_path)
