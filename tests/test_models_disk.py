"""Tests for the Linux mount/disk resolution helpers (no network, any platform)."""
from __future__ import annotations

import os

from playcache import models


class _Stat:
    def __init__(self, dev: int):
        self.st_dev = dev


def _identity_realpath(p: str) -> str:
    return p


def test_mount_escape_decode():
    assert models._decode_mount_escapes("/mnt/my\\040games") == "/mnt/my games"
    assert models._decode_mount_escapes("/media/usb\\134backup") == "/media/usb\\backup"
    assert models._decode_mount_escapes("/plain") == "/plain"


def test_root_mount_prefix_matches(monkeypatch):
    monkeypatch.setattr(os.path, "realpath", _identity_realpath)
    monkeypatch.setattr(os, "stat", lambda p: _Stat(5))
    monkeypatch.setattr(
        models, "_load_mounts", lambda: [("/dev/sda1", "/", "ext4")]
    )
    assert models._linux_mount_for("/some/game") == "/"


def test_mount_boundary_found_by_device_change(monkeypatch):
    monkeypatch.setattr(os.path, "realpath", _identity_realpath)

    def fake_stat(p: str) -> _Stat:
        return _Stat(5 if p.startswith("/mnt/games") else 2)

    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setattr(
        models,
        "_load_mounts",
        lambda: [("/dev/sdb1", "/mnt/games", "ext4"), ("/dev/sda1", "/", "ext4")],
    )
    assert models._linux_mount_for("/mnt/games/half knight") == "/mnt/games"


def test_unstatable_path_falls_back_to_existing_ancestor(monkeypatch):
    monkeypatch.setattr(os.path, "realpath", _identity_realpath)

    def fake_stat(p: str) -> _Stat:
        if p == "/mnt/games/gone":
            raise OSError("deleted folder")
        return _Stat(5 if p.startswith("/mnt/games") else 2)

    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setattr(
        models,
        "_load_mounts",
        lambda: [("/dev/sdb1", "/mnt/games", "ext4"), ("/dev/sda1", "/", "ext4")],
    )
    assert models._linux_mount_for("/mnt/games/gone") == "/mnt/games"


def test_mount_with_spaces_matches(monkeypatch):
    monkeypatch.setattr(os.path, "realpath", _identity_realpath)

    def fake_stat(p: str) -> _Stat:
        return _Stat(5 if p.startswith("/mnt/my games") else 2)

    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setattr(
        models,
        "_load_mounts",
        lambda: [("/dev/sdb1", "/mnt/my games", "ext4"), ("/dev/sda1", "/", "ext4")],
    )
    assert models._linux_mount_for("/mnt/my games/hk") == "/mnt/my games"


def test_nothing_statable_falls_back_to_mount_prefix(monkeypatch):
    monkeypatch.setattr(os.path, "realpath", _identity_realpath)

    def fake_stat(p: str) -> _Stat:
        raise OSError("nothing exists")

    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setattr(
        models, "_load_mounts", lambda: [("/dev/sdb1", "/mnt/games", "ext4")]
    )
    assert models._linux_mount_for("/mnt/games/x") == "/mnt/games"


def test_disk_property_is_cached_per_record(monkeypatch):
    from playcache.models import GameRecord

    monkeypatch.setattr(models.sys, "platform", "linux")
    calls: list[str] = []

    def fake_mount(path: str) -> str:
        calls.append(path)
        return "/mnt/games"

    monkeypatch.setattr(models, "_linux_mount_for", fake_mount)
    monkeypatch.setattr(models, "_volume_label", lambda mount: "Games HDD")
    rec = GameRecord(folder_path="/mnt/games/Hollow Knight")
    assert rec.disk == "Games HDD"
    assert rec.disk == "Games HDD"
    assert len(calls) == 1
