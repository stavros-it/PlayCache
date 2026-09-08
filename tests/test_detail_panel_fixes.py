"""Regression tests for detail-panel fixes.

Covers: "Open Website" must only launch http(s) URLs (API data can carry
file:// or custom schemes), the cover placeholder must leave "Loading…"
when the image fetch fails, Save must re-resolve the model row by
folder_path after a model reset (and skip the model update when the
record vanished), and the description editor must be a QPlainTextEdit
(its rich-text Ctrl+B/Ctrl+I bindings collided with the window-level
Backup/Restore shortcuts).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import warnings

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QPlainTextEdit

import playcache.gui.detail_panel as detail_panel_module
from playcache.db import Database
from playcache.gui.detail_panel import DetailPanel
from playcache.gui.table_model import GamesTableModel
from playcache.models import GameRecord

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def qapp():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = QApplication.instance() or QApplication([])
    yield app


class _FakeImageCache:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def request(self, url: str) -> None:
        self.requests.append(url)


class _StubMessageBox:
    @staticmethod
    def information(*args, **kwargs) -> None:
        return None

    @staticmethod
    def warning(*args, **kwargs) -> None:
        return None


@pytest.fixture
def stub_message_box(monkeypatch):
    monkeypatch.setattr(detail_panel_module, "QMessageBox", _StubMessageBox)


@pytest.fixture
def open_url_calls(monkeypatch):
    calls: list[QUrl] = []

    class _FakeDesktopServices:
        @staticmethod
        def openUrl(url: QUrl) -> None:
            calls.append(url)

    monkeypatch.setattr(detail_panel_module, "QDesktopServices", _FakeDesktopServices)
    return calls


def _make_panel(tmp_path) -> tuple[Database, GamesTableModel, DetailPanel, _FakeImageCache]:
    db = Database(str(tmp_path / "lib.db"))
    model = GamesTableModel([])
    image_cache = _FakeImageCache()
    panel = DetailPanel(db, model, image_cache)
    return db, model, panel, image_cache


def _record(name: str, **overrides) -> GameRecord:
    return GameRecord(
        folder_name=name, folder_path=f"/games/{name}", game_name=name, **overrides
    )


@pytest.mark.parametrize("url", ["file:///C:/Windows", "smb://host/share", "steam://run/123"])
def test_open_website_rejects_non_http_schemes(qapp, tmp_path, open_url_calls, url):
    db, model, panel, _ = _make_panel(tmp_path)
    record = _record("Alpha", website=url)
    db.upsert(record)
    panel.set_record(record, 0)

    assert not panel.website_btn.isEnabled()
    panel._open_website()
    assert open_url_calls == []


@pytest.mark.parametrize("url", ["https://example.com/games/alpha", "http://example.com"])
def test_open_website_allows_http_schemes(qapp, tmp_path, open_url_calls, url):
    db, model, panel, _ = _make_panel(tmp_path)
    record = _record("Alpha", website=url)
    db.upsert(record)
    panel.set_record(record, 0)

    assert panel.website_btn.isEnabled()
    panel._open_website()
    assert len(open_url_calls) == 1
    assert open_url_calls[0].toString() == url


def test_cover_shows_no_cover_when_image_load_fails(qapp, tmp_path):
    db, model, panel, image_cache = _make_panel(tmp_path)
    record = _record("Alpha", cover_url="https://example.com/cover.jpg")
    db.upsert(record)
    panel.set_record(record, 0)

    assert panel.cover_label.text() == "Loading…"
    assert image_cache.requests == ["https://example.com/cover.jpg"]

    panel.on_image_loaded("https://example.com/cover.jpg", None)
    assert panel.cover_label.text() == "No cover"

    panel.set_record(record, 0)
    assert panel.cover_label.text() == "Loading…"
    panel.on_image_loaded("https://elsewhere.example/x.jpg", None)
    assert panel.cover_label.text() == "Loading…"


def test_description_editor_is_plain_text(qapp, tmp_path, stub_message_box):
    db, model, panel, _ = _make_panel(tmp_path)
    record = _record("Alpha")
    db.upsert(record)
    model.set_records([record])
    panel.set_record(record, 0)

    editor = panel._inputs["short_description"]
    assert isinstance(editor, QPlainTextEdit)
    editor.setPlainText("A fine game indeed")
    panel._save()

    assert db.get_by_path("/games/Alpha").short_description == "A fine game indeed"
    assert model.record_at(0).short_description == "A fine game indeed"


def test_save_after_model_reset_updates_the_correct_row(qapp, tmp_path, stub_message_box):
    db, model, panel, _ = _make_panel(tmp_path)
    record_a = _record("Alpha")
    record_b = _record("Beta")
    db.upsert(record_a)
    db.upsert(record_b)
    model.set_records([record_a, record_b])
    panel.set_record(record_a, 0)
    panel._inputs["user_rating"].setText("9/10")

    fresh = db.all_records()
    model.set_records(list(reversed(fresh)))

    panel._save()

    assert db.get_by_path("/games/Alpha").user_rating == "9/10"
    assert model.record_at(0).folder_path == "/games/Beta"
    assert model.record_at(1).folder_path == "/games/Alpha"
    assert model.record_at(1).user_rating == "9/10"
    assert panel._row == 1


def test_save_skips_model_update_when_record_left_the_model(qapp, tmp_path, stub_message_box):
    db, model, panel, _ = _make_panel(tmp_path)
    record_a = _record("Alpha")
    record_b = _record("Beta")
    db.upsert(record_a)
    db.upsert(record_b)
    model.set_records([record_a, record_b])
    panel.set_record(record_a, 0)
    panel._inputs["user_rating"].setText("8/10")

    model.set_records([record_b])

    panel._save()

    assert db.get_by_path("/games/Alpha").user_rating == "8/10"
    assert model.rowCount() == 1
    assert model.record_at(0).folder_path == "/games/Beta"
    assert model.record_at(0).user_rating == ""
    assert panel._row == -1
