"""Tests for manual override persistence and rescan protection."""
from playcache.cataloger import Cataloger
from playcache.config import Config
from playcache.db import Database
from playcache.models import GameRecord


def _record(folder_path="/games/Hollow Knight", **kw):
    base = {
        "folder_name": "Hollow Knight",
        "folder_path": folder_path,
        "game_name": "Hollow Knight",
        "platform": "PC",
        "store": "GOG",
        "user_rating": "9.5/10",
        "game_type": "Metroidvania",
        "short_description": "Original description.",
        "data_source": "rawg",
        "fetch_status": "ok",
    }
    base.update(kw)
    return GameRecord(**base)


class TestOverrideStorage:
    def test_set_field_updates_value_and_overrides(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_record())
        ok = db.set_field("/games/Hollow Knight", "user_rating", "10/10")
        assert ok is True
        rec = db.get_by_path("/games/Hollow Knight")
        assert rec.user_rating == "10/10"
        assert rec.manual_overrides == '{"user_rating": "10/10"}'

    def test_set_multiple_fields_accumulate(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_record())
        db.set_field("/games/Hollow Knight", "user_rating", "10/10")
        db.set_field("/games/Hollow Knight", "game_type", "Souls-like")
        rec = db.get_by_path("/games/Hollow Knight")
        overrides = db.get_overrides("/games/Hollow Knight")
        assert overrides == {"user_rating": "10/10", "game_type": "Souls-like"}
        assert rec.user_rating == "10/10"
        assert rec.game_type == "Souls-like"

    def test_set_field_rejects_non_editable(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_record())
        try:
            db.set_field("/games/Hollow Knight", "rawg_id", "999")
        except ValueError:
            return
        assert False, "ValueError expected for non-editable field"

    def test_clear_override_removes_field(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_record())
        db.set_field("/games/Hollow Knight", "user_rating", "10/10")
        assert db.clear_override("/games/Hollow Knight", "user_rating") is True
        overrides = db.get_overrides("/games/Hollow Knight")
        assert overrides == {}

    def test_clear_override_unknown_field_returns_false(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_record())
        assert db.clear_override("/games/Hollow Knight", "user_rating") is False

    def test_get_overrides_missing_record(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        assert db.get_overrides("/nonexistent") == {}

    def test_set_field_missing_record(self, tmp_path):
        db = Database(str(tmp_path / "t.db"))
        assert db.set_field("/nonexistent", "user_rating", "10/10") is False

    def test_overrides_survive_upsert(self, tmp_path):
        """Re-upserting a record (e.g. from rescan) preserves the overrides column."""
        db = Database(str(tmp_path / "t.db"))
        db.upsert(_record())
        db.set_field("/games/Hollow Knight", "user_rating", "10/10")
        # Simulate a rescan upserting the same path with fresh API data
        fresh = _record(
            user_rating="7/10",  # API says 7/10
            game_type="Action / Indie",
            short_description="Fresh from API.",
        )
        fresh.manual_overrides = '{"user_rating": "10/10"}'
        db.upsert(fresh)
        rec = db.get_by_path("/games/Hollow Knight")
        assert rec.manual_overrides == '{"user_rating": "10/10"}'
        # The upsert itself overwrites user_rating; the cataloger is responsible
        # for re-applying the override after fetch (see test below).
        assert rec.user_rating == "7/10"


class TestCatalogerRespectsOverrides:
    """The cataloger must re-apply manual overrides after an API fetch."""

    class StubRAWG:
        name = "rawg"

        def __init__(self, config):
            self.config = config

        def is_available(self):
            return True

        def fetch(self, record, *, overrides=None):
            # Simulate API data overwriting everything
            record.game_name = "Hollow Knight"
            record.user_rating = "7/10"          # API rating
            record.game_type = "Action / Indie"
            record.short_description = "API description."
            record.data_source = "rawg"
            record.fetch_status = "ok"
            return record

    class StubTGDB:
        name = "thegamesdb"

        def __init__(self, config):
            self.config = config

        def is_available(self):
            return False

        def fetch(self, record, *, overrides=None):
            return record

    def test_rescan_preserves_user_edits(self, tmp_path):
        cfg = Config()
        cfg.db_path = str(tmp_path / "t.db")
        db = Database(cfg.db_path)
        cat = Cataloger(cfg, db=db,
                        rawg=self.StubRAWG(cfg), tgdb=self.StubTGDB(cfg))

        # Create a real game folder so the scanner finds it
        game_dir = tmp_path / "Hollow Knight"
        game_dir.mkdir()

        # First scan: seed the DB with API data
        cat.scan_to_db(str(tmp_path))
        rec = db.get_by_path(str(game_dir.resolve()))
        assert rec.user_rating == "7/10"
        assert rec.game_type == "Action / Indie"

        # User manually edits the rating
        db.set_field(rec.folder_path, "user_rating", "10/10")
        assert db.get_by_path(rec.folder_path).user_rating == "10/10"

        # Second scan with rescan=True: API returns 7/10 but the override
        # (10/10) must win.
        cat.scan_to_db(str(tmp_path), rescan=True, only_missing=False)

        rec = db.get_by_path(rec.folder_path)
        assert rec.user_rating == "10/10", "manual override was overwritten!"
        assert rec.game_type == "Action / Indie"  # not overridden -> API value
        assert rec.manual_overrides == '{"user_rating": "10/10"}'


class TestSchemaMigration:
    def test_old_db_without_overrides_column_migrates(self, tmp_path):
        """An existing DB created before manual_overrides should be migrated.

        Simulates the exact previous schema (all columns except
        ``manual_overrides``) and verifies the migration adds the column.
        """
        import sqlite3
        path = str(tmp_path / "old.db")
        # The schema exactly as it was in v1.0.0 (before manual_overrides)
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_name TEXT NOT NULL,
                folder_path TEXT NOT NULL UNIQUE,
                game_name TEXT,
                platform TEXT,
                store TEXT,
                user_rating TEXT,
                game_type TEXT,
                short_description TEXT,
                rawg_id INTEGER,
                rawg_slug TEXT,
                thegamesdb_id INTEGER,
                release_date TEXT,
                developer TEXT,
                publisher TEXT,
                metacritic_score INTEGER,
                cover_url TEXT,
                website TEXT,
                data_source TEXT,
                fetch_status TEXT,
                fetch_message TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO games (folder_name, folder_path, game_name, user_rating,
                              fetch_status, store, platform)
            VALUES ('Old Game', '/games/Old', 'Old Game', '8/10', 'ok', 'GOG', 'PC');
        """)
        conn.commit()
        conn.close()

        # Opening with Database should add the column via migration
        db = Database(path)
        rec = db.get_by_path("/games/Old")
        assert rec is not None
        assert rec.game_name == "Old Game"
        assert rec.user_rating == "8/10"
        assert rec.store == "GOG"
        assert rec.manual_overrides == ""
        assert rec.esrb_rating == ""  # migrated column, empty by default
        # The new column should now exist and be writable
        assert db.set_field("/games/Old", "user_rating", "9/10") is True
        assert db.get_overrides("/games/Old") == {"user_rating": "9/10"}
        # And the v_excel view should work
        rows = db.list_excel_view()
        assert any(r["GAME NAME"] == "Old Game" for r in rows)
