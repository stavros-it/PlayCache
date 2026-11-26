"""Copies of a game on different platforms are never treated as duplicates (no network)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import warnings
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from playcache.cataloger import Cataloger
from playcache.config import Config
from playcache.db import Database
from playcache.gui.duplicates_dialog import DuplicatesDialog
from playcache.gui.main_window import MainWindow
from playcache.models import GameRecord
from playcache.thegamesdb_client import TheGamesDBClient


@pytest.fixture(scope="module")
def qapp():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = QApplication.instance() or QApplication([])
    yield app


def _rec(folder_path: str, name: str = "Torchlight 2", platform: str = "PC", **kw) -> GameRecord:
    base = {
        "folder_name": folder_path.rsplit("/", 1)[-1],
        "folder_path": folder_path,
        "game_name": name,
        "platform": platform,
        "fetch_status": "ok",
        "data_source": "rawg",
    }
    base.update(kw)
    return GameRecord(**base)


class TestPurgeIsPlatformAware:
    def test_other_platform_copy_survives(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_rec("/games/tl2", platform="PC"))
        db.upsert(_rec("/games/tl2.sh", platform="PC (Linux)"))
        db.upsert(_rec("/games/tl2-switch", platform="SWITCH"))
        assert db.purge_exact_duplicates() == 0
        assert db.count() == 3

    def test_same_platform_copy_purged(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_rec("/games/a", platform="PC"))
        db.upsert(_rec("/games/b", platform="PC", fetch_status="pending"))
        db.upsert(_rec("/games/c", platform="PC (Linux)"))
        assert db.purge_exact_duplicates() == 1
        assert db.get_by_path("/games/b") is None
        assert db.get_by_path("/games/c") is not None

    def test_empty_platform_counts_as_pc(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_rec("/games/a", platform="PC"))
        db.upsert(_rec("/games/b", platform="", fetch_status="pending"))
        assert db.purge_exact_duplicates() == 1


class TestFindDuplicatesIsPlatformAware:
    def test_cross_platform_pair_not_grouped(self):
        groups = DuplicatesDialog._group_duplicates([
            _rec("/a", platform="PC"),
            _rec("/b", platform="PC (Linux)"),
            _rec("/c", platform="ANDROID"),
        ])
        assert groups == {}

    def test_same_platform_pair_grouped(self):
        groups = DuplicatesDialog._group_duplicates([
            _rec("/a", platform="PC"),
            _rec("/b", name="Torchlight II", platform="PC"),
            _rec("/c", platform="PC (Linux)"),
        ])
        assert len(groups) == 1
        members = next(iter(groups.values()))
        assert sorted(r.folder_path for r in members) == ["/a", "/b"]


class _NoRAWG:
    def is_available(self):
        return False


class TestConflictIsPlatformAware:
    def test_other_platform_on_other_disk_is_not_a_conflict(self, tmp_path):
        cfg = replace(Config(), db_path=str(tmp_path / "c.db"))
        db = Database(cfg.db_path)
        cat = Cataloger(cfg, db=db, rawg=_NoRAWG(), tgdb=_NoRAWG())
        existing = _rec("/other/disk/Torchlight 2", platform="PC (Linux)")
        db.upsert(existing)
        new = _rec(str(tmp_path / "Torchlight 2"), platform="PC")
        assert cat._find_conflict(new) is None

    def test_same_platform_on_other_disk_is_a_conflict(self, tmp_path, monkeypatch):
        cfg = replace(Config(), db_path=str(tmp_path / "c.db"))
        db = Database(cfg.db_path)
        cat = Cataloger(cfg, db=db, rawg=_NoRAWG(), tgdb=_NoRAWG())
        db.upsert(_rec("/other/disk/Torchlight 2", platform="PC"))
        monkeypatch.setattr(GameRecord, "disk", property(lambda self: self.folder_path[:6]))
        new = _rec(str(tmp_path / "Torchlight 2"), platform="PC")
        found = cat._find_conflict(new)
        assert found is not None and found.folder_path == "/other/disk/Torchlight 2"


class TestTgdbKeepsScannerPlatform:
    def _apply(self, platform: str) -> str:
        client = TheGamesDBClient(replace(Config(), thegamesdb_api_key=""))
        record = GameRecord(folder_name="g", game_name="Zelda", platform=platform)
        game = {"id": 1, "game_title": "Zelda", "platform": 2}
        includes = {"platform": {"2": {"id": 2, "name": "Nintendo GameCube"}}}
        client._apply(record, game, includes)
        return record.platform

    def test_scanner_platform_not_overwritten(self):
        assert self._apply("PC (Fan Port)") == "PC (Fan Port)"
        assert self._apply("PC") == "PC"

    def test_generic_console_refined_by_api(self):
        assert self._apply("CONSOLE") == "Nintendo GameCube"
        assert self._apply("") == "Nintendo GameCube"


def _platform_items(window: MainWindow) -> list[str]:
    combo = window.platform_combo
    return [combo.itemText(i) for i in range(combo.count())]


class TestPlatformFilter:
    def test_combo_follows_catalog(self, qapp, tmp_path):
        db = Database(str(tmp_path / "lib.db"))
        db.upsert(_rec("/games/a", platform="PC"))
        db.upsert(_rec("/games/b", platform="PC (Linux)"))
        db.upsert(_rec("/games/c", name="Mario", platform="SWITCH"))
        db.upsert(_rec("/games/d", name="Doom", platform=""))
        window = MainWindow(replace(Config(), db_path=str(tmp_path / "lib.db")))
        assert _platform_items(window) == ["All", "PC", "PC (Linux)", "SWITCH"]
        window.platform_combo.setCurrentText("PC")
        assert window._proxy.rowCount() == 2
        window.platform_combo.setCurrentText("SWITCH")
        assert window._proxy.rowCount() == 1

    def test_refresh_preserves_selection(self, qapp, tmp_path):
        window = MainWindow(replace(Config(), db_path=str(tmp_path / "lib.db")))
        window._db.upsert(_rec("/games/a", platform="PC"))
        window._db.upsert(_rec("/games/b", platform="ANDROID"))
        window._refresh_table()
        window.platform_combo.setCurrentText("ANDROID")
        window._db.upsert(_rec("/games/c", name="Zelda", platform="GAMECUBE"))
        window._refresh_table()
        assert window.platform_combo.currentText() == "ANDROID"
        assert window._proxy.rowCount() == 1
        with window._db.connect() as conn:
            conn.execute("DELETE FROM games WHERE folder_path = '/games/b';")
        window._refresh_table()
        assert window.platform_combo.currentText() == "All"
        assert window._proxy.rowCount() == 2

    def test_combines_with_store_filter(self, qapp, tmp_path):
        window = MainWindow(replace(Config(), db_path=str(tmp_path / "lib.db")))
        window._db.upsert(_rec("/games/a", platform="PC", store="GOG"))
        window._db.upsert(_rec("/games/b", platform="PC (Linux)", store="GOG"))
        window._db.upsert(_rec("/games/c", name="Doom", platform="PC", store="Steam"))
        window._refresh_table()
        window.store_combo.setCurrentText("GOG")
        window.platform_combo.setCurrentText("PC")
        assert window._proxy.rowCount() == 1
