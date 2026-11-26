"""Cover cache file naming and downloads shared by the GUI cache and backups."""
from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
MAX_COVER_BYTES = 32 * 1024 * 1024


def cover_file_name(url: str) -> str:
    """Cache file name for a cover URL: a hash of the URL plus its extension."""
    ext = ""
    clean = url.rsplit("#", 1)[0].rsplit("?", 1)[0].lower()
    for suffix in IMAGE_EXTS:
        if clean.endswith(suffix):
            ext = suffix
            break
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return f"{digest}{ext}"


def is_fetchable(url: str | None) -> bool:
    return bool(url) and url.lower().startswith(("http://", "https://"))


def missing_covers(urls: Iterable[str | None], covers_dir: str | Path) -> list[str]:
    """Cover URLs that have no cached file in ``covers_dir`` yet (unique, ordered)."""
    folder = Path(covers_dir)
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if not url or not is_fetchable(url) or url in seen:
            continue
        seen.add(url)
        if not (folder / cover_file_name(url)).is_file():
            out.append(url)
    return out


def write_cover(covers_dir: str | Path, url: str, data: bytes) -> Path:
    """Store ``data`` as the cached cover for ``url`` (atomic write)."""
    folder = Path(covers_dir)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / cover_file_name(url)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    except OSError:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    return dest


def download_cover(url: str, covers_dir: str | Path, *, session=None, timeout: int = 15) -> bool:
    """Download one cover into the cache. Returns True when a file was stored."""
    if not is_fetchable(url):
        return False
    import requests

    getter = session or requests
    try:
        resp = getter.get(url, timeout=timeout)
    except requests.RequestException as e:
        log.debug("Cover download failed for %s: %s", url, e)
        return False
    if resp.status_code != 200:
        return False
    data = resp.content or b""
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if not data or len(data) > MAX_COVER_BYTES or (ctype and not ctype.startswith("image/")):
        return False
    try:
        write_cover(covers_dir, url, data)
    except OSError as e:
        log.warning("Could not cache cover %s: %s", url, e)
        return False
    return True
