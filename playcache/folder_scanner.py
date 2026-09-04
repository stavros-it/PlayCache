"""Scan a drive/folder for installed games and produce clean, searchable names.

A "game folder" is a directory whose name carries the game title. The scanner:
  * lists the immediate children of the given root
  * descends into recognised library roots (steamapps/common, GOG Games, ...)
  * skips system/hidden folders on a drive root
  * strips release-group/version noise from folder names for better API matching
  * smart-detects game names from metadata files, GOG setup executables,
    and game .exe files when the folder name is noisy or unhelpful
  * treats game archives (.zip/.7z/.rar/.iso) as games in their own right,
    parsing the title out of the archive filename
  * guesses the store (Steam / GOG / Epic / ...) from the path
"""
from __future__ import annotations

import json
import logging
import os
import re
import struct
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from string import capwords

log = logging.getLogger(__name__)

# Root folders that are definitely not games (typical OS drive contents).
# Union of Windows + Linux system folders so the scanner works on both.
DEFAULT_SKIP = {
    # Windows
    "windows", "program files", "program files (x86)", "programdata", "users",
    "$recycle.bin", "system volume information", "$winreagent", "$sysreset",
    "$windows.~bt", "recovery", "perflogs", "intel", "amd", "nvidia",
    "msocache", "config.msi",
    # Linux
    "boot", "bin", "sbin", "etc", "var", "usr", "lib", "lib64", "lib32",
    "libx32", "run", "sys", "proc", "dev", "srv", "snap", "lost+found",
    "swapfile", ".cache", ".config", ".local", "node_modules",
}

# Folder NAMES (lowercased) that are library containers, not games.
CONTAINER_NAMES = {
    "steamapps", "common", "gog games", "gog game", "epic games",
    "origin games", "steamlibrary", "battle.net", "battlenet",
    "ubisoft", "ubisoft game launcher", "ubisoft games",
    "games", "game library",
}

# Path patterns -> store label. Used to GUESS the store from a full path.
LIBRARY_ROOTS: list[tuple[str, str]] = [
    (r"steamapps[\\/]+common", "Steam"),
    (r"steamlibrary", "Steam"),
    (r"\bsteam\b", "Steam"),
    (r"gog galaxy", "GOG"),
    (r"\bgog games?\b", "GOG"),
    (r"\bgog\b[\\/]", "GOG"),
    (r"epic games[\\/]+", "Epic"),
    (r"origin games", "Origin"),
    (r"\bubisoft\b[\\/]", "Ubisoft"),
    (r"battle\.?net", "Battle.net"),
    (r"\bheroic\b", "Heroic"),
    (r"\blutris\b", "Lutris"),
    (r"\bbottles\b", "Bottles"),
    (r"\bminigalaxy\b", "GOG"),
    (r"\bgamehub\b", "GameHub"),
    (r"\blegendary\b", "Epic"),
]

# Noise tokens to strip from folder names before searching APIs.
NOISE_TOKENS = [
    "steamrip", "online-fix", "onlinefix", "multiplayer", "multiplayer-fix",
    "repack", "repacks", "repacked", "codex", "empress", "fitgirl", "dodi",
    "xatab", "corepack", "blackbox", "reloaded", "skidrow", "plaza",
    "tinyiso", "direct-play", "directplay", "pre-installed", "preinstalled",
    "full-unlocked", "unlocked", "cracked", "crack", "fixed", "fix",
    "compressed", "supercompressed", "highlycompressed", "portable",
    "multi9", "multi7", "multi5", "multilanguage", "multi-language",
    "dlc", "all-dlc", "complete-edition", "goty", "direct", "iso",
    "gog", "goggames", "gog-games", "gogalaxy", "goggalaxy",
    "windows", "win", "win64", "win32",
    "linux", "appimage", "deb", "rpm", "flatpak", "snap",
    "steamrip", "online", "pre", "full", "unlocked",
]

# Regex chunks removed from folder names
NOISE_REGEX = [
    re.compile(r"\[[^\]]*\]"),                 # [Anything In Brackets]
    re.compile(r"\([^)]*(?:crack|fix|repack|rip|multi|online|dlc|edition|build|v\d|gog|windows)[^)]*\)", re.IGNORECASE),
    re.compile(r"\b(?:v|build\.?|ver\.?|update)\s*\d[\d.]*\b", re.IGNORECASE),  # v1.2 / Build 12345
    re.compile(r"\(\d{3,}\)"),                 # ID in parentheses: (90803)
    # NOTE: do NOT strip bare 4-digit years — they are part of many game titles
    # ("Cyberpunk 2077", "Battlefield 1942", "1979 Revolution"). Release-year
    # tags in parentheses/brackets are already stripped by the rules above.
    re.compile(r"[_]+"),                       # underscores -> space
    re.compile(r"\s{2,}"),                     # collapse spaces
]

PLATFORM_HINTS = [
    (re.compile(r"\blinux\b", re.IGNORECASE), "PC (Linux)"),
    (re.compile(r"\bfan[- ]?port\b", re.IGNORECASE), "PC (Fan Port)"),
    (re.compile(r"\bmod\b", re.IGNORECASE), "PC (Mod)"),
]

# =====================================================================
# Smart game-name detection from files and metadata
# =====================================================================

# Executables that are never the game binary (launchers, installers, helpers).
_NON_GAME_EXES = {
    "setup", "installer", "install", "uninstall", "unins000", "unins001",
    "launcher", "launch", "redist", "dxsetup", "dxdllsetup", "vcredist",
    "vcredist_x64", "vcredist_x86", "dotnet", "ndp",
    "steam", "steamapi", "steam_api", "steam_api64",
    "crashpad_handler", "crashpad", "crashreporter", "crashreporter64",
    "validator", "reporter", "bugreporter",
    "unitycrashhandler", "unitycrashhandler64", "unityplayer",
    "bootstrapper", "bootstrap", "helper", "updater", "update",
    "patcher", "patch", "verify", "repair", "config", "configuration",
    "settings", "options", "debug", "profiler", "benchmark",
    "registration", "activate", "activation", "redeem",
    "epicgameslauncher", "uplay", "upc", "battlenet",
    "socialclub", "rockstar", "rgsc", "eac", "easyanticheat",
    "battleye", "beclient", "gameoverlayui", "streaming_client",
    "goggalaxy", "galaxyclient",
}

# Architecture/platform suffixes to strip from executable names.
_ARCH_SUFFIXES = re.compile(
    r"(?:[_\-]?(?:x64|x86|win64|win32|vk|vulkan|dx11|dx12|"
    r"d3d11|d3d12|64bit|32bit|"
    r"linux|linux64|i386|arm|aarch64|appimage|gl|ogl|x11|wayland))+$",
    re.IGNORECASE,
)

# CamelCase splitting patterns
_CAMEL_SPLIT = re.compile(r"([a-z])([A-Z])")
_ALLCAPS_SPLIT = re.compile(r"([A-Z]{2,})([A-Z][a-z])")

# GOG setup installer pattern: setup_<gamename>_<version>_(<id>).{exe,sh,bin}
# .exe = Windows installer, .sh = Linux installer, .bin = generic binary.
# Archive extensions are included so archived GOG installers parse too.
_GOG_SETUP_RE = re.compile(r"^setup_(.+)\.(?:exe|sh|bin|zip|7z|rar|iso)$", re.IGNORECASE)

# Tokens that are noise in GOG setup exe filenames
_GOG_SETUP_NOISE = {
    "gog", "steam", "epic", "dlc", "multi", "multi5", "multi7", "multi9",
    "windows", "win", "win64", "win32", "x64", "x86",
    "linux", "linux64", "appimage",
    "multilanguage", "multi-language", "artbook", "soundtrack", "ost",
    "bonus", "pack",
}

# Subdirs that never contain the game executable
_SKIP_SUBDIRS = {"data", "cache", "logs", "temp", "__pycache__", ".git"}

# Installer filename markers: an executable whose name carries one of these
# tokens (separated, or as a CamelCase suffix like "DoomEternalSetup") embeds
# the game title in the rest of the filename.
_INSTALL_TOKENS = {"setup", "install", "installer", "installshield", "repack", "unpacked"}

# Repack/scene group names that appear in installer filenames but are NOT
# the game title.
_REPACK_GROUPS = {
    "fitgirl", "dodi", "elamigos", "kaos", "masquerade", "goldberg",
    "prophet", "codex", "cpy", "plaza", "hoodlum", "skidrow", "reloaded",
    "razor1911", "onlinefix", "online", "fix", "steamrip", "xatab",
    "r.g.", "mechanics", "anomaly", "gog", "steam", "epic", "cs.rin",
}

# Tokens that make a candidate string look like junk rather than a title.
_JUNK_TOKENS = _INSTALL_TOKENS | _REPACK_GROUPS | {
    "unins", "uninstall", "unins000", "redist", "update", "updates",
    "build", "version", "ver", "crack", "cracked", "full", "final",
    "patch", "dlc", "demo", "beta", "alpha", "activated", "preinstalled",
    "program", "application", "app", "windows", "win64", "win32", "x64",
    "x86", "games", "game", "library", "common", "binaries", "bin",
    "disc", "disk", "cd", "dvd", "iso", "unity", "unityplayer", "unreal",
    "godot", "gamemaker", "wine", "proton", "dx", "vk", "directx",
}


@dataclass
class ScannedFolder:
    folder_name: str           # original on-disk name
    folder_path: str           # absolute path
    cleaned_name: str          # noise-stripped title for API search
    platform: str             # "PC" (default) or "PC (Linux)" etc.
    store: str                 # "Steam" | "GOG" | "Epic" | "" (unknown)
    is_library_root: bool      # True if this folder itself is a library container


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return text.strip()


def clean_folder_name(name: str) -> str:
    """Strip release-group / version noise from a folder name to aid API search.

    Preserves intra-word hyphens (e.g. ``"Half-Life"``, ``"Counter-Strike"``)
    while still stripping noise tokens attached by hyphens (e.g.
    ``"Doom Eternal-CODEX"`` → ``"Doom Eternal"``).
    """
    n = _normalize(name)
    n = re.sub(r"\.(exe|zip|rar|7z|iso|bin)$", "", n, flags=re.IGNORECASE)
    for rx in NOISE_REGEX:
        n = rx.sub(" ", n)
    tokens = re.split(r"[\s_.,]+", n)
    kept = []
    for t in tokens:
        t = t.strip(".,_/()[]{}")
        if not t:
            continue
        sub = t.split("-")
        good = []
        for s in sub:
            low = s.lower().strip(".,_/()[]{}")
            if not low or low in NOISE_TOKENS:
                continue
            if not re.search(r"[A-Za-z0-9]", s):
                continue
            good.append(s.strip(".,_/()[]{}"))
        if not good:
            continue
        cleaned_token = "-".join(good)
        kept.append(cleaned_token)
    n = " ".join(kept)
    n = re.sub(r"\s{2,}", " ", n).strip(" -")
    return n


def detect_store(path: str, api_store_hint: str | None = None) -> str:
    """Guess the store from the path, falling back to an API hint."""
    norm = path.replace("\\", "/").lower()
    for pattern, store in LIBRARY_ROOTS:
        if re.search(pattern, norm):
            return store
    return api_store_hint or ""


def detect_platform(path: str) -> str:
    norm = path.replace("\\", "/")
    for rx, label in PLATFORM_HINTS:
        if rx.search(norm):
            return label
    return "PC"


def _is_hidden(path: Path) -> bool:
    return path.name.startswith((".", "$"))


def _should_skip(name: str) -> bool:
    return name.lower().strip() in DEFAULT_SKIP


def _is_container(name: str) -> bool:
    """A folder whose NAME marks it as a library container (descend, don't yield)."""
    n = name.lower().strip()
    if n in CONTAINER_NAMES:
        return True
    return "steamlibrary" in n or n.startswith("steam library")


def _list_dirs(path: Path, _visited: set[str] | None = None) -> list[Path]:
    """List subdirectories, skipping symlinks/junctions that would create cycles.

    ``_visited`` is a set of real (resolved) paths already seen in the current
    traversal; it prevents infinite recursion through NTFS junctions and
    directory symlinks that point back to an ancestor.
    """
    if _visited is None:
        _visited = set()
    try:
        result = []
        for c in path.iterdir():
            if not c.is_dir():
                continue
            if _is_hidden(c):
                continue
            # Resolve symlinks/junctions to detect cycles.
            try:
                real = os.path.realpath(c)
            except OSError:
                real = str(c)
            if real in _visited:
                log.debug("Skipping cyclic symlink/junction: %s -> %s", c, real)
                continue
            result.append(c)
        result.sort(key=lambda p: p.name.lower())
        return result
    except (PermissionError, OSError) as e:
        log.debug("Cannot list %s: %s", path, e)
        return []


def scan_games(
    root: str,
    recursive: bool = False,
    skip: set[str] | None = None,
) -> Iterator[ScannedFolder]:
    """Yield ScannedFolder entries for every game folder found under ``root``.

    Traversal rules:
      * immediate children of ``root`` that are not system/hidden folders are
        either yielded as games OR descended into if their name marks them as a
        library container (steamapps, common, GOG Games, Epic Games, ...)
      * containers are descended recursively, so multi-level library trees like
        ``SteamLibrary/steamapps/common/<game>`` resolve to the actual game folder
      * ``recursive=True`` additionally descends into non-container folders that
        contain only subfolders (useful for ad-hoc grouping folders)

    Parameters
    ----------
    root : str
        Drive letter (e.g. ``D:`` on Windows) or a folder path
        (e.g. ``/mnt/games`` or ``~/.steam/steam`` on Linux).
    recursive : bool
        If True, also descend into grouping folders that contain only subfolders.
    skip : set[str], optional
        Extra folder names (lowercased) to skip beyond DEFAULT_SKIP.
    """
    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(f"Path does not exist: {root}")
    if root_path.is_file():
        raise NotADirectoryError(f"Expected a folder/drive, got a file: {root}")

    skip = (skip or set()) | DEFAULT_SKIP
    visited: set[str] = set()
    try:
        root_real = os.path.realpath(root_path)
        visited.add(root_real)
    except OSError:
        pass

    for child in _list_dirs(root_path, visited):
        if _should_skip(child.name) or child.name.lower() in skip:
            continue
        yield from _resolve(child, skip, recursive=recursive, _visited=visited)
    yield from _archive_entries(root_path)


def _resolve(
    path: Path,
    skip: set[str],
    recursive: bool,
    _visited: set[str] | None = None,
) -> Iterator[ScannedFolder]:
    """Yield game folders from ``path``, descending through containers."""
    if _visited is None:
        _visited = set()
    # Register this folder to prevent revisiting via symlink cycles.
    try:
        real = os.path.realpath(path)
        if real in _visited:
            log.debug("Skipping already-visited folder (cycle): %s", path)
            return
        _visited.add(real)
    except OSError:
        pass

    if _should_skip(path.name):
        return

    store = detect_store(str(path))

    if _is_container(path.name):
        yield from _archive_entries(path)
        for child in _list_dirs(path, _visited):
            if _should_skip(child.name) or child.name.lower() in skip:
                continue
            yield from _resolve(child, skip, recursive=recursive, _visited=_visited)
        return

    # Optional extra descent for grouping folders (no files, only subfolders)
    if recursive:
        try:
            entries = list(path.iterdir())
        except (PermissionError, OSError) as e:
            log.debug("Cannot read %s: %s", path, e)
            entries = []
        has_files = any(e.is_file() for e in entries)
        subdirs = [e for e in entries if e.is_dir() and not _is_hidden(e)]
        if not has_files and len(subdirs) >= 1:
            for child in sorted(subdirs, key=lambda p: p.name.lower()):
                if _should_skip(child.name):
                    continue
                yield from _resolve(child, skip, recursive=recursive, _visited=_visited)
            return

    archives = _archive_entries(path)
    if archives and not _collect_exe_paths(path):
        yield from archives
        return

    yield _make_scanned(path, store=store)


def _make_scanned(path: Path, store: str) -> ScannedFolder:
    name = path.name
    cleaned = clean_folder_name(name)
    # Smart-detect: try metadata files, GOG setup exes, and game .exe files
    # to find a better name than the (possibly noisy) folder name.
    cleaned = smart_detect_game_name(path, cleaned)
    platform = detect_platform(str(path))
    resolved_store = detect_store(str(path), api_store_hint=store) or store
    return ScannedFolder(
        folder_name=name,
        folder_path=str(path.resolve()),
        cleaned_name=cleaned or name,
        platform=platform,
        store=resolved_store,
        is_library_root=False,
    )


# =====================================================================
# Smart game-name detection from files and metadata
# =====================================================================

def _looks_like_game_name(name: str) -> bool:
    """Heuristic: does this string look like a real game name?"""
    n = name.strip()
    if len(n) < 2:
        return False
    if n.isdigit():
        return False
    return bool(re.search(r"[A-Za-z]", n))


def _clean_exe_name(filename: str) -> str:
    """Extract a game name from an executable filename.

    Handles CamelCase (``HollowKnight`` → ``Hollow Knight``), all-caps prefixes
    (``DOOMEternal`` → ``DOOM Eternal``), and architecture suffixes
    (``Game-x64vk`` → ``Game``).
    """
    name = re.sub(r"\.(exe|sh|bin|appimage)$", "", filename, flags=re.IGNORECASE)
    name = _ARCH_SUFFIXES.sub("", name)
    name = _ALLCAPS_SPLIT.sub(r"\1 \2", name)
    name = _CAMEL_SPLIT.sub(r"\1 \2", name)
    name = re.sub(r"[_.]+", " ", name)
    name = re.sub(r"\s{2,}", " ", name).strip()
    return name


def _clean_gog_setup_name(filename: str) -> str:
    """Extract a game name from a GOG setup executable filename.

    Example: ``setup_achilles_legends_untold_1.4.0.0_(74603).exe``
          → ``Achilles Legends Untold``
    """
    m = _GOG_SETUP_RE.match(filename)
    if not m:
        return ""
    body = m.group(1)
    tokens = body.split("_")
    kept = []
    for t in tokens:
        if not t:
            continue
        low = t.lower().strip("()")
        # Skip ID patterns: (90803)
        if re.match(r"^\(\d+\)$", t):
            continue
        # Skip version patterns: 1.4.0.0, 1.03.1628077
        if re.match(r"^\d+(\.\d+)*$", t):
            continue
        # Skip GOG/store/format tags
        if low in _GOG_SETUP_NOISE:
            continue
        kept.append(t)
    # capwords splits on whitespace only (not apostrophes), so
    # "assassin's creed" -> "Assassin's Creed" (correct).
    # str.title() would wrongly produce "Assassin'S Creed".
    return capwords(" ".join(kept))


# Extensions of game executables on Windows and Linux.
_GAME_EXE_EXTENSIONS = {".exe", ".appimage", ".sh", ".bin"}
# Linux shell-script names that are launchers, not games.
_NON_GAME_SCRIPTS = {"start", "run", "launch", "play", "startup"}


def _is_linux_executable(entry: Path) -> bool:
    """Check if a file is a Linux executable (ELF binary, AppImage, or script).

    On non-Linux platforms, returns False (we only scan for .exe there).
    """
    if sys.platform == "win32":
        return False
    try:
        if not entry.is_file():
            return False
        suffix = entry.suffix.lower()
        if suffix == ".appimage":
            return True
        if suffix in (".sh", ".bin"):
            return os.access(entry, os.X_OK)
        # Extensionless file: check if executable and has ELF magic
        if not suffix:
            if not os.access(entry, os.X_OK):
                return False
            try:
                with open(entry, "rb") as fh:
                    return fh.read(4) == b"\x7fELF"
            except OSError:
                return False
    except OSError:
        pass
    return False


def _is_game_binary_file(entry: Path) -> bool:
    """True if this file could be a game/installer executable on this platform."""
    suffix = entry.suffix.lower()
    if sys.platform == "win32":
        return suffix == ".exe"
    if suffix == ".exe":
        return True  # Wine/Proton games
    return _is_linux_executable(entry)


def _exe_files_at_depth(folder: Path, max_depth: int) -> list[Path]:
    """Collect executable files up to *max_depth* subfolder levels."""
    out: list[Path] = []

    def _scan(d: Path, depth: int) -> None:
        try:
            for entry in d.iterdir():
                if entry.is_file():
                    if _is_game_binary_file(entry):
                        out.append(entry)
                elif entry.is_dir() and depth < max_depth:
                    name_lower = entry.name.lower()
                    if not entry.name.startswith(".") and name_lower not in _SKIP_SUBDIRS:
                        _scan(entry, depth + 1)
        except (PermissionError, OSError) as e:
            log.debug("Cannot scan %s for executables: %s", d, e)

    _scan(folder, 0)
    return out


def _collect_exe_paths(folder: Path) -> list[Path]:
    """Executables in the folder; one level deeper when the top level is empty.

    Multi-disc and repack layouts hide the game binary/installer in a
    subfolder (``disc1/``, ``Game/Binaries/``); a second level is searched
    only when the first yields nothing, keeping large libraries fast.
    """
    paths = _exe_files_at_depth(folder, 1)
    if not paths:
        paths = _exe_files_at_depth(folder, 2)
    return paths


def _read_pe_metadata(path: Path) -> dict[str, str]:
    """Read ProductName/FileDescription from a Windows PE VERSIONINFO resource.

    Works for game exes AND bare installers whose filename carries no title.
    Returns ``{}`` on non-Windows platforms or when no version resource
    exists (never raises).
    """
    if sys.platform != "win32":
        return {}
    try:
        import ctypes

        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return {}
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, data):
            return {}
        lp = ctypes.c_void_p()
        ln = ctypes.c_uint()
        if not version.VerQueryValueW(
            data, "\\VarFileInfo\\Translation", ctypes.byref(lp), ctypes.byref(ln)
        ) or ln.value < 4:
            return {}
        lang, codepage = struct.unpack_from("<HH", ctypes.string_at(lp, 4))
        out: dict[str, str] = {}
        for field, key_name in (
            ("ProductName", "product_name"),
            ("FileDescription", "file_description"),
        ):
            key = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{field}"
            lp2 = ctypes.c_void_p()
            ln2 = ctypes.c_uint()
            if version.VerQueryValueW(
                data, key, ctypes.byref(lp2), ctypes.byref(ln2)
            ) and ln2.value:
                out[key_name] = ctypes.wstring_at(lp2).strip()
        return out
    except (OSError, AttributeError, ValueError) as e:
        log.debug("PE metadata read failed for %s: %s", path, e)
        return {}


def _find_gog_setup_exe(folder: Path) -> str | None:
    """Find a GOG setup installer and extract the game name from its filename.

    GOG setup installers look like
    ``setup_achilles_legends_untold_1.4.0.0_(74603).exe`` (Windows) or
    ``setup_achilles_legends_untold_1.4.0.0_(74603).sh`` (Linux).
    When multiple setup installers exist (game + DLC/artbook/soundtrack), the
    one with the shortest extracted name is preferred (the main game, not DLC).
    Returns the extracted game name, or ``None`` if no GOG setup is found.
    """
    candidates: list[str] = []
    try:
        for entry in folder.iterdir():
            if not entry.is_file():
                continue
            suffix = entry.suffix.lower()
            if suffix not in (".exe", ".sh", ".bin"):
                continue
            if not entry.name.lower().startswith("setup_"):
                continue
            if entry.stem.lower() == "setup":
                continue  # generic FitGirl installer, skip
            name = _clean_gog_setup_name(entry.name)
            if _looks_like_game_name(name):
                candidates.append(name)
    except (PermissionError, OSError) as e:
        log.debug("Cannot find GOG setup in %s: %s", folder, e)
    if not candidates:
        return None
    # Prefer the shortest extracted name (main game, not DLC/artbook)
    candidates.sort(key=len)
    return candidates[0]


def _read_gog_metadata(folder: Path) -> str | None:
    """Read game name from GOG's ``goggame-*.info`` JSON file.

    A GOG game folder may contain multiple ``goggame-<id>.info`` files — one
    for the base game and others for DLCs/artbooks/soundtracks. We prefer the
    one whose filename ID equals the JSON ``gameId`` field (the base game).
    Falls back to the first readable file.
    """
    candidates: list[tuple[str, str, str]] = []
    try:
        for entry in folder.iterdir():
            if not entry.is_file():
                continue
            m = re.match(r"goggame-(\d+)\.info$", entry.name, re.IGNORECASE)
            if not m:
                continue
            file_id = m.group(1)
            try:
                with open(entry, encoding="utf-8-sig") as f:
                    data = json.load(f)
            except (OSError, ValueError, json.JSONDecodeError) as e:
                log.debug("Cannot read GOG metadata %s: %s", entry, e)
                continue
            name = data.get("name") or data.get("Name")
            if not name or not _looks_like_game_name(str(name)):
                continue
            game_id = str(data.get("gameId") or data.get("GameId") or "")
            candidates.append((file_id, game_id, str(name).strip()))
    except (PermissionError, OSError) as e:
        log.debug("Cannot list %s for GOG metadata: %s", folder, e)
        return None
    if not candidates:
        return None
    for file_id, game_id, name in candidates:
        if game_id and file_id == game_id:
            return name
    return candidates[0][2]


# Cache: (steamapps_dir) -> {installdir_lower: game_name}
# Avoids re-reading every appmanifest for every game folder (O(N²) → O(N)).
_steam_manifest_cache: dict[str, dict[str, str]] = {}


def _read_steam_manifest(folder: Path) -> str | None:
    """Read game name from Steam's ``appmanifest_*.acf`` in the steamapps folder.

    The game folder is typically at ``.../steamapps/common/<game>/``.
    The manifest is at ``.../steamapps/appmanifest_<id>.acf`` and contains
    a VDF-like ``"name" "Game Name"`` entry with an ``"installdir"`` that
    should match the game folder name.

    Manifests are cached per ``steamapps/`` directory to avoid re-reading every
    manifest file for every game (which would be O(N²) for a library of N games).
    """
    current = folder
    for _ in range(3):
        parent = current.parent
        if parent.name.lower() == "steamapps":
            steamapps_dir = str(parent)
            manifests = _steam_manifest_cache.get(steamapps_dir)
            if manifests is None:
                manifests = _load_steam_manifests(parent)
                _steam_manifest_cache[steamapps_dir] = manifests
            return manifests.get(folder.name.lower())
        current = parent
    return None


def _load_steam_manifests(steamapps_dir: Path) -> dict[str, str]:
    """Parse all ``appmanifest_*.acf`` files into ``{installdir_lower: name}``."""
    result: dict[str, str] = {}
    try:
        for entry in steamapps_dir.iterdir():
            if not entry.is_file():
                continue
            if not re.match(r"appmanifest_.*\.acf$", entry.name, re.IGNORECASE):
                continue
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                log.debug("Cannot read Steam manifest %s: %s", entry, e)
                continue
            inst = re.search(r'"installdir"\s+"([^"]+)"', text)
            name_match = re.search(r'"name"\s+"([^"]+)"', text)
            if inst and name_match and _looks_like_game_name(name_match.group(1)):
                result[inst.group(1).lower()] = name_match.group(1).strip()
    except (PermissionError, OSError) as e:
        log.debug("Cannot list steamapps dir %s: %s", steamapps_dir, e)
    return result


def _looks_like_installer(filename: str) -> bool:
    """True if an executable filename carries an installer marker token.

    Matches separated tokens (``Hollow Knight-Setup.exe``,
    ``doom_eternal_installer.exe``) and CamelCase-attached suffixes
    (``DoomEternalSetup.exe``). Bare ``setup.exe``/``installer.exe`` carry no
    title and are excluded (the folder name is the better source).
    """
    stem = re.sub(r"\.(exe|sh|bin|appimage)$", "", filename, flags=re.IGNORECASE)
    low = stem.lower()
    if low in _NON_GAME_EXES or low in _NON_GAME_SCRIPTS:
        return False
    if low.startswith("setup_"):
        return False  # GOG installers — parsed by _find_gog_setup_exe
    if re.search(r"(?i)(?:^|[-_.\s])(?:setup|install(?:er|shield)?|repack|unpacked)(?:$|[-_.\s])", low):
        return True
    return bool(re.search(r"(?i)(?:setup|install(?:er|shield)?|repack|unpacked)$", low))


def _clean_installer_name(filename: str) -> str:
    """Extract the game title embedded in an installer filename.

    ``Hollow Knight-Setup.exe`` → ``Hollow Knight``
    ``doom_eternal_installer.exe`` → ``Doom Eternal``
    ``hollow_knight_dodi_setup.exe`` → ``Hollow Knight``
    ``DoomEternalSetup.exe`` → ``Doom Eternal``
    Repack-group names, installer markers, dotted versions and ``(id)`` tags
    are stripped. Returns ``""`` when no title remains.
    """
    stem = re.sub(r"\.(exe|sh|bin|appimage)$", "", filename, flags=re.IGNORECASE)
    if stem.lower().startswith("setup_"):
        return ""
    stem = re.sub(r"(?i)(?:[-_.\s]*(?:setup|install(?:er|shield)?|repack|unpacked)+)+$", "", stem)
    kept = []
    for t in re.split(r"[-_.\s]+", stem):
        if not t:
            continue
        low = t.lower()
        if low in _REPACK_GROUPS or low in _INSTALL_TOKENS:
            continue
        if re.match(r"^v?\d+(?:\.\d+)+$", low):
            continue
        if re.match(r"^\(\d+\)$", t):
            continue
        kept.append(t)
    if not kept:
        return ""
    return capwords(_clean_exe_name(" ".join(kept)).replace("-", " "))


# =====================================================================
# Game archives (.zip / .7z / .rar / .iso) as game entries
# =====================================================================

_ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".iso"}

# Multi-part RAR volumes: only ``Game.part1.rar`` is yielded; parts 2+ and
# ``.r00``-style continuation volumes are skipped.
_MULTIPART_RAR_RE = re.compile(r"^.+\.part(\d+)\.rar$", re.IGNORECASE)

# Download-site URL prefixes embedded in archive names
# (``fitgirl-repacks.site-Hollow Knight.zip``).
_URL_PREFIX_RE = re.compile(
    r"^(?:www\.)?[a-z0-9][a-z0-9.\-]*\.(?:com|net|org|site|io|xyz|me)\b[-_\s]*",
    re.IGNORECASE,
)

_BITNESS_RE = re.compile(r"\b(?:32|64)[\- ]?bit\b", re.IGNORECASE)
_PART_TOKEN_RE = re.compile(r"\bpart\d+\b", re.IGNORECASE)

# Archive stems that are never game titles.
_ARCHIVE_JUNK_NAMES = {
    "readme", "manual", "notes", "docs", "data", "cache", "temp",
    "backup", "backups", "download", "downloads", "archive", "archives",
    "patch", "patches", "update", "updates", "crack", "cracks",
    "trainer", "trainers", "cheats", "saves", "save", "savegame",
    "savegames", "zips", "rars", "isos", "misc", "stuff", "unknown",
    "game", "games",
}


def _is_archive(entry: Path) -> bool:
    return entry.suffix.lower() in _ARCHIVE_EXTENSIONS


def _is_multipart_continuation(entry: Path) -> bool:
    m = _MULTIPART_RAR_RE.match(entry.name)
    return bool(m and int(m.group(1)) > 1)


def _clean_archive_name(filename: str) -> str:
    """Extract a game title from an archive filename.

    ``Hollow Knight.zip`` → ``Hollow Knight``
    ``Hollow.Knight.v1.0.231.32-bit.(48932).zip`` → ``Hollow Knight``
    ``fitgirl-repacks.site-Hollow Knight.zip`` → ``Hollow Knight``
    ``setup_achilles_legends_untold_1.4.0.0_(74603).zip`` → ``Achilles Legends Untold``
    ``Hollow Knight.part1.rar`` → ``Hollow Knight``

    Returns ``""`` when the stem is junk (readme.zip, data.zip, ...).
    """
    stem = re.sub(r"\.(zip|7z|rar|iso)$", "", filename, flags=re.IGNORECASE)
    if not stem:
        return ""
    if stem.lower().startswith("setup_"):
        return _clean_gog_setup_name(filename)
    if stem.lower() in _ARCHIVE_JUNK_NAMES:
        return ""
    stem = _PART_TOKEN_RE.sub(" ", stem)
    stem = _URL_PREFIX_RE.sub(" ", stem)
    stem = _BITNESS_RE.sub(" ", stem)
    stem = _ALLCAPS_SPLIT.sub(r"\1 \2", stem)
    stem = _CAMEL_SPLIT.sub(r"\1 \2", stem)
    return clean_folder_name(stem)


def _archive_entries(folder: Path) -> list[ScannedFolder]:
    """ScannedFolder entries for game archives among the folder's files.

    Archives whose parsed name is junk (``readme.zip``) or empty are skipped,
    as are multi-part RAR continuation volumes. Store/platform come from the
    archive's path.
    """
    entries: list[ScannedFolder] = []
    try:
        children = [c for c in folder.iterdir() if c.is_file() and not _is_hidden(c)]
    except (PermissionError, OSError) as e:
        log.debug("Cannot list %s for archives: %s", folder, e)
        return []
    for c in sorted(children, key=lambda p: p.name.lower()):
        if not _is_archive(c) or _is_multipart_continuation(c):
            continue
        name = _clean_archive_name(c.name)
        if not name or not _looks_like_game_name(name) or _title_quality(name) <= 0:
            continue
        entries.append(
            ScannedFolder(
                folder_name=c.name,
                folder_path=str(c.resolve()),
                cleaned_name=name,
                platform=detect_platform(str(c)),
                store=detect_store(str(c)),
                is_library_root=False,
            )
        )
    return entries


def _title_quality(name: str) -> float:
    """Score how title-like a candidate name is (0.0 – 1.0).

    Penalizes junk tokens (repack groups, installer markers, engines),
    dotted version numbers, and digit-heavy strings; rewards 2–5 word
    titles. All-junk candidates (e.g. "Setup Program") score 0.
    """
    n = (name or "").strip()
    if not _looks_like_game_name(n) or len(n) > 60:
        return 0.0
    tokens = [t for t in re.split(r"[\s:;,.\-—–]+", n) if t]
    if not tokens:
        return 0.0
    lows = [t.lower() for t in tokens]
    if all(t in _JUNK_TOKENS for t in lows):
        return 0.0
    w = len(tokens)
    if w == 1:
        score = 0.55
    elif w <= 5:
        score = 1.0
    elif w <= 8:
        score = 0.8
    else:
        score = 0.5
    score *= 0.6 ** sum(1 for t in lows if t in _JUNK_TOKENS)
    if re.search(r"\d+\.\d+", n):
        score *= 0.6
    if sum(c.isdigit() for c in n) / max(len(n), 1) > 0.4:
        score *= 0.5
    return min(score, 1.0)


def _norm_key(name: str) -> str:
    """Normalize a candidate name so independent sources can be compared."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _installer_candidates(folder: Path) -> list[str]:
    """Game titles extracted from installer executable filenames."""
    names: list[str] = []
    for p in _collect_exe_paths(folder):
        if not _looks_like_installer(p.name):
            continue
        name = _clean_installer_name(p.name)
        if name and _looks_like_game_name(name):
            names.append(name)
    return names


def _best_name_from_evidence(folder_path: Path, cleaned_folder_name: str) -> str:
    """Pick the best game name by scoring evidence from every folder signal.

    Candidates (with source weights): installer filenames 0.90, PE
    ProductName 0.75, PE FileDescription 0.70, cleaned folder name 0.60,
    plain exe stems 0.55, parent folder name 0.40 (only when the folder name
    itself is junk). Final score = weight x title-quality, +0.10 when two
    different sources agree on the same normalized name. Ties prefer the
    shorter name (the main game, not DLC). Below-threshold results fall back
    to the cleaned folder name.
    """
    candidates: list[tuple[str, float, str]] = []

    def add(name: str, weight: float, source: str) -> None:
        name = (name or "").strip()
        if name and _looks_like_game_name(name):
            candidates.append((name, weight, source))

    for name in _installer_candidates(folder_path):
        add(name, 0.90, "installer")

    sized: list[tuple[Path, int]] = []
    for p in _collect_exe_paths(folder_path):
        stem = p.stem.lower()
        if stem in _NON_GAME_EXES or stem in _NON_GAME_SCRIPTS or stem.startswith("setup_"):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        if size >= 1_000_000:
            sized.append((p, size))
    sized.sort(key=lambda t: t[1], reverse=True)
    for p, _size in sized[:3]:
        meta = _read_pe_metadata(p)
        if meta.get("product_name"):
            add(meta["product_name"], 0.75, "pe_product")
        if meta.get("file_description"):
            add(meta["file_description"], 0.70, "pe_desc")

    if _title_quality(cleaned_folder_name) > 0:
        add(cleaned_folder_name, 0.60, "folder")
    else:
        parent = folder_path.parent
        if not _is_container(parent.name):
            add(clean_folder_name(parent.name), 0.40, "parent")

    for p, size in sized:
        cleaned = _clean_exe_name(p.name)
        if cleaned:
            add(cleaned, 0.55, "stem")

    if not candidates:
        return cleaned_folder_name

    sources_by_key: dict[str, set[str]] = {}
    for name, _weight, source in candidates:
        sources_by_key.setdefault(_norm_key(name), set()).add(source)

    best: tuple[tuple[float, int], str] | None = None
    for name, weight, _source in candidates:
        q = _title_quality(name)
        if q <= 0:
            continue
        score = weight * q
        if len(sources_by_key[_norm_key(name)]) > 1:
            score += 0.10
        key = (-score, len(name))
        if best is None or key < best[0]:
            best = (key, name)
    if best is None:
        return cleaned_folder_name
    if -best[0][0] < 0.20:
        return cleaned_folder_name
    return best[1]


def smart_detect_game_name(folder_path: Path, cleaned_folder_name: str) -> str:
    """Smart-detect the game name from multiple sources.

    Authoritative metadata wins outright, in order of reliability:

    1. **Steam manifest** (``appmanifest_*.acf``) — matched by ``installdir``.
    2. **GOG metadata** (``goggame-*.info`` JSON).
    3. **GOG setup executable** (``setup_achilles_legends_untold_..._.exe``).

    Otherwise every remaining signal is collected as evidence and scored:

    * installer filenames (``Hollow Knight-Setup.exe``, ``DoomEternalSetup.exe``,
      repack installers) — the title is deliberately embedded;
    * PE VERSIONINFO ``ProductName`` / ``FileDescription`` of the largest
      executables (Windows) — rescues bare ``setup.exe`` repacks and generic
      binaries (``game.exe``, ``main.exe``);
    * cleaned folder name, plain exe stems (CamelCase cleaned, ≥1MB), and the
      parent folder name (only when the folder name itself is junk);
      executables are searched one subfolder level deeper when the top level
      yields nothing (multi-disc layouts).

    The top-scoring candidate wins (weight x title-quality, +agreement bonus
    when independent sources concur); below-threshold results fall back to
    the cleaned folder name.
    """
    name = _read_steam_manifest(folder_path)
    if name and _looks_like_game_name(name):
        return name

    name = _read_gog_metadata(folder_path)
    if name and _looks_like_game_name(name):
        return name

    name = _find_gog_setup_exe(folder_path)
    if name and _looks_like_game_name(name):
        return name

    return _best_name_from_evidence(folder_path, cleaned_folder_name)

