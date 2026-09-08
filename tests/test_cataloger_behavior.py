"""Behavioral regression tests for Cataloger.scan_to_db / Cataloger._fetch.

Covers: cancellation via the progress callback, only_missing semantics,
provider="rawg" quota isolation, rescan seeding of stored IDs/name, and
error-path preservation of existing rows. All API clients are fakes.
"""
from __future__ import annotations

import pytest

import playcache.cataloger as cataloger_module
from playcache.cataloger import Cataloger
from playcache.config import Config
from playcache.db import Database
from playcache.models import GameRecord


class RecordingRAWG:
    """Mimics RAWGClient.fetch's ID-vs-search decision and records calls."""

    name = "rawg"

    def __init__(self, config: Config):
        self.config = config
        self.fetch_by_id_calls: list[int] = []
        self.search_calls: list[str] = []
        self.overrides_seen: list[dict | None] = []

    def is_available(self) -> bool:
        return True

    def fetch(self, record: GameRecord, *, overrides: dict | None = None) -> GameRecord:
        self.overrides_seen.append(overrides)
        name_overridden = bool(overrides and "game_name" in overrides)
        if record.rawg_id and not name_overridden:
            self.fetch_by_id_calls.append(record.rawg_id)
        else:
            self.search_calls.append(record.game_name or record.folder_name)
        record.game_name = record.game_name or "Hollow Knight"
        record.user_rating = "9/10"
        record.data_source = self.name
        record.fetch_status = "ok"
        record.fetch_message = ""
        return record


class ExplodingRAWG:
    name = "rawg"

    def __init__(self, config: Config):
        self.config = config

    def is_available(self) -> bool:
        return True

    def fetch(self, record: GameRecord, *, overrides: dict | None = None) -> GameRecord:
        raise RuntimeError(
            "RAWG request failed after 3 retries: "
            "MaxRetryError url=/api/games?search=Hollow+Knight&key=SECRET"
        )


class UnavailableTGDB:
    name = "thegamesdb"

    def __init__(self, config: Config):
        self.config = config

    def is_available(self) -> bool:
        return False

    def fetch(self, record: GameRecord, *, overrides: dict | None = None) -> GameRecord:
        return record


class CountingTGDB:
    name = "thegamesdb"

    def __init__(self, config: Config):
        self.config = config
        self.fetch_calls = 0

    def is_available(self) -> bool:
        return True

    def fetch(self, record: GameRecord, *, overrides: dict | None = None) -> GameRecord:
        self.fetch_calls += 1
        record.thegamesdb_id = 9999
        record.esrb_rating = "T - Teen"
        record.fetch_status = "ok"
        record.data_source = self.name
        return record


def _make_cataloger(tmp_path, rawg, tgdb) -> tuple[Config, Database, Cataloger]:
    cfg = Config()
    cfg.db_path = str(tmp_path / "t.db")
    db = Database(cfg.db_path)
    cat = Cataloger(cfg, db=db, rawg=rawg(cfg), tgdb=tgdb(cfg))
    return cfg, db, cat


def _cancel_progress(idx: int, total: int, record, message: str) -> None:
    raise InterruptedError("scan cancelled")


# --------------------------------------------------------------------- #
# Cancellation (InterruptedError from the progress callback)
# --------------------------------------------------------------------- #
def test_cancel_mid_scan_propagates_without_error_row(tmp_path):
    _cfg, db, cat = _make_cataloger(tmp_path, RecordingRAWG, UnavailableTGDB)
    (tmp_path / "Hollow Knight").mkdir()
    (tmp_path / "Deep Rock Galactic").mkdir()

    with pytest.raises(InterruptedError):
        cat.scan_to_db(str(tmp_path), progress=_cancel_progress)

    assert db.count() == 1
    rec = db.all_records()[0]
    assert rec.fetch_status == "ok"
    assert rec.fetch_message == ""


def test_cancelled_dry_run_writes_nothing(tmp_path):
    _cfg, db, cat = _make_cataloger(tmp_path, RecordingRAWG, UnavailableTGDB)
    (tmp_path / "Hollow Knight").mkdir()

    with pytest.raises(InterruptedError):
        cat.scan_to_db(str(tmp_path), dry_run=True, progress=_cancel_progress)

    assert db.count() == 0


def test_cancel_on_already_catalogued_skip_keeps_row_ok(tmp_path):
    _cfg, db, cat = _make_cataloger(tmp_path, RecordingRAWG, UnavailableTGDB)
    game_dir = tmp_path / "Hollow Knight"
    game_dir.mkdir()
    path = str(game_dir.resolve())
    db.upsert(
        GameRecord(
            folder_name="Hollow Knight", folder_path=path, game_name="Hollow Knight",
            platform="PC", store="GOG", user_rating="9/10",
            data_source="rawg", fetch_status="ok",
        )
    )

    with pytest.raises(InterruptedError):
        cat.scan_to_db(str(tmp_path), progress=_cancel_progress)

    rec = db.get_by_path(path)
    assert rec is not None
    assert rec.fetch_status == "ok"
    assert rec.fetch_message == ""
    assert rec.user_rating == "9/10"


# --------------------------------------------------------------------- #
# only_missing semantics
# --------------------------------------------------------------------- #
def _two_catalogued_games(db: Database, tmp_path) -> tuple[str, str]:
    (tmp_path / "Hollow Knight").mkdir()
    (tmp_path / "Deep Rock Galactic").mkdir()
    hk_path = str((tmp_path / "Hollow Knight").resolve())
    drg_path = str((tmp_path / "Deep Rock Galactic").resolve())
    for name, path in (("Hollow Knight", hk_path), ("Deep Rock Galactic", drg_path)):
        db.upsert(
            GameRecord(
                folder_name=name, folder_path=path, game_name=name,
                platform="PC", store="GOG", user_rating="9/10",
                data_source="rawg", fetch_status="ok",
            )
        )
    return hk_path, drg_path


def test_only_missing_checked_skips_ok_rows_but_retries_not_found(tmp_path):
    _cfg, db, cat = _make_cataloger(tmp_path, RecordingRAWG, UnavailableTGDB)
    hk_path, drg_path = _two_catalogued_games(db, tmp_path)
    drg = db.get_by_path(drg_path)
    drg.fetch_status = "not_found"
    db.upsert(drg)

    summary = cat.scan_to_db(str(tmp_path), only_missing=True)

    assert summary["skipped"] == 1
    assert summary["ok"] == 1
    assert summary["stored"] == 1
    assert db.get_by_path(hk_path).fetch_status == "ok"
    assert db.get_by_path(drg_path).fetch_status == "ok"


def test_only_missing_unchecked_refetches_not_found_and_ok_rows(tmp_path):
    _cfg, db, cat = _make_cataloger(tmp_path, RecordingRAWG, UnavailableTGDB)
    hk_path, drg_path = _two_catalogued_games(db, tmp_path)
    drg = db.get_by_path(drg_path)
    drg.fetch_status = "not_found"
    db.upsert(drg)

    summary = cat.scan_to_db(str(tmp_path), only_missing=False)

    assert summary["skipped"] == 0
    assert summary["ok"] == 2
    assert summary["stored"] == 2
    assert db.get_by_path(hk_path).fetch_status == "ok"
    assert db.get_by_path(drg_path).fetch_status == "ok"


# --------------------------------------------------------------------- #
# provider="rawg" must not touch TheGamesDB
# --------------------------------------------------------------------- #
def test_provider_rawg_makes_no_tgdb_calls(tmp_path):
    _cfg, db, cat = _make_cataloger(tmp_path, RecordingRAWG, CountingTGDB)

    rec = GameRecord(
        folder_name="Hollow Knight", folder_path="/games/Hollow Knight",
        game_name="Hollow Knight",
    )
    out = cat._fetch(rec, provider="rawg")
    assert out.fetch_status == "ok"
    assert out.data_source == "rawg"
    assert out.esrb_rating == ""
    assert cat.tgdb.fetch_calls == 0

    rec2 = GameRecord(
        folder_name="Deep Rock Galactic", folder_path="/games/Deep Rock Galactic",
        game_name="Deep Rock Galactic",
    )
    out2 = cat._fetch(rec2, provider="auto")
    assert out2.fetch_status == "ok"
    assert out2.esrb_rating == "T - Teen"
    assert cat.tgdb.fetch_calls == 1


# --------------------------------------------------------------------- #
# Rescan seeds stored IDs / name and passes overrides
# --------------------------------------------------------------------- #
def test_rescan_fetches_by_stored_id_and_passes_overrides(tmp_path):
    _cfg, db, cat = _make_cataloger(tmp_path, RecordingRAWG, UnavailableTGDB)
    rawg = cat.rawg
    game_dir = tmp_path / "Hollow Knight"
    game_dir.mkdir()
    path = str(game_dir.resolve())
    db.upsert(
        GameRecord(
            folder_name="Hollow Knight", folder_path=path, game_name="Hollow Knight",
            platform="PC", store="GOG", rawg_id=11226,
            data_source="rawg", fetch_status="ok",
        )
    )
    db.set_field(path, "user_rating", "10/10")

    summary = cat.scan_to_db(str(tmp_path), rescan=True)

    assert rawg.fetch_by_id_calls == [11226]
    assert rawg.search_calls == []
    assert rawg.overrides_seen == [{"user_rating": "10/10"}]
    rec = db.get_by_path(path)
    assert rec is not None
    assert rec.fetch_status == "ok"
    assert rec.user_rating == "10/10"
    assert rec.rawg_id == 11226
    assert rec.manual_overrides == '{"user_rating": "10/10"}'
    assert summary["ok"] == 1


def test_rescan_without_ids_searches_by_stored_name_not_folder_name(tmp_path):
    _cfg, db, cat = _make_cataloger(tmp_path, RecordingRAWG, UnavailableTGDB)
    rawg = cat.rawg
    game_dir = tmp_path / "Hollow Knight Deluxe"
    game_dir.mkdir()
    path = str(game_dir.resolve())
    db.upsert(
        GameRecord(
            folder_name="Hollow Knight Deluxe", folder_path=path,
            game_name="Hollow Knight", platform="PC", store="GOG",
            data_source="rawg", fetch_status="ok",
        )
    )

    cat.scan_to_db(str(tmp_path), rescan=True)

    assert rawg.search_calls == ["Hollow Knight"]
    assert rawg.fetch_by_id_calls == []
    rec = db.get_by_path(path)
    assert rec is not None
    assert rec.fetch_status == "ok"


# --------------------------------------------------------------------- #
# Unexpected exceptions must not wipe existing rows
# --------------------------------------------------------------------- #
def test_fetch_exception_preserves_existing_row_metadata_and_overrides(tmp_path):
    _cfg, db, cat = _make_cataloger(tmp_path, ExplodingRAWG, UnavailableTGDB)
    game_dir = tmp_path / "Hollow Knight"
    game_dir.mkdir()
    path = str(game_dir.resolve())
    db.upsert(
        GameRecord(
            folder_name="Hollow Knight", folder_path=path, game_name="Hollow Knight",
            platform="PC", store="GOG", user_rating="9/10",
            short_description="A beautifully crafted action-adventure.",
            developer="Team Cherry", publisher="Team Cherry",
            rawg_id=11226, release_date="2017-02-24",
            data_source="rawg", fetch_status="ok",
        )
    )
    db.set_field(path, "user_rating", "10/10")

    summary = cat.scan_to_db(str(tmp_path), rescan=True)

    rec = db.get_by_path(path)
    assert rec is not None
    assert rec.fetch_status == "error"
    assert "scan error:" in rec.fetch_message
    assert "key=SECRET" in rec.fetch_message
    assert rec.developer == "Team Cherry"
    assert rec.publisher == "Team Cherry"
    assert rec.short_description == "A beautifully crafted action-adventure."
    assert rec.release_date == "2017-02-24"
    assert rec.rawg_id == 11226
    assert rec.store == "GOG"
    assert rec.user_rating == "10/10"
    assert rec.manual_overrides == '{"user_rating": "10/10"}'
    assert summary["error"] == 1
    assert summary["stored"] == 1


# --------------------------------------------------------------------- #
# skip_folders config wiring
# --------------------------------------------------------------------- #
def test_scan_to_db_passes_skip_folders_to_scanner(tmp_path, monkeypatch):
    cfg = Config()
    cfg.db_path = str(tmp_path / "t.db")
    cfg.skip_folders = ("Junk", "DOCS")
    db = Database(cfg.db_path)
    cat = Cataloger(cfg, db=db, rawg=RecordingRAWG(cfg), tgdb=UnavailableTGDB(cfg))

    seen: dict = {}

    def fake_scan_games(root, recursive=False, skip=None):
        seen["root"] = root
        seen["recursive"] = recursive
        seen["skip"] = skip
        return iter([])

    monkeypatch.setattr(cataloger_module, "scan_games", fake_scan_games)

    cat.scan_to_db(str(tmp_path), recursive=True)

    assert seen["root"] == str(tmp_path)
    assert seen["recursive"] is True
    assert seen["skip"] == {"junk", "docs"}
