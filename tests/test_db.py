"""Tests for the SQLite database layer (no network)."""
import os
from pathlib import Path

from playcache.db import Database
from playcache.models import GameRecord


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


def test_init_creates_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    assert Path(db.db_path).exists()
    assert db.count() == 0


def test_upsert_and_get(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    rec = _sample_record()
    assert db.upsert(rec) is True

    fetched = db.get_by_path(rec.folder_path)
    assert fetched is not None
    assert fetched.game_name == "Hollow Knight"
    assert fetched.store == "GOG"
    assert fetched.user_rating == "9.5/10"
    assert fetched.rawg_id == 1234
    assert fetched.fetch_status == "ok"


def test_upsert_updates_existing(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    rec = _sample_record()
    db.upsert(rec)

    rec.user_rating = "9/10"
    rec.game_type = "Action / Metroidvania"
    db.upsert(rec)

    assert db.count() == 1
    fetched = db.get_by_path(rec.folder_path)
    assert fetched.user_rating == "9/10"
    assert fetched.game_type == "Action / Metroidvania"


def test_excel_view(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.upsert(_sample_record(folder_path="/games/A"))
    db.upsert(_sample_record(folder_path="/games/B", game_name="Biomutant",
                             store="Steam", user_rating="7/10"))
    rows = db.list_excel_view()
    assert len(rows) == 2
    assert list(rows[0].keys()) == [
        "GAME NAME", "PLATFORM", "GOG / STEAM", "USER RATING",
        "GAME TYPE", "SHORT DESCRIPTION",
    ]
    names = [r["GAME NAME"] for r in rows]
    assert names == sorted(names)  # ordered by name

    # Fallbacks: missing store -> 'Other', missing platform -> 'PC'
    db.upsert(_sample_record(folder_path="/games/C", game_name="NoStore",
                             store="", platform=""))
    rows = {r["GAME NAME"]: r for r in db.list_excel_view()}
    assert rows["NoStore"]["GOG / STEAM"] == "Other"
    assert rows["NoStore"]["PLATFORM"] == "PC"


def test_excel_view_uses_folder_name_when_game_name_empty(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.upsert(GameRecord(folder_name="My Folder", folder_path="/games/My Folder",
                         game_name="", platform="PC", store="Steam",
                         fetch_status="not_found"))
    rows = db.list_excel_view()
    assert rows[0]["GAME NAME"] == "My Folder"


def test_stats(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.upsert(_sample_record(folder_path="/games/1", data_source="rawg", fetch_status="ok"))
    db.upsert(_sample_record(folder_path="/games/2", data_source="thegamesdb", fetch_status="ok"))
    db.upsert(_sample_record(folder_path="/games/3", data_source="", fetch_status="not_found"))
    stats = db.stats()
    assert stats["total"] == 3
    assert stats["by_status"]["ok"] == 2
    assert stats["by_status"]["not_found"] == 1
    assert stats["by_source"]["rawg"] == 1
    assert stats["by_source"]["thegamesdb"] == 1
    # New distributions
    assert stats["by_platform"]["PC"] == 3
    assert stats["by_store"]["GOG"] == 3
    assert stats["by_esrb"]["(none)"] == 3  # no ESRB set on samples
    # Completeness counters
    comp = stats["completeness"]
    assert comp["with_name"] == 3
    assert comp["with_rating"] == 3
    assert comp["with_release"] == 3
    assert comp["with_esrb"] == 0
    assert comp["with_metacritic"] == 0


def test_stats_distributions(tmp_path, monkeypatch):
    """Stats correctly bucket games by disk (volume label) and release year."""
    # Stub volume label lookup so the test is deterministic on any platform.
    # "C:" has a label, "D:" has none (falls back to drive letter).
    from playcache import db as _db
    from playcache import models as _models
    _models._drive_label_cache.clear()

    def _fake_label(root: str) -> str:
        return "SSD" if root.upper().startswith("C:") else ""

    monkeypatch.setattr(_db, "_volume_label", _fake_label)

    # On Linux/Mac, os.path.splitdrive doesn't recognize "C:" as a drive
    # letter. Stub it to mimic Windows behavior so the test is deterministic
    # across platforms.
    def _fake_splitdrive(path: str) -> tuple[str, str]:
        if len(path) >= 2 and path[1] == ":":
            return (path[:2], path[2:])
        return ("", path)

    monkeypatch.setattr(os.path, "splitdrive", _fake_splitdrive)

    db = Database(str(tmp_path / "test.db"))
    db.upsert(_sample_record(folder_path="C:/Games/Game1", release_date="2017-02-24"))
    db.upsert(_sample_record(folder_path="D:/Games/Game2", release_date="2020"))
    db.upsert(_sample_record(folder_path="D:/Games/Game3", release_date=""))  # no date
    db.upsert(_sample_record(folder_path="/manual/My Game", release_date="2021"))
    stats = db.stats()
    # C: resolved to its volume label "SSD"
    assert stats["by_disk"]["SSD"] == 1
    # D: has no label → falls back to drive letter
    assert stats["by_disk"]["D:"] == 2
    # Manual entries grouped as "Manual"
    assert stats["by_disk"]["Manual"] == 1
    assert stats["by_year"]["2017"] == 1
    assert stats["by_year"]["2020"] == 1
    assert stats["by_year"]["2021"] == 1
    assert "with_release" in stats["completeness"]
    assert stats["completeness"]["with_release"] == 3


def test_reset_fetch_status(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.upsert(_sample_record(folder_path="/games/1"))
    n = db.reset_fetch_status()
    assert n == 1
    rec = db.get_by_path("/games/1")
    assert rec.fetch_status == "pending"
    assert rec.data_source == ""
