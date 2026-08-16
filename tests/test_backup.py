"""Tests for compressed JSON backup/restore (no network)."""
import gzip
import json
from datetime import datetime
from pathlib import Path

import pytest

from playcache import __version__
from playcache.backup import FORMAT_VERSION, export_backup, import_backup
from playcache.db import COLUMNS, Database
from playcache.models import GameRecord


def _sample(folder_path="/games/Hollow Knight", **kw):
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
        "metacritic_score": 90,
        "data_source": "rawg",
        "fetch_status": "ok",
        "esrb_rating": "T - Teen",
        "manual_overrides": '{"user_rating": "10/10"}',
    }
    base.update(kw)
    return GameRecord(**base)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_creates_gz_file(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.upsert(_sample())
    out = export_backup(db, str(tmp_path / "backup.json.gz"))
    assert Path(out).is_file()
    # Confirm it's actually gzipped JSON
    with gzip.open(out, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["format_version"] == FORMAT_VERSION
    assert data["count"] == 1
    assert data["app_version"] == __version__
    assert "exported_at" in data
    # exported_at must be ISO-parseable
    datetime.fromisoformat(data["exported_at"])


def test_export_contains_all_columns(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    rec = _sample(manual_overrides='{"game_name": "Custom"}')
    db.upsert(rec)
    out = export_backup(db, str(tmp_path / "backup.json.gz"))
    with gzip.open(out, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    row = data["games"][0]
    for col in COLUMNS:
        assert col in row, f"missing column: {col}"
    assert row["folder_path"] == "/games/Hollow Knight"
    assert row["manual_overrides"] == '{"game_name": "Custom"}'
    assert row["metacritic_score"] == 90


def test_export_empty_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    out = export_backup(db, str(tmp_path / "empty.json.gz"))
    with gzip.open(out, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["count"] == 0
    assert data["games"] == []


def test_export_creates_parent_dir(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.upsert(_sample())
    nested = tmp_path / "nested" / "deep" / "backup.json.gz"
    out = export_backup(db, str(nested))
    assert Path(out).is_file()


def test_export_permission_error_message(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.upsert(_sample())
    # Try to write to a path that can't be opened (use a directory as filename)
    with pytest.raises(PermissionError, match="may be open in another"):
        export_backup(db, str(tmp_path))


# ---------------------------------------------------------------------------
# Import (merge mode)
# ---------------------------------------------------------------------------


def test_import_merges_new_rows(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    out = export_backup(db, str(tmp_path / "empty.json.gz"))
    # Backup has no rows; import should be a no-op
    summary = import_backup(db, out)
    assert summary["imported"] == 0
    assert summary["skipped"] == 0
    assert db.count() == 0


def test_import_round_trip_preserves_data(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    rec1 = _sample(folder_path="/games/Hollow Knight")
    rec2 = _sample(folder_path="/games/Portal", game_name="Portal",
                   user_rating="10/10", rawg_id=999,
                   manual_overrides='{"user_rating": "10/10"}')
    db.upsert(rec1)
    db.upsert(rec2)
    out = export_backup(db, str(tmp_path / "backup.json.gz"))

    # Restore into a fresh DB
    db2 = Database(str(tmp_path / "restored.db"))
    summary = import_backup(db2, out)
    assert summary["imported"] == 2
    assert summary["skipped"] == 0
    assert db2.count() == 2

    r1 = db2.get_by_path("/games/Hollow Knight")
    r2 = db2.get_by_path("/games/Portal")
    assert r1.game_name == "Hollow Knight"
    assert r1.user_rating == "9.5/10"
    assert r1.metacritic_score == 90
    assert r1.esrb_rating == "T - Teen"
    assert r2.user_rating == "10/10"
    assert r2.rawg_id == 999
    assert r2.manual_overrides == '{"user_rating": "10/10"}'


def test_import_merge_upserts_existing_path(tmp_path):
    """Importing a row whose folder_path already exists should overwrite it."""
    db = Database(str(tmp_path / "test.db"))
    db.upsert(_sample(folder_path="/games/HK", user_rating="5/10",
                     fetch_status="pending"))
    # Build a backup with the same folder_path but different values
    db2 = Database(str(tmp_path / "src.db"))
    db2.upsert(_sample(folder_path="/games/HK", user_rating="9/10",
                       fetch_status="ok", game_name="Hollow Knight Updated"))
    out = export_backup(db2, str(tmp_path / "backup.json.gz"))

    summary = import_backup(db, out)  # merge mode
    assert summary["imported"] == 1
    assert db.count() == 1  # no duplicate
    rec = db.get_by_path("/games/HK")
    assert rec.user_rating == "9/10"
    assert rec.game_name == "Hollow Knight Updated"


def test_import_replace_all_wipes_first(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.upsert(_sample(folder_path="/games/A"))
    db.upsert(_sample(folder_path="/games/B"))
    # Backup contains only A
    db2 = Database(str(tmp_path / "src.db"))
    db2.upsert(_sample(folder_path="/games/A", game_name="A2"))
    out = export_backup(db2, str(tmp_path / "backup.json.gz"))

    summary = import_backup(db, out, replace_all=True)
    assert summary["imported"] == 1
    assert db.count() == 1  # B is gone
    rec = db.get_by_path("/games/A")
    assert rec.game_name == "A2"


def test_import_skips_rows_without_folder_path(tmp_path):
    """Rows missing folder_path can't be upserted (UNIQUE key) — skip them."""
    db = Database(str(tmp_path / "test.db"))
    # Craft a backup envelope by hand with a bad row
    envelope = {
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "exported_at": "2026-01-01T00:00:00",
        "count": 2,
        "games": [
            _sample(folder_path="/games/OK").to_db_row(),
            {"folder_path": "", "game_name": "No path"},  # bad
            {"game_name": "Also no path"},  # also bad
            "not even a dict",  # also bad
        ],
    }
    p = tmp_path / "bad.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(envelope, fh)
    summary = import_backup(db, str(p))
    assert summary["imported"] == 1
    assert summary["skipped"] == 3


def test_import_rejects_bad_envelope(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    # Not a dict
    p = tmp_path / "bad.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump([1, 2, 3], fh)
    with pytest.raises(ValueError, match="not a valid PlayCache backup"):
        import_backup(db, str(p))


def test_import_rejects_unknown_format_version(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    p = tmp_path / "future.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump({"format_version": 999, "games": []}, fh)
    with pytest.raises(ValueError, match="newer than this app supports"):
        import_backup(db, str(p))


def test_import_rejects_non_list_games(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    p = tmp_path / "bad.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump({"format_version": 1, "games": "not a list"}, fh)
    with pytest.raises(TypeError, match="'games' must be a list"):
        import_backup(db, str(p))


def test_import_handles_legacy_unknown_columns(tmp_path):
    """Backups from future versions may have extra columns — must be ignored."""
    db = Database(str(tmp_path / "test.db"))
    envelope = {
        "format_version": FORMAT_VERSION,
        "app_version": "9.9.9",
        "exported_at": "2026-01-01T00:00:00",
        "count": 1,
        "games": [
            {
                **_sample(folder_path="/games/Future").to_db_row(),
                "future_column": "ignored",
                "another_future_field": 42,
            }
        ],
    }
    p = tmp_path / "future.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(envelope, fh)
    summary = import_backup(db, str(p))
    assert summary["imported"] == 1
    assert summary["app_version"] == "9.9.9"
    assert db.get_by_path("/games/Future") is not None


def test_import_missing_columns_get_defaults(tmp_path):
    """Backups from older versions may lack newer columns — defaults apply."""
    db = Database(str(tmp_path / "test.db"))
    envelope = {
        "format_version": FORMAT_VERSION,
        "app_version": "0.1.0",
        "exported_at": "2020-01-01T00:00:00",
        "count": 1,
        "games": [
            {
                "folder_name": "OldGame",
                "folder_path": "/games/OldGame",
                "game_name": "OldGame",
                # No esrb_rating, no manual_overrides, no metacritic_score, etc.
            }
        ],
    }
    p = tmp_path / "old.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(envelope, fh)
    summary = import_backup(db, str(p))
    assert summary["imported"] == 1
    rec = db.get_by_path("/games/OldGame")
    assert rec.esrb_rating == ""
    assert rec.manual_overrides == ""
    assert rec.metacritic_score is None
    assert rec.platform == "PC"  # default from dataclass


def test_import_corrupt_gzip_raises(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    p = tmp_path / "corrupt.json.gz"
    p.write_bytes(b"this is not gzip data at all")
    with pytest.raises((OSError, EOFError, gzip.BadGzipFile)):
        import_backup(db, str(p))
