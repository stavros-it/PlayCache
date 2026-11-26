"""Full backups (covers + settings) and drive-letter-independent restore (no network)."""
from __future__ import annotations

import configparser
import gzip
import json
import os
import zipfile
from dataclasses import replace

import pytest

from playcache import backup, volumes
from playcache.backup import FORMAT_VERSION, export_backup, import_backup
from playcache.cataloger import Cataloger
from playcache.config import Config, catalog_settings, restore_catalog_settings
from playcache.covers import cover_file_name, download_cover, missing_covers, write_cover
from playcache.db import Database
from playcache.models import GameRecord

URL = "https://media.example.test/games/doom.jpg"
VID = "ABCD1234"


def _rec(path: str, **kw) -> GameRecord:
    base = {
        "folder_name": os.path.basename(path),
        "folder_path": path,
        "game_name": "Doom",
        "platform": "PC",
        "developer": "id Software",
        "cover_url": URL,
        "fetch_status": "ok",
        "data_source": "rawg",
        "manual_overrides": '{"user_rating": "10/10"}',
    }
    base.update(kw)
    return GameRecord(**base)


@pytest.fixture
def fake_volumes(monkeypatch):
    """Volume layer with one volume ``VID`` whose current root the test sets."""
    state: dict[str, str] = {}

    def locate(path):
        root = state.get("root")
        if root and os.path.abspath(path).startswith(os.path.abspath(root)):
            inner = os.path.relpath(path, root).replace("\\", "/")
            return VID, "" if inner == "." else inner
        return "", ""

    monkeypatch.setattr(volumes, "current_roots", lambda: {VID: state["root"]})
    monkeypatch.setattr(volumes, "locate", locate)
    return state


class TestFullBackupFile:
    def test_zip_holds_catalog_settings_and_covers(self, tmp_path):
        db = Database(str(tmp_path / "a.db"))
        db.upsert(_rec("/games/Doom"))
        covers = tmp_path / "covers"
        write_cover(covers, URL, b"JPEGDATA")
        out = export_backup(
            db, str(tmp_path / "b.zip"), covers_dir=str(covers),
            settings={"fuzzy_threshold": 70},
        )
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            envelope = json.loads(zf.read("catalog.json"))
            assert zf.read("covers/" + cover_file_name(URL)) == b"JPEGDATA"
        assert "catalog.json" in names
        assert envelope["format_version"] == FORMAT_VERSION
        assert envelope["settings"] == {"fuzzy_threshold": 70}
        assert envelope["games"][0]["developer"] == "id Software"

    def test_restore_on_new_pc_brings_covers_and_data(self, tmp_path):
        old = Database(str(tmp_path / "old.db"))
        old.upsert(_rec("/games/Doom"))
        old_covers = tmp_path / "old_covers"
        write_cover(old_covers, URL, b"JPEGDATA")
        out = export_backup(old, str(tmp_path / "b.zip"), covers_dir=str(old_covers))

        new = Database(str(tmp_path / "new.db"))
        new_covers = tmp_path / "new_covers"
        summary = import_backup(new, out, covers_dir=str(new_covers))
        assert summary["imported"] == 1
        assert summary["covers"] == 1
        assert (new_covers / cover_file_name(URL)).read_bytes() == b"JPEGDATA"
        rec = new.get_by_path("/games/Doom")
        assert rec.developer == "id Software"
        assert rec.fetch_status == "ok"
        assert new.get_overrides("/games/Doom") == {"user_rating": "10/10"}

    def test_only_known_cover_names_are_extracted(self, tmp_path):
        db = Database(str(tmp_path / "a.db"))
        db.upsert(_rec("/games/Doom"))
        out = export_backup(db, str(tmp_path / "b.zip"))
        with zipfile.ZipFile(out, "a") as zf:
            zf.writestr("covers/../evil.txt", b"x")
            zf.writestr("covers/" + cover_file_name("https://other.test/x.png"), b"x")
        target = tmp_path / "restore" / "covers"
        summary = import_backup(Database(str(tmp_path / "n.db")), out, covers_dir=str(target))
        assert summary["covers"] == 0
        assert not (tmp_path / "restore" / "evil.txt").exists()
        assert not target.exists() or list(target.iterdir()) == []

    def test_zip_without_catalog_is_rejected(self, tmp_path):
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("readme.txt", "x")
        with pytest.raises(ValueError, match="catalog.json"):
            import_backup(Database(str(tmp_path / "n.db")), str(bad))

    def test_catalog_only_gz_still_supported(self, tmp_path):
        db = Database(str(tmp_path / "a.db"))
        db.upsert(_rec("/games/Doom"))
        out = export_backup(db, str(tmp_path / "b.json.gz"), settings={"max_retries": 5})
        with gzip.open(out, "rt", encoding="utf-8") as fh:
            assert json.load(fh)["settings"] == {"max_retries": 5}
        summary = import_backup(Database(str(tmp_path / "n.db")), out)
        assert summary["imported"] == 1
        assert summary["covers"] == 0
        assert summary["settings"] == {"max_retries": 5}

    def test_version_1_backup_imports(self, tmp_path):
        path = tmp_path / "v1.json.gz"
        row = _rec("/games/Doom").to_db_row()
        del row["volume_id"], row["volume_path"]
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump({"format_version": 1, "games": [row]}, fh)
        db = Database(str(tmp_path / "n.db"))
        summary = import_backup(db, str(path))
        assert summary["imported"] == 1
        assert summary["settings"] == {}
        assert db.get_by_path("/games/Doom").volume_id == ""


class TestRelinkOnImport:
    def test_export_records_volume_of_existing_folders(self, tmp_path, fake_volumes):
        drive = tmp_path / "I"
        (drive / "1-FPS" / "Doom").mkdir(parents=True)
        fake_volumes["root"] = str(drive)
        db = Database(str(tmp_path / "a.db"))
        db.upsert(_rec(str(drive / "1-FPS" / "Doom")))
        out = export_backup(db, str(tmp_path / "b.json.gz"))
        with gzip.open(out, "rt", encoding="utf-8") as fh:
            row = json.load(fh)["games"][0]
        assert (row["volume_id"], row["volume_path"]) == (VID, "1-FPS/Doom")
        assert db.get_by_path(str(drive / "1-FPS" / "Doom")).volume_id == VID

    def test_import_follows_volume_to_new_drive(self, tmp_path, fake_volumes):
        new_drive = tmp_path / "E"
        (new_drive / "1-FPS" / "Doom").mkdir(parents=True)
        fake_volumes["root"] = str(new_drive)
        backup_file = tmp_path / "b.json.gz"
        row = _rec("I:\\1-FPS\\Doom", volume_id=VID, volume_path="1-FPS/Doom").to_db_row()
        with gzip.open(backup_file, "wt", encoding="utf-8") as fh:
            json.dump({"format_version": FORMAT_VERSION, "games": [row]}, fh)
        db = Database(str(tmp_path / "n.db"))
        summary = import_backup(db, str(backup_file))
        assert summary["relinked"] == 1
        moved = db.get_by_path(str(new_drive / "1-FPS" / "Doom"))
        assert moved is not None and moved.developer == "id Software"
        assert db.get_by_path("I:\\1-FPS\\Doom") is None

    def test_disconnected_volume_keeps_its_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(volumes, "current_roots", lambda: {})
        backup_file = tmp_path / "b.json.gz"
        row = _rec("Q:\\1-FPS\\Doom", volume_id=VID, volume_path="1-FPS/Doom").to_db_row()
        with gzip.open(backup_file, "wt", encoding="utf-8") as fh:
            json.dump({"format_version": FORMAT_VERSION, "games": [row]}, fh)
        monkeypatch.setattr(volumes, "swap_drive_letter", lambda p, roots=None: None)
        db = Database(str(tmp_path / "n.db"))
        assert import_backup(db, str(backup_file))["relinked"] == 0
        assert db.get_by_path("Q:\\1-FPS\\Doom") is not None

    def test_relink_helper_rewrites_missing_path(self, tmp_path, fake_volumes):
        fake_volumes["root"] = str(tmp_path)
        (tmp_path / "1-FPS" / "Doom").mkdir(parents=True)
        recs = [_rec("I:\\1-FPS\\Doom", volume_id=VID, volume_path="1-FPS/Doom")]
        assert backup._relink(recs) == 1
        assert recs[0].folder_path == os.path.join(str(tmp_path), "1-FPS", "Doom")


class TestVolumes:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("6A1C2F3B1C2F02E5", "1C2F02E5"),
            ("1c2f-02e5", "1C2F02E5"),
            ("1C2F02E5", "1C2F02E5"),
            ("0b3e7f1c-5d2a-4e0b-9a77-0123456789ab", "0B3E7F1C5D2A4E0B9A770123456789AB"),
            ("", ""),
        ],
    )
    def test_normalize_id_matches_windows_and_linux(self, raw, expected):
        assert volumes.normalize_id(raw) == expected

    def test_resolve_builds_path_on_current_root(self, tmp_path):
        roots = {VID: str(tmp_path)}
        assert volumes.resolve(VID.lower(), "1-FPS/Doom", roots) == os.path.join(
            str(tmp_path), "1-FPS", "Doom"
        )
        assert volumes.resolve("FFFFFFFF", "1-FPS/Doom", roots) is None

    def test_swap_drive_letter_needs_exactly_one_hit(self, monkeypatch):
        present = {os.path.join("E:\\", "Games\\Doom")}
        monkeypatch.setattr(os.path, "exists", lambda p: p in present)
        assert volumes.swap_drive_letter("I:\\Games\\Doom", ["C:\\", "E:\\", "I:\\"]) == (
            os.path.join("E:\\", "Games\\Doom")
        )
        present.add(os.path.join("F:\\", "Games\\Doom"))
        assert volumes.swap_drive_letter("I:\\Games\\Doom", ["E:\\", "F:\\"]) is None
        assert volumes.swap_drive_letter("/games/Doom", ["E:\\"]) is None

    def test_manual_entries_have_no_volume(self):
        assert volumes.locate("/manual/Doom") == ("", "")


class _Unavailable:
    name = "rawg"

    def __init__(self, config=None):
        self.calls = 0

    def is_available(self) -> bool:
        return False

    def fetch(self, record, *, overrides=None):
        self.calls += 1
        return record


class TestRelinkOnScan:
    def test_moved_disk_reuses_catalogued_game(self, tmp_path, fake_volumes):
        drive = tmp_path / "E"
        game = drive / "Doom"
        game.mkdir(parents=True)
        (game / "doom.exe").write_bytes(b"x")
        fake_volumes["root"] = str(drive)
        cfg = replace(Config(), db_path=str(tmp_path / "c.db"))
        db = Database(cfg.db_path)
        db.upsert(_rec("I:\\Doom", volume_id=VID, volume_path="Doom"))
        rawg, tgdb = _Unavailable(), _Unavailable()
        cat = Cataloger(cfg, db=db, rawg=rawg, tgdb=tgdb)
        summary = cat.scan_to_db(str(drive))
        assert summary["relinked"] == 1
        assert summary["skipped"] == 1
        assert rawg.calls == tgdb.calls == 0
        rec = db.get_by_path(str(game))
        assert rec is not None and rec.developer == "id Software"
        assert db.get_by_path("I:\\Doom") is None
        assert db.count() == 1

    def test_other_volume_is_not_relinked(self, tmp_path, fake_volumes):
        drive = tmp_path / "E"
        game = drive / "Doom"
        game.mkdir(parents=True)
        (game / "doom.exe").write_bytes(b"x")
        fake_volumes["root"] = str(drive)
        cfg = replace(Config(), db_path=str(tmp_path / "c.db"))
        db = Database(cfg.db_path)
        db.upsert(_rec("I:\\Doom", volume_id="99999999", volume_path="Doom"))
        cat = Cataloger(cfg, db=db, rawg=_Unavailable(), tgdb=_Unavailable())
        summary = cat.scan_to_db(str(drive))
        assert summary["relinked"] == 0
        assert db.count() == 2

    def test_scan_backfills_volume_of_old_rows(self, tmp_path, fake_volumes):
        game = tmp_path / "Doom"
        game.mkdir()
        (game / "doom.exe").write_bytes(b"x")
        fake_volumes["root"] = str(tmp_path)
        cfg = replace(Config(), db_path=str(tmp_path / "c.db"))
        db = Database(cfg.db_path)
        db.upsert(_rec(str(game)))
        Cataloger(cfg, db=db, rawg=_Unavailable(), tgdb=_Unavailable()).scan_to_db(str(tmp_path))
        rec = db.get_by_path(str(game))
        assert (rec.volume_id, rec.volume_path) == (VID, "Doom")


class _Resp:
    def __init__(self, status=200, content=b"IMG", ctype="image/jpeg"):
        self.status_code = status
        self.content = content
        self.headers = {"Content-Type": ctype}


class _Session:
    def __init__(self, resp):
        self.resp = resp
        self.urls: list[str] = []

    def get(self, url, timeout=0):
        self.urls.append(url)
        return self.resp


class TestCovers:
    def test_missing_covers_skips_cached_and_non_http(self, tmp_path):
        write_cover(tmp_path, URL, b"x")
        other = "https://media.example.test/b.png"
        urls = [URL, other, other, None, "file:///etc/passwd", ""]
        assert missing_covers(urls, tmp_path) == [other]

    def test_download_stores_image(self, tmp_path):
        session = _Session(_Resp())
        assert download_cover(URL, tmp_path, session=session) is True
        assert (tmp_path / cover_file_name(URL)).read_bytes() == b"IMG"

    @pytest.mark.parametrize(
        "resp", [_Resp(status=404), _Resp(ctype="text/html"), _Resp(content=b"")],
    )
    def test_download_rejects_bad_responses(self, tmp_path, resp):
        assert download_cover(URL, tmp_path, session=_Session(resp)) is False
        assert list(tmp_path.iterdir()) == []

    def test_download_refuses_non_http(self, tmp_path):
        session = _Session(_Resp())
        assert download_cover("file:///etc/passwd", tmp_path, session=session) is False
        assert session.urls == []

    def test_gui_cache_uses_same_names(self, tmp_path):
        from playcache.image_cache import ImageCache

        cache = ImageCache(cache_dir=str(tmp_path))
        assert cache._path_for(URL).name == cover_file_name(URL)


class TestSettings:
    def test_backup_settings_leave_out_secrets(self):
        cfg = replace(Config(), rawg_api_key="SECRET", thegamesdb_api_key="SECRET2")
        values = catalog_settings(cfg)
        assert "SECRET" not in json.dumps(values)
        assert "db_path" not in values

    def test_restore_writes_ini_and_keeps_keys(self, tmp_path):
        ini = tmp_path / "config.ini"
        ini.write_text("[rawg]\napi_key = KEEP\n[catalog]\ndb_path = mine.db\n", encoding="utf-8")
        cfg = replace(Config(), config_path=str(ini))
        applied = restore_catalog_settings(cfg, {
            "fuzzy_threshold": 70,
            "skip_folders": ["Windows", "Temp"],
            "request_delay": "bad",
            "max_retries": True,
            "rawg_api_key": "HACK",
        })
        assert sorted(applied) == ["fuzzy_threshold", "skip_folders"]
        parser = configparser.ConfigParser()
        parser.read(ini, encoding="utf-8")
        assert parser.get("rawg", "api_key") == "KEEP"
        assert parser.get("catalog", "db_path") == "mine.db"
        assert parser.get("catalog", "fuzzy_threshold") == "70"
        assert parser.get("catalog", "skip_folders") == "Windows,Temp"
        assert cfg.fuzzy_threshold == 70
        assert cfg.skip_folders == ("Windows", "Temp")
        assert cfg.rawg_api_key == ""

    def test_restore_nothing_valid_writes_nothing(self, tmp_path):
        cfg = replace(Config(), config_path=str(tmp_path / "config.ini"))
        assert restore_catalog_settings(cfg, {"fuzzy_threshold": "x"}) == []
        assert not (tmp_path / "config.ini").exists()
