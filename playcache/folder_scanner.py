"""Scan a drive/folder for games and produce clean, searchable names.

The scanner walks the tree and classifies every folder as one of:

  * a **library container** (``steamapps/common``, ``GOG Games``, ...) -
    descended into;
  * a **game** - the folder itself is one game (installed copy, repack,
    GOG installer set, scene ISO, disc dump, ROM folder, ...);
  * a **grouping folder** (``1-RPG``, ``000Kidz``, ``EMU Redump``) - holds
    other games as subfolders and/or loose files, so it is descended into
    and its loose archives/installers/dumps are yielded one by one;
  * **nothing** - folders with no game evidence at all (empty folders,
    music, documents) are never catalogued.

Each entry gets a platform from :mod:`playcache.platforms` (file contents
first, then folder names such as ``PS2``/``1-Linux Games``/``EMU``), a store
guess from the path, and a cleaned title. Entries with the same title on the
same platform are collapsed into one (the most complete copy wins); copies on
different platforms are kept.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import struct
import sys
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from string import capwords

from . import platforms as _plat

log = logging.getLogger(__name__)

DEFAULT_SKIP = {
    "windows", "program files", "program files (x86)", "programdata", "users",
    "$recycle.bin", "system volume information", "$winreagent", "$sysreset",
    "$windows.~bt", "recovery", "perflogs", "intel", "amd", "nvidia",
    "msocache", "config.msi",
    "boot", "bin", "sbin", "etc", "var", "usr", "lib", "lib64", "lib32",
    "libx32", "run", "sys", "proc", "dev", "srv", "snap", "lost+found",
    "swapfile", ".cache", ".config", ".local", "node_modules",
}

CONTAINER_NAMES = {
    "steamapps", "common", "gog games", "gog game", "epic games",
    "origin games", "steamlibrary", "battle.net", "battlenet",
    "ubisoft", "ubisoft game launcher", "ubisoft games",
    "games", "game library",
}

LIBRARY_ROOTS: list[tuple[str, str]] = [
    (r"steamapps[\\/]+common", "Steam"),
    (r"steamlibrary", "Steam"),
    (r"(?:^|[\\/])steam[\\/]", "Steam"),
    (r"gog galaxy", "GOG"),
    (r"\bgog games?\b", "GOG"),
    (r"\bgog\b[\\/]", "GOG"),
    (r"[\[(]gog[\])]", "GOG"),
    (r"[-_. ]gog(?:$|[\\/])", "GOG"),
    (r"epic games[\\/]+", "Epic"),
    (r"origin games", "Origin"),
    (r"ubisoft games[\\/]", "Ubisoft"),
    (r"\bubisoft\b[\\/]", "Ubisoft"),
    (r"(?:^|[\\/])battle\.?net[\\/]", "Battle.net"),
    (r"(?:^|[\\/])heroic[\\/]", "Heroic"),
    (r"(?:^|[\\/])lutris[\\/]", "Lutris"),
    (r"(?:^|[\\/])bottles[\\/]", "Bottles"),
    (r"(?:^|[\\/])minigalaxy[\\/]", "GOG"),
    (r"(?:^|[\\/])gamehub[\\/]", "GameHub"),
    (r"(?:^|[\\/])legendary[\\/]", "Epic"),
]

_SOURCE_TAGS_B64 = (
    "c3RlYW1yaXAgb25saW5lLWZpeCBvbmxpbmVmaXggY29kZXggZW1wcmVzcyBmaXRn"
    "aXJsIGRvZGkgeGF0YWIgY29yZXBhY2sgYmxhY2tib3ggcmVsb2FkZWQgc2tpZHJv"
    "dyBwbGF6YSB0aW55aXNvIGNweSBydW5lIHRlbm9rZSBmbHQgZmFpcmxpZ2h0IGRv"
    "Z2UgcmF6b3IxOTExIHJhem9yIGhvb2RsdW0gcHJvcGhldCBnb2xkYmVyZyBlbGFt"
    "aWdvcyBtYXNxdWVyYWRlIGthb3MgY3JhbmtleWUgZGFya3NpZCBpZ3J1aGEgZGVj"
    "ZXB0aWNvbiBjaG92a2Egc3BpZWxlcg=="
)
SOURCE_TAGS = frozenset(base64.b64decode(_SOURCE_TAGS_B64).decode("ascii").split())

NOISE_TOKENS = [
    "multiplayer", "multiplayer-fix", "repack", "repacks", "repacked",
    "direct-play", "directplay", "pre-installed", "preinstalled",
    "full-unlocked", "unlocked", "cracked", "crack", "fixed", "fix",
    "compressed", "supercompressed", "highlycompressed", "portable",
    "multi9", "multi7", "multi5", "multilanguage", "multi-language",
    "dlc", "dlcs", "all-dlc", "all-dlcs", "complete-edition", "goty", "direct", "iso",
    "gog", "goggames", "gog-games", "gogalaxy", "goggalaxy",
    "windows", "win", "win64", "win32", "x64", "x86", "x86_64", "64bit", "32bit",
    "linux", "appimage", "deb", "rpm", "flatpak", "snap",
    "android", "apk", "arm64", "armv7", "arm64-v8a", "v8a", "aarch64",
    "online", "pre", "full", "unlocked", "easy-setup",
    "sr", "wow", "anomaly", "mechanics",
    *sorted(SOURCE_TAGS),
]

_SITE_RE = re.compile(r"[-_ ]?[A-Za-z0-9]{3,}\.(?:com|net|org)\b", re.IGNORECASE)

NOISE_REGEX = [
    _SITE_RE,
    re.compile(r"(?<=_)\d+(?:\.\d+)+_[a-z](?=_|$)", re.IGNORECASE),
    re.compile(r"\(\s*[a-z]\s*\)", re.IGNORECASE),
    re.compile(r"\[[^\]]*\]"),
    re.compile(r"\([^)]*(?:crack|fix|repack|rip|multi|online|dlc|edition|build|v\d|gog|windows)[^)]*\)", re.IGNORECASE),
    re.compile(r"\((?:Rev\s*\d+|USA|Europe|Japan|World|Asia|Australia|EUR|JPN|(?:[A-Za-z]{2},)+[A-Za-z]{2})\)"),
    re.compile(r"(?:\b(?:all|incl|including)[\s._-]+)?\bdlcs?\b", re.IGNORECASE),
    re.compile(r"[_]+"),
    re.compile(r"\b(?:v|build\.?|ver\.?|update)\s*\d[\d.]*\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+){2,}(?:-\d+)?[a-z]?\b", re.IGNORECASE),
    re.compile(r"\b\d+\.\d+[a-z]?(?=\s*\()", re.IGNORECASE),
    re.compile(r"\brc\d+\b", re.IGNORECASE),
    re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b\d{6,}\b"),
    re.compile(r"\(\d{3,}\)"),
    re.compile(r"\((?=[^)]*\d)[^)]*\)"),
    re.compile(r"\s{2,}"),
]

_ARTICLE_RE = re.compile(r"^(.+?),\s*(the|a|an)\b(?=\s*(?:[-:(\[]|$))", re.IGNORECASE)

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
    "goggalaxy", "galaxyclient", "quicksfv", "autorun", "dxwebsetup",
}

_ARCH_SUFFIXES = re.compile(
    r"(?:[_\-]?(?i:x64|x86|win64|win32|dx11|dx12|d3d11|d3d12|64bit|32bit|i386|aarch64|linux64|x11)"
    r"|(?:(?<=[a-z])(?=[A-Z])|[_\-]|(?<=\d))(?i:vk|vulkan|gl|ogl|wayland|linux|appimage|arm))+$"
)

_CAMEL_SPLIT = re.compile(r"([a-z])([A-Z])")
_ALLCAPS_SPLIT = re.compile(r"([A-Z]{2,})([A-Z][a-z]{2,})")

_GOG_SETUP_RE = re.compile(r"^setup_(.+)\.(?:exe|sh|bin|zip|7z|rar|iso)$", re.IGNORECASE)
_GOG_LINUX_RE = re.compile(r"^gog_(.+)\.sh$", re.IGNORECASE)
_GOG_ID_RE = re.compile(r"\((\d{3,})\)(?:-\d+)?\.[a-z0-9]+$", re.IGNORECASE)
_SH_ID_RE = re.compile(r"_(\d{4,})\.sh$", re.IGNORECASE)
_VOLUME_BIN_RE = re.compile(r"-\d+\.bin$", re.IGNORECASE)

_GOG_SETUP_NOISE = {
    "gog", "steam", "epic", "dlc", "multi", "multi5", "multi7", "multi9",
    "windows", "win", "win64", "win32", "x64", "x86",
    "linux", "linux64", "appimage",
    "multilanguage", "multi-language", "artbook", "soundtrack", "ost",
    "bonus", "pack",
}
_STORE_WORDS = {"gog", "steam", "epic"}

_SKIP_SUBDIRS = {"data", "cache", "logs", "temp", "__pycache__", ".git"}

_CONTENT_SUBDIRS = _SKIP_SUBDIRS | {
    "bin", "binaries", "win32", "win64", "x64", "x86", "engine", "content",
    "game", "assets", "resources", "res", "plugins", "lib", "libs", "system",
    "characters", "expansions", "campaign", "campaigns", "maps", "levels",
    "sound", "sounds", "textures", "shaders", "editor", "localization",
    "language", "languages", "lang", "movies", "videos", "video",
}

_EXTRA_SUBDIRS = {
    "md5", "dlc", "dlcs", "bonus", "bonuses", "extras", "extra", "goodies",
    "redist", "_redist", "redists", "_commonredist", "commonredist", "directx",
    "vcredist", "dotnet", "prerequisites", "prereqs", "support", "crack",
    "cracks", "nocd", "fix", "fixes", "patch", "patches", "update", "updates",
    "soundtrack", "soundtracks", "ost", "music", "mp3", "flac", "wav",
    "artbook", "art", "artwork", "wallpaper", "wallpapers", "manual",
    "manuals", "docs", "doc", "documentation", "readme", "guide", "guides",
    "scans", "covers", "boxart", "trailers", "screenshots", "save", "saves",
    "savegame", "savegames", "mods", "tools", "sdk", "server", "trainer",
    "trainers", "cheats", "installer", "installers", "__installer",
    "_installer", "setup", "launcher", "shadercache", "compatdata",
    "downloading", "workshop", "temp", "tmp", "sourcemods", "online",
    "multiplayer", "keygen", "serial", "license", "licenses", "eula",
}

_PLATFORM_DIR_WORDS = {
    "pc", "windows", "win", "win32", "win64", "x64", "x86", "linux", "mac",
    "macos", "osx", "mobile", "android", "ios", "steam", "gog", "itch", "io",
    "epic", "release", "releases", "version", "versions", "build", "builds",
    "32bit", "64bit", "port", "native",
}

_DISC_DIR_RE = re.compile(r"^(?:cd|dvd|disc|disk)[\s_-]*\d+$", re.IGNORECASE)

_INSTALL_TOKENS = {"setup", "install", "installer", "installshield", "repack", "unpacked"}

_SOURCE_GROUPS_B64 = (
    "Zml0Z2lybCBkb2RpIGVsYW1pZ29zIGthb3MgbWFzcXVlcmFkZSBnb2xkYmVyZyBw"
    "cm9waGV0IGNvZGV4IGNweSBwbGF6YSBob29kbHVtIHNraWRyb3cgcmVsb2FkZWQg"
    "cmF6b3IxOTExIG9ubGluZWZpeCBzdGVhbXJpcCB4YXRhYiBjcy5yaW4gci5nLg=="
)
SOURCE_GROUPS = frozenset(base64.b64decode(_SOURCE_GROUPS_B64).decode("ascii").split()) | {
    "online", "fix", "mechanics", "anomaly", "gog", "steam", "epic",
}

_ENGINE_TOKENS = {"unity", "unityplayer", "unreal", "godot", "gamemaker"}

_JUNK_TOKENS = _INSTALL_TOKENS | SOURCE_GROUPS | {
    "unins", "uninstall", "unins000", "redist", "update", "updates",
    "build", "version", "ver", "crack", "cracked", "full", "final",
    "patch", "dlc", "demo", "beta", "alpha", "activated", "preinstalled",
    "program", "application", "app", "windows", "win64", "win32", "x64",
    "x86", "games", "game", "library", "common", "binaries", "bin",
    "disc", "disk", "cd", "dvd", "iso", "wine", "proton", "dx", "vk", "directx",
}

_EXTRAS_FILE_TOKENS = {
    "manual", "manuals", "ost", "soundtrack", "soundtracks", "artbook",
    "wallpaper", "wallpapers", "guide", "bonus", "goodies", "crack", "cracks",
    "patch", "patches", "fix", "hotfix", "update", "updates", "trainer",
    "trainers", "cheats", "save", "saves", "savegame", "savegames", "mp3",
    "flac", "wav", "nocd", "redist", "directx", "vcredist", "readme", "scans",
    "covers", "keygen", "artworks", "artwork", "avatars", "avatar",
    "ringtones", "novella", "novellas", "concept", "comics", "map",
}

_NON_EVIDENCE_TOKENS = {
    "crack", "cracks", "keygen", "trainer", "trainers", "cheats", "redist",
    "directx", "vcredist", "dxsetup", "dotnet", "quicksfv",
}

_ROMAN = {
    "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7",
    "viii": "8", "ix": "9", "x": "10", "xi": "11", "xii": "12", "xiii": "13",
    "xiv": "14", "xv": "15", "xvi": "16",
}
_ROMAN_TITLE = {k.capitalize(): k.upper() for k in _ROMAN if len(k) > 1}

_EDITION_RE = re.compile(
    r"\b(?:(?:complete|goty|game of the year|deluxe|definitive|ultimate|gold|"
    r"standard|digital|premium|collector'?s)\s+)?edition\b|\bgoty\b",
    re.IGNORECASE,
)

_TRAILING_JUNK_RE = re.compile(
    r"^(?:hotfix\d*|fix|patch\d*|update\d*|launchfix|ddrawfix|win\d+|lang|setup|installer|"
    r"-?cs\d*|rc\d+|gog(?:-\d+)?|goty|build-?\d+|rev-?\d+|\d{5,}|"
    r"\d{4}-\d{2}-\d{2}|\d{8}|v?\d+(?:\.\d+)+[a-z.]{0,3}(?:-[a-z0-9]+)?|-+)$",
    re.IGNORECASE,
)

_LANG_TOKENS = {
    "en", "de", "fr", "es", "it", "pt", "ru", "pl", "cs", "hu", "jp", "cn",
    "kr", "mx", "br", "nl", "tr",
}

_SOURCE_RANK = {
    "installed": 6, "folder": 5, "installer": 4, "image": 3, "archive": 3,
    "rom": 3, "variant": 1,
}


@dataclass
class ScannedFolder:
    folder_name: str
    folder_path: str
    cleaned_name: str
    platform: str
    store: str
    is_library_root: bool
    source: str = "folder"


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return text.strip()


def clean_folder_name(name: str) -> str:
    """Strip source-tag / version noise from a folder name to aid API search.

    Preserves intra-word hyphens (``Half-Life``) while stripping download
    tags attached by hyphens (``Game-Tag`` -> ``Game``). Words joined by two
    or more hyphens (``Star-Wars-Yoda-Stories``) are split into words, and a
    trailing article is moved to the front (``Legend of Zelda, The`` ->
    ``The Legend of Zelda``).
    """
    n = _normalize(name)
    n = re.sub(r"\.(exe|zip|rar|7z|iso|bin|apk|tar|gz|tgz)$", "", n, flags=re.IGNORECASE)
    machine = "_" in n
    n = _ARTICLE_RE.sub(lambda m: f"{m.group(2).capitalize()} {m.group(1)}", n)
    n = re.sub(r"\s&\s", " and ", n)
    for rx in NOISE_REGEX:
        n = rx.sub(" ", n)
    if machine:
        n = re.sub(r"\b\d+\.\d+[a-z]?\b", " ", n, flags=re.IGNORECASE)
    tokens = re.split(r"[\s_.,]+", n)
    kept: list[str] = []
    tag_positions: set[int] = set()
    for t in tokens:
        t = t.strip(".,_/()[]{}")
        if not t:
            continue
        low_t = t.lower()
        if low_t in SOURCE_TAGS:
            tag_positions.add(len(kept))
            kept.append(t)
            continue
        if low_t in NOISE_TOKENS:
            continue
        parts = [t] if t.count("-") < 2 else t.split("-")
        for part in parts:
            sub = part.split("-")
            good = []
            for s in sub:
                low = s.lower().strip(".,_/()[]{}")
                if not low or low in NOISE_TOKENS:
                    continue
                if not any(ch.isalnum() for ch in s):
                    continue
                good.append(s.strip(".,_/()[]{}"))
            if good:
                kept.append("-".join(good))
    while len(kept) > 1 and (
        len(kept) - 1 in tag_positions or kept[-1].lower() in ("by", "en", "eng")
    ):
        kept.pop()
    while len(kept) > 1 and re.fullmatch(r"\d{5,}", kept[-1]):
        kept.pop()
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
    """Platform implied by the folder names in ``path`` (``PC`` by default)."""
    return _plat.detect_platform(path)


SWITCH_DUMP_EXTS = frozenset({".nsp", ".nsz", ".xci", ".xcz"})
SWITCH_PLATFORM = _plat.SWITCH
_SWITCH_SCAN_DEPTH = 2


def has_switch_dump(path: Path, depth: int = _SWITCH_SCAN_DEPTH) -> bool:
    files, dirs = _ls(path)
    if any(f.suffix.lower() in SWITCH_DUMP_EXTS for f in files):
        return True
    return depth > 0 and any(has_switch_dump(d, depth - 1) for d in dirs)


_cache: dict[str, dict] | None = None


def _cached(bucket: str, key: str):
    if _cache is None:
        return None
    return _cache.setdefault(bucket, {}).get(key)


def _store_cache(bucket: str, key: str, value):
    if _cache is not None:
        _cache.setdefault(bucket, {})[key] = value
    return value


def _ls(path: Path) -> tuple[list[Path], list[Path]]:
    """Non-hidden (files, dirs) of ``path``, sorted by name; cached per scan."""
    key = str(path)
    hit = _cached("ls", key)
    if hit is not None:
        return hit
    files: list[Path] = []
    dirs: list[Path] = []
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith((".", "$")):
                    continue
                try:
                    if e.is_dir():
                        dirs.append(Path(e.path))
                    elif e.is_file():
                        files.append(Path(e.path))
                except OSError:
                    continue
    except OSError as e:
        log.debug("Cannot list %s: %s", path, e)
    files.sort(key=lambda p: p.name.lower())
    dirs.sort(key=lambda p: p.name.lower())
    return _store_cache("ls", key, (files, dirs))


def _should_skip(name: str) -> bool:
    return name.lower().strip() in DEFAULT_SKIP


def _is_container(name: str) -> bool:
    """A folder whose NAME marks it as a library container (descend, don't yield)."""
    n = name.lower().strip()
    if n in CONTAINER_NAMES:
        return True
    if "steamlibrary" in n or n.startswith("steam library"):
        return True
    return n.endswith(("gog games", "epic games", "origin games", "ubisoft games"))


def _dir_words(name: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", name.lower())


def _is_extra_dir(name: str) -> bool:
    low = name.lower().strip()
    if low in _EXTRA_SUBDIRS:
        return True
    words = _dir_words(low)
    return bool(words) and words[0] in _EXTRA_SUBDIRS


def _is_platform_dir(name: str) -> bool:
    words = _dir_words(name)
    if not words:
        return False
    return all(w in _PLATFORM_DIR_WORDS for w in words) or " ".join(words) in _plat._ALIAS_TO_SYSTEM


def _is_nested_dir(name: str) -> bool:
    """A subfolder that is part of its parent game, never a game itself."""
    low = name.lower().strip()
    return (
        low in _CONTENT_SUBDIRS
        or _is_extra_dir(low)
        or bool(_DISC_DIR_RE.match(low))
        or low.endswith("_data")
        or _is_platform_dir(low)
    )


def _list_dirs(path: Path, _visited: set[str] | None = None) -> list[Path]:
    """Subdirectories of ``path`` that do not loop back to a visited folder."""
    if _visited is None:
        _visited = set()
    result = []
    for c in _ls(path)[1]:
        try:
            real = os.path.realpath(c)
        except OSError:
            real = str(c)
        if real in _visited:
            log.debug("Skipping cyclic symlink/junction: %s -> %s", c, real)
            continue
        result.append(c)
    return result


def _normalize_root(root: str) -> str:
    stripped = root.strip()
    if re.fullmatch(r"[A-Za-z]:", stripped):
        return stripped + "/"
    return stripped


def scan_games(
    root: str,
    recursive: bool = False,
    skip: set[str] | None = None,
    *,
    dedupe: bool = True,
) -> Iterator[ScannedFolder]:
    """Yield a :class:`ScannedFolder` for every game found under ``root``.

    Parameters
    ----------
    root : str
        Drive letter (``D:``) or folder path (``/mnt/games``).
    recursive : bool
        Also descend into folders that hold nothing but same-titled
        subfolders (wrapper folders) instead of cataloguing the wrapper.
    skip : set[str], optional
        Extra folder names (lowercased) to skip beyond DEFAULT_SKIP.
    dedupe : bool
        Collapse entries with the same title on the same platform
        (:func:`dedupe_games`). Different platforms are always kept.
    """
    global _cache
    root = _normalize_root(root)
    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(f"Path does not exist: {root}")
    if root_path.is_file():
        raise NotADirectoryError(f"Expected a folder/drive, got a file: {root}")

    skip = {s.lower() for s in (skip or set())} | DEFAULT_SKIP
    _steam_manifest_cache.clear()
    visited: set[str] = set()
    try:
        visited.add(os.path.realpath(root_path))
    except OSError:
        pass

    _cache = {}
    try:
        results: list[ScannedFolder] = []
        for child in _list_dirs(root_path, visited):
            if child.name.lower() in skip or _should_skip(child.name):
                continue
            results.extend(_resolve(child, skip, recursive=recursive, _visited=visited))
        results.extend(_loose_games(root_path))
        if dedupe:
            results = dedupe_games(results)
    finally:
        _cache = None
    yield from results


def _child_dirs(path: Path, skip: set[str], visited: set[str]) -> list[Path]:
    return [
        c for c in _list_dirs(path, visited)
        if not (_should_skip(c.name) or c.name.lower() in skip or _is_extra_dir(c.name))
    ]


def _resolve(
    path: Path,
    skip: set[str],
    recursive: bool,
    _visited: set[str] | None = None,
) -> Iterator[ScannedFolder]:
    """Yield games from ``path`` according to its classification."""
    if _visited is None:
        _visited = set()
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

    if _is_container(path.name):
        yield from _loose_games(path)
        for child in _child_dirs(path, skip, _visited):
            yield from _resolve(child, skip, recursive=recursive, _visited=_visited)
        return

    kind = _classify(path, skip, recursive)
    if kind == "game":
        main = _make_scanned(path, store=detect_store(str(path)))
        yield main
        yield from _variant_entries(path, main)
    elif kind == "group":
        yield from _loose_games(path)
        for child in _child_dirs(path, skip, _visited):
            yield from _resolve(child, skip, recursive=recursive, _visited=_visited)


def _classify(path: Path, skip: set[str], recursive: bool = False) -> str:
    """``"game"``, ``"group"`` or ``"skip"`` for a non-container folder."""
    files, dirs = _ls(path)
    dirs = [d for d in dirs if not (_should_skip(d.name) or d.name.lower() in skip)]
    if _has_strong_marker(path, files):
        return "game"
    title = _title_key(clean_folder_name(path.name))
    evdirs = [d for d in dirs if not _is_nested_dir(d.name) and _has_evidence(d, skip)]
    foreign = [d for d in evdirs if _title_key(clean_folder_name(d.name)) != title or not title]
    if foreign and not _same_product_dirs(path, foreign):
        return "group"
    if recursive and evdirs and not files:
        return "group"
    clusters = _clusters(_loose_items(path))
    package = _has_package_marker(files)
    if not clusters:
        if package or evdirs or _has_evidence(path, skip):
            return "game"
        return "skip"
    if package:
        return "game"
    keys = [c[0] for c in clusters]
    sequels = [k for k in keys if k != title and k.startswith(title) and k[len(title):].isdigit()]
    if title and title in keys and not sequels:
        return "game"
    installers = [c for c in clusters if c[1]]
    folder_title = clean_folder_name(path.name)
    specific = (
        _title_quality(folder_title) > 0
        and not _has_parent_junk(folder_title)
        and not re.match(r"^\d+\s*[-_.]", path.name)
    )
    if title and not sequels and len(installers) <= 1 and all(
        _related(folder_title, c[2]) for c in clusters
    ):
        return "game"
    if len(installers) == 1 and (
        _related(folder_title, installers[0][2]) or (len(clusters) == 1 and specific)
    ):
        return "game"
    return "group"


def _same_product_dirs(path: Path, dirs: list[Path]) -> bool:
    """Subfolders that are install steps of one GOG product (same build ID)."""
    ids: set[str] = set(_gog_ids(path))
    for d in dirs:
        sub = _gog_ids(d)
        if not sub:
            return False
        ids |= sub
    return len(ids) == 1


def _has_strong_marker(path: Path, files: list[Path]) -> bool:
    """An installed game: a real game binary, GOG/Steam metadata at the top."""
    for f in files:
        low = f.name.lower()
        if re.match(r"goggame-\d+\.info$", low) or low == "steam_appid.txt":
            return True
        if _is_game_binary_file(f) and not _is_installer_name(f.name):
            stem = re.sub(r"\.(exe|sh|bin|appimage|x86_64|x86)$", "", low)
            if stem not in _NON_GAME_EXES and stem not in _NON_GAME_SCRIPTS:
                return True
    return _read_steam_manifest(path) is not None


def _has_package_marker(files: list[Path]) -> bool:
    """A downloaded single-game package: repack parts, bare installer, scene ISO, ..."""
    names = [f.name.lower() for f in files]
    suffixes = {f.suffix.lower() for f in files}
    if any(re.match(r"^(?:fg|setup)-.*\.bin$", n) for n in names) or ".doi" in suffixes:
        return True
    for n in names:
        stem, ext = os.path.splitext(n)
        if ext == ".exe" and re.fullmatch(r"(?:setup|install|installer)(?:-[a-z0-9]+)?", stem):
            return True
        if ext in (".exe", ".sh") and _looks_like_installer(n):
            return True
    if ".nfo" in suffixes and suffixes & {".iso", ".rar", ".zip", ".7z"}:
        return True
    if ".cue" in suffixes and ".bin" in suffixes:
        return True
    return _part_sets(files) >= 1


_MULTIPART_RAR_RE = re.compile(r"^.+\.part(\d+)\.rar$", re.IGNORECASE)


def _part_sets(files: list[Path]) -> int:
    """Number of distinct multi-part archive sets (>=2 parts) among ``files``."""
    counts: dict[str, int] = {}
    for c in files:
        m = _MULTIPART_RAR_RE.match(c.name)
        if m:
            base = _squash(re.sub(r"\.part\d+\.rar$", "", c.name, flags=re.IGNORECASE))
        elif re.search(r"\.(?:7z|zip|rar)\.\d{3}$", c.name, re.IGNORECASE):
            base = _squash(re.sub(r"\.(?:7z|zip|rar)\.\d{3}$", "", c.name, flags=re.IGNORECASE))
        else:
            continue
        counts[base] = counts.get(base, 0) + 1
    return sum(1 for n in counts.values() if n >= 2)


def _is_evidence_file(f: Path) -> bool:
    """True when a file indicates a game lives here (binary, installer, dump, ...)."""
    low = f.name.lower()
    suffix = f.suffix.lower()
    if suffix in (".exe", ".msi", ".doi") or suffix in _plat.LINUX_BINARY_EXTENSIONS:
        words = set(re.split(r"[\s._\-()\[\]+,]+", low))
        return not words & _NON_EVIDENCE_TOKENS
    if re.match(r"goggame-\d+\.info$", low) or low == "steam_appid.txt":
        return True
    if suffix == ".bin" and re.match(r"^(?:fg|setup)[-_]", low):
        return True
    if suffix in _plat.CONSOLE_IMAGE_EXTENSIONS or suffix in _plat.ANDROID_EXTENSIONS:
        return True
    if _is_archive(f) and not _is_multipart_continuation(f):
        name = _clean_archive_name(f.name)
        return bool(name) and _title_quality(name) > 0 and not _is_extras_file(f.name)
    return _plat._is_elf(f)


def _has_evidence(path: Path, skip: set[str], depth: int = 3) -> bool:
    key = f"{path}|{depth}"
    hit = _cached("evidence", key)
    if hit is not None:
        return hit
    files, dirs = _ls(path)
    found = any(_is_evidence_file(f) for f in files)
    if not found and depth > 0:
        for d in dirs:
            low = d.name.lower()
            if low in skip or _should_skip(low) or _is_extra_dir(low):
                continue
            if _has_evidence(d, skip, depth - 1):
                found = True
                break
    return _store_cache("evidence", key, found)


def _walk_files(path: Path, depth: int = 2, limit: int = 3000) -> list[tuple[Path, int]]:
    """(file, depth) pairs under ``path`` breadth-first, skipping extras folders."""
    out: list[tuple[Path, int]] = []
    queue: list[tuple[Path, int]] = [(path, 0)]
    while queue and len(out) < limit:
        d, level = queue.pop(0)
        files, dirs = _ls(d)
        out.extend((f, level) for f in files)
        if level < depth:
            queue.extend((s, level + 1) for s in dirs if not _is_extra_dir(s.name))
    return out[:limit]


def _content_verdict(f: Path, level: int) -> str | None:
    suffix = f.suffix.lower()
    if _is_extras_file(f.name) and suffix not in _plat.ROM_EXTENSIONS:
        return None
    peek = level <= 1 or (suffix == ".zip" and level <= 2)
    if suffix == ".sh" and level > 0:
        return None
    verdict = _plat.file_content(f, peek=peek)
    if verdict is None and _is_archive(f) and not _is_multipart_continuation(f):
        return _archive_name_verdict(f)
    return verdict


def _archive_name_verdict(f: Path) -> str:
    named = _plat.name_hint(f.name)
    if named is None:
        return _plat.WEAK_PC
    if named == _plat.PC:
        return named
    if _plat.path_hint(str(f.parent)) in (_plat.PC_FAN_PORT, _plat.PC_MOD):
        return _plat.WEAK_PC
    return named


def _folder_platform(path: Path) -> str:
    verdicts: list[str | None] = []
    for f, level in _walk_files(path):
        v = _content_verdict(f, level)
        if v == _plat.PC:
            return _plat.resolve(_plat.PC, str(path))
        verdicts.append(v)
    return _plat.resolve(_plat.combine(verdicts), str(path))


def _make_scanned(path: Path, store: str, exe_paths: list[Path] | None = None) -> ScannedFolder:
    name = path.name
    cleaned = clean_folder_name(name)
    cleaned = smart_detect_game_name(path, cleaned, exe_paths)
    files = _ls(path)[0]
    resolved_store = detect_store(str(path), api_store_hint=store) or store
    if not resolved_store:
        resolved_store = _store_from_files(files)
    source = "installed" if _has_strong_marker(path, files) else "folder"
    return ScannedFolder(
        folder_name=name,
        folder_path=str(path.resolve()),
        cleaned_name=_display_case(cleaned or name),
        platform=_folder_platform(path),
        store=resolved_store,
        is_library_root=False,
        source=source,
    )


def _display_case(name: str) -> str:
    """Title-case names that arrive all lower-case (``metal eden``)."""
    return capwords(name) if name.islower() else name


def _store_from_files(files: Iterable[Path]) -> str:
    for f in files:
        low = f.name.lower()
        if re.match(r"goggame-\d+\.info$", low) or _is_gog_installer(f.name):
            return "GOG"
        if low == "steam_appid.txt":
            return "Steam"
    return ""


def _is_gog_installer(filename: str) -> bool:
    low = filename.lower()
    if _GOG_LINUX_RE.match(low):
        return True
    return bool(_GOG_SETUP_RE.match(low) and _GOG_ID_RE.search(low))


def _variant_entries(path: Path, main: ScannedFolder) -> Iterator[ScannedFolder]:
    """Extra entries for builds of the same game for other platforms.

    A folder holding a Windows installer plus a GOG Linux installer, an APK
    or a console dump yields one more entry per extra platform (pointing at
    the largest file of that platform), titled like the folder's game.
    """
    best: dict[str, tuple[int, Path]] = {}
    for f, level in _walk_files(path):
        suffix = f.suffix.lower()
        label: str | None = None
        if suffix in _plat.ANDROID_EXTENSIONS:
            label = _plat.ANDROID
        elif suffix in _plat.ROM_EXTENSIONS:
            label = _plat.ROM_EXTENSIONS[suffix]
        elif suffix in _plat.SNIFF_EXTENSIONS and level <= 1:
            sniffed = _plat.sniff_disc(f)
            if sniffed and sniffed not in (_plat.WEAK_PC, _plat.CONSOLE):
                label = sniffed
        elif level == 0 and (
            (suffix == ".sh" and (_GOG_LINUX_RE.match(f.name) or _SH_ID_RE.search(f.name)))
            or suffix in (".appimage", ".deb", ".rpm")
        ):
            label = _plat.PC_LINUX
        if not label or label == main.platform:
            continue
        if label == _plat.PC_LINUX and main.platform not in (_plat.PC, _plat.PC_FAN_PORT, _plat.PC_MOD):
            continue
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        if label not in best or size > best[label][0]:
            best[label] = (size, f)
    for label in sorted(best):
        f = best[label][1]
        yield ScannedFolder(
            folder_name=f.name,
            folder_path=str(f.resolve()),
            cleaned_name=main.cleaned_name,
            platform=label,
            store=main.store if label in _plat.PC_PLATFORMS else "",
            is_library_root=False,
            source="variant",
        )


def _looks_like_game_name(name: str) -> bool:
    """Heuristic: does this string look like a real game name?"""
    n = name.strip()
    if len(n) < 2:
        return False
    if n.isdigit():
        return False
    return any(ch.isalpha() for ch in n)


def _clean_exe_name(filename: str) -> str:
    """Extract a game name from an executable filename.

    Handles CamelCase (``HollowKnight`` -> ``Hollow Knight``), all-caps
    prefixes (``DOOMEternal`` -> ``DOOM Eternal``), and architecture
    suffixes (``Game-x64vk`` -> ``Game``).
    """
    name = re.sub(r"\.(exe|sh|bin|appimage|x86_64|x86)$", "", filename, flags=re.IGNORECASE)
    name = _ARCH_SUFFIXES.sub("", name)
    name = _ALLCAPS_SPLIT.sub(r"\1 \2", name)
    name = _CAMEL_SPLIT.sub(r"\1 \2", name)
    name = re.sub(r"[_.]+", " ", name)
    name = re.sub(r"\s{2,}", " ", name).strip()
    return name


def _split_word_digits(token: str) -> list[str]:
    m = re.fullmatch(r"([A-Za-z]{3,})(\d{1,2})", token)
    if not m or m.group(1).lower() in ("hotfix", "patch", "update", "build", "fix", "win"):
        return [token]
    return [m.group(1), m.group(2)]


def _join_possessives(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for t in tokens:
        if t.lower() == "s" and out and out[-1].isalpha():
            out[-1] = out[-1] + "'s"
        else:
            out.append(t)
    return out


def _polish_title(name: str) -> str:
    """Strip installer/version leftovers from a candidate title.

    Removes parenthesised groups containing digits (``(64bit)``, ``(3.2)``),
    single-letter tags (``(a)``), trailing fix/patch/update/version tokens,
    GOG's ``tm`` trademark residue (``Star Warstm`` -> ``Star Wars``) and
    upper-cases Roman numerals (``Ii`` -> ``II``).
    """
    n = re.sub(r"\((?=[^)]*\d)[^)]*\)", " ", name or "")
    n = re.sub(r"\(\s*[a-z]\s*\)", " ", n, flags=re.IGNORECASE)
    n = re.sub(r"\bmusic\s+fix\b", " ", n, flags=re.IGNORECASE)
    n = re.sub(r"\b(?:lang|language|content)\s+update\b", " ", n, flags=re.IGNORECASE)
    tokens = []
    for t in n.split():
        if len(t) >= 5 and t.lower().endswith("tm") and t[:-2].isalpha():
            t = t[:-2]
        tokens.append(_ROMAN_TITLE.get(t, t))
    while len(tokens) > 1 and _TRAILING_JUNK_RE.match(tokens[-1]):
        tokens.pop()
    while len(tokens) > 1 and tokens[-1].lower() == "update":
        tokens.pop()
    return " ".join(tokens).strip(" -")


def _clean_gog_setup_name(filename: str) -> str:
    """Extract a game name from a GOG setup executable filename.

    Example: ``setup_achilles_legends_untold_1.4.0.0_(74603).exe``
          -> ``Achilles Legends Untold``
    """
    m = _GOG_SETUP_RE.match(filename)
    if not m:
        return ""
    body = m.group(1)
    tokens = body.split("_")
    kept: list[str] = []
    for i, t in enumerate(tokens):
        if not t or not any(ch.isalnum() for ch in t):
            continue
        low = t.lower().strip("()")
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if re.match(r"^\(\d+\)(?:-\d+)?$", t):
            continue
        if len(t) >= 5 and t.isdigit() and re.match(r"^\(\d+\)(?:-\d+)?$", nxt):
            continue
        if re.match(r"^(?:v\d+(?:\.\d+)*[a-z]?|\d+(?:\.\d+)+[a-z]?)$", t, re.IGNORECASE):
            continue
        if low in _GOG_SETUP_NOISE and not (low in _STORE_WORDS and not kept):
            continue
        kept.extend(_split_word_digits(t))
    return _polish_title(capwords(" ".join(kept)))


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
        if suffix in (".appimage", ".x86_64"):
            return True
        if suffix in (".sh", ".bin"):
            return os.access(entry, os.X_OK)
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
    if suffix == ".exe":
        return True
    if suffix in (".appimage", ".x86_64"):
        return True
    if sys.platform == "win32":
        return False
    return _is_linux_executable(entry)


def _exe_files_at_depth(folder: Path, max_depth: int) -> list[Path]:
    """Collect executable files up to *max_depth* subfolder levels."""
    out: list[Path] = []

    def _scan(d: Path, depth: int) -> None:
        files, dirs = _ls(d)
        out.extend(f for f in files if _is_game_binary_file(f))
        if depth < max_depth:
            for entry in dirs:
                name_lower = entry.name.lower()
                if name_lower not in _SKIP_SUBDIRS and not _is_extra_dir(name_lower):
                    _scan(entry, depth + 1)

    _scan(folder, 0)
    return out


def _collect_exe_paths(folder: Path) -> list[Path]:
    """Executables in the folder; one level deeper when the top level is empty."""
    paths = _exe_files_at_depth(folder, 1)
    if not paths:
        paths = _exe_files_at_depth(folder, 2)
    return paths


def _read_pe_metadata(path: Path) -> dict[str, str]:
    """Read ProductName/FileDescription from a Windows PE VERSIONINFO resource.

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
    """Name of the main game among the folder's GOG ``setup_*`` installers.

    DLC, soundtrack and artbook installers sit next to the base game; the
    base game is the installer set with the largest total size (``.exe``
    plus its ``-N.bin`` volumes). Ties prefer the shortest name.
    """
    totals: dict[str, int] = {}
    extras: set[str] = set()
    for entry in _ls(folder)[0]:
        if entry.suffix.lower() not in (".exe", ".sh", ".bin"):
            continue
        if not entry.name.lower().startswith("setup_") or entry.stem.lower() == "setup":
            continue
        name = _clean_gog_setup_name(entry.name)
        if not _looks_like_game_name(name):
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            size = 0
        totals[name] = totals.get(name, 0) + size
        if _is_extras_file(entry.name):
            extras.add(name)
    if not totals:
        return None
    main = [n for n in totals if n not in extras]
    if not main:
        return None
    return min(main, key=lambda n: (-totals[n], len(n)))


def _read_gog_metadata(folder: Path) -> str | None:
    """Read game name from GOG's ``goggame-*.info`` JSON file.

    Prefers the file whose filename ID equals the JSON ``gameId`` (the base
    game over DLC/soundtrack entries); falls back to the first readable one.
    """
    candidates: list[tuple[str, str, str]] = []
    for entry in _ls(folder)[0]:
        m = re.match(r"goggame-(\d+)\.info$", entry.name, re.IGNORECASE)
        if not m:
            continue
        file_id = m.group(1)
        try:
            with open(entry, encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            log.debug("Cannot read GOG metadata %s: %s", entry, e)
            continue
        if not isinstance(data, dict):
            log.debug("Skipping non-object GOG metadata %s", entry)
            continue
        name = data.get("name") or data.get("Name")
        if not name or not _looks_like_game_name(str(name)):
            continue
        game_id = str(data.get("gameId") or data.get("GameId") or "")
        candidates.append((file_id, game_id, str(name).strip()))
    if not candidates:
        return None
    for file_id, game_id, name in candidates:
        if game_id and file_id == game_id:
            return name
    return candidates[0][2]


_steam_manifest_cache: dict[str, dict[str, str]] = {}


def _read_steam_manifest(folder: Path) -> str | None:
    """Read game name from Steam's ``appmanifest_*.acf`` in the steamapps folder.

    Manifests are cached per ``steamapps/`` directory.
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
        entries = list(steamapps_dir.iterdir())
    except OSError as e:
        log.debug("Cannot list steamapps dir %s: %s", steamapps_dir, e)
        return result
    for entry in entries:
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
    return result


def _looks_like_installer(filename: str) -> bool:
    """True if an executable filename carries an installer marker token.

    Bare ``setup.exe``/``installer.exe`` carry no title and are excluded.
    """
    stem = re.sub(r"\.(exe|sh|bin|appimage)$", "", filename, flags=re.IGNORECASE)
    low = stem.lower()
    if low in _NON_GAME_EXES or low in _NON_GAME_SCRIPTS:
        return False
    if low.startswith("setup_"):
        return False
    if re.fullmatch(r"(?:setup|install|installer)-[a-z0-9]+", low):
        return False
    if re.search(r"(?i)(?:^|[-_.\s])(?:setup|install(?:er|shield)?|repack|unpacked)(?:$|[-_.\s])", low):
        return True
    return bool(re.search(r"(?i)(?:setup|install(?:er|shield)?|repack|unpacked)$", low))


def _clean_installer_name(filename: str) -> str:
    """Extract the game title embedded in an installer filename.

    ``Hollow Knight-Setup.exe`` -> ``Hollow Knight``;
    ``DoomEternalSetup.exe`` -> ``Doom Eternal``. Returns ``""`` when no
    title remains.
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
        if low in SOURCE_GROUPS or low in _INSTALL_TOKENS:
            continue
        if re.match(r"^v?\d+(?:\.\d+)+$", low):
            continue
        if re.match(r"^\(\d+\)$", t):
            continue
        kept.append(t)
    if not kept:
        return ""
    return capwords(_clean_exe_name(" ".join(kept)).replace("-", " "))


_ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".iso"}
_TAR_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")

_URL_PREFIX_RE = re.compile(
    r"^(?:www\.)?[a-z0-9][a-z0-9.\-]*\.(?:com|net|org|site|io|xyz|me)\b[-_\s]*",
    re.IGNORECASE,
)

_BITNESS_RE = re.compile(r"\b(?:32|64)[\- ]?bit\b", re.IGNORECASE)
_PART_TOKEN_RE = re.compile(r"\bpart\d+\b", re.IGNORECASE)

_ARCHIVE_JUNK_NAMES = {
    "readme", "manual", "notes", "docs", "data", "cache", "temp",
    "backup", "backups", "download", "downloads", "archive", "archives",
    "patch", "patches", "update", "updates", "crack", "cracks",
    "trainer", "trainers", "cheats", "saves", "save", "savegame",
    "savegames", "zips", "rars", "isos", "misc", "stuff", "unknown",
    "game", "games",
}


def _is_archive(entry: Path) -> bool:
    low = entry.name.lower()
    return entry.suffix.lower() in _ARCHIVE_EXTENSIONS or low.endswith(_TAR_SUFFIXES)


def _is_multipart_continuation(entry: Path) -> bool:
    m = _MULTIPART_RAR_RE.match(entry.name)
    return bool(m and int(m.group(1)) > 1)


def _is_extras_file(filename: str) -> bool:
    """Manuals, soundtracks, cracks, patches and saves are never games."""
    words = re.split(r"[\s._\-()\[\]+,]+", filename.lower())
    return any(w in _EXTRAS_FILE_TOKENS for w in words)


def _strip_archive_ext(filename: str) -> str:
    low = filename.lower()
    for suf in _TAR_SUFFIXES:
        if low.endswith(suf):
            return filename[: -len(suf)]
    return re.sub(r"\.(zip|7z|rar|iso)$", "", filename, flags=re.IGNORECASE)


def _clean_archive_name(filename: str) -> str:
    """Extract a game title from an archive/dump filename.

    ``Hollow.Knight.v1.0.231.32-bit.(48932).zip`` -> ``Hollow Knight``;
    ``Hollow Knight.part1.rar`` -> ``Hollow Knight``. Returns ``""`` when
    the stem is junk (``readme.zip``, ``data.zip``, ...).
    """
    stem = _strip_archive_ext(filename)
    if not stem:
        return ""
    if stem.lower().startswith("setup_"):
        return _clean_gog_setup_name(filename)
    if stem.lower() in _ARCHIVE_JUNK_NAMES:
        return ""
    if re.match(r"^(?:windows|win|office|adobe)[\s._-]*\d*$", stem, re.IGNORECASE):
        return ""
    stem = re.sub(r"^game[-_]", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[-_](?:master|main)$", "", stem, flags=re.IGNORECASE)
    stem = _strip_system_prefix(stem)
    stem = _PART_TOKEN_RE.sub(" ", stem)
    stem = _URL_PREFIX_RE.sub(" ", stem)
    stem = _SITE_RE.sub(" ", stem)
    stem = _BITNESS_RE.sub(" ", stem)
    stem = re.sub(r"(?:\b(?:all|incl|including)[\s._-]+)?\bdlcs?\b", " ", stem, flags=re.IGNORECASE)
    stem = _ALLCAPS_SPLIT.sub(r"\1 \2", stem)
    stem = _CAMEL_SPLIT.sub(r"\1 \2", stem)
    return clean_folder_name(stem)


def _strip_system_prefix(stem: str) -> str:
    """Drop system tags: ``N64 Zelda`` -> ``Zelda``, ``Halo.Wii-GRP`` -> ``Halo``."""
    return _plat.strip_system_tags(stem)


def _squash(name: str) -> str:
    """Reduce a name to bare alphanumerics so case/punctuation can't differ."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _title_key(name: str) -> str:
    """Comparison key for titles: case, accents, punctuation, articles,
    edition suffixes and Roman numerals do not matter.

    ``The Legend of Zelda: Twilight Princess`` and
    ``Legend of Zelda Twilight Princess`` share a key, as do ``Far Cry`` /
    ``Farcry`` and ``Hello Neighbor 2 Deluxe Edition`` / ``Hello Neighbor II``.
    """
    return "".join(_title_tokens(name))


def _title_tokens(name: str) -> list[str]:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("&", " and ").replace("_", " ")
    s = re.sub(r"['’`]", "", s)
    s = _EDITION_RE.sub(" ", s)
    tokens = [_ROMAN.get(t, t) for t in re.findall(r"\w+", s)]
    return [t for t in tokens if t not in ("the", "a", "an")]


def _related(a: str, b: str) -> bool:
    """Titles share at least half of the shorter one's words."""
    ta, tb = set(_title_tokens(a)), set(_title_tokens(b))
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.5


def _media_title(filename: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename)
    return clean_folder_name(stem)


def _make_file_entry(f: Path, name: str, source: str) -> ScannedFolder:
    store = detect_store(str(f)) or ("GOG" if _is_gog_installer(f.name) else "")
    return ScannedFolder(
        folder_name=f.name,
        folder_path=str(f.resolve()),
        cleaned_name=_display_case(name),
        platform=_plat.resolve(_plat.file_content(f), str(f)),
        store=store,
        is_library_root=False,
        source=source,
    )


def _loose_items(folder: Path) -> list[tuple[ScannedFolder, str, bool]]:
    """Loose game files in ``folder`` as (entry, cluster key, is_installer).

    Covers archives, GOG/Linux installers, disc images, ROM dumps and APKs.
    Manuals, soundtracks, cracks and multi-part continuation volumes are
    ignored. The cluster key groups files of one product: the GOG build ID
    when present, otherwise the title key.
    """
    key = str(folder)
    hit = _cached("loose", key)
    if hit is not None:
        return hit
    items: list[tuple[ScannedFolder, str, bool]] = []
    for c in _ls(folder)[0]:
        suffix = c.suffix.lower()
        low = c.name.lower()
        if _is_extras_file(c.name) and suffix not in _plat.ROM_EXTENSIONS:
            continue
        name = ""
        source = ""
        installer = False
        if _GOG_SETUP_RE.match(c.name) and suffix in (".exe", ".sh", ".bin"):
            if suffix == ".bin" and _VOLUME_BIN_RE.search(low):
                continue
            name = _clean_gog_setup_name(c.name)
            source, installer = "installer", True
        elif _GOG_LINUX_RE.match(c.name):
            name = _clean_gog_linux_name(c.name)
            source, installer = "installer", True
        elif suffix == ".sh":
            name = _clean_generic_sh_name(c.name)
            source, installer = "installer", True
        elif _is_archive(c):
            if _is_multipart_continuation(c):
                continue
            name = _clean_archive_name(c.name)
            source = "image" if suffix == ".iso" else "archive"
        elif suffix in _plat.CONSOLE_IMAGE_EXTENSIONS or suffix in _plat.ANDROID_EXTENSIONS:
            name = _media_title(c.name)
            source = "image" if suffix in _plat.SNIFF_EXTENSIONS else "rom"
        if not name or not _looks_like_game_name(name) or _title_quality(name) <= 0:
            continue
        entry = _make_file_entry(c, name, source)
        m = _GOG_ID_RE.search(c.name) or _SH_ID_RE.search(c.name)
        group = f"id:{m.group(1)}" if m and installer else _title_key(name)
        items.append((entry, group, installer))
    return _store_cache("loose", key, items)


def _clusters(items: list[tuple[ScannedFolder, str, bool]]) -> list[tuple[str, bool, str]]:
    """Distinct products among loose items as (title key, is_installer, title)."""
    seen: dict[str, tuple[str, bool, str]] = {}
    for entry, group, installer in items:
        if group not in seen:
            seen[group] = (_title_key(entry.cleaned_name), installer, entry.cleaned_name)
    return list(seen.values())


def _gog_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    for f in _ls(path)[0]:
        if f.name.lower().startswith(("setup_", "patch_")):
            m = _GOG_ID_RE.search(f.name)
            if m:
                ids.add(m.group(1))
    return ids


def _loose_games(folder: Path) -> list[ScannedFolder]:
    """Loose game entries of ``folder``, one per (title, platform)."""
    out: list[ScannedFolder] = []
    seen: set[tuple[str, str]] = set()
    for entry, _group, _inst in _loose_items(folder):
        k = (_title_key(entry.cleaned_name) or entry.folder_path, entry.platform)
        if k in seen:
            continue
        seen.add(k)
        out.append(entry)
    return out


_SH_TRAILING_RE = re.compile(r"^v?\d+(\.\d+)*[a-z]?$", re.IGNORECASE)
_SH_TRAILING_NOISE = {
    "linux", "win", "windows", "hf", "hotfix", "en", "de", "fr", "es", "it",
    "pt", "ru", "pl", "cs", "hu", "jp", "cn", "kr", "mx", "gog", "x64",
    "x86", "64bit", "32bit", "update", "patch", "fix", "build",
}


def _clean_gog_linux_name(filename: str) -> str:
    """Extract the game name from a GOG Linux installer (``gog_<name>_<ver>.sh``)."""
    m = _GOG_LINUX_RE.match(filename)
    if not m:
        return ""
    tokens = m.group(1).split("_")
    kept: list[str] = []
    for i, t in enumerate(tokens):
        if not t or not any(ch.isalnum() for ch in t):
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if re.match(r"^\(\d+\)(?:-\d+)?$", t):
            continue
        if len(t) >= 5 and t.isdigit() and re.match(r"^\(\d+\)(?:-\d+)?$", nxt):
            continue
        if re.match(r"^(?:v\d+(?:\.\d+)*[a-z]?|\d+(?:\.\d+)+[a-z]?)$", t, re.IGNORECASE):
            continue
        if t.lower().strip("()") in _GOG_SETUP_NOISE:
            continue
        kept.extend(_split_word_digits(t))
    return _polish_title(capwords(" ".join(_join_possessives(kept))))


def _clean_generic_sh_name(filename: str) -> str:
    stem = re.sub(r"\.sh$", "", filename, flags=re.IGNORECASE)
    if stem.lower() in _NON_GAME_SCRIPTS or stem.lower() in _ARCHIVE_JUNK_NAMES:
        return ""
    tokens = stem.split("_")
    cut = False
    for i, t in enumerate(tokens):
        if i > 0 and t.lower() in _LANG_TOKENS:
            tokens = tokens[:i]
            cut = True
            break
    while tokens and not cut:
        low = tokens[-1].lower()
        if _SH_TRAILING_RE.match(low) or low in _SH_TRAILING_NOISE:
            tokens.pop()
        else:
            break
    kept = [t for t in tokens if any(ch.isalnum() for ch in t)]
    if not kept:
        return ""
    return capwords(" ".join(_join_possessives(kept)))


def _is_installer_name(filename: str) -> bool:
    stem = re.sub(r"\.(exe|sh|bin|appimage)$", "", filename, flags=re.IGNORECASE)
    low = stem.lower()
    if low.startswith(("setup_", "gog_", "patch_", "update_", "setup-", "install-")):
        return True
    if low in ("setup", "install", "installer"):
        return True
    return _looks_like_installer(filename)


def _title_quality(name: str, strict: bool = False) -> float:
    """Score how title-like a candidate name is (0.0 - 1.0).

    Penalizes junk tokens (source-group tags, installer markers), dotted
    version numbers and digit-heavy strings; rewards 2-5 word titles.
    ``strict`` also treats engine names (Unity, Unreal, ...) as junk, which
    is used for executable-derived candidates (``UnrealGame.exe``).
    """
    n = (name or "").strip()
    if not _looks_like_game_name(n) or len(n) > 60:
        return 0.0
    tokens = [t for t in re.split(r"[\s:;,.\-—–]+", n) if t]
    if not tokens:
        return 0.0
    junk = _JUNK_TOKENS | _ENGINE_TOKENS if strict else _JUNK_TOKENS
    lows = [t.lower() for t in tokens]
    if all(t in junk for t in lows):
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
    score *= 0.6 ** sum(1 for t in lows if t in junk)
    if re.search(r"\d+\.\d+", n):
        score *= 0.6
    if sum(c.isdigit() for c in n) / max(len(n), 1) > 0.4:
        score *= 0.5
    return min(score, 1.0)


_PARENT_JUNK_TOKENS = _JUNK_TOKENS | {
    "new", "folder", "folders", "tmp", "temp", "unsorted", "downloads",
    "backups", "misc", "my", "stuff", "installers", "setups", "isos", "roms",
    "archives", "linux", "windows", "mac", "collection",
}


def _has_parent_junk(name: str) -> bool:
    return any(
        t.lower() in _PARENT_JUNK_TOKENS for t in re.split(r"[\s:;,.\-—–]+", name) if t
    )


def _installer_candidates(exe_paths: list[Path]) -> list[str]:
    """Game titles extracted from installer executable filenames."""
    names: list[str] = []
    for p in exe_paths:
        if not _looks_like_installer(p.name):
            continue
        name = _clean_installer_name(p.name)
        if name and _looks_like_game_name(name):
            names.append(name)
    return names


def _is_human_name(raw: str) -> bool:
    """A folder name typed by a person (spaces, no ``_`` or ``Word.Word``)."""
    return " " in raw and "_" not in raw and not re.search(r"[A-Za-z]\.[A-Za-z]", raw)


def _best_name_from_evidence(
    folder_path: Path, cleaned_folder_name: str, exe_paths: list[Path] | None = None
) -> str:
    """Pick the best game name by scoring evidence from every folder signal.

    Candidates (source weights): titled installer filenames 0.90, folder
    name typed by a person 0.88 (otherwise 0.60), main GOG ``setup_*``
    installer 0.85, PE ProductName 0.75, PE FileDescription 0.70, plain exe
    stems 0.55, parent folder name 0.40 (only when the folder name is
    junk). Score = weight x title quality, +0.10 when two sources agree.
    When the winner nearly matches another candidate (a typo or a missing
    space), the variant with more words is kept.
    """
    candidates: list[tuple[str, float, str]] = []

    def add(name: str, weight: float, source: str) -> None:
        name = (name or "").strip()
        if name and _looks_like_game_name(name):
            candidates.append((name, weight, source))

    if exe_paths is None:
        exe_paths = _collect_exe_paths(folder_path)

    for name in _installer_candidates(exe_paths):
        add(name, 0.90, "installer")

    gog = _find_gog_setup_exe(folder_path)
    if gog:
        add(gog, 0.85, "gog_setup")

    sized: list[tuple[Path, int]] = []
    for p in exe_paths:
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
            add(_polish_title(meta["product_name"]), 0.75, "pe_product")
        if meta.get("file_description"):
            add(_polish_title(meta["file_description"]), 0.70, "pe_desc")

    if _title_quality(cleaned_folder_name) > 0:
        human = _is_human_name(folder_path.name)
        folder_name = cleaned_folder_name if human else _polish_title(cleaned_folder_name)
        add(folder_name, 0.88 if human else 0.60, "folder")
    else:
        parent = folder_path.parent
        if not _is_container(parent.name):
            parent_name = clean_folder_name(parent.name)
            if _title_quality(parent_name) >= 0.55 and not _has_parent_junk(parent_name):
                add(parent_name, 0.40, "parent")

    for p, _size in sized:
        cleaned = _clean_exe_name(p.name)
        if cleaned:
            add(cleaned, 0.55, "stem")

    if not candidates:
        return cleaned_folder_name

    sources_by_key: dict[str, set[str]] = {}
    for name, _weight, source in candidates:
        sources_by_key.setdefault(_title_key(name), set()).add(source)

    best: tuple[tuple[float, int], str] | None = None
    for name, weight, source in candidates:
        q = _title_quality(name, strict=source in ("stem", "pe_product", "pe_desc"))
        if q <= 0:
            continue
        score = weight * q
        if len(sources_by_key[_title_key(name)]) > 1:
            score += 0.10
        key = (-score, len(name))
        if best is None or key < best[0]:
            best = (key, name)
    if best is None or -best[0][0] < 0.20:
        return cleaned_folder_name
    winner = best[1]
    win_key = _title_key(winner)
    win_source = next(src for n, _w, src in candidates if n == winner)
    for name, _weight, source in candidates:
        if source in ("stem", "parent") or name == winner or _title_quality(name) <= 0:
            continue
        other = _title_key(name)
        if other == win_key:
            better = len(name.split()) > len(winner.split())
        elif len(win_key) >= 6 and abs(len(other) - len(win_key)) <= 1:
            better = SequenceMatcher(None, win_key, other).ratio() >= 0.9 and (
                len(name.split()) > len(winner.split())
                or (win_source == "folder" and source in ("installer", "gog_setup"))
            )
        else:
            better = False
        if better:
            winner, win_key, win_source = name, other, source
    return winner


def smart_detect_game_name(
    folder_path: Path, cleaned_folder_name: str, exe_paths: list[Path] | None = None
) -> str:
    """Smart-detect the game name from multiple sources.

    Authoritative metadata wins outright: the Steam manifest
    (``appmanifest_*.acf``, matched by ``installdir``), then GOG metadata
    (``goggame-*.info``). Otherwise every remaining signal (installer
    filenames, the main GOG ``setup_*`` installer, PE version info, folder
    name, exe stems, parent folder) is scored by
    :func:`_best_name_from_evidence`.
    """
    name = _read_steam_manifest(folder_path)
    if name and _looks_like_game_name(name):
        return name

    name = _read_gog_metadata(folder_path)
    if name and _looks_like_game_name(name):
        return name

    return _best_name_from_evidence(folder_path, cleaned_folder_name, exe_paths)


def dedupe_key(name: str) -> str:
    """Public title key used to decide whether two entries are the same game."""
    return _title_key(name)


def dedupe_games(entries: Iterable[ScannedFolder]) -> list[ScannedFolder]:
    """Collapse entries that are the same game on the same platform.

    The kept copy is the most complete one: installed folder > game folder >
    loose installer > archive/dump > cross-platform variant, then one with a
    known store, then the shorter path. A missing store is filled from the
    dropped copy. Copies on different platforms are all kept. Order of first
    appearance is preserved.
    """
    kept: list[ScannedFolder] = []
    index: dict[tuple[str, str], int] = {}
    for e in entries:
        key = _title_key(e.cleaned_name)
        if not key:
            kept.append(e)
            continue
        k = (key, e.platform)
        if k not in index:
            index[k] = len(kept)
            kept.append(e)
            continue
        i = index[k]
        cur = kept[i]
        if _entry_rank(e) > _entry_rank(cur):
            if not e.store and cur.store:
                e.store = cur.store
            kept[i] = e
            log.debug("Duplicate %r: keeping %s over %s", e.cleaned_name, e.folder_path, cur.folder_path)
        else:
            if not cur.store and e.store:
                cur.store = e.store
            log.debug("Duplicate %r: keeping %s over %s", cur.cleaned_name, cur.folder_path, e.folder_path)
    return kept


def _entry_rank(e: ScannedFolder) -> tuple[int, int, int]:
    return (_SOURCE_RANK.get(e.source, 0), 1 if e.store else 0, -len(e.folder_path))
