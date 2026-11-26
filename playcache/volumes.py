"""Volume identity for catalogued paths, independent of drive letters.

Every scanned game stores the ID of the volume it lives on (Windows volume
serial number, Linux filesystem UUID) and its path inside that volume. When
the same disk later shows up under another drive letter or mount point (a
new PC, a different USB port), the game's path is rebuilt from the volume's
current root instead of treating it as a new game.

IDs are normalised so one NTFS/exFAT/FAT disk gets the same ID on Windows
and Linux: Linux reports a 16-hex (NTFS) or ``XXXX-XXXX`` (FAT/exFAT) UUID
whose last 8 hex digits are the Windows serial number.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_id_cache: dict[str, str] = {}


def clear_cache() -> None:
    """Forget cached volume IDs (call when drives may have been swapped)."""
    _id_cache.clear()


def normalize_id(raw: str) -> str:
    """Canonical volume ID: upper-case hex, Windows-serial length when possible."""
    s = re.sub(r"[^0-9A-Fa-f]", "", raw or "").upper()
    if len(s) in (8, 16):
        return s[-8:]
    return s


def _windows_serial(root: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import ctypes

        serial = ctypes.c_uint32(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), None, 0, ctypes.byref(serial), None, None, None, 0,
        )
    except (OSError, AttributeError, ValueError):
        return ""
    return f"{serial.value:08X}" if ok and serial.value else ""


def _linux_uuid(mount_point: str) -> str:
    from .models import _load_mounts

    by_uuid = Path("/dev/disk/by-uuid")
    for dev, mp, _fs in _load_mounts():
        if mp != mount_point or not dev.startswith("/dev/"):
            continue
        real = os.path.realpath(dev)
        try:
            for entry in by_uuid.iterdir():
                try:
                    if os.path.realpath(entry) == real:
                        return entry.name
                except OSError:
                    continue
        except OSError:
            return ""
    return ""


def volume_root(path: str) -> str:
    """Root of the volume holding ``path`` (``I:\\`` or a mount point), or ``""``."""
    if not path or path.startswith("/manual/"):
        return ""
    if sys.platform == "win32":
        drive, _ = os.path.splitdrive(path)
        if not drive or drive.startswith(("\\\\", "//")):
            return ""
        return drive + "\\"
    from .models import _linux_mount_for

    return _linux_mount_for(path)


def root_id(root: str) -> str:
    """Normalised ID of the volume mounted at ``root`` (cached), or ``""``."""
    if root in _id_cache:
        return _id_cache[root]
    raw = _windows_serial(root) if sys.platform == "win32" else _linux_uuid(root)
    vid = normalize_id(raw)
    _id_cache[root] = vid
    return vid


def locate(path: str) -> tuple[str, str]:
    """``(volume_id, path inside the volume)`` for an existing path.

    The inner path uses ``/`` separators and no leading slash. Returns
    ``("", "")`` for manual entries, network shares and unknown volumes.
    """
    root = volume_root(path)
    if not root:
        return "", ""
    vid = root_id(root)
    if not vid:
        return "", ""
    try:
        inner = os.path.relpath(path, root)
    except ValueError:
        return "", ""
    inner = inner.replace("\\", "/")
    if inner == ".":
        inner = ""
    if inner == ".." or inner.startswith("../"):
        return "", ""
    return vid, inner


def _mount_roots() -> list[str]:
    if sys.platform == "win32":
        listdrives = getattr(os, "listdrives", None)
        if listdrives is None:
            return [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]
        try:
            return list(listdrives())
        except OSError:
            return []
    from .models import _load_mounts

    return [mp for dev, mp, _fs in _load_mounts() if dev.startswith("/dev/")]


def current_roots() -> dict[str, str]:
    """Map of volume ID -> current root for every mounted volume."""
    roots: dict[str, str] = {}
    for root in _mount_roots():
        vid = root_id(root)
        if vid and vid not in roots:
            roots[vid] = root
    return roots


def resolve(volume_id: str, inner_path: str, roots: dict[str, str]) -> str | None:
    """Current absolute path of ``inner_path`` on volume ``volume_id``, or ``None``."""
    root = roots.get(normalize_id(volume_id))
    if not root:
        return None
    parts = [p for p in inner_path.split("/") if p]
    return os.path.join(root, *parts) if parts else root


def swap_drive_letter(path: str, roots: list[str] | None = None) -> str | None:
    """Same path on another drive letter, when exactly one drive holds it.

    Fallback for catalog rows that carry no volume ID (backups made before
    volume IDs existed). Windows-style paths only.
    """
    if not re.match(r"^[A-Za-z]:[\\/]", path):
        return None
    rest = path[3:]
    hits = []
    for root in roots if roots is not None else _mount_roots():
        if root[:1].upper() == path[:1].upper():
            continue
        candidate = os.path.join(root, rest)
        if os.path.exists(candidate):
            hits.append(candidate)
    return hits[0] if len(hits) == 1 else None
