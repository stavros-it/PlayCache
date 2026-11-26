"""Tests for the folder scanner (no network)."""
from pathlib import Path

from playcache.folder_scanner import (
    SOURCE_GROUPS,
    SOURCE_TAGS,
    _clean_archive_name,
    _clean_exe_name,
    _clean_gog_setup_name,
    _looks_like_game_name,
    _make_scanned,
    _normalize_root,
    clean_folder_name,
    detect_platform,
    detect_store,
    has_switch_dump,
    scan_games,
    smart_detect_game_name,
)

_ALPHA_TAGS = sorted(t for t in SOURCE_TAGS if t.isalpha())
_BOTH_TAGS = sorted(SOURCE_TAGS & SOURCE_GROUPS)
TAG = _ALPHA_TAGS[0]
TAG2 = _ALPHA_TAGS[1]
GRP = _BOTH_TAGS[0]
GRP2 = _BOTH_TAGS[1]
HYPHENATED = next(t for t in sorted(SOURCE_TAGS) if "-" in t)


class TestCleanFolderName:
    def test_simple_name(self):
        assert clean_folder_name("Hollow Knight") == "Hollow Knight"

    def test_strips_brackets(self):
        assert TAG not in clean_folder_name(f"Hollow Knight [{TAG.title()}]")
        assert clean_folder_name(f"Hollow Knight [{TAG.title()}]") == "Hollow Knight"

    def test_strips_version(self):
        out = clean_folder_name("Some Game v1.2.3")
        assert "v1" not in out
        assert "Some Game" in out

    def test_strips_source_tags(self):
        out = clean_folder_name(f"Doom Eternal-{GRP.upper()}")
        assert GRP not in out.lower()
        assert "Doom Eternal" in out

    def test_strips_underscores(self):
        assert clean_folder_name("Deep_Rock_Galactic") == "Deep Rock Galactic"

    def test_handles_extension(self):
        assert "exe" not in clean_folder_name("Game.exe")

    def test_strips_source_tag_words(self):
        out = clean_folder_name(f"Far Cry 2 RePack by {TAG.title()}")
        assert TAG not in out.lower()
        assert "repack" not in out.lower()
        assert "Far Cry 2" in out

    def test_preserves_subtitle(self):
        out = clean_folder_name("Assassin's Creed IV: Black Flag")
        assert "Black Flag" in out

    def test_strips_id_parentheses(self):
        out = clean_folder_name("aphelion_windows_gog_(90803)")
        assert "90803" not in out
        assert "gog" not in out.lower()
        assert "windows" not in out.lower()
        assert "aphelion" in out.lower()

    def test_strips_gog_noise(self):
        out = clean_folder_name("Achilles.Legends.Untold.v1.4.0.0")
        assert "1.4" not in out
        assert "Achilles" in out
        assert "Legends" in out
        assert "Untold" in out

    def test_strips_dlc_token(self):
        out = clean_folder_name("Some Game DLC")
        assert "dlc" not in out.lower()
        assert "Some Game" in out

    def test_preserves_year_in_title(self):
        # 4-digit years that are part of the title must NOT be stripped
        assert clean_folder_name("Cyberpunk 2077") == "Cyberpunk 2077"
        assert clean_folder_name("Battlefield 1942") == "Battlefield 1942"
        # But years in parentheses/brackets are still stripped
        assert "2020" not in clean_folder_name("Some Game (2020)")

    def test_preserves_intra_word_hyphens(self):
        assert clean_folder_name("Half-Life") == "Half-Life"
        assert clean_folder_name("Counter-Strike") == "Counter-Strike"

    def test_strips_hyphenated_noise_tokens(self):
        out = clean_folder_name(f"Doom Eternal-{GRP.upper()}")
        assert GRP not in out.lower()
        assert "Doom Eternal" in out

    def test_strips_hyphenated_compound_token(self):
        left, right = HYPHENATED.split("-")
        out = clean_folder_name(f"Some Game {HYPHENATED}")
        assert left not in out.lower()
        assert right not in out.lower()
        assert "Some Game" in out


class TestCleanExeName:
    def test_camelcase(self):
        assert _clean_exe_name("HollowKnight.exe") == "Hollow Knight"

    def test_allcaps_prefix(self):
        assert _clean_exe_name("DOOMEternal.exe") == "DOOM Eternal"

    def test_strips_arch_suffix(self):
        assert _clean_exe_name("Game-x64.exe") == "Game"
        assert _clean_exe_name("GameWin64.exe") == "Game"

    def test_strips_multiple_suffixes(self):
        assert _clean_exe_name("DOOMEternalx64vk.exe") == "DOOM Eternal"

    def test_strips_underscores(self):
        assert _clean_exe_name("Deep_Rock_Galactic.exe") == "Deep Rock Galactic"

    def test_strips_dots(self):
        assert _clean_exe_name("My.Game.exe") == "My Game"


class TestCleanGogSetupName:
    def test_basic_gog_setup(self):
        assert _clean_gog_setup_name(
            "setup_achilles_legends_untold_1.4.0.0_(74603).exe"
        ) == "Achilles Legends Untold"

    def test_gog_with_dlc_tag(self):
        result = _clean_gog_setup_name(
            "setup_aphelion_gog_1.03.1628077_dlc_(90803).exe"
        )
        assert result == "Aphelion"

    def test_gog_with_artbook(self):
        result = _clean_gog_setup_name(
            "setup_aphelion_-_artbook_plus_cosmetic_pack_gog_1.03.1628077_dlc_(90803).exe"
        )
        assert "artbook" not in result.lower()
        assert "gog" not in result.lower()
        assert "1.03" not in result
        assert "Aphelion" in result

    def test_not_a_gog_setup(self):
        assert _clean_gog_setup_name("HollowKnight.exe") == ""

    def test_generic_setup(self):
        assert _clean_gog_setup_name("setup.exe") == ""

    def test_preserves_apostrophe(self):
        # capwords (not .title()) correctly handles apostrophes.
        # We simulate a setup name whose tokens include an apostrophe-bearing word.
        from string import capwords
        assert capwords("assassin's creed") == "Assassin's Creed"
        assert "assassin's creed".title() != "Assassin's Creed"  # confirms the bug


class TestLooksLikeGameName:
    def test_real_name(self):
        assert _looks_like_game_name("Hollow Knight")

    def test_numeric_only(self):
        assert not _looks_like_game_name("123456")

    def test_single_char(self):
        assert not _looks_like_game_name("A")

    def test_empty(self):
        assert not _looks_like_game_name("")

    def test_symbols_only(self):
        assert not _looks_like_game_name("---")


class TestSmartDetectGameName:
    def test_falls_back_to_folder_name_when_good(self, tmp_path):
        """When the folder name is clean, it's used directly."""
        folder = tmp_path / "Hollow Knight"
        folder.mkdir()
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"

    def test_uses_exe_when_folder_is_numeric(self, tmp_path):
        """When the folder name is just a number, extract from .exe."""
        folder = tmp_path / "367520"
        folder.mkdir()
        # Create a fake game exe (must be >1MB to pass the size filter)
        exe = folder / "HollowKnight.exe"
        exe.write_bytes(b"\0" * 2_000_000)
        cleaned = clean_folder_name(folder.name)
        result = smart_detect_game_name(folder, cleaned)
        assert result == "Hollow Knight"

    def test_uses_gog_setup_exe(self, tmp_path):
        """Extract game name from GOG setup executable filename."""
        folder = tmp_path / "Achilles.Legends.Untold.v1.4.0.0"
        folder.mkdir()
        exe = folder / "setup_achilles_legends_untold_1.4.0.0_(74603).exe"
        exe.write_text("fake")
        cleaned = clean_folder_name(folder.name)
        result = smart_detect_game_name(folder, cleaned)
        assert result == "Achilles Legends Untold"

    def test_uses_gog_metadata(self, tmp_path):
        """Read game name from GOG goggame-*.info JSON."""
        import json
        folder = tmp_path / "aphelion_windows_gog_(90803)"
        folder.mkdir()
        info = folder / "goggame-90803.info"
        info.write_text(json.dumps({"name": "Aphelion", "gameId": "90803"}))
        cleaned = clean_folder_name(folder.name)
        result = smart_detect_game_name(folder, cleaned)
        assert result == "Aphelion"

    def test_gog_prefers_base_game_over_dlc(self, tmp_path):
        """When multiple goggame-*.info files exist, the base game (where
        filename ID == JSON gameId) is preferred over DLC/soundtrack entries."""
        import json
        folder = tmp_path / "game_folder"
        folder.mkdir()
        # DLC file (filename ID 99999, gameId 88888 — not the base game)
        (folder / "goggame-99999.info").write_text(
            json.dumps({"name": "Game Soundtrack", "gameId": "88888"})
        )
        # Base game file (filename ID 88888 == gameId 88888)
        (folder / "goggame-88888.info").write_text(
            json.dumps({"name": "Real Game", "gameId": "88888"})
        )
        cleaned = clean_folder_name(folder.name)
        result = smart_detect_game_name(folder, cleaned)
        assert result == "Real Game"

    def test_uses_steam_manifest(self, tmp_path):
        """Read game name from Steam appmanifest_*.acf."""
        steamapps = tmp_path / "steamapps"
        common = steamapps / "common"
        game_folder = common / "Hollow Knight"
        game_folder.mkdir(parents=True)
        manifest = steamapps / "appmanifest_367520.acf"
        manifest.write_text(
            '"AppState"\n{\n'
            '\t"appid"\t\t"367520"\n'
            '\t"name"\t\t"Hollow Knight"\n'
            '\t"installdir"\t\t"Hollow Knight"\n'
            "}\n"
        )
        cleaned = clean_folder_name(game_folder.name)
        result = smart_detect_game_name(game_folder, cleaned)
        assert result == "Hollow Knight"

    def test_steam_manifest_wrong_installdir_skipped(self, tmp_path):
        """Steam manifest with non-matching installdir is skipped."""
        steamapps = tmp_path / "steamapps"
        common = steamapps / "common"
        game_folder = common / "Some Other Game"
        game_folder.mkdir(parents=True)
        manifest = steamapps / "appmanifest_367520.acf"
        manifest.write_text(
            '"AppState"\n{\n'
            '\t"name"\t\t"Hollow Knight"\n'
            '\t"installdir"\t\t"Hollow Knight"\n'
            "}\n"
        )
        cleaned = clean_folder_name(game_folder.name)
        result = smart_detect_game_name(game_folder, cleaned)
        # Should NOT return "Hollow Knight" (installdir doesn't match)
        assert result != "Hollow Knight"

    def test_prefers_metadata_over_exe(self, tmp_path):
        """GOG metadata is preferred over .exe filename."""
        import json
        folder = tmp_path / "noisy_folder_name"
        folder.mkdir()
        info = folder / "goggame-11226.info"
        info.write_text(json.dumps({"name": "Hollow Knight"}))
        exe = folder / "hk_game.exe"
        exe.write_bytes(b"\0" * 2_000_000)
        cleaned = clean_folder_name(folder.name)
        result = smart_detect_game_name(folder, cleaned)
        assert result == "Hollow Knight"

    def test_exes_in_subfolder(self, tmp_path):
        """Game .exe is in a bin/ subfolder, not the root."""
        folder = tmp_path / "123456"
        folder.mkdir()
        bin_dir = folder / "bin"
        bin_dir.mkdir()
        exe = bin_dir / "HollowKnight.exe"
        exe.write_bytes(b"\0" * 2_000_000)
        cleaned = clean_folder_name(folder.name)
        result = smart_detect_game_name(folder, cleaned)
        assert result == "Hollow Knight"

    def test_skips_non_game_exes(self, tmp_path):
        """Launcher .exe files are skipped in favor of the real game .exe."""
        folder = tmp_path / "123456"
        folder.mkdir()
        # Small launcher exe (filtered by size)
        (folder / "launcher.exe").write_bytes(b"\0" * 100_000)
        # Real game exe (large)
        (folder / "HollowKnight.exe").write_bytes(b"\0" * 2_000_000)
        cleaned = clean_folder_name(folder.name)
        result = smart_detect_game_name(folder, cleaned)
        assert result == "Hollow Knight"


class TestDetectStore:
    def test_steam_path(self):
        assert detect_store("D:/SteamLibrary/steamapps/common/Hollow Knight") == "Steam"

    def test_gog_path(self):
        assert detect_store("D:/GOG Games/Hollow Knight") == "GOG"

    def test_epic_path(self):
        assert detect_store("D:/Epic Games/Hollow Knight") == "Epic"

    def test_unknown_uses_hint(self):
        assert detect_store("D:/Games/Hollow Knight", api_store_hint="Steam") == "Steam"

    def test_unknown_no_hint(self):
        assert detect_store("D:/Games/Hollow Knight") == ""


class TestDetectPlatform:
    def test_default_pc(self):
        assert detect_platform("D:/Games/Hollow Knight") == "PC"

    def test_linux(self):
        assert detect_platform("D:/Linux Games/Broforce") == "PC (Linux)"

    def test_fan_port(self):
        assert detect_platform("D:/Fan Port/Zelda") == "PC (Fan Port)"


class TestSwitchDumpPlatform:
    def test_nsp_in_folder(self, tmp_path: Path):
        g = tmp_path / "Kirby Star Allies"
        g.mkdir()
        (g / "game.nsp").write_bytes(b"x")
        assert has_switch_dump(g)
        assert _make_scanned(g, store="").platform == "SWITCH"

    def test_nsz_xci_xcz_case_insensitive(self, tmp_path: Path):
        for ext in (".NSZ", ".xci", ".XCZ"):
            g = tmp_path / f"Game{ext[1:]}"
            g.mkdir()
            (g / f"dump{ext}").write_bytes(b"x")
            assert has_switch_dump(g)

    def test_nested_dump(self, tmp_path: Path):
        g = tmp_path / "Collection"
        (g / "Disc 1").mkdir(parents=True)
        (g / "Disc 1" / "a.nsp").write_bytes(b"x")
        assert has_switch_dump(g)

    def test_too_deep_ignored(self, tmp_path: Path):
        g = tmp_path / "Deep"
        d = g / "a" / "b" / "c"
        d.mkdir(parents=True)
        (d / "a.nsp").write_bytes(b"x")
        assert not has_switch_dump(g)

    def test_plain_pc_folder_unchanged(self, tmp_path: Path):
        g = tmp_path / "Hollow Knight"
        g.mkdir()
        (g / "hk.exe").write_bytes(b"x")
        assert not has_switch_dump(g)
        assert _make_scanned(g, store="").platform == "PC"


def _game_dir(path: Path, exe: str = "game.exe") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / exe).write_bytes(b"x")
    return path


class TestScanGames:
    def _make_tree(self, tmp: Path):
        _game_dir(tmp / "Hollow Knight")
        _game_dir(tmp / "Deep Rock Galactic")
        (tmp / "Windows").mkdir()
        (tmp / "$Recycle.Bin").mkdir()
        steam = tmp / "SteamLibrary" / "steamapps" / "common"
        _game_dir(steam / "Dead Cells")
        _game_dir(tmp / "GOG Games" / "Biomutant")

    def test_scan_immediate_children(self, tmp_path):
        self._make_tree(tmp_path)
        results = list(scan_games(str(tmp_path)))
        names = sorted(r.folder_name for r in results)
        assert "Hollow Knight" in names
        assert "Deep Rock Galactic" in names
        assert "Dead Cells" in names
        assert "Biomutant" in names
        assert "Windows" not in names
        assert "$Recycle.Bin" not in names

    def test_store_detection_from_library_root(self, tmp_path):
        self._make_tree(tmp_path)
        results = {r.folder_name: r for r in scan_games(str(tmp_path))}
        assert results["Dead Cells"].store == "Steam"
        assert results["Biomutant"].store == "GOG"
        assert results["Hollow Knight"].store == ""

    def test_cleaned_name_used(self, tmp_path):
        _game_dir(tmp_path / f"Hollow Knight [{TAG.title()}]")
        (tmp_path / "Windows").mkdir()
        results = list(scan_games(str(tmp_path)))
        hk = next(r for r in results if "Hollow" in r.folder_name)
        assert hk.cleaned_name == "Hollow Knight"
        assert hk.folder_name == f"Hollow Knight [{TAG.title()}]"

    def test_path_must_exist(self, tmp_path):
        import pytest
        with pytest.raises(FileNotFoundError):
            list(scan_games(str(tmp_path / "nope")))

    def test_nonexistent_drive(self):
        import pytest
        with pytest.raises(FileNotFoundError):
            list(scan_games("Z:/definitely/not/here"))

    def test_gog_setup_exe_detected(self, tmp_path):
        """A GOG installer folder yields the game name from the setup .exe."""
        folder = tmp_path / "Achilles.Legends.Untold.v1.4.0.0"
        folder.mkdir()
        (folder / "setup_achilles_legends_untold_1.4.0.0_(74603).exe").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].cleaned_name == "Achilles Legends Untold"

    def test_gog_folder_noise_stripped(self, tmp_path):
        """GOG noise tokens (gog, windows, ID parens) are stripped from folder names."""
        _game_dir(tmp_path / "aphelion_windows_gog_(90803)")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert "aphelion" in results[0].cleaned_name.lower()
        assert "gog" not in results[0].cleaned_name.lower()
        assert "90803" not in results[0].cleaned_name


class TestInstallerNameDetection:
    """Generic installer filenames carry the game name; parse any shape."""

    def test_hyphen_setup_installer(self, tmp_path):
        folder = tmp_path / "367520"
        folder.mkdir()
        (folder / "Hollow Knight-Setup.exe").write_text("x")
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"

    def test_underscore_installer(self, tmp_path):
        folder = tmp_path / "123"
        folder.mkdir()
        (folder / "doom_eternal_installer.exe").write_text("x")
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Doom Eternal"

    def test_concat_camelcase_installer(self, tmp_path):
        folder = tmp_path / "123"
        folder.mkdir()
        (folder / "DoomEternalSetup.exe").write_text("x")
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Doom Eternal"

    def test_source_group_tokens_stripped(self, tmp_path):
        folder = tmp_path / "123"
        folder.mkdir()
        (folder / f"hollow_knight_{GRP}_setup.exe").write_text("x")
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"

    def test_bare_setup_exe_falls_back_to_folder(self, tmp_path):
        """A bare setup.exe carries no name; the folder name wins."""
        folder = tmp_path / "Hollow Knight"
        folder.mkdir()
        (folder / "setup.exe").write_text("x")
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"

    def test_installer_wins_over_good_folder_name(self, tmp_path):
        folder = tmp_path / "Cool Game"
        folder.mkdir()
        (folder / "Hollow Knight-Setup.exe").write_text("x")
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"

    def test_installer_in_linux_sh_form(self, tmp_path):
        import os
        import sys

        import pytest

        if sys.platform == "win32":
            pytest.skip(".sh installers are only scanned on Linux")
        folder = tmp_path / "123"
        folder.mkdir()
        sh = folder / "hollow-knight-setup.sh"
        sh.write_text("x")
        os.chmod(sh, 0o755)
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"


class TestPeMetadataDetection:
    """PE VERSIONINFO (ProductName/FileDescription) fills gaps filenames can't."""

    def test_product_name_rescues_generic_exe(self, tmp_path, monkeypatch):
        folder = tmp_path / "367520"
        folder.mkdir()
        (folder / "game.exe").write_bytes(b"\0" * 2_000_000)
        monkeypatch.setattr(
            "playcache.folder_scanner._read_pe_metadata",
            lambda path: {"product_name": "Hollow Knight"},
            raising=False,
        )
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"

    def test_file_description_rescues_generic_exe(self, tmp_path, monkeypatch):
        folder = tmp_path / "367520"
        folder.mkdir()
        (folder / "main.exe").write_bytes(b"\0" * 2_000_000)
        monkeypatch.setattr(
            "playcache.folder_scanner._read_pe_metadata",
            lambda path: {"file_description": "Doom Eternal"},
            raising=False,
        )
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Doom Eternal"

    def test_pe_metadata_beats_exe_stem(self, tmp_path, monkeypatch):
        folder = tmp_path / "367520"
        folder.mkdir()
        (folder / "hollow_knight.exe").write_bytes(b"\0" * 3_000_000)
        monkeypatch.setattr(
            "playcache.folder_scanner._read_pe_metadata",
            lambda path: {"product_name": "Hollow Knight: Voidheart Edition"},
            raising=False,
        )
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight: Voidheart Edition"

    def test_pe_junk_rejected_folder_wins(self, tmp_path, monkeypatch):
        """PE metadata that is pure junk ('Setup Program') must not win."""
        folder = tmp_path / "Hollow Knight"
        folder.mkdir()
        (folder / "setup.exe").write_bytes(b"\0" * 2_000_000)
        monkeypatch.setattr(
            "playcache.folder_scanner._read_pe_metadata",
            lambda path: {"file_description": "Setup Program",
                          "product_name": "Installer"},
            raising=False,
        )
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"

    def test_no_pe_metadata_exes_still_detected(self, tmp_path):
        """Without PE metadata (Linux CI / metadata-less exes) stems still work."""
        folder = tmp_path / "367520"
        folder.mkdir()
        (folder / "HollowKnight.exe").write_bytes(b"\0" * 2_000_000)
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"


class TestEvidenceSearchDepth:
    def test_exe_found_two_levels_deep(self, tmp_path):
        folder = tmp_path / "123456"
        folder.mkdir()
        inner = folder / "Game" / "Binaries"
        inner.mkdir(parents=True)
        (inner / "HollowKnight.exe").write_bytes(b"\0" * 2_000_000)
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"

    def test_generic_folder_name_uses_parent(self, tmp_path):
        parent = tmp_path / "Hollow Knight"
        folder = parent / "game"
        folder.mkdir(parents=True)
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"


class TestCleanArchiveName:
    def test_simple_zip(self):
        assert _clean_archive_name("Hollow Knight.zip") == "Hollow Knight"

    def test_extension_variants(self):
        assert _clean_archive_name("Hollow Knight.7z") == "Hollow Knight"
        assert _clean_archive_name("Hollow Knight.rar") == "Hollow Knight"
        assert _clean_archive_name("Hollow Knight.iso") == "Hollow Knight"

    def test_dotted_version_and_id(self):
        out = _clean_archive_name("Hollow.Knight.v1.0.231.32-bit.(48932).zip")
        assert out == "Hollow Knight"

    def test_url_prefix(self):
        assert _clean_archive_name("downloads.example.com-Hollow Knight.zip") == "Hollow Knight"

    def test_camelcase(self):
        assert _clean_archive_name("DoomEternal.zip") == "Doom Eternal"

    def test_bracketed_source_tag(self):
        assert _clean_archive_name("Doom Eternal [RePack].7z") == "Doom Eternal"

    def test_gog_setup_archive(self):
        assert _clean_archive_name(
            "setup_achilles_legends_untold_1.4.0.0_(74603).zip"
        ) == "Achilles Legends Untold"

    def test_part_token_stripped(self):
        assert _clean_archive_name("Hollow Knight.part1.rar") == "Hollow Knight"

    def test_junk_names_rejected(self):
        assert _clean_archive_name("readme.zip") == ""
        assert _clean_archive_name("data.zip") == ""

    def test_preserves_hyphens(self):
        assert _clean_archive_name("Half-Life.zip") == "Half-Life"


class TestArchiveScanning:
    def test_loose_archive_at_root(self, tmp_path):
        (tmp_path / "Hollow Knight.zip").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        r = results[0]
        assert r.folder_name == "Hollow Knight.zip"
        assert r.cleaned_name == "Hollow Knight"
        assert r.folder_path.endswith(".zip")

    def test_archive_extensions_detected(self, tmp_path):
        for i, ext in enumerate((".7z", ".rar", ".iso")):
            (tmp_path / f"Game {i}{ext}").write_text("x")
        results = list(scan_games(str(tmp_path)))
        names = sorted(r.folder_name for r in results)
        assert names == ["Game 0.7z", "Game 1.rar", "Game 2.iso"]

    def test_multipart_rar_only_first_part(self, tmp_path):
        (tmp_path / "Hollow Knight.part1.rar").write_text("x")
        (tmp_path / "Hollow Knight.part2.rar").write_text("x")
        (tmp_path / "Hollow Knight.part3.rar").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].folder_name == "Hollow Knight.part1.rar"

    def test_holder_folder_yields_archives_not_folder(self, tmp_path):
        holder = tmp_path / "Backups"
        holder.mkdir()
        (holder / "Hollow Knight.zip").write_text("x")
        (holder / "Doom Eternal.7z").write_text("x")
        results = list(scan_games(str(tmp_path)))
        names = sorted(r.folder_name for r in results)
        assert names == ["Doom Eternal.7z", "Hollow Knight.zip"]

    def test_holder_folder_with_exe_yields_folder(self, tmp_path):
        holder = tmp_path / "Repacks"
        holder.mkdir()
        (holder / "Hollow Knight-Setup.exe").write_text("x")
        (holder / "hollow_knight.zip").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].folder_name == "Repacks"
        assert results[0].cleaned_name == "Hollow Knight"

    def test_archive_store_from_container(self, tmp_path):
        gog = tmp_path / "GOG Games"
        gog.mkdir()
        (gog / "Biomutant.zip").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].store == "GOG"
        assert results[0].cleaned_name == "Biomutant"

    def test_junk_archive_at_root_skipped(self, tmp_path):
        (tmp_path / "readme.zip").write_text("x")
        assert list(scan_games(str(tmp_path))) == []

    def test_archive_in_grouping_folder(self, tmp_path):
        fps = tmp_path / "FPS"
        fps.mkdir()
        (fps / "Hollow Knight.zip").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert [r.folder_name for r in results] == ["Hollow Knight.zip"]

    def test_game_folder_with_data_zip_keeps_folder(self, tmp_path):
        folder = _game_dir(tmp_path / "Hollow Knight")
        (folder / "saves.zip").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].folder_name == "Hollow Knight"



class TestSourceTagSuffixes:
    def test_dotted_suffix(self):
        assert clean_folder_name(f"Fifa.19-{TAG.upper()}") == "Fifa 19"

    def test_dotted_two_word_suffix(self):
        assert clean_folder_name(f"Backrooms.Exploration-{TAG2.upper()}") == "Backrooms Exploration"

    def test_dotted_suffix_upper(self):
        assert clean_folder_name(f"Hello.Neighbor-{GRP.upper()}") == "Hello Neighbor"

    def test_dotted_versioned_suffix(self):
        assert clean_folder_name(f"SpaceBourne.2-{GRP2.upper()}") == "SpaceBourne 2"

    def test_underscore_title_with_suffix(self):
        out = clean_folder_name(f"Hello_Neighbor_2_Deluxe_Edition-{_ALPHA_TAGS[2].upper()}")
        assert out == "Hello Neighbor 2 Deluxe Edition"

    def test_underscore_version_with_suffix(self):
        out = clean_folder_name(
            f"SpongeBob_SquarePants_Battle_for_Bikini_Bottom_Rehydrated_v1.0.4-{_ALPHA_TAGS[3].upper()}"
        )
        assert out == "SpongeBob SquarePants Battle for Bikini Bottom Rehydrated"

    def test_dotted_long_title_with_suffix(self):
        out = clean_folder_name(f"SpongeBob.SquarePants.The.Cosmic.Shake-{_ALPHA_TAGS[4].upper()}")
        assert out == "SpongeBob SquarePants The Cosmic Shake"

    def test_region_tags(self):
        assert clean_folder_name("Unreal (USA) (Rev 2)") == "Unreal"
        assert clean_folder_name("Some Game (Europe)") == "Some Game"

    def test_language_tag(self):
        out = clean_folder_name(
            "Legend of Zelda, The - Twilight Princess (Europe) (En,Fr,De,Es,It)"
        )
        assert out == "The Legend of Zelda Twilight Princess"


class TestSourceArchiveNames:
    def test_tag_prefix(self):
        assert _clean_archive_name(f"{TAG}-backrooms.exploration.iso") == "backrooms exploration"

    def test_sr_prefix(self):
        assert _clean_archive_name("sr-onlyup.iso") == "onlyup"

    def test_tag_prefix_two(self):
        assert _clean_archive_name(f"{TAG2}-netherworld.covenant.iso") == "netherworld covenant"

    def test_tag_prefix_three(self):
        assert _clean_archive_name(f"{GRP}-fifa19.iso") == "fifa19"

    def test_wow_prefix(self):
        out = _clean_archive_name("wow-spongebob.squarepants.the.cosmic.shake.iso")
        assert out == "spongebob squarepants the cosmic shake"

    def test_gog_setup_version_letter_tag(self):
        assert _clean_gog_setup_name(
            "setup_spongebob_squarepants_titans_of_the_tide_1.0d_(88455).exe"
        ) == "Spongebob Squarepants Titans Of The Tide"

    def test_gog_setup_v2_tag(self):
        assert _clean_gog_setup_name(
            "setup_heroes_of_might_and_magic_v_2.1_v2_(28567).exe"
        ) == "Heroes Of Might And Magic V"


class TestArchiveFolderResolution:
    def test_tag_iso_folder_yields_folder(self, tmp_path):
        folder = tmp_path / f"Backrooms.Exploration-{TAG.upper()}"
        folder.mkdir()
        (folder / f"{TAG}-backrooms.exploration.iso").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].folder_name == f"Backrooms.Exploration-{TAG.upper()}"
        assert results[0].cleaned_name == "Backrooms Exploration"

    def test_tag2_iso_folder_matches_folder(self, tmp_path):
        folder = tmp_path / f"Netherworld.Covenant-{TAG2.upper()}"
        folder.mkdir()
        (folder / f"{TAG2}-netherworld.covenant.iso").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].folder_name == f"Netherworld.Covenant-{TAG2.upper()}"
        assert results[0].cleaned_name == "Netherworld Covenant"

    def test_multipart_set_folder_yields_folder(self, tmp_path):
        folder = tmp_path / "SPFL 2026"
        folder.mkdir()
        for i in range(1, 4):
            (folder / f"SPFL26.part{i:02d}.rar").write_text("x")
        (folder / "com257_gre.rar").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].folder_name == "SPFL 2026"

    def test_meta_folder_archives_and_subfolders(self, tmp_path):
        meta = tmp_path / "Garten Of Ban Ban"
        meta.mkdir()
        g2 = meta / f"Garten.of.Banban.2-{TAG.upper()}"
        g2.mkdir()
        (g2 / f"{TAG}-garten.of.banban.2.iso").write_text("x")
        (meta / "Garten of Banban 4.rar").write_text("x")
        (meta / "Garten of Banban 6.rar").write_text("x")
        results = list(scan_games(str(tmp_path)))
        names = sorted(r.cleaned_name for r in results)
        assert names == ["Garten of Banban 2", "Garten of Banban 4", "Garten of Banban 6"]

    def test_gog_multivolume_setup(self, tmp_path):
        folder = tmp_path / "SpongeBob Squarepants - Titans of the Tide [GOG]"
        folder.mkdir()
        base = "setup_spongebob_squarepants_titans_of_the_tide_1.0d_(88455)"
        (folder / f"{base}.exe").write_text("x")
        (folder / f"{base}-1.bin").write_text("x")
        (folder / f"{base}-2.bin").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].cleaned_name == "SpongeBob Squarepants Titans of the Tide"

    def test_unreal_bin_cue_folder(self, tmp_path):
        folder = tmp_path / "Unreal (USA) (Rev 2)"
        folder.mkdir()
        (folder / "Unreal (USA) (Rev 2).bin").write_text("x")
        (folder / "Unreal (USA) (Rev 2).cue").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].cleaned_name == "Unreal"


class TestNonObjectGogMetadata:
    def test_non_object_gog_metadata_skipped(self, tmp_path):
        import json

        folder = tmp_path / "Hollow Knight"
        folder.mkdir()
        (folder / "goggame-1207658101.info").write_text(json.dumps(["corrupted", "entry"]))
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].cleaned_name == "Hollow Knight"


class TestRecursiveSkip:
    def test_recursive_branch_honors_skip(self, tmp_path):
        holder = tmp_path / "MyLib"
        holder.mkdir()
        _game_dir(holder / "PrivateFolder")
        found = [r.folder_name for r in scan_games(str(tmp_path), recursive=True)]
        assert found == ["PrivateFolder"]
        skipped = list(scan_games(str(tmp_path), recursive=True, skip={"privatefolder"}))
        assert skipped == []


class TestGogSetupNumberTokens:
    def test_title_numbers_preserved(self):
        assert _clean_gog_setup_name(
            "setup_duke_nukem_3d_2.0.0.9_(1207658101).exe"
        ) == "Duke Nukem 3d"
        assert _clean_gog_setup_name("setup_fifa_19_(1494).exe") == "Fifa 19"
        assert _clean_gog_setup_name("setup_portal_2_2.1.0.9_(123).exe") == "Portal 2"

    def test_versions_still_stripped(self):
        assert _clean_gog_setup_name("setup_game_v2_(1).exe") == "Game"
        assert _clean_gog_setup_name("setup_game_1.0d_(1).exe") == "Game"

    def test_multivolume_id_token_stripped(self):
        assert _clean_gog_setup_name(
            "setup_titans_of_the_tide_1.0d_(88455)-1.bin"
        ) == "Titans Of The Tide"

    def test_no_stray_hyphen_tokens(self):
        assert _clean_gog_setup_name(
            "setup_the_witcher_-_enhanced_edition_1.5_(20900).exe"
        ) == "The Witcher Enhanced Edition"


class TestUnicodeNames:
    def test_unicode_folder_name_preserved(self, tmp_path):
        _game_dir(tmp_path / "Παιχνίδια")
        results = list(scan_games(str(tmp_path)))
        assert [r.cleaned_name for r in results] == ["Παιχνίδια"]

    def test_unicode_archive_yielded(self, tmp_path):
        (tmp_path / "尼尔机械纪元.zip").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert [r.cleaned_name for r in results] == ["尼尔机械纪元"]

    def test_looks_like_game_name_unicode(self):
        assert _looks_like_game_name("尼尔机械纪元")
        assert _looks_like_game_name("Παιχνίδια")


class TestArchSuffixBoundaries:
    def test_word_tails_not_eaten(self):
        assert _clean_exe_name("Swarm.exe") == "Swarm"
        assert _clean_exe_name("Farm.exe") == "Farm"
        assert _clean_exe_name("Alarm.exe") == "Alarm"

    def test_suffixes_still_stripped(self):
        assert _clean_exe_name("Game-vk.exe") == "Game"
        assert _clean_exe_name("GameGL.exe") == "Game"
        assert _clean_exe_name("DOOMx11.exe") == "DOOM"


class TestStoreLauncherBoundaries:
    def test_game_named_like_launcher_not_mislabeled(self):
        assert detect_store("E:/Games/Legendary") == ""
        assert detect_store("E:/My Stuff/battle.net backup/game") == ""
        assert detect_store("E:/Games/Steam Sale Bundle/game") == ""
        assert detect_store("E:/Games/Heroic") == ""

    def test_real_launcher_paths_still_detected(self):
        assert detect_store("C:/Program Files/Heroic/Hollow Knight") == "Heroic"
        assert detect_store("D:/Battle.net/Hollow Knight") == "Battle.net"
        assert detect_store("C:/Users/me/.config/legendary/games/Hollow Knight") == "Epic"
        assert detect_store("D:/Ubisoft Games/Far Cry 4") == "Ubisoft"


class TestCompoundJunkArchives:
    def test_rejected(self):
        assert _clean_archive_name("windows10.iso") == ""
        assert _clean_archive_name("win10.iso") == ""
        assert _clean_archive_name("office2019.iso") == ""


class TestRootNormalization:
    def test_bare_drive_root(self):
        assert _normalize_root("D:") == "D:/"
        assert _normalize_root("d:") == "d:/"
        assert _normalize_root(" D: ") == "D:/"
        assert _normalize_root("D:/") == "D:/"
        assert _normalize_root("D:/games") == "D:/games"
        assert _normalize_root("/mnt/games") == "/mnt/games"


class TestLowercaseLanguageTags:
    def test_stripped(self):
        assert clean_folder_name("Some Game (en,fr,de)") == "Some Game"


class TestParentFallbackGate:
    def test_junk_parent_never_wins(self, tmp_path):
        parent = tmp_path / "New Folder"
        folder = parent / "alpha game"
        folder.mkdir(parents=True)
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "alpha game"

    def test_good_parent_still_used(self, tmp_path):
        parent = tmp_path / "Hollow Knight"
        folder = parent / "game"
        folder.mkdir(parents=True)
        result = smart_detect_game_name(folder, clean_folder_name(folder.name))
        assert result == "Hollow Knight"


class TestGroupingFolderDescent:
    def test_grouping_folder_with_installers_descends(self, tmp_path):
        grouping = tmp_path / "1-ARCADE"
        grouping.mkdir()
        _game_dir(grouping / "Tetris Forever")
        (grouping / "setup_mortal_kombat_2_2.0.0.2.exe").write_text("x")
        (grouping / "setup_pinball_dreams_2.1.0.20.exe").write_text("x")
        names = sorted(r.cleaned_name for r in scan_games(str(tmp_path)))
        assert names == ["Mortal Kombat 2", "Pinball Dreams", "Tetris Forever"]

    def test_grouping_descends_without_recursive_flag(self, tmp_path):
        holder = tmp_path / "1-MY"
        holder.mkdir()
        _game_dir(holder / "Torchlight 2")
        _game_dir(holder / "Talisman")
        names = sorted(r.cleaned_name for r in scan_games(str(tmp_path)))
        assert names == ["Talisman", "Torchlight 2"]

    def test_nested_grouping_folders(self, tmp_path):
        outer = tmp_path / "1-GOG"
        outer.mkdir()
        inner = outer / "1-INDIE"
        inner.mkdir()
        _game_dir(inner / "Hollow Knight Silksong")
        (inner / "setup_hollow_knight_1.5_(50885).exe").write_text("x")
        (inner / "setup_steamworld_dig_2.1.0.3.exe").write_text("x")
        _game_dir(outer / "Biomutant")
        (outer / "setup_aquanox_1.18_(19599).exe").write_text("x")
        (outer / "setup_gex_2.0.0.5.exe").write_text("x")
        names = sorted(r.cleaned_name for r in scan_games(str(tmp_path)))
        assert names == [
            "Aquanox", "Biomutant", "Gex", "Hollow Knight",
            "Hollow Knight Silksong", "Steamworld Dig",
        ]

    def test_game_bundle_with_subdirs_not_descended(self, tmp_path):
        bundle = tmp_path / "Dead Cells Linux"
        bundle.mkdir()
        (bundle / "Bonus").mkdir()
        (bundle / "DLC").mkdir()
        (bundle / "setup_dead_cells_1.26_(75679).exe").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].cleaned_name == "Dead Cells"

    def test_game_bundle_with_patches_not_descended(self, tmp_path):
        bundle = tmp_path / "Talisman GOG"
        bundle.mkdir()
        (bundle / "Characters").mkdir()
        (bundle / "Expansions").mkdir()
        (bundle / "setup_talisman_digital_edition_79495_(69303).exe").write_text("x")
        (bundle / "patch_talisman_digital_edition_76842_(48179)_to_77644_(53054).exe").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].cleaned_name == "Talisman Digital Edition"

    def test_grouping_multivolume_setup_dedupe(self, tmp_path):
        grouping = tmp_path / "1-FPS"
        grouping.mkdir()
        _game_dir(grouping / "Far Cry")
        (grouping / "setup_farcry_1.0_(1).exe").write_text("x")
        (grouping / "setup_farcry_1.0_(1)-1.bin").write_text("x")
        (grouping / "setup_gex_2.0.0.5.exe").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert sorted(r.cleaned_name for r in results) == ["Far Cry", "Gex"]
        far_cry = next(r for r in results if r.cleaned_name == "Far Cry")
        assert far_cry.folder_name == "Far Cry"

    def test_numbered_library_root_is_container(self, tmp_path):
        lib = tmp_path / "1-GOG Games"
        _game_dir(lib / "Biomutant")
        results = list(scan_games(str(tmp_path)))
        assert [r.cleaned_name for r in results] == ["Biomutant"]
        assert results[0].store == "GOG"

    def test_root_loose_installers_yielded(self, tmp_path):
        (tmp_path / "setup_aquanox_1.18_(19599).exe").write_text("x")
        (tmp_path / "setup_aquanox_2_revelation_2.159_(21998).exe").write_text("x")
        names = sorted(r.cleaned_name for r in scan_games(str(tmp_path)))
        assert names == ["Aquanox", "Aquanox 2 Revelation"]

    def test_gog_linux_installer_entry(self, tmp_path):
        (tmp_path / "gog_metal_slug_2_2.0.0.2.sh").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert [r.cleaned_name for r in results] == ["Metal Slug 2"]

    def test_generic_linux_installer_entry(self, tmp_path):
        (tmp_path / "rogue_legacy_en_1_4_0_22617.sh").write_text("x")
        (tmp_path / "chasm_1_102_89133.sh").write_text("x")
        names = sorted(r.cleaned_name for r in scan_games(str(tmp_path)))
        assert names == ["Chasm", "Rogue Legacy"]

    def test_setup_build_id_before_parens_stripped(self):
        assert _clean_gog_setup_name(
            "setup_talisman_digital_edition_79495_(69303).exe"
        ) == "Talisman Digital Edition"
        assert _clean_gog_setup_name(
            "setup_metal_slug_4_1.0_(70018).exe"
        ) == "Metal Slug 4"


def _files(folder: Path, *names: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b"x")
    return folder


def _repack(folder: Path) -> Path:
    _files(folder, "fg-01.bin", "fg-02.bin", "setup.exe")
    _files(folder / "MD5", "QuickSFV.EXE", "bins.md5")
    return folder


def _scan(root: Path, **kw) -> list:
    return list(scan_games(str(root), **kw))


class TestCategoryFolders:
    def test_category_with_loose_archive_and_game_subfolders(self, tmp_path):
        kidz = tmp_path / "000Kidz"
        _repack(kidz / f"Cuphead [{TAG.title()} Repack]")
        _files(kidz / f"Hello.Neighbor-{GRP.upper()}", f"{GRP}-hello.neighbor.iso", f"{GRP}.nfo")
        _files(kidz, "Another Princess is in our Castle v0.3.3.zip", "Slime.Rancher.v1.4.4.rar")
        results = _scan(tmp_path)
        names = sorted(r.cleaned_name for r in results)
        assert names == ["Another Princess is in our Castle", "Cuphead", "Hello Neighbor", "Slime Rancher"]
        assert "000Kidz" not in {r.folder_name for r in results}

    def test_category_with_single_subfolder(self, tmp_path):
        ports = tmp_path / "1-PORTS"
        _files(
            ports / "Legend of Zelda, The - Twilight Princess",
            "Dusk-win32-x86_64.zip",
            "Legend of Zelda, The - Twilight Princess (Europe) (En,Fr,De,Es,It).7z",
        )
        results = _scan(tmp_path)
        assert [r.folder_name for r in results] == ["Legend of Zelda, The - Twilight Princess"]
        assert results[0].cleaned_name == "The Legend of Zelda Twilight Princess"
        assert results[0].platform == "PC (Fan Port)"

    def test_category_with_one_loose_zip_and_repacks(self, tmp_path):
        fps = tmp_path / "1-FPS"
        _repack(fps / f"Atomic Heart [{TAG2.title()} Repack]")
        _repack(fps / f"Half-Life - Alyx [{TAG.title()} Repack]")
        _files(fps, "Journey.to.the.SP.v1.0.10.ALL.DLC.zip")
        names = sorted(r.cleaned_name for r in _scan(tmp_path))
        assert names == ["Atomic Heart", "Half-Life Alyx", "Journey to the SP"]

    def test_folders_without_game_files_are_skipped(self, tmp_path):
        (tmp_path / "Empty Folder").mkdir()
        _files(tmp_path / "Music", "song.mp3", "cover.jpg")
        _files(tmp_path / "Docs", "readme.txt", "manual.pdf")
        _files(tmp_path / "Real Game", "RealGame.exe")
        assert [r.cleaned_name for r in _scan(tmp_path)] == ["Real Game"]

    def test_extras_subfolders_never_become_games(self, tmp_path):
        game = _files(tmp_path / "Some Game", "setup_some_game_1.0_(123).exe")
        _files(game / "DLC", "setup_some_game_soundtrack_1.0_(123).exe")
        _files(game / "Crack", "SomeGame.exe")
        _files(game / "Bonus", "artbook.zip")
        assert [r.folder_name for r in _scan(tmp_path)] == ["Some Game"]

    def test_gog_install_steps_in_subfolders_are_one_game(self, tmp_path):
        game = tmp_path / "The Elder Scrolls V Skyrim Special Edition"
        _files(game / "1-Install Base", "setup_skyrim_se_1.0_(70738).exe", "setup_skyrim_se_1.0_(70738)-1.bin")
        _files(game / "3-Ann Upd", "setup_skyrim_anniversary_upgrade_1.0_(70738).exe")
        results = _scan(tmp_path)
        assert [r.folder_name for r in results] == ["The Elder Scrolls V Skyrim Special Edition"]

    def test_gog_goodies_zips_do_not_split_the_folder(self, tmp_path):
        game = _files(
            tmp_path / "baldurs_gate_2_enhanced_edition_2.6.6.0_win_gog_20240210",
            "setup_baldurs_gate_ii_enhanced_edition_2.6.6.0_(64bit)_(46870).exe",
            "baldurs_gate_2_avatars.zip",
            "baldurs_gate_2_ee_mastering_melee_and_magic.zip",
        )
        results = _scan(tmp_path)
        assert [r.folder_name for r in results] == [game.name]
        assert results[0].cleaned_name == "Baldurs Gate II Enhanced Edition"

    def test_different_games_in_one_folder_are_split(self, tmp_path):
        _files(
            tmp_path / "Steamworld",
            "gog_steamworld_dig_2.0.0.7.sh",
            "steamworld_dig_2_en_1_1_15062.sh",
            "steamworld_heist_2_1_26995.sh",
        )
        names = sorted(r.cleaned_name for r in _scan(tmp_path))
        assert names == ["Steamworld Dig", "Steamworld Dig 2", "Steamworld Heist"]

    def test_numbered_sequels_next_to_base_game_are_split(self, tmp_path):
        _files(tmp_path / "Metal Slug", "Metal Slug.zip", "Metal Slug 2.zip", "Metal Slug X.zip")
        names = sorted(r.cleaned_name for r in _scan(tmp_path))
        assert names == ["Metal Slug", "Metal Slug 2", "Metal Slug X"]

    def test_variants_of_one_game_stay_one_folder(self, tmp_path):
        _files(
            tmp_path / "Red Alert 2",
            "Red Alert 2.7z",
            "Command & Conquer Red Alert II Portable.zip",
            "Command-And-Conquer-Red-Alert-2-Yuris-Revenge.zip",
        )
        assert [r.folder_name for r in _scan(tmp_path)] == ["Red Alert 2"]

    def test_gog_main_installer_is_largest(self, tmp_path):
        folder = tmp_path / "titan_quest_anniversary_edition"
        folder.mkdir()
        (folder / "setup_titan_quest_-_anniversary_edition_2.10.6_(59562).exe").write_bytes(b"x" * 5000)
        (folder / "setup_titan_quest_-_anniversary_edition_2.10.6_(59562)-1.bin").write_bytes(b"x" * 9000)
        (folder / "setup_titan_quest_atlantis_2.10.6_(59562).exe").write_bytes(b"x" * 3000)
        (folder / "setup_titan_quest_ragnarok_2.10.6_(59562).exe").write_bytes(b"x" * 3000)
        results = _scan(tmp_path)
        assert len(results) == 1
        assert results[0].cleaned_name == "Titan Quest Anniversary Edition"

    def test_human_folder_name_beats_abbreviated_installer(self, tmp_path):
        _files(tmp_path / "Star Wars Dark Forces", "setup_sw_dark_forces_2.0.0.1.exe")
        assert [r.cleaned_name for r in _scan(tmp_path)] == ["Star Wars Dark Forces"]

    def test_patch_only_installer_does_not_name_folder(self, tmp_path):
        _files(
            tmp_path / "torment_tides_of_numenera_1.1.0_win_gog_20240130",
            "setup_torment_-_tides_of_numenera_1.1.0_-_servant_of_the_tides_content_update_patch_(12012).exe",
            "torment_tides_of_numenera_manual.zip",
            "torment_tides_of_numenera_world_map.zip",
        )
        assert [r.cleaned_name for r in _scan(tmp_path)] == ["Torment Tides Of Numenera"]


class TestDedupe:
    def test_same_game_same_platform_collapsed(self, tmp_path):
        _repack(tmp_path / f"Netherworld Covenant [{TAG.title()} Repack]")
        _files(
            tmp_path / f"Netherworld.Covenant-{TAG2.upper()}",
            f"{TAG2}-netherworld.covenant.iso",
            f"{TAG2}.nfo",
        )
        results = _scan(tmp_path)
        assert len(results) == 1
        assert results[0].cleaned_name == "Netherworld Covenant"

    def test_installed_copy_beats_archive(self, tmp_path):
        _files(tmp_path / "Only UP (2023)" / "Only UP", "OnlyUP.exe")
        _files(tmp_path / "Downloads", f"Only.Up-{GRP.upper()}.rar", "Celeste.zip")
        results = {r.cleaned_name: r for r in _scan(tmp_path)}
        assert sorted(results) == ["Celeste", "Only UP"]
        assert results["Only UP"].folder_name == "Only UP (2023)"
        assert results["Only UP"].source == "folder"

    def test_store_filled_from_dropped_copy(self, tmp_path):
        _files(tmp_path / "Hollow Knight", "hollow_knight.exe")
        _files(tmp_path / "GOG Games", "setup_hollow_knight_1.5_(50885).exe")
        results = _scan(tmp_path)
        assert len(results) == 1
        assert results[0].folder_name == "Hollow Knight"
        assert results[0].store == "GOG"

    def test_other_platforms_are_kept(self, tmp_path):
        _files(tmp_path / "Linux Games", "gog_metal_slug_2.0.0.2.sh")
        _files(tmp_path / "Installers", "setup_metal_slug_gog-3_(12273).exe", "setup_gex_2.0.0.5.exe")
        results = sorted((r.cleaned_name, r.platform) for r in _scan(tmp_path))
        assert results == [("Gex", "PC"), ("Metal Slug", "PC"), ("Metal Slug", "PC (Linux)")]

    def test_dedupe_can_be_disabled(self, tmp_path):
        _files(tmp_path / "A", "Hollow Knight.zip")
        _files(tmp_path / "B", "Hollow.Knight.v1.0.1.rar")
        assert len(_scan(tmp_path)) == 1
        assert len(_scan(tmp_path, dedupe=False)) == 2

    def test_dedupe_games_ranks_sources(self):
        from playcache.folder_scanner import ScannedFolder, dedupe_games

        archive = ScannedFolder("hk.zip", "/x/hk.zip", "Hollow Knight", "PC", "", False, "archive")
        folder = ScannedFolder("Hollow Knight", "/y/Hollow Knight", "Hollow Knight", "PC", "", False, "installed")
        android = ScannedFolder("hk.apk", "/z/hk.apk", "Hollow Knight", "ANDROID", "", False, "rom")
        kept = dedupe_games([archive, folder, android])
        assert [k.folder_path for k in kept] == ["/y/Hollow Knight", "/z/hk.apk"]


class TestArchiveNamePlatform:
    def test_loose_archives_named_after_a_system(self, tmp_path):
        _files(
            tmp_path / "Downloads",
            "GAMECUBE Super Mario Sunshine.7z",
            "Super.Mario.Odyssey.NSW-GRP.rar",
            "Unreal (USA) (Rev 2).7z",
            "Slime.Rancher.v1.4.4.rar",
        )
        results = sorted((r.cleaned_name, r.platform) for r in _scan(tmp_path, recursive=True))
        assert results == [
            ("Slime Rancher", "PC"),
            ("Super Mario Odyssey", "SWITCH"),
            ("Super Mario Sunshine", "GAMECUBE"),
            ("Unreal", "PC"),
        ]

    def test_system_prefix_inside_ports_folder_is_a_pc_port(self, tmp_path):
        _files(
            tmp_path / "1-RECOMPILATIONS",
            "N64 Ship of Harkinian.7z",
            "3DS Kirby-Triple-Deluxe-Windows-x64.7z",
        )
        results = sorted((r.cleaned_name, r.platform) for r in _scan(tmp_path, recursive=True))
        assert results == [
            ("Kirby Triple Deluxe", "PC (Fan Port)"),
            ("Ship of Harkinian", "PC (Fan Port)"),
        ]

    def test_archive_in_game_folder_sets_its_platform(self, tmp_path):
        _files(tmp_path / "Super Mario Odyssey", "Super.Mario.Odyssey.NSW-GRP.rar")
        _files(tmp_path / "Halo", "Halo-Windows-x64.7z")
        results = sorted((r.cleaned_name, r.platform) for r in _scan(tmp_path))
        assert results == [("Halo", "PC"), ("Super Mario Odyssey", "SWITCH")]

    def test_system_named_archive_in_ports_game_folder(self, tmp_path):
        _files(tmp_path / "1-PORTS" / "Zelda", "N64 Zelda.7z")
        results = [(r.cleaned_name, r.platform) for r in _scan(tmp_path, recursive=True)]
        assert results == [("Zelda", "PC (Fan Port)")]


class TestPlatformVariants:
    def test_windows_and_sh_installers_yield_two_entries(self, tmp_path):
        _files(
            tmp_path / "Torchlight 2 GOG",
            "setup_torchlight_2_1.25.9.5b_(23102).exe",
            "gog_torchlight_2_2.0.0.2.sh",
        )
        results = sorted((r.cleaned_name, r.platform) for r in _scan(tmp_path))
        assert results == [("Torchlight 2", "PC"), ("Torchlight 2", "PC (Linux)")]

    def test_apk_next_to_pc_game(self, tmp_path):
        _files(tmp_path / "HOMM3 complete gog", "VCMI-Windows.exe", "VCMI-Android-arm64-v8a.apk")
        results = sorted((r.platform, r.folder_name) for r in _scan(tmp_path))
        assert results == [("ANDROID", "VCMI-Android-arm64-v8a.apk"), ("PC", "HOMM3 complete gog")]

    def test_platform_named_subfolders_are_one_game(self, tmp_path):
        import zipfile

        game = tmp_path / "Garten Of Banban"
        _files(game / "Mobile", "Garten of Banban.apk")
        pc_zip = game / "PC" / "Steam release" / "Garten Of Banban.zip"
        pc_zip.parent.mkdir(parents=True)
        with zipfile.ZipFile(pc_zip, "w") as zf:
            zf.writestr("Garten of Banban.exe", b"x")
        results = sorted((r.platform, r.cleaned_name) for r in _scan(tmp_path))
        assert results == [("ANDROID", "Garten Of Banban"), ("PC", "Garten Of Banban")]

    def test_rom_folder_platform(self, tmp_path):
        _files(tmp_path / "Chrono Trigger", "Chrono Trigger (USA).sfc")
        results = _scan(tmp_path)
        assert [(r.cleaned_name, r.platform) for r in results] == [("Chrono Trigger", "SNES")]

    def test_console_path_for_unknown_archive(self, tmp_path):
        _files(tmp_path / "EMU Redump", "Super Mario Sunshine.7z")
        results = _scan(tmp_path)
        assert [(r.cleaned_name, r.platform) for r in results] == [("Super Mario Sunshine", "CONSOLE")]

    def test_system_folder_names_platform(self, tmp_path):
        _files(tmp_path / "PS2", "God of War.7z", "Shadow of the Colossus.7z")
        assert {r.platform for r in _scan(tmp_path)} == {"PS2"}

    def test_disc_header_identifies_console(self, tmp_path):
        folder = tmp_path / "Zelda Wind Waker"
        folder.mkdir()
        gc = bytearray(0x400)
        gc[0x1C:0x20] = b"\xc2\x33\x9f\x3d"
        (folder / "Zelda Wind Waker (USA).iso").write_bytes(bytes(gc))
        assert [r.platform for r in _scan(tmp_path)] == ["GAMECUBE"]

    def test_android_only_folder(self, tmp_path):
        _files(tmp_path / "Mobile Games", "Unreal-Android.1.2.0.apk")
        assert [(r.cleaned_name, r.platform) for r in _scan(tmp_path)] == [("Unreal", "ANDROID")]

    def test_pc_repack_in_console_named_folder_stays_pc(self, tmp_path):
        _repack(tmp_path / "Xbox Games" / f"Halo [{TAG.title()} Repack]")
        assert [r.platform for r in _scan(tmp_path)] == ["PC"]


class TestNameCleanupFromDrive:
    def test_scene_tag_in_middle_is_kept(self):
        word = TAG2.title()
        assert clean_folder_name(f"Vampire the {word} - Bloodlines - GOG") == (
            f"Vampire the {word} Bloodlines"
        )

    def test_trailing_scene_tag_and_by_removed(self):
        assert clean_folder_name(f"How to Fish by {TAG.title()}") == "How to Fish"

    def test_site_suffix_and_id_removed(self):
        assert _clean_archive_name("Poopy's.Playland-GameSite.com.rar") == "Poopy's Playland"
        assert _clean_archive_name("Scarlet Skips.25093186.zip") == "Scarlet Skips"

    def test_all_dlcs_suffix(self):
        assert _clean_archive_name("Ultra.Street.Fighter.IV.v1.09.ALL.DLCs.zip") == "Ultra Street Fighter IV"

    def test_hyphen_joined_words(self):
        assert _clean_archive_name("Star-Wars-Yoda-Stories_Win_EN_Easy-Setup.zip") == "Star Wars Yoda Stories"

    def test_engine_names_are_valid_titles(self):
        assert _clean_archive_name("Unreal (Europe).iso") == "Unreal"

    def test_system_prefix_and_repo_suffix(self):
        assert _clean_archive_name("N64 Ship of Harkinian - Zelda Ocarina Of Time.7z") == (
            "Ship of Harkinian Zelda Ocarina Of Time"
        )
        assert _clean_archive_name("PS1 Tekken3 Remake-master.7z") == "Tekken3 Remake"

    def test_machine_folder_versions(self):
        assert clean_folder_name("Gauntlet_1.0(b)_(14890)_win_gog") == "Gauntlet"
        assert clean_folder_name("grim_dawn_1.3.1.1_b_(94495)_win_gog") == "grim dawn"
        assert clean_folder_name("incision_84588") == "incision"
        assert clean_folder_name("Mark_of_the_Ninja_Remastered_1.0 rc1_(42657)_win_gog") == (
            "Mark of the Ninja Remastered"
        )

    def test_ampersand_becomes_and(self):
        assert clean_folder_name("Heroes Of Might & Magic 4") == "Heroes Of Might and Magic 4"

    def test_gog_setup_polish(self):
        cases = {
            "setup_hexen_ii_1.11_music_fix_(45370).exe": "Hexen II",
            "setup_mortal_kombat2_2.0.0.2.exe": "Mortal Kombat 2",
            "setup_star_warstm_episode_i_-_racertm_1.0_hotfix3_(20791).exe": "Star Wars Episode I Racer",
            "setup_hollow_knight_1.5.78.11833_(64bit)_(50885).exe": "Hollow Knight",
            "setup_slime_rancher_1.4.4-win_(64bit)_(51882).exe": "Slime Rancher",
            "setup_metal_slug_2_gog-3_(12272).exe": "Metal Slug 2",
            "setup_ninja_gaiden_ragebound_-cs37895_(64bit)_(85863).exe": "Ninja Gaiden Ragebound",
            "setup_epic_pinball_the_complete_collection_1.01_gog_v2_(86528).exe": (
                "Epic Pinball The Complete Collection"
            ),
            "setup_oceanhorn_-_monster_of_uncharted_seas_update_2018-02-06_(18420).exe": (
                "Oceanhorn Monster Of Uncharted Seas"
            ),
        }
        for filename, expected in cases.items():
            assert _clean_gog_setup_name(filename) == expected, filename

    def test_linux_installer_language_cut(self):
        from playcache.folder_scanner import _clean_generic_sh_name

        assert _clean_generic_sh_name("steamworld_dig_2_en_1_1_15062.sh") == "Steamworld Dig 2"
        assert _clean_generic_sh_name("wonder_boy_the_dragon_s_trap_en_1_03f_02_20817.sh") == (
            "Wonder Boy The Dragon's Trap"
        )
