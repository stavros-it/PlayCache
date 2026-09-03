"""Tests for the post-scan exact-duplicate purge (no network)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import warnings
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from playcache.config import Config
from playcache.db import Database
from playcache.models import GameRecord


@pytest.fixture(scope="module")
def qapp():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = QApplication.instance() or QApplication([])
    yield app


def _sample_record(folder_path="/games/Hollow Knight", **kw):
    base = {
        "folder_name": "Hollow Knight",
        "folder_path": folder_path,
        "game_name": "Hollow Knight",
        "platform": "PC",
        "store": "GOG",
        "user_rating": "9.5/10",
        "game_type": "Metroidvania",
        "short_description": "Beautifully crafted action-adventure.",
        "rawg_id": 1234,
        "rawg_slug": "hollow-knight",
        "release_date": "2017-02-24",
        "developer": "Team Cherry",
        "publisher": "Team Cherry",
        "data_source": "rawg",
        "fetch_status": "ok",
    }
    base.update(kw)
    return GameRecord(**base)


class TestPurgeExactDuplicates:
    def test_keeps_most_complete_copy(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_sample_record())
        db.upsert(
            _sample_record(
                folder_path="/games/Hollow Knight (copy)",
                fetch_status="pending",
                user_rating="",
                game_type="",
                short_description="",
                rawg_id=None,
                rawg_slug=None,
                release_date="",
                developer="",
                publisher="",
                data_source="",
            )
        )
        assert db.purge_exact_duplicates() == 1
        assert db.count() == 1
        assert db.get_by_path("/games/Hollow Knight") is not None
        assert db.get_by_path("/games/Hollow Knight (copy)") is None

    def test_case_insensitive_grouping(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_sample_record(folder_path="/games/a", game_name="DOOM"))
        db.upsert(_sample_record(folder_path="/games/b", game_name="doom"))
        assert db.purge_exact_duplicates() == 1
        assert db.count() == 1

    def test_distinct_names_untouched(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_sample_record(folder_path="/games/a", game_name="Hollow Knight"))
        db.upsert(_sample_record(folder_path="/games/b", game_name="Doom"))
        assert db.purge_exact_duplicates() == 0
        assert db.count() == 2

    def test_single_row_untouched(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_sample_record())
        assert db.purge_exact_duplicates() == 0
        assert db.count() == 1

    def test_empty_db(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        assert db.purge_exact_duplicates() == 0

    def test_never_removes_all_copies(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        for i in range(3):
            db.upsert(_sample_record(folder_path=f"/games/p{i}"))
        purged = db.purge_exact_duplicates()
        assert purged == 2
        assert db.count() == 1

    def test_rows_without_name_never_grouped(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_sample_record(folder_path="/games/a", game_name=""))
        db.upsert(_sample_record(folder_path="/games/b", game_name=""))
        assert db.purge_exact_duplicates() == 0
        assert db.count() == 2

    def test_manual_override_counts_toward_completeness(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        base = {
            "user_rating": "",
            "game_type": "",
            "short_description": "",
            "rawg_id": None,
            "rawg_slug": None,
            "release_date": "",
            "developer": "",
            "publisher": "",
            "data_source": "",
            "fetch_status": "pending",
        }
        db.upsert(_sample_record(folder_path="/games/plain", **base))
        db.upsert(_sample_record(folder_path="/games/curated", **base))
        db.set_field("/games/curated", "user_rating", "10/10")
        assert db.purge_exact_duplicates() == 1
        assert db.get_by_path("/games/curated") is not None
        assert db.get_by_path("/games/plain") is None


def test_scan_dialog_close_purges_duplicates(qapp, tmp_path, monkeypatch):
    """After the scan dialog closes, MainWindow purges exact duplicates."""
    from playcache.gui.main_window import MainWindow, ScanDialog

    config = replace(Config(), db_path=str(tmp_path / "lib.db"))
    window = MainWindow(config)
    calls = []
    monkeypatch.setattr(
        window._db, "purge_exact_duplicates", lambda: calls.append(1) or 0
    )
    monkeypatch.setattr(ScanDialog, "exec", lambda self: None)
    window._open_scan_dialog()
    assert calls
