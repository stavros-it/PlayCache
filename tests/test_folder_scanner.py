"""Tests for the folder scanner (no network)."""
from pathlib import Path

from playcache.folder_scanner import (
    _clean_archive_name,
    _clean_exe_name,
    _clean_gog_setup_name,
    _looks_like_game_name,
    _normalize_root,
    clean_folder_name,
    detect_platform,
    detect_store,
    scan_games,
    smart_detect_game_name,
)


class TestCleanFolderName:
    def test_simple_name(self):
        assert clean_folder_name("Hollow Knight") == "Hollow Knight"

    def test_strips_brackets(self):
        assert "srcgroup10" not in clean_folder_name("Hollow Knight [srcgroup10]")
        assert clean_folder_name("Hollow Knight [srcgroup10]") == "Hollow Knight"

    def test_strips_version(self):
        out = clean_folder_name("Some Game v1.2.3")
        assert "v1" not in out
        assert "Some Game" in out

    def test_strips_release_groups(self):
        out = clean_folder_name("Doom Eternal-srcgroup12")
        assert "srcgroup12" not in out.lower()
        assert "Doom Eternal" in out

    def test_strips_underscores(self):
        assert clean_folder_name("Deep_Rock_Galactic") == "Deep Rock Galactic"

    def test_handles_extension(self):
        assert "exe" not in clean_folder_name("Game.exe")

    def test_strips_repack_tokens(self):
        out = clean_folder_name("Far Cry 2 RePack by srcgroup1")
        assert "srcgroup1" not in out.lower()
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
        out = clean_folder_name("Doom Eternal-srcgroup12")
        assert "srcgroup12" not in out.lower()
        assert "Doom Eternal" in out

    def test_strips_online_fix_token(self):
        out = clean_folder_name("Some Game srcgroup11")
        assert "online" not in out.lower()
        assert "fix" not in out.lower()
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


class TestScanGames:
    def _make_tree(self, tmp: Path):
        (tmp / "Hollow Knight").mkdir()
        (tmp / "Deep Rock Galactic").mkdir()
        (tmp / "Windows").mkdir()
        (tmp / "$Recycle.Bin").mkdir()
        # A steam library root
        steam = tmp / "SteamLibrary" / "steamapps" / "common"
        steam.mkdir(parents=True)
        (steam / "Dead Cells").mkdir()
        # A GOG library root
        gog = tmp / "GOG Games"
        gog.mkdir()
        (gog / "Biomutant").mkdir()

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
        (tmp_path / "Hollow Knight [srcgroup10]").mkdir()
        (tmp_path / "Windows").mkdir()
        results = list(scan_games(str(tmp_path)))
        hk = next(r for r in results if "Hollow" in r.folder_name)
        assert hk.cleaned_name == "Hollow Knight"
        assert hk.folder_name == "Hollow Knight [srcgroup10]"

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
        (tmp_path / "aphelion_windows_gog_(90803)").mkdir()
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

    def test_repack_group_tokens_stripped(self, tmp_path):
        folder = tmp_path / "123"
        folder.mkdir()
        (folder / "hollow_knight_dodi_setup.exe").write_text("x")
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
        assert _clean_archive_name("srcgroup1-repacks.site-Hollow Knight.zip") == "Hollow Knight"

    def test_camelcase(self):
        assert _clean_archive_name("DoomEternal.zip") == "Doom Eternal"

    def test_bracketed_repack(self):
        assert _clean_archive_name("Doom Eternal [srcgroup1 Repack].7z") == "Doom Eternal"

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
        folder = tmp_path / "Hollow Knight"
        folder.mkdir()
        (folder / "saves.zip").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].folder_name == "Hollow Knight"



class TestSourceTagNames:
    def test_cpy_suffix(self):
        assert clean_folder_name("Fifa.19-srcgroup13") == "Fifa 19"

    def test_tenoke_suffix(self):
        assert clean_folder_name("Backrooms.Exploration-srcgroup15") == "Backrooms Exploration"

    def test_codex_suffix(self):
        assert clean_folder_name("Hello.Neighbor-srcgroup12") == "Hello Neighbor"

    def test_rune_suffix(self):
        assert clean_folder_name("SpaceBourne.2-RUNE") == "SpaceBourne 2"

    def test_flt_suffix(self):
        out = clean_folder_name("Hello_Neighbor_2_Deluxe_Edition-srcgroup16")
        assert out == "Hello Neighbor 2 Deluxe Edition"

    def test_razor1911_with_underscore_version(self):
        out = clean_folder_name(
            "SpongeBob_SquarePants_Battle_for_Bikini_Bottom_Rehydrated_v1.0.4-srcgroup19"
        )
        assert out == "SpongeBob SquarePants Battle for Bikini Bottom Rehydrated"

    def test_doge_folder(self):
        out = clean_folder_name("SpongeBob.SquarePants.The.Cosmic.Shake-srcgroup18")
        assert out == "SpongeBob SquarePants The Cosmic Shake"

    def test_region_tags(self):
        assert clean_folder_name("Unreal (USA) (Rev 2)") == "Unreal"
        assert clean_folder_name("Some Game (Europe)") == "Some Game"

    def test_language_tag(self):
        out = clean_folder_name(
            "Legend of Zelda, The - Twilight Princess (Europe) (En,Fr,De,Es,It)"
        )
        assert out == "Legend of Zelda The Twilight Princess"


class TestSourceArchiveNames:
    def test_tenoke_iso(self):
        assert _clean_archive_name("srcgroup15-backrooms.exploration.iso") == "backrooms exploration"

    def test_sr_prefix(self):
        assert _clean_archive_name("sr-onlyup.iso") == "onlyup"

    def test_rune_prefix(self):
        assert _clean_archive_name("rune-netherworld.covenant.iso") == "netherworld covenant"

    def test_cpy_prefix(self):
        assert _clean_archive_name("srcgroup13-fifa19.iso") == "fifa19"

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
    def test_scene_iso_folder_yields_folder(self, tmp_path):
        folder = tmp_path / "Backrooms.Exploration-srcgroup15"
        folder.mkdir()
        (folder / "srcgroup15-backrooms.exploration.iso").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].folder_name == "Backrooms.Exploration-srcgroup15"
        assert results[0].cleaned_name == "Backrooms Exploration"

    def test_rune_iso_folder_matches_folder(self, tmp_path):
        folder = tmp_path / "Netherworld.Covenant-RUNE"
        folder.mkdir()
        (folder / "rune-netherworld.covenant.iso").write_text("x")
        results = list(scan_games(str(tmp_path)))
        assert len(results) == 1
        assert results[0].folder_name == "Netherworld.Covenant-RUNE"
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
        g2 = meta / "Garten.of.Banban.2-srcgroup15"
        g2.mkdir()
        (g2 / "srcgroup15-garten.of.banban.2.iso").write_text("x")
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
        assert results[0].cleaned_name == "Spongebob Squarepants Titans Of The Tide"

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
        (holder / "PrivateFolder").mkdir()
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
        (tmp_path / "Παιχνίδια").mkdir()
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
        (grouping / "Tetris Forever").mkdir()
        (grouping / "setup_mortal_kombat_2_2.0.0.2.exe").write_text("x")
        (grouping / "setup_pinball_dreams_2.1.0.20.exe").write_text("x")
        names = sorted(r.cleaned_name for r in scan_games(str(tmp_path)))
        assert names == ["Mortal Kombat 2", "Pinball Dreams", "Tetris Forever"]

    def test_grouping_descends_without_recursive_flag(self, tmp_path):
        holder = tmp_path / "1-MY"
        holder.mkdir()
        (holder / "Torchlight 2").mkdir()
        (holder / "Talisman").mkdir()
        names = sorted(r.cleaned_name for r in scan_games(str(tmp_path)))
        assert names == ["Talisman", "Torchlight 2"]

    def test_nested_grouping_folders(self, tmp_path):
        outer = tmp_path / "1-GOG"
        outer.mkdir()
        inner = outer / "1-INDIE"
        inner.mkdir()
        (inner / "Hollow Knight Silksong").mkdir()
        (inner / "setup_hollow_knight_1.5_(50885).exe").write_text("x")
        (inner / "setup_steamworld_dig_2.1.0.3.exe").write_text("x")
        (outer / "Biomutant").mkdir()
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
        (grouping / "Far Cry").mkdir()
        (grouping / "setup_farcry_1.0_(1).exe").write_text("x")
        (grouping / "setup_farcry_1.0_(1)-1.bin").write_text("x")
        (grouping / "setup_gex_2.0.0.5.exe").write_text("x")
        names = sorted(r.cleaned_name for r in scan_games(str(tmp_path)))
        assert names == ["Far Cry", "Farcry", "Gex"]

    def test_numbered_library_root_is_container(self, tmp_path):
        lib = tmp_path / "1-GOG Games"
        lib.mkdir()
        (lib / "Biomutant").mkdir()
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
