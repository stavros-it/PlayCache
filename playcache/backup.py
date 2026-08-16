"""Compressed JSON backup/restore for the PlayCache catalog.

Format: gzip-compressed JSON (``.json.gz``). One file holds the entire
catalog — every column of every row — plus a small metadata envelope so
future schema changes can be detected and migrated.

Design:
- Uses only stdlib (``json``, ``gzip``, ``datetime``) — no extra deps.
- The envelope is versioned (``format_version``). The current format is 1.
  Future versions can branch on this in ``import_backup``.
- Import is an **upsert**: rows are matched by ``folder_path`` (the UNIQUE
  key) and inserted-or-replaced. Existing rows with the same path are
  overwritten; rows with new paths are added; rows not in the backup are
  left untouched.
- Field-level forward/backward compatibility is handled by
  ``GameRecord.from_row`` which ignores unknown keys and supplies defaults
  for missing ones — so a backup from an older or newer version still
  imports cleanly into whatever schema the running app has.
"""
from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .db import COLUMNS, Database
from .models import GameRecord

FORMAT_VERSION = 1


def export_backup(db: Database, output_path: str) -> str:
    """Write the entire catalog to a compressed JSON file (``.json.gz``).

    Returns the path written. Raises ``PermissionError`` (with a friendly
    message) if the destination is locked, and ``OSError`` for other I/O
    failures.
    """
    records = list(db.all_records())
    envelope = {
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "exported_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "count": len(records),
        "games": [rec.to_db_row() for rec in records],
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(envelope, ensure_ascii=False, indent=2)
    try:
        with gzip.open(out, "wt", encoding="utf-8") as fh:
            fh.write(payload)
    except OSError as e:
        raise PermissionError(
            f"Cannot write to '{out}'. The file may be open in another "
            f"program. Close it and try again."
        ) from e
    return str(out)


def import_backup(db: Database, input_path: str, *, replace_all: bool = False) -> dict:
    """Load a compressed JSON backup and upsert every row into ``db``.

    Parameters
    ----------
    db
        Target database (rows are upserted into it).
    input_path
        Path to a ``.json.gz`` backup produced by :func:`export_backup`.
    replace_all
        If True, **delete every existing row** before importing. Useful for
        restoring a snapshot. Default False (merge by ``folder_path``).

    Returns a summary dict: ``{"imported": int, "skipped": int,
    "format_version": int, "app_version": str}``. ``skipped`` counts rows
    present in the backup but rejected (e.g. missing the required
    ``folder_path`` key).

    Raises ``ValueError`` if the file is not a valid backup envelope, and
    re-raises any ``OSError`` / ``gzip.BadGzipFile`` from the underlying
    reads.
    """
    with gzip.open(input_path, "rt", encoding="utf-8") as fh:
        envelope = json.load(fh)

    if not isinstance(envelope, dict) or "format_version" not in envelope:
        raise ValueError(
            f"'{input_path}' is not a valid PlayCache backup "
            f"(missing 'format_version')."
        )
    version = envelope.get("format_version")
    if not isinstance(version, int) or version < 1:
        raise ValueError(f"Unsupported backup format_version: {version!r}")
    if version > FORMAT_VERSION:
        raise ValueError(
            f"Backup format_version {version} is newer than this app supports "
            f"({FORMAT_VERSION}). Upgrade PlayCache and try again."
        )

    games = envelope.get("games", [])
    if not isinstance(games, list):
        raise TypeError("'games' must be a list.")

    if replace_all:
        with db.connect() as conn:
            conn.execute("DELETE FROM games;")

    imported = 0
    skipped = 0
    for row in games:
        if not isinstance(row, dict):
            skipped += 1
            continue
        folder_path = row.get("folder_path")
        if not folder_path:
            skipped += 1
            continue
        # Drop None values so dataclass defaults apply for fields the
        # backup didn't populate (or explicitly set to null). This matters
        # for NOT NULL columns like esrb_rating / manual_overrides: passing
        # None would violate the constraint, but omitting the key lets the
        # dataclass default ("") kick in. Fields with a None default
        # (rawg_id, metacritic_score, …) get None either way.
        clean = {c: v for c, v in row.items() if c in COLUMNS and v is not None}
        record = GameRecord.from_row(clean)
        db.upsert(record)
        imported += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "format_version": version,
        "app_version": envelope.get("app_version", "unknown"),
    }
