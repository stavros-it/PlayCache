"""Orchestrates: scan folders -> fetch metadata (TheGamesDB, then RAWG) -> upsert DB."""
from __future__ import annotations

import json
import logging

from .config import Config
from .db import Database
from .folder_scanner import ScannedFolder, scan_games
from .models import GameRecord
from .rawg_client import RAWGClient
from .thegamesdb_client import TheGamesDBClient

log = logging.getLogger(__name__)

# Fields that API data populates and that manual overrides can protect.
OVERRIDE_PROTECTED_FIELDS = (
    "game_name", "platform", "store", "user_rating", "game_type",
    "short_description", "release_date", "developer", "publisher", "website",
)


class Cataloger:
    def __init__(
        self,
        config: Config,
        db: Database | None = None,
        rawg: RAWGClient | None = None,
        tgdb: TheGamesDBClient | None = None,
    ):
        self.config = config
        self.db = db or Database(config.db_path)
        self.rawg = rawg or RAWGClient(config)
        self.tgdb = tgdb or TheGamesDBClient(config)

    # ------------------------------------------------------------------ #
    def scan_to_db(
        self,
        root: str,
        *,
        rescan: bool = False,
        only_missing: bool = True,
        limit: int | None = None,
        name_filter: str | None = None,
        dry_run: bool = False,
        recursive: bool = False,
        progress: callable | None = None,
        conflict_handler: callable | None = None,
    ) -> dict:
        """Scan ``root`` for game folders and fetch/store metadata.

        Returns a summary dict: {scanned, fetched, ok, not_found, error, skipped,
        processed, stored, conflicts}.
        ``progress(idx, total, record_or_scanned, message)`` is called per folder.
        ``conflict_handler(new_record, existing_record)`` is called when a scanned
        game matches an existing DB entry on a *different* disk. It must return
        one of: ``"new"`` (replace old with new), ``"old"`` (skip, keep old),
        ``"both"`` (keep both as separate entries). If not provided, both are kept.
        ``recursive=True`` descends into grouping folders (no files, only subdirs).
        """
        folders = list(scan_games(root, recursive=recursive))
        if name_filter:
            nf = name_filter.lower()
            folders = [f for f in folders if nf in f.folder_name.lower()]

        total = len(folders)
        if limit:
            folders = folders[:limit]

        summary = {"scanned": total, "processed": 0, "ok": 0,
                   "not_found": 0, "error": 0, "skipped": 0, "stored": 0,
                   "conflicts": 0}

        rawg_ok = self.rawg.is_available()
        tgdb_ok = self.tgdb.is_available()
        if not rawg_ok and not tgdb_ok:
            log.warning("No API keys configured; games will be stored with empty metadata.")

        for idx, scanned in enumerate(folders, 1):
            summary["processed"] += 1
            record = self._build_record(scanned)

            try:
                # Check for same game on a different disk (conflict)
                existing_path = self.db.get_by_path(record.folder_path)
                conflict = self._find_conflict(record)
                if conflict and conflict_handler and not dry_run:
                    summary["conflicts"] += 1
                    choice = conflict_handler(record, conflict)
                    if choice == "old":
                        summary["skipped"] += 1
                        if progress:
                            progress(idx, len(folders), record,
                                     f"kept existing on {conflict.disk}")
                        continue
                    if choice == "new":
                        # Preserve manual overrides from the old entry before
                        # deleting it, so user edits migrate to the new path.
                        conflict_overrides = self.db.get_overrides(conflict.folder_path)
                        with self.db.connect() as conn:
                            conn.execute(
                                "DELETE FROM games WHERE folder_path = ?;",
                                (conflict.folder_path,),
                            )
                        log.info("Replaced '%s' on %s with copy on %s",
                                 record.game_name, conflict.disk, record.disk)
                    else:
                        conflict_overrides = None
                else:
                    conflict_overrides = None

                # Decide whether we need to fetch
                existing = existing_path
                if existing and not rescan:
                    status = existing.fetch_status
                    if status == "ok" or (bool(status) and not only_missing):
                        record = existing
                        summary["skipped"] += 1
                        if progress:
                            progress(idx, len(folders), record, "already catalogued")
                        continue

                if dry_run:
                    if progress:
                        progress(idx, len(folders), record, "[dry-run] would fetch")
                    summary["skipped"] += 1
                    continue

                record.fetch_status = "pending"
                # Load manual overrides from the existing row (or migrated from
                # the conflict-replaced entry) so the fetch can restore
                # user-edited values after applying API data.
                overrides = conflict_overrides or (
                    self.db.get_overrides(record.folder_path) if existing else {}
                )
                record = self._fetch(record)
                self._apply_overrides(record, overrides)

                if record.fetch_status == "ok":
                    summary["ok"] += 1
                elif record.fetch_status == "not_found":
                    summary["not_found"] += 1
                else:
                    summary["error"] += 1

                if not record.game_name:
                    record.game_name = scanned.cleaned_name or scanned.folder_name
                if not record.store:
                    record.store = "Other"

                self.db.upsert(record)
                summary["stored"] += 1

                if progress:
                    msg = f"{record.data_source or '?'}: {record.fetch_status}"
                    progress(idx, len(folders), record, msg)

            except Exception as exc:
                # A single-game failure must NOT abort the whole scan.
                log.exception("Failed to process '%s'", scanned.folder_name)
                record.fetch_status = "error"
                record.fetch_message = f"scan error: {exc}"
                summary["error"] += 1
                if not record.game_name:
                    record.game_name = scanned.cleaned_name or scanned.folder_name
                if not record.store:
                    record.store = "Other"
                try:
                    self.db.upsert(record)
                    summary["stored"] += 1
                except Exception:
                    log.exception("Could not store error record for '%s'", scanned.folder_name)
                if progress:
                    progress(idx, len(folders), record, f"error: {exc}")

        return summary

    def _find_conflict(self, record: GameRecord) -> GameRecord | None:
        """Find an existing DB entry with the same game name on a different disk.

        Returns the conflicting record (to prompt the user) or ``None``.
        Uses case-insensitive name comparison and ignores the path's own entry.

        Note: disk comparison uses the volume label, which means two drives with
        the *same* label would not be detected as a conflict. This is acceptable
        for typical use; the rare same-label case still stores both entries.
        """
        name = (record.game_name or record.folder_name).strip().lower()
        if not name:
            return None
        for rec in self.db.all_records():
            if rec.folder_path == record.folder_path:
                continue  # same entry (update, not conflict)
            other_name = (rec.game_name or rec.folder_name).strip().lower()
            if other_name == name and rec.disk != record.disk:
                return rec
        return None

    # ------------------------------------------------------------------ #
    def _build_record(self, scanned: ScannedFolder) -> GameRecord:
        return GameRecord(
            folder_name=scanned.folder_name,
            folder_path=scanned.folder_path,
            game_name=scanned.cleaned_name,
            platform=scanned.platform,
            store=scanned.store,
            fetch_status="pending",
        )

    def _fetch(self, record: GameRecord) -> GameRecord:
        """Try TheGamesDB first; on not_found/error fall back to RAWG.

        After a successful TheGamesDB fetch, also query RAWG to fill in fields
        that TheGamesDB doesn't provide (numeric user_rating, metacritic_score,
        cover image, website). This is a no-op when RAWG is unavailable.
        """
        # TheGamesDB (primary)
        if self.tgdb.is_available():
            record = self.tgdb.fetch(record)
            if record.fetch_status == "ok":
                self._merge_from_rawg(record)
                return record

        # Fallback to RAWG
        if self.rawg.is_available():
            prev_msg = record.fetch_message
            record = self.rawg.fetch(record)
            if record.fetch_status == "ok":
                return record
            if record.fetch_message and prev_msg:
                record.fetch_message = f"{prev_msg}; {record.fetch_message}"

        if record.fetch_status not in ("ok", "not_found", "error"):
            record.fetch_status = "not_found"
        return record

    def _merge_from_rawg(self, record: GameRecord) -> None:
        """Fill empty fields from RAWG after TheGamesDB succeeds.

        TheGamesDB lacks numeric ratings and Metacritic scores, so we query RAWG
        to fill those (plus cover image / website) when missing. Runs in-place on
        ``record``. Skipped silently when RAWG is unavailable or returns no match.
        Does NOT change ``data_source`` — TheGamesDB remains the primary source.
        """
        if not self.rawg.is_available():
            return
        # Skip if there's nothing to merge
        if record.user_rating and record.metacritic_score and record.cover_url and record.website:
            return
        # Fetch into a throwaway record so RAWG doesn't clobber TGDB data
        probe = GameRecord(
            folder_name=record.folder_name,
            folder_path=record.folder_path,
            game_name=record.game_name or record.folder_name,
        )
        probe = self.rawg.fetch(probe)
        if probe.fetch_status != "ok":
            return
        # Always capture RAWG IDs for future re-fetch, even if all fields
        # are already filled by TGDB.
        if probe.rawg_id:
            record.rawg_id = probe.rawg_id
        if probe.rawg_slug:
            record.rawg_slug = probe.rawg_slug
        # Fill only empty fields from the RAWG probe
        if not record.user_rating and probe.user_rating:
            record.user_rating = probe.user_rating
        if not record.metacritic_score and probe.metacritic_score:
            record.metacritic_score = probe.metacritic_score
        if not record.cover_url and probe.cover_url:
            record.cover_url = probe.cover_url
        if not record.website and probe.website:
            record.website = probe.website

    @staticmethod
    def _apply_overrides(record: GameRecord, overrides: dict) -> None:
        """Restore manually-edited field values onto ``record`` after an API fetch.

        This protects user edits from being overwritten by fresh API data on
        rescan. The ``manual_overrides`` JSON column itself is preserved on the
        record so it round-trips back through ``upsert``.
        """
        if not overrides:
            return
        for field, value in overrides.items():
            if field in OVERRIDE_PROTECTED_FIELDS and hasattr(record, field):
                setattr(record, field, value)
        # Carry the overrides map forward so upsert preserves it
        record.manual_overrides = json.dumps(overrides, ensure_ascii=False) if overrides else ""
