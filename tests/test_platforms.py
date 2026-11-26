"""Tests for platform detection: path hints, file contents, disc headers (no network)."""
from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest

from playcache import platforms as plat


class TestPathHint:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("E:/Consoles/PS2/God of War", "PS2"),
            ("E:/1-PS2 Games/God of War", "PS2"),
            ("E:/Sony PlayStation 2/God of War.7z", "PS2"),
            ("E:/Nintendo GameCube/Zelda.7z", "GAMECUBE"),
            ("E:/ROMs/snes/Chrono Trigger.sfc", "SNES"),
            ("E:/Emulation/Wii U/Mario Kart 8", "WII U"),
            ("E:/Games/God of War [PS2]", "PS2"),
            ("E:/Games/Mario Odyssey (Switch)", "SWITCH"),
            ("I:/EMU Redump/Super Mario Sunshine.7z", plat.CONSOLE),
            ("I:/1-GOG Games/1-Linux Games/Dead Cells", plat.PC_LINUX),
            ("I:/1-PORTS/Zelda", plat.PC_FAN_PORT),
            ("I:/1-RECOMPILATIONS/Mario.7z", plat.PC_FAN_PORT),
            ("D:/Fan Port/Zelda", plat.PC_FAN_PORT),
            ("D:/Android/Unreal.apk", plat.ANDROID),
        ],
    )
    def test_system_folders(self, path, expected):
        assert plat.path_hint(path) == expected

    @pytest.mark.parametrize(
        "path",
        [
            "D:/Games/Wii Sports Club Remake",
            "C:/XboxGames/Halo Infinite",
            "D:/Games/Hollow Knight",
            "I:/1-RPG/Borderlands 3",
            "I:/1-GOG Games/1-ARCADE/Metal Slug",
            "I:/1-PORTS/Zelda (Europe) (En,Fr,De,Es,It).7z",
        ],
    )
    def test_game_titles_are_not_systems(self, path):
        assert plat.path_hint(path) in (None, plat.PC, plat.PC_FAN_PORT)

    def test_nearest_segment_wins(self):
        assert plat.path_hint("E:/Emulation/PS1/Crash") == "PS1"
        assert plat.path_hint("E:/PS2/PC Games/Doom") == plat.PC

    def test_detect_platform_defaults_to_pc(self):
        assert plat.detect_platform("D:/Games/Hollow Knight") == plat.PC


class TestResolve:
    def test_pc_content_beats_console_path(self):
        assert plat.resolve(plat.PC, "C:/Xbox Games/Halo") == plat.PC

    def test_pc_content_refined_by_linux_and_port_paths(self):
        assert plat.resolve(plat.PC, "D:/Linux Games/Torchlight") == plat.PC_LINUX
        assert plat.resolve(plat.PC, "I:/1-PORTS/Zelda") == plat.PC_FAN_PORT

    def test_console_content_beats_path(self):
        assert plat.resolve("GAMECUBE", "D:/PC Games/Zelda") == "GAMECUBE"

    def test_unknown_content_uses_path(self):
        assert plat.resolve(None, "I:/EMU Redump/Mario.7z") == plat.CONSOLE
        assert plat.resolve(plat.WEAK_PC, "E:/PS2/Game") == "PS2"
        assert plat.resolve(plat.WEAK_PC, "E:/Games/Game") == plat.PC
        assert plat.resolve(None, "E:/Games/Game") == plat.PC


class TestFileContent:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("game.nsp", plat.SWITCH), ("game.xci", plat.SWITCH), ("rom.sfc", "SNES"),
            ("rom.z64", "N64"), ("rom.gba", "GBA"), ("rom.nds", "NDS"),
            ("rom.3ds", "3DS"), ("disc.wbfs", "WII"), ("disc.cso", "PSP"),
            ("game.apk", plat.ANDROID), ("game.exe", plat.PC), ("data1.doi", plat.PC),
            ("gog_game_1.0.sh", plat.PC_LINUX), ("game.x86_64", plat.PC_LINUX),
            ("disc.chd", plat.CONSOLE), ("fg-01.bin", plat.PC),
            ("setup_game_1.0_(123)-1.bin", plat.PC),
        ],
    )
    def test_extensions(self, tmp_path, name, expected):
        f = tmp_path / name
        f.write_bytes(b"x")
        assert plat.file_content(f) == expected

    def test_plain_bin_and_7z_say_nothing(self, tmp_path):
        (tmp_path / "data.bin").write_bytes(b"x")
        (tmp_path / "game.7z").write_bytes(b"x")
        assert plat.file_content(tmp_path / "data.bin") is None
        assert plat.file_content(tmp_path / "game.7z") is None

    def test_zip_members(self, tmp_path):
        pc = tmp_path / "pc.zip"
        with zipfile.ZipFile(pc, "w") as zf:
            zf.writestr("Game/Game.exe", b"x")
        rom = tmp_path / "rom.zip"
        with zipfile.ZipFile(rom, "w") as zf:
            zf.writestr("Chrono Trigger (USA).sfc", b"x")
        apk = tmp_path / "apk.zip"
        with zipfile.ZipFile(apk, "w") as zf:
            zf.writestr("game.apk", b"x")
        assert plat.file_content(pc) == plat.PC
        assert plat.file_content(rom) == "SNES"
        assert plat.file_content(apk) == plat.ANDROID

    def test_broken_zip_is_unknown(self, tmp_path):
        (tmp_path / "empty.zip").write_bytes(b"")
        assert plat.file_content(tmp_path / "empty.zip") is None


def _pvd(sysid: str, volid: str = "", root_lba: int = 0, root_len: int = 0) -> bytes:
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[8:40] = sysid.ljust(32).encode("ascii")
    pvd[40:72] = volid.ljust(32).encode("ascii")
    root = bytearray(34)
    root[0] = 34
    struct.pack_into("<I", root, 2, root_lba)
    struct.pack_into("<I", root, 10, root_len)
    pvd[156:190] = root
    return bytes(pvd)


def _dir_record(name: bytes, lba: int, length: int) -> bytes:
    ident = name + b";1"
    size = 33 + len(ident) + (1 if len(ident) % 2 == 0 else 0)
    rec = bytearray(size)
    rec[0] = size
    struct.pack_into("<I", rec, 2, lba)
    struct.pack_into("<I", rec, 10, length)
    rec[32] = len(ident)
    rec[33:33 + len(ident)] = ident
    return bytes(rec)


class TestDiscSniffing:
    def test_gamecube_and_wii_magic(self, tmp_path):
        gc = bytearray(0x400)
        gc[0x1C:0x20] = b"\xc2\x33\x9f\x3d"
        wii = bytearray(0x400)
        wii[0x18:0x1C] = b"\x5d\x1c\x9e\xa3"
        (tmp_path / "gc.iso").write_bytes(bytes(gc))
        (tmp_path / "wii.iso").write_bytes(bytes(wii))
        assert plat.sniff_disc(tmp_path / "gc.iso") == "GAMECUBE"
        assert plat.sniff_disc(tmp_path / "wii.iso") == "WII"

    def test_rvz_disc_type(self, tmp_path):
        head = bytearray(0x80)
        head[:4] = b"RVZ\x01"
        struct.pack_into(">I", head, 0x48, 2)
        (tmp_path / "game.rvz").write_bytes(bytes(head))
        assert plat.file_content(tmp_path / "game.rvz") == "WII"

    def test_sega_headers(self, tmp_path):
        (tmp_path / "sat.iso").write_bytes(b"SEGA SEGASATURN " + bytes(0x100))
        (tmp_path / "dc.iso").write_bytes(b"SEGA SEGAKATANA " + bytes(0x100))
        assert plat.sniff_disc(tmp_path / "sat.iso") == "SATURN"
        assert plat.sniff_disc(tmp_path / "dc.iso") == "DREAMCAST"

    def test_generic_iso9660_is_weak_pc(self, tmp_path):
        (tmp_path / "pc.iso").write_bytes(bytes(0x8000) + _pvd("WIN32"))
        assert plat.sniff_disc(tmp_path / "pc.iso") == plat.WEAK_PC

    def test_psp_iso(self, tmp_path):
        (tmp_path / "psp.iso").write_bytes(bytes(0x8000) + _pvd("PSP GAME"))
        assert plat.sniff_disc(tmp_path / "psp.iso") == "PSP"

    def test_raw_playstation_bin_via_cue(self, tmp_path):
        raw = bytearray(16 * 2352 + 24) + bytearray(_pvd("PLAYSTATION"))
        (tmp_path / "crash.bin").write_bytes(bytes(raw))
        (tmp_path / "crash.cue").write_text('FILE "crash.bin" BINARY\n')
        assert plat.file_content(tmp_path / "crash.cue") == "PS1"
        assert plat.file_content(tmp_path / "crash.bin") == "PS1"

    def test_ps2_detected_from_system_cnf(self, tmp_path):
        image = bytearray(0x8000) + bytearray(_pvd("PLAYSTATION", root_lba=20, root_len=2048))
        image += bytearray(20 * 2048 - len(image))
        directory = bytearray(2048)
        rec = _dir_record(b"SYSTEM.CNF", 21, 32)
        directory[: len(rec)] = rec
        image += directory
        cnf = bytearray(2048)
        cnf[:32] = b"BOOT2 = cdrom0:\\SLUS_201.23;1\r\n"
        image += cnf
        (tmp_path / "ps2.iso").write_bytes(bytes(image))
        assert plat.sniff_disc(tmp_path / "ps2.iso") == "PS2"

    def test_zip_member_disc_header(self, tmp_path):
        gc = bytearray(0x20000)
        gc[0x1C:0x20] = b"\xc2\x33\x9f\x3d"
        z = tmp_path / "zelda.zip"
        with zipfile.ZipFile(z, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Zelda (USA).iso", bytes(gc))
        assert plat.peek_zip(z) == "GAMECUBE"

    def test_unreadable_file(self, tmp_path):
        assert plat.sniff_disc(Path(tmp_path / "missing.iso")) is None


class TestCombine:
    def test_pc_wins(self):
        assert plat.combine([plat.ANDROID, "SNES", plat.PC]) == plat.PC

    def test_console_beats_linux_and_unknown(self):
        assert plat.combine([plat.WEAK_PC, "GAMECUBE", plat.PC_LINUX]) == "GAMECUBE"

    def test_unknown_archive_beats_lone_apk(self):
        assert plat.combine([plat.ANDROID, plat.WEAK_PC]) == plat.WEAK_PC
        assert plat.combine([plat.ANDROID]) == plat.ANDROID

    def test_empty(self):
        assert plat.combine([None, None]) is None


def test_all_platforms_lists_known_labels():
    assert plat.PC in plat.ALL_PLATFORMS
    assert plat.SWITCH in plat.ALL_PLATFORMS
    assert "PS2" in plat.ALL_PLATFORMS
    assert len(plat.ALL_PLATFORMS) == len(set(plat.ALL_PLATFORMS))
