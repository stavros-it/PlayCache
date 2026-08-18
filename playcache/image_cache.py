"""Async image fetcher with on-disk cache for game cover/background images.

Uses Qt's QNetworkAccessManager so downloads happen off the GUI thread without
spawning extra Python threads. Cached files live under ``<db_dir>/covers/``
and are keyed by a hash of the URL so duplicate URLs aren't re-downloaded.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

log = logging.getLogger(__name__)

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")


class ImageCache(QObject):
    """Lazy-loads images from the network with on-disk caching.

    Usage:
        cache = ImageCache(parent=window)
        cache.image_loaded.connect(on_pixmap)   # on_pixmap(url, QPixmap)
        cache.request(url)                       # fire-and-forget; emits when ready
    """

    image_loaded = Signal(str, object)   # url, QPixmap (or None on failure)

    def __init__(self, cache_dir: str | None = None, parent: QObject | None = None):
        super().__init__(parent)
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            base = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
            self.cache_dir = Path(base or ".") / "playcache_covers"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._nam = QNetworkAccessManager(self)
        self._pending: dict[str, QNetworkReply] = {}

    # ------------------------------------------------------------------ #
    def request(self, url: str) -> None:
        """Asynchronously load ``url``; emit ``image_loaded`` when done.

        Serves from disk cache if present; otherwise downloads once and caches.
        If the URL is already being fetched, the in-flight reply will emit
        ``image_loaded`` for all callers — no second request is made.

        Only ``http://`` and ``https://`` URLs are fetched. Other schemes
        (notably ``file://``) are rejected to prevent local-file reads via
        malicious API responses.
        """
        if not url:
            return

        lower = url.lower()
        if not lower.startswith(("http://", "https://")):
            log.debug("Rejecting non-http image URL: %s", url)
            self.image_loaded.emit(url, None)
            return

        cached_path = self._path_for(url)
        if cached_path.is_file():
            pixmap = QPixmap(str(cached_path))
            if not pixmap.isNull():
                self.image_loaded.emit(url, pixmap)
                return
            try:
                cached_path.unlink()
            except OSError:
                pass

        if url in self._pending:
            return

        req = QNetworkRequest(QUrl(url))
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        req.setTransferTimeout(15_000)
        reply = self._nam.get(req)
        self._pending[url] = reply
        reply.finished.connect(lambda r=reply, u=url: self._on_finished(r, u))

    # ------------------------------------------------------------------ #
    def _on_finished(self, reply: QNetworkReply, url: str) -> None:
        self._pending.pop(url, None)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                log.debug("image fetch failed for %s: %s", url, reply.error())
                self.image_loaded.emit(url, None)
                return
            data = reply.readAll()
            if not data:
                self.image_loaded.emit(url, None)
                return
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            if pixmap.isNull():
                log.debug("image data for %s is not a valid image", url)
                self.image_loaded.emit(url, None)
                return
            cached_path = self._path_for(url)
            tmp_path = cached_path.with_suffix(cached_path.suffix + ".tmp")
            try:
                tmp_path.write_bytes(bytes(data))
                os.replace(tmp_path, cached_path)
            except OSError as e:
                log.warning("Could not cache image to %s: %s", cached_path, e)
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
            self.image_loaded.emit(url, pixmap)
        finally:
            reply.deleteLater()

    # ------------------------------------------------------------------ #
    def _path_for(self, url: str) -> Path:
        ext = ""
        clean = url.rsplit("#", 1)[0].rsplit("?", 1)[0].lower()
        for suffix in _IMAGE_EXTS:
            if clean.endswith(suffix):
                ext = suffix
                break
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / f"{digest}{ext}"

    def clear(self) -> int:
        """Delete every cached file. Returns the number of files removed.

        Aborts all in-flight requests first so they don't re-write files
        after clearing.
        """
        for reply in list(self._pending.values()):
            reply.abort()
            reply.deleteLater()
        self._pending.clear()

        count = 0
        for f in self.cache_dir.rglob("*"):
            if f.is_file():
                try:
                    f.unlink()
                    count += 1
                except OSError as e:
                    log.debug("Could not delete %s: %s", f, e)
        return count
