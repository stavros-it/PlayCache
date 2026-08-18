"""Canonical data record passed between scanner, API clients, and the database."""
from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

_drive_label_cache: dict[str, str] = {}
_mount_cache: list[tuple[str, str, str]] | None = None

_INT_FIELDS = {"rawg_id", "thegamesdb_id", "metacritic_score"}


def clear_volume_label_cache() -> None:
    """Clear the cached volume labels.

    Call this when a drive may have been swapped (e.g. USB hot-plug) so the
    next ``disk`` / ``stats()`` call re-queries the OS for fresh labels.
    """
    _drive_label_cache.clear()


def _load_mounts() -> list[tuple[str, str, str]]:
    """Read /proc/mounts and return [(device, mount_point, fs_type), ...].

    Sorted by mount-point length descending so the longest-prefix match is
    found first. Cached for the process lifetime.
    """
    global _mount_cache
    if _mount_cache is not None:
        return _mount_cache
    mounts: list[tuple[str, str, str]] = []
    try:
        with open("/proc/mounts", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 3:
                    dev, mp, fs = parts[0], parts[1], parts[2]
                    mp = os.path.normpath(mp)
                    mounts.append((dev, mp, fs))
        mounts.sort(key=lambda x: len(x[1]), reverse=True)
    except (OSError, UnicodeDecodeError):
        pass
    _mount_cache = mounts
    return mounts


def _linux_mount_for(path: str) -> str:
    """Return the mount point that contains ``path`` (e.g. ``/home`` or ``/``).

    Walks up the path tree until the device number (``st_dev``) changes,
    which identifies the mount boundary. Falls back to the longest
    mount-point-prefix from /proc/mounts.
    """
    resolved = os.path.realpath(path)
    try:
        target_dev = os.stat(resolved).st_dev
    except OSError:
        target_dev = 0

    current = resolved
    while current and current != os.sep:
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        try:
            parent_dev = os.stat(parent).st_dev
        except OSError:
            break
        if parent_dev != target_dev:
            return current
        current = parent

    for _dev, mp, _fs in _load_mounts():
        if resolved == mp or resolved.startswith(mp + os.sep):
            return mp

    return current if current and current != os.sep else os.sep


def _linux_volume_label(mount_point: str) -> str:
    """Get the filesystem label for a Linux mount point.

    Tries /dev/disk/by-label/ symlinks first (no subprocess), then falls
    back to reading the device from /proc/mounts and checking by-label.
    Returns the mount point itself if no label is found (more useful than
    an empty string for grouping).
    """
    for dev, mp, _fs in _load_mounts():
        if mp == mount_point and dev.startswith("/dev/"):
            base = os.path.basename(dev)
            by_label = Path("/dev/disk/by-label")
            if by_label.is_dir():
                try:
                    for entry in by_label.iterdir():
                        try:
                            if os.path.realpath(entry) == dev:
                                return entry.name
                        except OSError:
                            continue
                except OSError:
                    pass
            return base
    return mount_point


def _volume_label(drive_root: str) -> str:
    """Get the volume label for a drive root. Cached.

    On Windows, ``drive_root`` is a drive letter root (e.g. ``C:\\``) and
    the label is fetched via the Win32 ``GetVolumeInformationW`` API.

    On Linux, ``drive_root`` is a mount point (e.g. ``/home`` or ``/``) and
    the label is resolved from /dev/disk/by-label or /proc/mounts.

    Returns an empty string if the label can't be determined.
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
    elif sys.platform.startswith("linux"):
        label = _linux_volume_label(drive_root)
    _drive_label_cache[drive_root] = label
    return label


@dataclass
class GameRecord:
    # Core identity (from filesystem)
    folder_name: str = ""
    folder_path: str = ""

    # Catalog columns (match the 6-column reference Excel layout)
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

        - **Windows**: returns the volume label (e.g. ``"TOSHIBA 2TB"``) when
          available, falling back to the drive letter (``"D:"``). UNC paths
          (``\\\\server\\share\\...``) are grouped by ``\\\\server\\share``.
        - **Linux**: returns the filesystem label or device name for the mount
          point containing the path (e.g. ``"nvme0n1p2"`` or ``"Games"``).
          Falls back to the mount point (e.g. ``/mnt/games``).
        - **Manual entries** (``/manual/...`` paths) return ``"Manual"``.
        """
        path = self.folder_path or ""
        if not path or path.startswith("/manual/"):
            return "Manual"
        if sys.platform == "win32":
            drive, _ = os.path.splitdrive(path)
            if drive:
                root = f"{drive}{os.sep}"
                label = _volume_label(root)
                return label or drive
            if path.startswith("\\\\"):
                parts = path.split("\\")
                if len(parts) >= 4 and parts[2]:
                    return f"\\\\{parts[2]}\\{parts[3]}"
            return "—"
        mount = _linux_mount_for(path)
        label = _volume_label(mount)
        return label or mount

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
        """Build a record from a DB row dict (ignores unknown keys).

        Coerces known integer fields (``rawg_id``, ``thegamesdb_id``,
        ``metacritic_score``) to ``int | None`` so SQLite's dynamic typing
        can't silently store a string where an int is expected.
        """
        valid = {f.name for f in fields(cls)}
        kwargs: dict = {}
        for k, v in row.items():
            if k not in valid:
                continue
            if k in _INT_FIELDS and v is not None:
                try:
                    kwargs[k] = int(v)
                except (TypeError, ValueError):
                    kwargs[k] = None
            else:
                kwargs[k] = v
        return cls(**kwargs)
