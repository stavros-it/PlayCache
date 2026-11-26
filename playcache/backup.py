"""Backup/restore for the PlayCache catalog.

Two formats:

* **Full backup** (``.zip``, the default) - ``catalog.json`` (every column of
  every row plus the non-secret settings) and ``covers/`` holding the cached
  cover image of every game. Restoring it on another PC needs no network:
  metadata, manual edits and covers all come from the file.
* **Catalog only** (``.json.gz``) - the same JSON envelope gzip-compressed,
  without images. Older backups use this format and still import.

Design:
- Uses only stdlib (``json``, ``gzip``, ``zipfile``) - no extra deps.
- The envelope is versioned (``format_version``, currently 2). Version 2
  adds ``settings`` and the per-row ``volume_id`` / ``volume_path``; version
  1 files import unchanged.
- Rows carry the ID of the volume they live on and their path inside it.
  On import, a row whose path does not exist is re-pointed at the folder on
  the drive that now holds that volume (``I:`` on the old PC, ``E:`` on the
  new one). Rows without a volume ID fall back to "the same path on exactly
  one other drive letter".
- Import is an **upsert** keyed by ``folder_path`` (after relinking).
  ``replace_all=True`` does DELETE + all upserts in a single transaction.
- Export writes to a temp file then atomically renames.
"""
from __future__ import annotations

import gzip
import json
import os
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, volumes
from .covers import MAX_COVER_BYTES, cover_file_name, is_fetchable, write_cover
from .db import COLUMNS, Database
from .models import GameRecord

FORMAT_VERSION = 2

CATALOG_MEMBER = "catalog.json"
COVERS_PREFIX = "covers/"
_MAX_CATALOG_BYTES = 512 * 1024 * 1024


def is_full_backup(path: str) -> bool:
    """True when ``path`` names a full (zip) backup rather than ``.json.gz``."""
    return str(path).lower().endswith(".zip")


def _fill_volumes(db: Database, records: list[GameRecord]) -> None:
    volumes.clear_cache()
    for rec in records:
        if rec.volume_id or not rec.folder_path or not os.path.exists(rec.folder_path):
            continue
        vid, inner = volumes.locate(rec.folder_path)
        if vid:
            rec.volume_id, rec.volume_path = vid, inner
            db.set_volume(rec.folder_path, vid, inner)


def _cover_urls(records: list[GameRecord]) -> list[str]:
    seen: dict[str, None] = {}
    for rec in records:
        if is_fetchable(rec.cover_url):
            seen.setdefault(rec.cover_url or "", None)
    return list(seen)


def _write_atomic(out: Path, writer: Callable[[Path], None]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    try:
        writer(tmp)
        fd = os.open(tmp, os.O_RDWR)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, out)
    except OSError as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        errno = getattr(e, "errno", None)
        if errno in (13, 5, 21):
            raise PermissionError(
                f"Cannot write to '{out}'. The file may be open in another "
                f"program, the location is read-only, or it is a directory. "
                f"Close it and try again."
            ) from e
        raise OSError(f"Could not write backup to '{out}': {e}") from e


def export_backup(
    db: Database,
    output_path: str,
    *,
    covers_dir: str | None = None,
    settings: dict | None = None,
) -> str:
    """Write the catalog to ``output_path`` and return the path written.

    A ``.zip`` path writes a full backup: the catalog, ``settings`` and every
    cover image found in ``covers_dir``. Any other path writes the
    catalog-only gzip JSON. Rows that lack a volume ID get one first when
    their folder exists, so the backup can be relinked on another PC.
    Raises ``OSError`` (with a contextual message) on I/O failure.
    """
    records = list(db.all_records())
    _fill_volumes(db, records)
    envelope = {
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "exported_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "count": len(records),
        "settings": settings or {},
        "games": [rec.to_db_row() for rec in records],
    }
    payload = json.dumps(envelope, ensure_ascii=False, indent=2)
    out = Path(output_path)

    if not is_full_backup(output_path):
        def write_gz(tmp: Path) -> None:
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                fh.write(payload)

        _write_atomic(out, write_gz)
        return str(out)

    folder = Path(covers_dir) if covers_dir else None

    def write_zip(tmp: Path) -> None:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(CATALOG_MEMBER, payload)
            if folder is None:
                return
            for url in _cover_urls(records):
                name = cover_file_name(url)
                src = folder / name
                if src.is_file():
                    zf.write(src, COVERS_PREFIX + name, compress_type=zipfile.ZIP_STORED)

    _write_atomic(out, write_zip)
    return str(out)


def count_cached_covers(db: Database, covers_dir: str) -> tuple[int, int]:
    """``(cached, total)`` cover images for the catalog in ``covers_dir``."""
    urls = _cover_urls(list(db.all_records()))
    folder = Path(covers_dir)
    cached = sum(1 for u in urls if (folder / cover_file_name(u)).is_file())
    return cached, len(urls)


def _read_envelope(input_path: str) -> tuple[dict, zipfile.ZipFile | None]:
    if zipfile.is_zipfile(input_path):
        zf = zipfile.ZipFile(input_path)
        try:
            info = zf.getinfo(CATALOG_MEMBER)
        except KeyError:
            zf.close()
            raise ValueError(
                f"'{input_path}' is not a valid PlayCache backup (no {CATALOG_MEMBER})."
            ) from None
        if info.file_size > _MAX_CATALOG_BYTES:
            zf.close()
            raise ValueError(f"'{input_path}': {CATALOG_MEMBER} is too large.")
        with zf.open(info) as fh:
            envelope = json.loads(fh.read().decode("utf-8"))
        return envelope, zf
    with gzip.open(input_path, "rt", encoding="utf-8") as fh:
        return json.load(fh), None


def _relink(records: list[GameRecord]) -> int:
    """Re-point rows whose folder is missing at the drive that now holds it."""
    volumes.clear_cache()
    roots: dict[str, str] | None = None
    relinked = 0
    for rec in records:
        path = rec.folder_path
        if path.startswith("/manual/") or os.path.exists(path):
            continue
        new_path: str | None = None
        if rec.volume_id:
            if roots is None:
                roots = volumes.current_roots()
            candidate = volumes.resolve(rec.volume_id, rec.volume_path, roots)
            if candidate and os.path.exists(candidate):
                new_path = candidate
        if new_path is None:
            new_path = volumes.swap_drive_letter(path)
            if new_path and not rec.volume_id:
                rec.volume_id, rec.volume_path = volumes.locate(new_path)
        if new_path and new_path != path:
            rec.folder_path = new_path
            relinked += 1
    return relinked


def _restore_covers(zf: zipfile.ZipFile, records: list[GameRecord], covers_dir: str) -> int:
    names = {i.filename: i for i in zf.infolist()}
    folder = Path(covers_dir)
    restored = 0
    for url in _cover_urls(records):
        name = cover_file_name(url)
        info = names.get(COVERS_PREFIX + name)
        if info is None or info.file_size > MAX_COVER_BYTES or (folder / name).is_file():
            continue
        with zf.open(info) as fh:
            data = fh.read(MAX_COVER_BYTES + 1)
        if data and len(data) <= MAX_COVER_BYTES:
            write_cover(folder, url, data)
            restored += 1
    return restored


def import_backup(
    db: Database,
    input_path: str,
    *,
    replace_all: bool = False,
    covers_dir: str | None = None,
    relink: bool = True,
) -> dict:
    """Load a backup (``.zip`` or ``.json.gz``) and upsert every row into ``db``.

    ``replace_all`` deletes every existing row first (in the same
    transaction as the upserts). ``covers_dir`` receives the cover images of
    a full backup (existing files are kept). ``relink`` re-points rows whose
    folder is missing at the drive that now holds the same volume.

    Returns ``{"imported", "skipped", "relinked", "covers", "settings",
    "format_version", "app_version"}``. ``skipped`` counts rows rejected as
    malformed; ``settings`` is the backed-up settings dict (may be empty).

    Raises ``ValueError`` if the file is not a valid backup envelope, and
    re-raises any ``OSError`` / ``gzip.BadGzipFile`` from the underlying
    reads.
    """
    envelope, zf = _read_envelope(input_path)
    try:
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
            if any(not isinstance(v, (str, int, float, bool)) for v in clean.values()):
                skipped += 1
                continue
            parsed.append(GameRecord.from_row(clean))

        relinked = _relink(parsed) if relink else 0
        imported = db.upsert_many(parsed, replace_all=replace_all)
        covers = _restore_covers(zf, parsed, covers_dir) if zf and covers_dir else 0
        settings = envelope.get("settings")
    finally:
        if zf is not None:
            zf.close()

    return {
        "imported": imported,
        "skipped": skipped,
        "relinked": relinked,
        "covers": covers,
        "settings": settings if isinstance(settings, dict) else {},
        "format_version": version,
        "app_version": envelope.get("app_version") or "unknown",
    }
