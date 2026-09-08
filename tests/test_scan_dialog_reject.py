"""Regression tests: Escape / title-bar X during a scan must hit the close guard.

``_on_close`` (cancel + stop + detach the ScanWorker) was connected only to
the button box's ``rejected`` signal. QDialog's built-in Escape key and the
window-system close (title-bar X) call ``reject()`` directly, which bypassed
the guard entirely: the dialog closed while the scan kept running hidden —
crash on app exit ("QThread: Destroyed while thread is still running") and an
unguarded second scan became possible. ``reject()`` must route through
``_on_close`` with a re-entrancy flag.
"""

from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import warnings

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
)

from playcache.config import Config
from playcache.gui.qtutils import worker_is_running
from playcache.gui.scan_dialog import ScanDialog


@pytest.fixture(scope="module")
def qapp():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = QApplication.instance() or QApplication([])
    yield app


class _BlockingCataloger:
    """scan_to_db that loops until cancelled via the progress callback."""

    def __init__(self) -> None:
        self.release = threading.Event()

    def scan_to_db(self, root, **kwargs):
        progress = kwargs.get("progress")
        idx = 0
        while not self.release.is_set():
            idx += 1
            if progress is not None:
                progress(idx, 100, None, "working")
            time.sleep(0.02)
        return {
            "scanned": 0,
            "processed": 0,
            "ok": 0,
            "not_found": 0,
            "error": 0,
            "skipped": 0,
            "conflicts": 0,
            "stored": 0,
        }


def _start_scan(cataloger: _BlockingCataloger) -> ScanDialog:
    dialog = ScanDialog(cataloger, Config(), parent=None)
    dialog.path_edit.setText(os.getcwd())
    dialog.show()
    dialog._start()
    return dialog


def _spy_on_close(monkeypatch) -> list[int]:
    calls: list[int] = []
    original = ScanDialog._on_close
    monkeypatch.setattr(ScanDialog, "_on_close", lambda self: (calls.append(1), original(self)))
    return calls


def _cleanup_dialog(qapp, dialog: ScanDialog, cataloger: _BlockingCataloger) -> None:
    worker = getattr(dialog, "_worker", None)
    if worker is not None and worker_is_running(worker):
        worker.cancel()
        cataloger.release.set()
        worker.wait(10000)
    dialog.deleteLater()
    qapp.processEvents()


def test_escape_during_running_scan_runs_close_guard(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    calls = _spy_on_close(monkeypatch)
    cataloger = _BlockingCataloger()
    dialog = _start_scan(cataloger)
    try:
        worker = dialog._worker
        assert worker is not None
        assert worker_is_running(worker)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert len(calls) == 1
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert not dialog.isVisible()
        assert dialog._worker is None
    finally:
        _cleanup_dialog(qapp, dialog, cataloger)


def test_reject_during_running_scan_cancels_worker(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    calls = _spy_on_close(monkeypatch)
    cataloger = _BlockingCataloger()
    dialog = _start_scan(cataloger)
    try:
        worker = dialog._worker
        assert worker is not None
        assert worker_is_running(worker)
        dialog.reject()
        assert len(calls) == 1
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog._worker is None
    finally:
        _cleanup_dialog(qapp, dialog, cataloger)


def test_close_event_during_running_scan_runs_close_guard(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    calls = _spy_on_close(monkeypatch)
    cataloger = _BlockingCataloger()
    dialog = _start_scan(cataloger)
    try:
        assert dialog._worker is not None
        event = QCloseEvent()
        qapp.sendEvent(dialog, event)
        assert len(calls) == 1
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog._worker is None
    finally:
        _cleanup_dialog(qapp, dialog, cataloger)


def test_close_button_during_running_scan_cancels_worker(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    calls = _spy_on_close(monkeypatch)
    cataloger = _BlockingCataloger()
    dialog = _start_scan(cataloger)
    try:
        close_btn = next(
            btn
            for btn in dialog.buttons.buttons()
            if dialog.buttons.buttonRole(btn) == QDialogButtonBox.ButtonRole.RejectRole
        )
        QTest.mouseClick(close_btn, Qt.MouseButton.LeftButton)
        assert len(calls) == 1
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog._worker is None
    finally:
        _cleanup_dialog(qapp, dialog, cataloger)


def test_guard_decline_keeps_dialog_open_then_retry_closes(qapp, monkeypatch):
    answers = {"reply": QMessageBox.StandardButton.No}
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: answers["reply"])
    calls = _spy_on_close(monkeypatch)
    cataloger = _BlockingCataloger()
    dialog = _start_scan(cataloger)
    try:
        worker = dialog._worker
        assert worker is not None
        dialog.reject()
        assert len(calls) == 1
        assert dialog.isVisible()
        assert dialog._worker is worker
        assert worker_is_running(worker)
        answers["reply"] = QMessageBox.StandardButton.Yes
        dialog.reject()
        assert len(calls) == 2
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog._worker is None
    finally:
        _cleanup_dialog(qapp, dialog, cataloger)


def test_reject_idle_dialog_closes(qapp):
    cataloger = _BlockingCataloger()
    dialog = ScanDialog(cataloger, Config(), parent=None)
    try:
        dialog.reject()
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert not dialog.isVisible()
    finally:
        _cleanup_dialog(qapp, dialog, cataloger)
