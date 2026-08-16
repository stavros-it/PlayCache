"""Canonical data record passed between scanner, API clients, and the database."""
from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, fields

_drive_label_cache: dict[str, str] = {}


def _volume_label(drive_root: str) -> str:
    """Get the volume label for a drive root (e.g. ``C:\\``). Cached.

    Returns an empty string on non-Windows or if the drive has no label.
    """
    if drive_root in _drive_label_cache:
        return _drive_label_cache[drive_root]
    label = ""
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(drive_root), buf, len(buf),
                None, None, None, None, 0,
            )
            if ok:
                label = buf.value or ""
        except (OSError, AttributeError):
            pass
    _drive_label_cache[drive_root] = label
    return label


@dataclass
class GameRecord:
    # Core identity (from filesystem)
    folder_name: str = ""
    folder_path: str = ""

    # Catalog columns (match Game_Library.xlsx headers)
    game_name: str = ""
    platform: str = "PC"
    store: str = ""            # "Steam" | "GOG" | "Epic" | "GOG / Steam" | "Other"
    user_rating: str = ""      # "9/10", "8.5/10"
    game_type: str = ""        # genres joined with " / "
    short_description: str = ""

    # Extra metadata
    rawg_id: int | None = None
    rawg_slug: str | None = None
    thegamesdb_id: int | None = None
    release_date: str | None = None
    developer: str = ""
    publisher: str = ""
    metacritic_score: int | None = None
    cover_url: str | None = None
    website: str | None = None
    esrb_rating: str = ""       # ESRB age rating from TheGamesDB ("T - Teen", "E - Everyone")

    # Provenance
    data_source: str = ""      # "rawg" | "thegamesdb" | "none"
    fetch_status: str = ""    # "ok" | "not_found" | "error" | "skipped" | "pending"
    fetch_message: str = ""

    # Manual overrides: JSON string of {field: value} the user edited by hand.
    # These are preserved across rescans (API data won't overwrite them).
    manual_overrides: str = ""

    @property
    def disk(self) -> str:
        """Display name of the disk/drive this game lives on.

        Returns the volume label (e.g. ``"TOSHIBA 2TB"``) when available.
        Falls back to the drive letter (``"D:"``) if the drive has no label.
        Manual entries (no real folder) return ``"Manual"``.
        """
        path = self.folder_path or ""
        if not path or path.startswith("/manual/"):
            return "Manual"
        drive = os.path.splitdrive(path)[0]  # "C:" on Windows, "" on Linux/Mac
        if not drive:
            return "—"
        root = os.path.join(drive, os.sep)  # "C:\\"
        label = _volume_label(root)
        if label:
            return label
        return drive

    @property
    def release_date_display(self) -> str:
        """Release date formatted as DD-MM-YYYY (Greek regional format).

        Parses the stored ISO date (``YYYY-MM-DD``, ``YYYY-MM``, or ``YYYY``)
        and re-formats with zero-padded day/month. Returns ``""`` if unknown.
        """
        v = (self.release_date or "").strip()
        if not v:
            return ""
        parts = v.split("-")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            y, m, d = parts
            if len(y) == 4 and 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
                return f"{int(d):02d}-{int(m):02d}-{y}"
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            y, m = parts
            if len(y) == 4 and 1 <= int(m) <= 12:
                return f"??-{int(m):02d}-{y}"
        if len(parts) == 1 and parts[0].isdigit() and len(parts[0]) == 4:
            return parts[0]
        return v

    def to_db_row(self) -> dict:
        """Return only fields that map to DB columns (excludes nothing extra)."""
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> GameRecord:
        """Build a record from a DB row dict (ignores unknown keys)."""
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in row.items() if k in valid})
