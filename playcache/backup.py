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
- Export writes to a temp file then atomically renames, so a crash or disk
  full never leaves a corrupt-looking backup file.
- Import with ``replace_all=True`` does DELETE + all upserts in a single
  transaction, so a crash mid-import never loses the existing catalog.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .db import COLUMNS, Database
from .models import GameRecord

FORMAT_VERSION = 1


def export_backup(db: Database, output_path: str) -> str:
    """Write the entire catalog to a compressed JSON file (``.json.gz``).

    Returns the path written. The write is atomic: a temp file is used and
    only renamed into place once fully written and flushed, so a crash or
    disk-full never leaves a partially-written file that looks valid.
    Raises ``OSError`` (with a contextual message) on I/O failure.
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
    tmp = out.with_suffix(out.suffix + ".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, out)
    except OSError as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        errno = getattr(e, "errno", None)
        if errno in (13, 5):
            raise PermissionError(
                f"Cannot write to '{out}'. The file may be open in another "
                f"program, or the location is read-only. Close it and try again."
            ) from e
        raise OSError(f"Could not write backup to '{out}': {e}") from e
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
        restoring a snapshot. The DELETE and all upserts run in a **single
        transaction**, so a crash mid-import rolls back and the existing
        catalog is preserved. Default False (merge by ``folder_path``).

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

    parsed: list[GameRecord] = []
    skipped = 0
    for row in games:
        if not isinstance(row, dict):
            skipped += 1
            continue
        folder_path = row.get("folder_path")
        if not isinstance(folder_path, str) or not folder_path:
            skipped += 1
            continue
        clean = {c: v for c, v in row.items() if c in COLUMNS and v is not None}
        parsed.append(GameRecord.from_row(clean))

    imported = db.upsert_many(parsed, replace_all=replace_all)

    return {
        "imported": imported,
        "skipped": skipped,
        "format_version": version,
        "app_version": envelope.get("app_version") or "unknown",
    }
