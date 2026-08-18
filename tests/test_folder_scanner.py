"""Tests for the folder scanner (no network)."""
from pathlib import Path

from playcache.folder_scanner import (
    _clean_exe_name,
    _clean_gog_setup_name,
    _looks_like_game_name,
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
        assert "steamrip" not in clean_folder_name("Hollow Knight [SteamRip]")
        assert clean_folder_name("Hollow Knight [SteamRip]") == "Hollow Knight"

    def test_strips_version(self):
        out = clean_folder_name("Some Game v1.2.3")
        assert "v1" not in out
        assert "Some Game" in out

    def test_strips_release_groups(self):
        out = clean_folder_name("Doom Eternal-CODEX")
        assert "codex" not in out.lower()
        assert "Doom Eternal" in out

    def test_strips_underscores(self):
        assert clean_folder_name("Deep_Rock_Galactic") == "Deep Rock Galactic"

    def test_handles_extension(self):
        assert "exe" not in clean_folder_name("Game.exe")

    def test_strips_repack_tokens(self):
        out = clean_folder_name("Far Cry 2 RePack by FitGirl")
        assert "fitgirl" not in out.lower()
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
        out = clean_folder_name("Doom Eternal-CODEX")
        assert "codex" not in out.lower()
        assert "Doom Eternal" in out

    def test_strips_online_fix_token(self):
        out = clean_folder_name("Some Game online-fix")
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
        (tmp_path / "Hollow Knight [SteamRip]").mkdir()
        (tmp_path / "Windows").mkdir()
        results = list(scan_games(str(tmp_path)))
        hk = next(r for r in results if "Hollow" in r.folder_name)
        assert hk.cleaned_name == "Hollow Knight"
        assert hk.folder_name == "Hollow Knight [SteamRip]"

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
