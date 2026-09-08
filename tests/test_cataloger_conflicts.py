"""Cross-disk conflict handling in Cataloger.scan_to_db (no network).

Simulates games living on two different disks by faking
``os.path.splitdrive`` so paths under a ``DiskD`` tree resolve to drive
``D:`` and ``DiskE`` trees to ``E:`` (the same pattern test_db.py uses for
its Windows disk tests).
"""
from __future__ import annotations

import os
import sys

import pytest

import playcache.models as _models
from playcache.cataloger import Cataloger
from playcache.config import Config
from playcache.db import Database
from playcache.models import GameRecord


class StubRAWG:
    name = "rawg"

    def __init__(self, config: Config):
        self.config = config

    def is_available(self) -> bool:
        return True

    def fetch(self, record: GameRecord, *, overrides: dict | None = None) -> GameRecord:
        record.game_name = record.game_name or "Hollow Knight"
        record.user_rating = "9/10"
        record.data_source = self.name
        record.fetch_status = "ok"
        record.fetch_message = ""
        return record


class UnavailableTGDB:
    name = "thegamesdb"

    def __init__(self, config: Config):
        self.config = config

    def is_available(self) -> bool:
        return False

    def fetch(self, record: GameRecord, *, overrides: dict | None = None) -> GameRecord:
        return record


def _fake_splitdrive(path: str) -> tuple[str, str]:
    low = path.lower().replace("/", "\\")
    if "diskd" in low:
        return ("D:", path)
    if "diske" in low:
        return ("E:", path)
    return ("", path)


@pytest.fixture()
def two_disks(tmp_path, monkeypatch):
    """Two game roots that GameRecord.disk resolves to D: and E:."""
    _models.clear_volume_label_cache()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(_models, "_volume_label", lambda root: "")
    monkeypatch.setattr(os.path, "splitdrive", _fake_splitdrive)
    root_d = tmp_path / "DiskD" / "Games"
    root_e = tmp_path / "DiskE" / "Games"
    root_d.mkdir(parents=True)
    root_e.mkdir(parents=True)
    return root_d, root_e


def _make_cataloger(tmp_path) -> tuple[Config, Database, Cataloger]:
    cfg = Config()
    cfg.db_path = str(tmp_path / "cat.db")
    db = Database(cfg.db_path)
    cat = Cataloger(cfg, db=db, rawg=StubRAWG(cfg), tgdb=UnavailableTGDB(cfg))
    return cfg, db, cat


def _hk_row(folder_path: str, **kw) -> GameRecord:
    base = {
        "folder_name": "Hollow Knight",
        "folder_path": folder_path,
        "game_name": "Hollow Knight",
        "platform": "PC",
        "store": "GOG",
        "fetch_status": "ok",
    }
    base.update(kw)
    return GameRecord(**base)


def test_conflict_prompted_for_new_folder_on_another_disk(two_disks, tmp_path):
    root_d, root_e = two_disks
    _cfg, db, cat = _make_cataloger(tmp_path)
    d_path = str(root_d / "Hollow Knight")
    db.upsert(_hk_row(d_path))
    (root_e / "Hollow Knight").mkdir()

    calls: list[tuple[str, str]] = []

    def handler(new_record: GameRecord, existing_record: GameRecord) -> str:
        calls.append((new_record.folder_path, existing_record.folder_path))
        return "both"

    summary = cat.scan_to_db(str(root_e), conflict_handler=handler)

    e_path = str((root_e / "Hollow Knight").resolve())
    assert calls == [(e_path, d_path)]
    assert summary["conflicts"] == 1
    assert summary["ok"] == 1
    assert summary["stored"] == 1
    assert db.count() == 2


def test_conflict_new_replaces_old_row_and_migrates_overrides(two_disks, tmp_path):
    root_d, root_e = two_disks
    _cfg, db, cat = _make_cataloger(tmp_path)
    d_path = str(root_d / "Hollow Knight")
    db.upsert(_hk_row(d_path))
    db.set_field(d_path, "user_rating", "10/10")
    (root_e / "Hollow Knight").mkdir()

    summary = cat.scan_to_db(str(root_e), conflict_handler=lambda n, o: "new")

    e_path = str((root_e / "Hollow Knight").resolve())
    assert db.get_by_path(d_path) is None
    stored = db.get_by_path(e_path)
    assert stored is not None
    assert stored.fetch_status == "ok"
    assert stored.user_rating == "10/10"
    assert stored.manual_overrides == '{"user_rating": "10/10"}'
    assert summary["conflicts"] == 1
    assert summary["stored"] == 1
    assert db.count() == 1


def test_conflict_old_stores_nothing(two_disks, tmp_path):
    root_d, root_e = two_disks
    _cfg, db, cat = _make_cataloger(tmp_path)
    d_path = str(root_d / "Hollow Knight")
    db.upsert(_hk_row(d_path, user_rating="8/10"))
    (root_e / "Hollow Knight").mkdir()

    summary = cat.scan_to_db(str(root_e), conflict_handler=lambda n, o: "old")

    e_path = str((root_e / "Hollow Knight").resolve())
    assert summary["conflicts"] == 1
    assert summary["stored"] == 0
    assert summary["skipped"] == 1
    assert db.count() == 1
    assert db.get_by_path(e_path) is None
    kept = db.get_by_path(d_path)
    assert kept is not None
    assert kept.user_rating == "8/10"
    assert kept.fetch_status == "ok"


def test_conflict_both_keeps_both_rows(two_disks, tmp_path):
    root_d, root_e = two_disks
    _cfg, db, cat = _make_cataloger(tmp_path)
    d_path = str(root_d / "Hollow Knight")
    db.upsert(_hk_row(d_path, user_rating="8/10"))
    (root_e / "Hollow Knight").mkdir()

    summary = cat.scan_to_db(str(root_e), conflict_handler=lambda n, o: "both")

    e_path = str((root_e / "Hollow Knight").resolve())
    assert db.count() == 2
    old = db.get_by_path(d_path)
    assert old is not None
    assert old.user_rating == "8/10"
    assert old.fetch_status == "ok"
    new = db.get_by_path(e_path)
    assert new is not None
    assert new.fetch_status == "ok"
    assert summary["conflicts"] == 1
    assert summary["stored"] == 1


def test_no_conflict_prompt_when_folder_path_already_in_db(two_disks, tmp_path):
    root_d, root_e = two_disks
    _cfg, db, cat = _make_cataloger(tmp_path)
    (root_d / "Hollow Knight").mkdir()
    d_path = str((root_d / "Hollow Knight").resolve())
    e_path = str((root_e / "Hollow Knight").resolve())
    db.upsert(_hk_row(d_path))
    db.upsert(_hk_row(e_path))

    calls: list[str] = []

    def handler(new_record: GameRecord, existing_record: GameRecord) -> str:
        calls.append(new_record.folder_path)
        return "both"

    summary = cat.scan_to_db(str(root_d), conflict_handler=handler)

    assert calls == []
    assert summary["conflicts"] == 0
    assert summary["skipped"] == 1
    assert summary["stored"] == 0
    assert db.count() == 2
    assert db.get_by_path(d_path).fetch_status == "ok"


def test_no_conflict_prompt_on_rescan_of_same_path(two_disks, tmp_path):
    root_d, root_e = two_disks
    _cfg, db, cat = _make_cataloger(tmp_path)
    (root_d / "Hollow Knight").mkdir()
    d_path = str((root_d / "Hollow Knight").resolve())
    e_path = str((root_e / "Hollow Knight").resolve())
    db.upsert(_hk_row(d_path))
    db.upsert(_hk_row(e_path))

    calls: list[str] = []

    def handler(new_record: GameRecord, existing_record: GameRecord) -> str:
        calls.append(new_record.folder_path)
        return "both"

    summary = cat.scan_to_db(str(root_d), rescan=True, conflict_handler=handler)

    assert calls == []
    assert summary["conflicts"] == 0
    assert summary["ok"] == 1
    assert summary["stored"] == 1
    assert db.count() == 2
    assert db.get_by_path(d_path).fetch_status == "ok"
