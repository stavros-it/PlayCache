"""Regression tests for the ImageCache security/robustness fixes.

Covers the 2026-08-18 behaviors: non-http(s) URL schemes (notably
``file://``) are rejected without issuing a network request, corrupt cached
files are unlinked instead of served, ``clear()`` aborts in-flight replies,
and duplicate in-flight URLs are deduplicated. The network layer is replaced
with fakes at the ``QNetworkAccessManager`` boundary, so no test touches
the network.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

from playcache.image_cache import ImageCache


class _FakeSignal:
    def __init__(self) -> None:
        self.slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self.slots.append(slot)


class _FakeReply:
    def __init__(self) -> None:
        self.finished = _FakeSignal()
        self.aborted = False
        self.deleted = False

    def abort(self) -> None:
        self.aborted = True

    def deleteLater(self) -> None:
        self.deleted = True


class _RecordingNam:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def get(self, request: Any) -> _FakeReply:
        self.requests.append(request)
        return _FakeReply()


@pytest.fixture()
def image_cache(qapp: QApplication, tmp_path: Path) -> ImageCache:
    instance = ImageCache(cache_dir=str(tmp_path / "covers"))
    instance._nam = _RecordingNam()
    return instance


def test_non_http_schemes_rejected_without_request(image_cache: ImageCache) -> None:
    emitted: list[tuple[str, Any]] = []
    image_cache.image_loaded.connect(lambda url, pixmap: emitted.append((url, pixmap)))

    image_cache.request("file:///etc/passwd")
    image_cache.request("ftp://example.test/cover.png")
    image_cache.request("data:image/png;base64,AAAA")

    assert image_cache._nam.requests == []
    assert image_cache._pending == {}
    assert emitted == [
        ("file:///etc/passwd", None),
        ("ftp://example.test/cover.png", None),
        ("data:image/png;base64,AAAA", None),
    ]
    assert list(image_cache.cache_dir.iterdir()) == []


def test_empty_url_ignored(image_cache: ImageCache) -> None:
    emitted: list[tuple[str, Any]] = []
    image_cache.image_loaded.connect(lambda url, pixmap: emitted.append((url, pixmap)))

    image_cache.request("")

    assert image_cache._nam.requests == []
    assert image_cache._pending == {}
    assert emitted == []


def test_valid_cached_image_served_without_request(image_cache: ImageCache) -> None:
    url = "https://example.test/covers/game.png"
    cached = image_cache._path_for(url)
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    assert image.save(str(cached), "PNG")

    emitted: list[tuple[str, Any]] = []
    image_cache.image_loaded.connect(lambda url, pixmap: emitted.append((url, pixmap)))

    image_cache.request(url)

    assert image_cache._nam.requests == []
    assert len(emitted) == 1
    assert emitted[0][0] == url
    pixmap = emitted[0][1]
    assert isinstance(pixmap, QPixmap)
    assert not pixmap.isNull()


def test_corrupt_cached_file_unlinked_and_refetched(image_cache: ImageCache) -> None:
    url = "https://example.test/covers/broken.png"
    corrupt = image_cache._path_for(url)
    corrupt.write_bytes(b"garbage bytes, definitely not an image")

    emitted: list[tuple[str, Any]] = []
    image_cache.image_loaded.connect(lambda url, pixmap: emitted.append((url, pixmap)))

    image_cache.request(url)

    assert not corrupt.exists()
    assert len(image_cache._nam.requests) == 1
    assert url in image_cache._pending
    assert emitted == []
    assert list(image_cache.cache_dir.glob("*.tmp")) == []


def test_in_flight_requests_deduplicated(image_cache: ImageCache) -> None:
    url = "https://example.test/covers/dedup.png"

    image_cache.request(url)
    image_cache.request(url)

    assert len(image_cache._nam.requests) == 1
    assert list(image_cache._pending) == [url]


def test_clear_aborts_pending_and_removes_cached_files(image_cache: ImageCache) -> None:
    url_a = "https://example.test/covers/a.png"
    url_b = "https://example.test/covers/b.png"
    reply_a = _FakeReply()
    reply_b = _FakeReply()
    image_cache._pending[url_a] = reply_a
    image_cache._pending[url_b] = reply_b
    image_cache._path_for(url_a).write_bytes(b"cached-a")
    image_cache._path_for(url_b).write_bytes(b"cached-b")

    removed = image_cache.clear()

    assert removed == 2
    assert image_cache._pending == {}
    assert reply_a.aborted and reply_a.deleted
    assert reply_b.aborted and reply_b.deleted
    assert not image_cache._path_for(url_a).exists()
    assert not image_cache._path_for(url_b).exists()
