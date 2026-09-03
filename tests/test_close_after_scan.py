"""Regression tests: Close after a finished scan must actually close.

Workers were wired as ``finished -> deleteLater``, which destroys the C++
object once the event loop resumes, while the Python attribute
(``ScanDialog._worker`` / ``MainWindow._refetch_worker``) kept referencing the
dead wrapper. Any later access — the dialog's Close button, re-fetch guards,
or ``MainWindow.closeEvent`` — raised
``RuntimeError: Internal C++ object already deleted`` and the rest of the slot
(including ``reject()`` / ``event.accept()``) never ran, so the window stayed
open.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import warnings
from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent, QThread
from PySide6.QtWidgets import QApplication, QDialog

from playcache.config import Config
from playcache.gui.scan_dialog import ScanDialog


@pytest.fixture(scope="module")
def qapp():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = QApplication.instance() or QApplication([])
    yield app


class _FakeCataloger:
    def scan_to_db(self, root, **kwargs):
        return {
            "scanned": 1,
            "processed": 1,
            "ok": 1,
            "not_found": 0,
            "error": 0,
            "skipped": 0,
            "conflicts": 0,
            "stored": 1,
        }


class _FinishedWorker(QThread):
    def run(self) -> None:
        return


def _run_to_deletion(qapp: QApplication, worker: QThread) -> None:
    worker.finished.connect(worker.deleteLater)
    worker.start()
    assert worker.wait(10000)
    for _ in range(10):
        qapp.processEvents()


def test_worker_is_running_tolerates_deleted_wrapper(qapp):
    from playcache.gui.qtutils import worker_is_running

    assert worker_is_running(None) is False
    worker = _FinishedWorker()
    _run_to_deletion(qapp, worker)
    with pytest.raises(RuntimeError):
        worker.isRunning()
    assert worker_is_running(worker) is False


def test_scan_dialog_close_after_finished_scan(qapp):
    dialog = ScanDialog(_FakeCataloger(), Config(), parent=None)
    dialog.path_edit.setText(os.getcwd())
    dialog._start()
    worker = dialog._worker
    assert worker is not None
    _run_to_deletion(qapp, worker)
    dialog._on_close()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_scan_dialog_close_idle_no_worker(qapp):
    dialog = ScanDialog(_FakeCataloger(), Config(), parent=None)
    dialog._on_close()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_main_window_close_with_deleted_refetch_worker(qapp, tmp_path):
    from playcache.gui.main_window import MainWindow

    config = replace(Config(), db_path=str(tmp_path / "lib.db"))
    window = MainWindow(config)
    worker = _FinishedWorker()
    window._refetch_worker = worker
    _run_to_deletion(qapp, worker)
    event = QEvent(QEvent.Type.Close)
    window.closeEvent(event)
    assert event.isAccepted()
