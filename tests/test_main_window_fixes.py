"""Regression tests for the v1.5.0 GUI-core audit fixes in MainWindow.

Covers: RefetchWorker skipping records deleted mid-run, the overrides
re-read before upsert, the data-driven store filter combo, busy-guards for
Add Game / Scan Drive / Settings, the detail-panel Re-fetch button provider
argument, current-index-based detail selection, restore status-bar refresh,
guarded persistence in the single-row refetch and Add Game slots, the light
per-tick status path, QuotaWorker cleanup/escalation, the empty-catalog
early return, and removal of the dead ``scan_requested`` signal.
"""

from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import warnings
from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QThread
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLineEdit,
    QMessageBox,
)

from playcache import __version__
from playcache.config import Config
from playcache.db import Database
from playcache.gui.main_window import MainWindow
from playcache.models import GameRecord


@pytest.fixture(scope="module")
def qapp():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = QApplication.instance() or QApplication([])
    yield app


def _record(folder_path: str, **kw) -> GameRecord:
    name = folder_path.rsplit("/", 1)[-1]
    base = {
        "folder_name": name,
        "folder_path": folder_path,
        "game_name": name,
        "fetch_status": "ok",
        "data_source": "rawg",
    }
    base.update(kw)
    return GameRecord(**base)


def _window(qapp, tmp_path) -> MainWindow:
    config = replace(Config(), db_path=str(tmp_path / "lib.db"))
    return MainWindow(config)


def _combo_items(window: MainWindow) -> list[str]:
    combo = window.store_combo
    return [combo.itemText(i) for i in range(combo.count())]


def _drain(qapp, rounds: int = 10) -> None:
    for _ in range(rounds):
        qapp.processEvents()


class _BlockedWorker(QThread):
    """A worker that blocks until released (a stand-in for a running worker)."""

    def __init__(self) -> None:
        super().__init__()
        self._release = threading.Event()

    def run(self) -> None:
        self._release.wait(10)

    def release(self) -> None:
        self._release.set()
        assert self.wait(5000)


class _StuckWorker(_BlockedWorker):
    """A worker whose wait() never succeeds and terminate() is recorded."""

    def __init__(self) -> None:
        super().__init__()
        self.waited = False
        self.terminated = False

    def wait(self, *args) -> bool:
        self.waited = True
        return False

    def terminate(self) -> None:
        self.terminated = True

    def release(self) -> None:
        self._release.set()
        assert QThread.wait(self, 5000)


def test_refetch_worker_skips_records_deleted_mid_run(qapp, tmp_path, monkeypatch):
    window = _window(qapp, tmp_path)
    db = window._db
    db.upsert(_record("/games/alpha"))
    db.upsert(_record("/games/beta"))
    window._refresh_table()

    def fake_fetch(record, provider="auto", overrides=None):
        if record.folder_path == "/games/alpha":
            with db.connect() as conn:
                conn.execute("DELETE FROM games WHERE folder_path = '/games/beta';")
        record.fetch_status = "ok"
        record.game_name = (record.game_name or "") + " (refetched)"
        return record

    monkeypatch.setattr(window._cataloger, "_fetch", fake_fetch)
    summaries: list[dict] = []
    monkeypatch.setattr(window, "_on_refetch_finished", lambda summary: summaries.append(summary))
    window._run_refetch([db.get_by_path("/games/alpha"), db.get_by_path("/games/beta")])
    worker = window._refetch_worker
    assert worker is not None
    assert worker.wait(10000)
    _drain(qapp)
    assert db.get_by_path("/games/alpha") is not None
    assert db.get_by_path("/games/beta") is None
    assert summaries and summaries[0].get("skipped", 0) == 1


def test_refetch_worker_preserves_edits_made_mid_run(qapp, tmp_path, monkeypatch):
    window = _window(qapp, tmp_path)
    db = window._db
    db.upsert(_record("/games/alpha", user_rating="5/10"))
    db.set_field("/games/alpha", "user_rating", "7/10")
    window._refresh_table()

    def fake_fetch(record, provider="auto", overrides=None):
        db.set_field("/games/alpha", "user_rating", "10/10")
        record.user_rating = "1/10"
        record.fetch_status = "ok"
        return record

    monkeypatch.setattr(window._cataloger, "_fetch", fake_fetch)
    monkeypatch.setattr(window, "_on_refetch_finished", lambda summary: None)
    window._run_refetch([db.get_by_path("/games/alpha")])
    worker = window._refetch_worker
    assert worker is not None
    assert worker.wait(10000)
    _drain(qapp)
    stored = db.get_by_path("/games/alpha")
    assert stored is not None
    assert stored.user_rating == "10/10"
    assert db.get_overrides("/games/alpha").get("user_rating") == "10/10"


def test_store_filter_combo_follows_catalog(qapp, tmp_path):
    db = Database(str(tmp_path / "lib.db"))
    db.upsert(_record("/games/hk", store="GOG / Steam"))
    db.upsert(_record("/games/ut99", store="Origin"))
    db.upsert(_record("/games/quake", store="Steam"))
    db.upsert(_record("/games/zzz", store=""))
    window = _window(qapp, tmp_path)
    assert _combo_items(window) == ["All", "GOG / Steam", "Origin", "Other", "Steam"]
    window.store_combo.setCurrentText("GOG / Steam")
    assert window._proxy.rowCount() == 1


def test_store_filter_refresh_preserves_selection(qapp, tmp_path):
    window = _window(qapp, tmp_path)
    window._db.upsert(_record("/games/a", store="Steam"))
    window._db.upsert(_record("/games/b", store="Origin"))
    window._refresh_table()
    window.store_combo.setCurrentText("Steam")
    assert window.store_combo.currentText() == "Steam"
    window._db.upsert(_record("/games/c", store="itch.io"))
    window._refresh_table()
    assert window.store_combo.currentText() == "Steam"
    assert "itch.io" in _combo_items(window)
    with window._db.connect() as conn:
        conn.execute("DELETE FROM games WHERE folder_path = '/games/a';")
    window._refresh_table()
    assert window.store_combo.currentText() == "All"
    assert window._proxy.rowCount() == 2


def _genre_items(window: MainWindow) -> list[str]:
    combo = window.genre_combo
    return [combo.itemText(i) for i in range(combo.count())]


def test_genre_combo_populated_from_catalog(qapp, tmp_path):
    db = Database(str(tmp_path / "lib.db"))
    db.upsert(_record("/games/hk", game_type="Action / RPG"))
    db.upsert(_record("/games/stardew", game_type="Indie"))
    db.upsert(_record("/games/nogenres", game_type=""))
    window = _window(qapp, tmp_path)
    assert _genre_items(window) == ["All", "Action", "Indie", "RPG"]


def test_genre_filter_matches_every_game_containing_the_genre(qapp, tmp_path):
    db = Database(str(tmp_path / "lib.db"))
    db.upsert(_record("/games/hk", game_type="Action / RPG"))
    db.upsert(_record("/games/doom", game_type="Action"))
    db.upsert(_record("/games/stardew", game_type="Indie / RPG"))
    db.upsert(_record("/games/nogenres", game_type=""))
    window = _window(qapp, tmp_path)

    window.genre_combo.setCurrentText("RPG")
    names = {
        window._proxy.index(row, 0).data() for row in range(window._proxy.rowCount())
    }
    assert names == {"hk", "stardew"}

    window.genre_combo.setCurrentText("Action")
    names = {
        window._proxy.index(row, 0).data() for row in range(window._proxy.rowCount())
    }
    assert names == {"doom", "hk"}

    window.genre_combo.setCurrentText("All")
    assert window._proxy.rowCount() == 4


def test_genre_filter_refresh_preserves_selection(qapp, tmp_path):
    window = _window(qapp, tmp_path)
    window._db.upsert(_record("/games/hk", game_type="Action / RPG"))
    window._refresh_table()
    window.genre_combo.setCurrentText("RPG")
    assert window.genre_combo.currentText() == "RPG"
    window._db.upsert(_record("/games/b", game_type="Strategy"))
    window._refresh_table()
    assert window.genre_combo.currentText() == "RPG"
    assert "Strategy" in _genre_items(window)
    with window._db.connect() as conn:
        conn.execute("DELETE FROM games WHERE folder_path = '/games/hk';")
    window._refresh_table()
    assert window.genre_combo.currentText() == "All"


def test_genre_filter_dedupes_case_variants(qapp, tmp_path):
    db = Database(str(tmp_path / "lib.db"))
    db.upsert(_record("/games/a", game_type="Action"))
    db.upsert(_record("/games/b", game_type="action / RPG"))
    window = _window(qapp, tmp_path)
    items = _genre_items(window)
    assert items == ["All", "Action", "RPG"]
    window.genre_combo.setCurrentText("Action")
    assert window._proxy.rowCount() == 2


def test_add_game_blocked_while_refetch_running(qapp, tmp_path, monkeypatch):
    window = _window(qapp, tmp_path)
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    warnings_shown: list[object] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings_shown.append(a))
    worker = _BlockedWorker()
    worker.start()
    try:
        window._refetch_worker = worker
        window._add_game()
        assert warnings_shown, "Add Game must warn while a re-fetch runs"
    finally:
        worker.release()
        window._refetch_worker = None


def test_scan_dialog_entry_blocked_while_refetch_running(qapp, tmp_path, monkeypatch):
    from playcache.gui.main_window import ScanDialog

    window = _window(qapp, tmp_path)
    monkeypatch.setattr(ScanDialog, "exec", lambda self: None)
    warnings_shown: list[object] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings_shown.append(a))
    worker = _BlockedWorker()
    worker.start()
    try:
        window._refetch_worker = worker
        window._open_scan_dialog()
        assert warnings_shown, "Scan Drive must warn while a re-fetch runs"
    finally:
        worker.release()
        window._refetch_worker = None


def test_settings_blocked_while_quota_fetch_running(qapp, tmp_path, monkeypatch):
    from playcache.gui.settings_dialog import SettingsDialog

    window = _window(qapp, tmp_path)
    monkeypatch.setattr(SettingsDialog, "exec", lambda self: None)
    warnings_shown: list[object] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings_shown.append(a))
    worker = _BlockedWorker()
    worker.start()
    try:
        window._quota_worker = worker
        window._open_settings()
        assert warnings_shown, "Settings must warn while the quota fetch runs"
    finally:
        worker.release()
        window._quota_worker = None


def test_detail_refetch_button_passes_auto_provider(qapp, tmp_path, monkeypatch):
    captured: list[object] = []

    def fake_refetch(self, provider="auto"):
        captured.append(provider)

    monkeypatch.setattr(MainWindow, "_refetch_selected", fake_refetch)
    window = _window(qapp, tmp_path)
    window.detail.refetch_btn.setEnabled(True)
    window.detail.refetch_btn.click()
    assert captured == ["auto"]


def test_selection_changed_uses_current_index(qapp, tmp_path):
    window = _window(qapp, tmp_path)
    window._db.upsert(_record("/games/a"))
    window._db.upsert(_record("/games/b"))
    window._db.upsert(_record("/games/c"))
    window._refresh_table()
    table = window.table
    model = table.selectionModel()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    model.select(window._proxy.index(0, 0), flags)
    model.setCurrentIndex(window._proxy.index(2, 0), QItemSelectionModel.SelectionFlag.NoUpdate)
    model.select(window._proxy.index(1, 0), flags)
    model.select(window._proxy.index(2, 0), flags)
    assert window.detail._record is not None
    assert window.detail._record.folder_path == "/games/c"


def test_import_backup_updates_status_bar(qapp, tmp_path, monkeypatch):
    from playcache.backup import export_backup

    seed = Database(str(tmp_path / "seed.db"))
    seed.upsert(_record("/games/hk"))
    seed.upsert(_record("/games/ut99"))
    backup_path = str(tmp_path / "backup.json.gz")
    export_backup(seed, backup_path)
    window = _window(qapp, tmp_path)
    assert window._status_label.text().startswith("0 games")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (backup_path, ""))
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    window._import_backup()
    assert window._db.count() == 2
    assert window._status_label.text().startswith("2 games")


def test_single_row_refetch_survives_db_error(qapp, tmp_path, monkeypatch):
    window = _window(qapp, tmp_path)
    window._db.upsert(_record("/games/hk"))
    window._refresh_table()
    window.table.selectRow(0)

    def boom(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(window._db, "upsert", boom)
    monkeypatch.setattr(
        window._cataloger,
        "_fetch",
        lambda rec, provider="auto", overrides=None: rec,
    )
    window._refetch_selected(provider="auto")
    assert "Re-fetch failed" in window.statusBar().currentMessage()


def test_add_game_survives_db_error(qapp, tmp_path, monkeypatch):
    window = _window(qapp, tmp_path)
    created: list[QDialog] = []

    def fake_exec(self) -> int:
        created.append(self)
        self.findChildren(QLineEdit)[0].setText("Zork")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)

    def boom(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(window._db, "upsert", boom)
    window._add_game()
    assert created, "Add Game dialog should have opened"
    assert window._db.count() == 0
    assert "Could not save" in window.statusBar().currentMessage()


def test_refetch_progress_avoids_db_queries(qapp, tmp_path, monkeypatch):
    window = _window(qapp, tmp_path)

    def boom(*args, **kwargs):
        raise AssertionError("progress ticks must not query the DB")

    monkeypatch.setattr(window._db, "count", boom)
    monkeypatch.setattr(window._db, "stats", boom)
    window._on_refetch_progress(1, 2, "rawg: ok - Game")
    assert window.statusBar().currentMessage() == "[1/2] rawg: ok - Game"
    assert "games" in window._status_label.text()


def test_quota_worker_cleaned_up_after_finish(qapp, tmp_path, monkeypatch):
    window = _window(qapp, tmp_path)
    tgdb = window._cataloger.tgdb
    monkeypatch.setattr(tgdb, "is_available", lambda: True)
    monkeypatch.setattr(tgdb, "_load_genres", lambda: {})
    window._fetch_quota_on_startup()
    worker = window._quota_worker
    assert worker is not None
    assert worker.wait(10000)
    _drain(qapp)
    assert getattr(window, "_quota_worker", None) is None


def test_close_event_terminates_stuck_quota_worker(qapp, tmp_path):
    window = _window(qapp, tmp_path)
    worker = _StuckWorker()
    worker.start()
    window._quota_worker = worker
    event = QEvent(QEvent.Type.Close)
    window.closeEvent(event)
    assert event.isAccepted()
    assert worker.waited
    assert worker.terminated
    worker.release()


def test_run_refetch_all_empty_catalog_early_return(qapp, tmp_path, monkeypatch):
    window = _window(qapp, tmp_path)
    boxes: list[object] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: boxes.append(a))
    window._run_refetch_all()
    assert getattr(window, "_refetch_worker", None) is None
    assert boxes == []
    assert window.statusBar().currentMessage() != ""


def test_dead_scan_requested_signal_removed_and_version_hoisted():
    from playcache.gui import main_window

    assert not hasattr(main_window.MainWindow, "scan_requested")
    assert main_window.__version__ == __version__
