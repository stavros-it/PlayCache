"""SQLite storage layer. Schema preserves the Excel columns plus extra metadata."""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

from .models import GameRecord, _volume_label

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_name          TEXT    NOT NULL,
    folder_path          TEXT    NOT NULL UNIQUE,
    game_name            TEXT,
    platform             TEXT,
    store                TEXT,
    user_rating          TEXT,
    game_type            TEXT,
    short_description    TEXT,
    rawg_id              INTEGER,
    rawg_slug            TEXT,
    thegamesdb_id        INTEGER,
    release_date         TEXT,
    developer            TEXT,
    publisher            TEXT,
    metacritic_score     INTEGER,
    cover_url            TEXT,
    website              TEXT,
    esrb_rating          TEXT NOT NULL DEFAULT '',
    data_source          TEXT,
    fetch_status         TEXT,
    fetch_message        TEXT,
    manual_overrides     TEXT    NOT NULL DEFAULT '',
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_games_game_name    ON games(game_name);
CREATE INDEX IF NOT EXISTS idx_games_fetch_status ON games(fetch_status);
CREATE INDEX IF NOT EXISTS idx_games_store        ON games(store);
"""

# A view that mirrors Game_Library.xlsx exactly (1 row per game, ordered)
EXCEL_VIEW = """
CREATE VIEW IF NOT EXISTS v_excel AS
SELECT
    COALESCE(NULLIF(game_name, ''), folder_name) AS "GAME NAME",
    COALESCE(NULLIF(platform, ''), 'PC')         AS "PLATFORM",
    COALESCE(NULLIF(store, ''), 'Other')          AS "GOG / STEAM",
    user_rating                                   AS "USER RATING",
    game_type                                     AS "GAME TYPE",
    short_description                             AS "SHORT DESCRIPTION"
FROM games
ORDER BY "GAME NAME";
"""

COLUMNS = [
    "folder_name", "folder_path", "game_name", "platform", "store",
    "user_rating", "game_type", "short_description",
    "rawg_id", "rawg_slug", "thegamesdb_id", "release_date",
    "developer", "publisher", "metacritic_score", "cover_url", "website",
    "esrb_rating", "data_source", "fetch_status", "fetch_message", "manual_overrides",
]

# Columns a user is allowed to edit manually in the GUI (others are read-only).
EDITABLE_COLUMNS = {
    "game_name", "platform", "store", "user_rating", "game_type",
    "short_description", "release_date", "developer", "publisher", "website",
}


class Database:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        self.init()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.executescript(EXCEL_VIEW)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add columns introduced after the initial schema to existing DBs."""
        existing = {
            row[1] for row in conn.execute("PRAGMA table_info(games);").fetchall()
        }
        if "manual_overrides" not in existing:
            conn.execute(
                "ALTER TABLE games ADD COLUMN manual_overrides "
                "TEXT NOT NULL DEFAULT '';"
            )
        if "esrb_rating" not in existing:
            conn.execute(
                "ALTER TABLE games ADD COLUMN esrb_rating "
                "TEXT NOT NULL DEFAULT '';"
            )

    def upsert(self, record: GameRecord) -> bool:
        """Insert a new record or update an existing one keyed by folder_path.

        Returns True if a row was inserted or updated.
        """
        row = record.to_db_row()
        values = [row[c] for c in COLUMNS]
        placeholders = ",".join(["?"] * len(COLUMNS))
        col_list = ",".join(COLUMNS)
        # Refresh updated_at via excluded (defaults to datetime('now') on insert)
        update_list = ",".join(
            [f"{c}=excluded.{c}" for c in COLUMNS] + ["updated_at=datetime('now')"]
        )
        sql = (
            f"INSERT INTO games ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT(folder_path) DO UPDATE SET {update_list};"
        )
        with self.connect() as conn:
            cur = conn.execute(sql, values)
            return cur.rowcount > 0

    def get_by_path(self, folder_path: str) -> GameRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM games WHERE folder_path = ?;", (folder_path,)
            ).fetchone()
        return GameRecord.from_row(dict(row)) if row else None

    def all_records(self) -> Iterable[GameRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM games ORDER BY COALESCE(NULLIF(game_name,''), folder_name);"
            ).fetchall()
        return [GameRecord.from_row(dict(r)) for r in rows]

    def list_excel_view(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute('SELECT * FROM v_excel;').fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM games;").fetchone()[0]

    def stats(self) -> dict:
        """Aggregate statistics for the stats dialog.

        Returns a dict with:
        * ``total`` — total game count
        * ``by_status`` — {fetch_status: count}, sorted by count desc
        * ``by_source`` — {data_source: count}, sorted by count desc
        * ``by_platform`` — {platform: count}, sorted by count desc
        * ``by_store`` — {store: count}, sorted by count desc
        * ``by_esrb`` — {esrb_rating: count}, sorted by count desc
        * ``by_disk`` — {volume_label: count}, sorted by count desc
          (volume label resolved from drive letter via Windows API;
          falls back to drive letter if no label; manual entries grouped as
          "Manual"; sorted by count desc)
        * ``by_year`` — {year: count}, sorted by year asc
        * ``completeness`` — counts of populated fields
          (with_name, with_rating, with_cover, with_release, with_metacritic,
          with_esrb, with_description, with_overrides)
        """
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM games;").fetchone()[0]

            def _group(expr: str) -> dict[str, int]:
                rows = conn.execute(
                    f"SELECT COALESCE(NULLIF({expr}, ''), '(none)') k, "
                    f"COUNT(*) c FROM games GROUP BY k ORDER BY c DESC;"
                ).fetchall()
                return {k: c for k, c in rows}

            by_status = _group("fetch_status")
            by_source = _group("data_source")
            by_platform = _group("platform")
            by_store = _group("store")
            by_esrb = _group("esrb_rating")

            # Disk: group by volume label (resolved from drive letter via
            # Windows API). Manual entries (/manual/...) grouped as "Manual".
            # Falls back to drive letter if no label is available.
            # folder_path has a UNIQUE constraint so no GROUP BY is needed.
            by_disk_rows = conn.execute(
                "SELECT folder_path FROM games;"
            ).fetchall()
            label_counts: dict[str, int] = {}
            for (folder_path,) in by_disk_rows:
                if not folder_path or folder_path.startswith("/manual/"):
                    key = "Manual"
                else:
                    drive = os.path.splitdrive(folder_path)[0]
                    root = os.path.join(drive, os.sep) if drive else ""
                    label = _volume_label(root) if root else ""
                    key = label or drive or "—"
                label_counts[key] = label_counts.get(key, 0) + 1
            by_disk = dict(
                sorted(label_counts.items(), key=lambda kv: kv[1], reverse=True)
            )

            # Year: from release_date (YYYY-MM-DD or YYYY-MM or YYYY)
            by_year_rows = conn.execute(
                "SELECT SUBSTR(release_date, 1, 4) y, COUNT(*) c "
                "FROM games WHERE release_date != '' "
                "GROUP BY y ORDER BY y;"
            ).fetchall()
            by_year = {y: c for y, c in by_year_rows if y and len(y) == 4 and y.isdigit()}

            def _count(expr: str) -> int:
                return conn.execute(
                    f"SELECT COUNT(*) FROM games WHERE {expr};"
                ).fetchone()[0]

            completeness = {
                "with_name": _count("game_name != ''"),
                "with_rating": _count("user_rating != ''"),
                "with_cover": _count("cover_url != ''"),
                "with_release": _count("release_date != ''"),
                "with_metacritic": _count("metacritic_score IS NOT NULL"),
                "with_esrb": _count("esrb_rating != ''"),
                "with_description": _count("short_description != ''"),
                "with_overrides": _count("manual_overrides != ''"),
            }

        return {
            "total": total,
            "by_status": by_status,
            "by_source": by_source,
            "by_platform": by_platform,
            "by_store": by_store,
            "by_esrb": by_esrb,
            "by_disk": by_disk,
            "by_year": by_year,
            "completeness": completeness,
        }

    def reset_fetch_status(self) -> int:
        """Mark every record so it will be refetched on next run. Returns count."""
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE games SET fetch_status='pending', data_source='', "
                "fetch_message='marked for rescan';"
            )
            return cur.rowcount

    # ------------------------------------------------------------------ #
    # Manual overrides: persist user edits and protect them on rescan.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_overrides(raw: str | None) -> dict:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @staticmethod
    def _dump_overrides(overrides: dict) -> str:
        return json.dumps(overrides, ensure_ascii=False) if overrides else ""

    def get_overrides(self, folder_path: str) -> dict:
        """Return the {field: value} override map for a game (empty if none)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT manual_overrides FROM games WHERE folder_path = ?;",
                (folder_path,),
            ).fetchone()
        return self._parse_overrides(row[0] if row else None)

    def set_field(self, folder_path: str, field: str, value: str) -> bool:
        """Update a single editable column and record it as a manual override.

        Future rescans will preserve this field's value instead of overwriting
        it with fresh API data. ``field`` must be in EDITABLE_COLUMNS.
        """
        if field not in EDITABLE_COLUMNS:
            raise ValueError(f"Field '{field}' is not editable")
        with self.connect() as conn:
            # Load current overrides, add/update this field, persist
            row = conn.execute(
                "SELECT manual_overrides FROM games WHERE folder_path = ?;",
                (folder_path,),
            ).fetchone()
            if not row:
                return False
            overrides = self._parse_overrides(row[0])
            overrides[field] = value
            conn.execute(
                f"UPDATE games SET {field} = ?, manual_overrides = ?, "
                f"updated_at = datetime('now') WHERE folder_path = ?;",
                (value, self._dump_overrides(overrides), folder_path),
            )
            return True

    def clear_override(self, folder_path: str, field: str) -> bool:
        """Remove a field from the manual overrides (next rescan may overwrite it)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT manual_overrides FROM games WHERE folder_path = ?;",
                (folder_path,),
            ).fetchone()
            if not row:
                return False
            overrides = self._parse_overrides(row[0])
            if field not in overrides:
                return False
            del overrides[field]
            conn.execute(
                "UPDATE games SET manual_overrides = ?, "
                "updated_at = datetime('now') WHERE folder_path = ?;",
                (self._dump_overrides(overrides), folder_path),
            )
            return True
