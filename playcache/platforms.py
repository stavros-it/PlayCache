"""Platform detection for scanned games: PC vs console vs Android.

Three independent signals are combined:

* **content** - file extensions (ROM dumps, APKs, executables), disc-image
  headers (GameCube/Wii magic words, Sega IP headers, Xbox XDVDFS, ISO9660
  system identifiers incl. PS1/PS2/PSP/PS3) and the member list of zip files;
* **path** - folder segments that name a system (``PS2``, ``Nintendo
  GameCube``, ``1-Linux Games``, ``EMU Redump``, ``[Switch]`` tags);
* a default of ``PC`` when nothing else is known.

Strong PC content (executables, repack parts) beats a console path hint,
console content beats every path hint, and a generic ISO9660 image only
counts as PC when the path says nothing else.
"""
from __future__ import annotations

import logging
import os
import re
import struct
import sys
import zipfile
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

PC = "PC"
PC_LINUX = "PC (Linux)"
PC_FAN_PORT = "PC (Fan Port)"
PC_MOD = "PC (Mod)"
ANDROID = "ANDROID"
CONSOLE = "CONSOLE"
SWITCH = "SWITCH"

PC_PLATFORMS = frozenset({PC, PC_LINUX, PC_FAN_PORT, PC_MOD})

WEAK_PC = "PC?"

ROM_EXTENSIONS: dict[str, str] = {
    ".nsp": SWITCH, ".nsz": SWITCH, ".xci": SWITCH, ".xcz": SWITCH,
    ".nds": "NDS",
    ".3ds": "3DS", ".cia": "3DS", ".cci": "3DS", ".cxi": "3DS",
    ".gba": "GBA", ".gbc": "GBC", ".gb": "GB",
    ".nes": "NES", ".fds": "NES",
    ".sfc": "SNES", ".smc": "SNES",
    ".n64": "N64", ".z64": "N64", ".v64": "N64",
    ".gcm": "GAMECUBE", ".gcz": "GAMECUBE",
    ".wbfs": "WII",
    ".wux": "WII U", ".wua": "WII U", ".rpx": "WII U",
    ".cso": "PSP", ".pbp": "PSP",
    ".vpk": "PS VITA",
    ".gen": "GENESIS", ".smd": "GENESIS", ".32x": "32X",
    ".sms": "MASTER SYSTEM", ".gg": "GAME GEAR",
    ".gdi": "DREAMCAST", ".cdi": "DREAMCAST",
    ".xbe": "XBOX",
    ".pce": "PC ENGINE",
    ".ngp": "NEO GEO POCKET",
    ".ws": "WONDERSWAN", ".wsc": "WONDERSWAN",
    ".a26": "ATARI 2600", ".lnx": "LYNX",
}

ANDROID_EXTENSIONS = frozenset({".apk", ".xapk", ".apks"})
SNIFF_EXTENSIONS = frozenset({".iso", ".img", ".mdf", ".cue", ".rvz", ".wia"})
GENERIC_CONSOLE_EXTENSIONS = frozenset({".chd"})
CONSOLE_IMAGE_EXTENSIONS = (
    frozenset(ROM_EXTENSIONS) | SNIFF_EXTENSIONS | GENERIC_CONSOLE_EXTENSIONS
)

PC_BINARY_EXTENSIONS = frozenset({".exe", ".dll", ".msi", ".doi"})
LINUX_BINARY_EXTENSIONS = frozenset({".sh", ".appimage", ".x86_64", ".x86", ".deb", ".rpm"})

_SYSTEM_ALIASES: dict[str, tuple[str, ...]] = {
    SWITCH: ("switch", "nsw"),
    "WII U": ("wii u", "wiiu"),
    "WII": ("wii",),
    "GAMECUBE": ("gamecube", "game cube", "ngc", "gcn"),
    "N64": ("n64",),
    "SNES": ("snes", "super nintendo", "super famicom", "sfc"),
    "NES": ("nes", "famicom", "nintendo entertainment system"),
    "GB": ("gb", "game boy", "gameboy"),
    "GBC": ("gbc", "game boy color", "gameboy color"),
    "GBA": ("gba", "game boy advance", "gameboy advance"),
    "NDS": ("nds", "ds"),
    "3DS": ("3ds", "n3ds", "new 3ds"),
    "PS1": ("ps1", "psx", "psone", "ps one", "playstation", "playstation 1"),
    "PS2": ("ps2", "playstation 2"),
    "PS3": ("ps3", "playstation 3"),
    "PS4": ("ps4", "playstation 4"),
    "PS5": ("ps5", "playstation 5"),
    "PSP": ("psp", "playstation portable"),
    "PS VITA": ("ps vita", "psvita", "vita", "playstation vita"),
    "XBOX": ("xbox", "original xbox"),
    "XBOX 360": ("xbox 360", "x360", "xbox360"),
    "XBOX ONE": ("xbox one",),
    "GENESIS": ("genesis", "mega drive", "megadrive"),
    "SEGA CD": ("sega cd", "mega cd", "segacd", "megacd"),
    "SATURN": ("saturn",),
    "DREAMCAST": ("dreamcast",),
    "MASTER SYSTEM": ("master system", "sms"),
    "GAME GEAR": ("game gear", "gamegear"),
    "NEO GEO": ("neo geo", "neogeo"),
    "ARCADE": ("mame", "fbneo", "final burn neo"),
    ANDROID: ("android", "apk", "apks"),
}

_ALIAS_TO_SYSTEM: dict[str, str] = {
    alias: system for system, aliases in _SYSTEM_ALIASES.items() for alias in aliases
}

_VENDOR_WORDS = frozenset({"nintendo", "sony", "sega", "microsoft", "snk", "atari"})
_GENERIC_WORDS = frozenset({
    "games", "game", "roms", "rom", "isos", "iso", "collection", "library",
    "dumps", "dump", "backups", "backup", "set", "files", "images", "titles",
})
_EMU_WORDS = frozenset({
    "emu", "emus", "emulation", "emulator", "emulators", "roms", "rom",
    "redump", "nointro", "retroarch", "consoles", "console", "launchbox",
})
_PC_PHRASES = frozenset({"pc", "windows", "win", "pc windows", "steam", "gog", "epic"})
_FAN_PORT_PHRASES = frozenset({
    "ports", "port", "fan port", "fan ports", "pc port", "pc ports",
    "fanport", "fanports", "source ports", "source port", "decomp", "decomps",
    "recomp", "recomps", "recompilation", "recompilations", "decompilation",
    "decompilations",
})

_PC_BUILD_TOKENS = frozenset({"windows", "win32", "win64", "x64", "pc"})
_SCENE_TAGS: dict[str, str] = {
    "psv": "PS VITA", "xboxone": "XBOX ONE", "ps2dvd": "PS2", "ps3dvd": "PS3",
}

ALL_PLATFORMS: tuple[str, ...] = (
    PC, PC_LINUX, PC_FAN_PORT, PC_MOD, *sorted(_SYSTEM_ALIASES),
    *sorted({p for p in ROM_EXTENSIONS.values()} - set(_SYSTEM_ALIASES)), CONSOLE,
)

_GC_MAGIC = b"\xc2\x33\x9f\x3d"
_WII_MAGIC = b"\x5d\x1c\x9e\xa3"
_XBOX_MAGIC = b"MICROSOFT*XBOX*MEDIA"
_XBOX_OFFSETS = ((0x10000, "XBOX"), (0x18310000, "XBOX"),
                 (0xFDA0000, "XBOX 360"), (0x2090000, "XBOX 360"))
_PVD_LOCATIONS = ((0x8000, 2048, 0, False), (0x9310, 2352, 16, True),
                  (0x9318, 2352, 24, True))
_PS2_SIZE_HINT = 1_000_000_000
_ZIP_MEMBER_LIMIT = 5000
_SNIFF_BYTES = 0x9318 + 2048


def _segment_words(segment: str) -> list[str]:
    s = segment.lower()
    s = re.sub(r"^\d+\s*[-_.]\s*", "", s)
    return re.findall(r"[a-z0-9]+", s)


def _segment_hint(segment: str) -> str | None:
    """Platform named by one path segment, or ``None``."""
    words = _segment_words(segment)
    if not words:
        return None
    if "linux" in words:
        return PC_LINUX
    if "mod" in words:
        return PC_MOD
    while words and words[0] in _VENDOR_WORDS:
        words = words[1:]
    emu = False
    while words and (words[0] in _GENERIC_WORDS or words[0] in _EMU_WORDS):
        emu = emu or words[0] in _EMU_WORDS
        words = words[1:]
    while words and (words[-1] in _GENERIC_WORDS or words[-1] in _EMU_WORDS):
        emu = emu or words[-1] in _EMU_WORDS
        words = words[:-1]
    while words and words[0] in _VENDOR_WORDS:
        words = words[1:]
    phrase = " ".join(words)
    if not phrase:
        return CONSOLE if emu else None
    if phrase in _FAN_PORT_PHRASES or "fan port" in phrase:
        return PC_FAN_PORT
    if phrase in _PC_PHRASES:
        return PC
    return _ALIAS_TO_SYSTEM.get(phrase)


def _path_segments(path: str) -> list[str]:
    norm = path.replace("\\", "/")
    rest = os.path.splitdrive(norm)[1]
    if re.match(r"^[A-Za-z]:", rest):
        rest = rest[2:]
    return [s for s in rest.split("/") if s and not re.fullmatch(r"[A-Za-z]:", s)]


def _own_hint(seg: str) -> str | None:
    for tag in re.findall(r"[\[(]([^\])]+)[\])]", seg):
        for part in re.split(r"[,;/]", tag):
            hint = _segment_hint(part)
            if hint and hint != CONSOLE:
                return hint
    return _segment_hint(_strip_extension(seg))


def _strip_extension(seg: str) -> str:
    return re.sub(r"\.[A-Za-z0-9]{1,5}$", "", seg)


def name_hint(name: str) -> str | None:
    """Platform named inside a game's file or folder name.

    ``Kirby-Windows-x64.7z`` is PC; ``GAMECUBE Super Mario Sunshine.7z`` and
    ``Super.Mario.Odyssey.NSW-GRP.rar`` name a console. Region tags such as
    ``(USA)`` say nothing: Redump names PC discs the same way. Returns
    ``None`` when the name says nothing.
    """
    stem = _strip_extension(name.strip())
    tokens = {t for t in re.split(r"[\s._\-()\[\]+,]+", stem.lower()) if t}
    if tokens & _PC_BUILD_TOKENS:
        return PC
    prefix = _SYSTEM_PREFIX_RE.match(stem)
    if prefix:
        system = _ALIAS_TO_SYSTEM.get(prefix.group(1).lower())
        if system:
            return system
    scene = _scene_platform(stem)
    if scene:
        return scene[0]
    return None


_SYSTEM_PREFIX_RE = re.compile(r"^([A-Z0-9]{2,}(?: (?:U|360|ONE|VITA|CD))?)[\s_-]+(?=\S{2})")
_SCENE_RE = re.compile(r"^(\S+\.\S+)-[A-Za-z0-9]+$")
_SCENE_REGION_TOKENS = frozenset({"pal", "ntsc", "usa", "eur", "jpn", "multi", "multi5"})


def _scene_platform(stem: str) -> tuple[str, str] | None:
    m = _SCENE_RE.match(stem)
    if not m:
        return None
    parts = m.group(1).split(".")
    last = parts[-1].lower()
    system = _ALIAS_TO_SYSTEM.get(last) or _SCENE_TAGS.get(last)
    if not system or len(parts) < 2:
        return None
    parts = parts[:-1]
    while len(parts) > 1 and parts[-1].lower() in _SCENE_REGION_TOKENS:
        parts = parts[:-1]
    return system, ".".join(parts)


def strip_system_tags(stem: str) -> str:
    """Remove the system tags :func:`name_hint` reads from a name.

    ``N64 Zelda`` -> ``Zelda``; ``Super.Mario.Odyssey.NSW-GRP`` ->
    ``Super.Mario.Odyssey``; anything else is returned unchanged.
    """
    m = _SYSTEM_PREFIX_RE.match(stem)
    if m and m.group(1).lower() in _ALIAS_TO_SYSTEM:
        return stem[m.end():]
    scene = _scene_platform(stem)
    if scene:
        return scene[1]
    return stem


def path_hint(path: str) -> str | None:
    """Platform implied by the path, nearest segment first.

    Bracketed tags in a segment (``God of War [PS2]``) are checked before the
    segment itself. When the nearest segment names no system outright, its
    name is read with :func:`name_hint`; a console named there does not beat
    a ports or mods folder above it (``1-RECOMPILATIONS/N64 Zelda.7z`` is a
    PC port of an N64 game). Returns ``None`` when nothing names a platform.
    """
    segments = _path_segments(path)
    if not segments:
        return None
    own = _own_hint(segments[-1])
    if own:
        return own
    outer: str | None = None
    for seg in reversed(segments[:-1]):
        outer = _own_hint(seg)
        if outer:
            break
    named = name_hint(segments[-1])
    if named is None:
        return outer
    if outer in (PC_FAN_PORT, PC_MOD):
        return outer
    return named


def detect_platform(path: str) -> str:
    """Platform from the path alone (``PC`` when no folder names one)."""
    return path_hint(path) or PC


def resolve(content: str | None, path: str) -> str:
    """Combine a content verdict with the path hint into a final label."""
    hint = path_hint(path)
    if content in PC_PLATFORMS:
        if content == PC and hint in (PC_LINUX, PC_FAN_PORT, PC_MOD):
            return hint
        if content == PC_LINUX and hint in (PC_FAN_PORT, PC_MOD):
            return hint
        return content
    if content and content not in (WEAK_PC, CONSOLE):
        return content
    if hint:
        return hint
    if content == CONSOLE:
        return CONSOLE
    return PC


def _u32le(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def sniff_buffer(head: bytes, size: int = 0, reader=None) -> str | None:
    """Identify a disc image from its first bytes.

    ``reader(offset, length)`` (optional) reads arbitrary ranges for checks
    beyond ``head`` (Xbox XDVDFS, PS2 ``SYSTEM.CNF``). Returns a platform
    label, :data:`WEAK_PC` for a generic ISO9660 image, or ``None``.
    """
    if len(head) >= 0x4C and head[:4] in (b"RVZ\x01", b"WIA\x01"):
        disc_type = struct.unpack_from(">I", head, 0x48)[0]
        return {1: "GAMECUBE", 2: "WII"}.get(disc_type)
    if len(head) >= 0x20:
        if head[0x1C:0x20] == _GC_MAGIC:
            return "GAMECUBE"
        if head[0x18:0x1C] == _WII_MAGIC:
            return "WII"
    for off in (0, 0x10):
        chunk = head[off:off + 16]
        if chunk.startswith(b"SEGA SEGASATURN"):
            return "SATURN"
        if chunk.startswith(b"SEGA SEGAKATANA"):
            return "DREAMCAST"
        if chunk.startswith(b"SEGADISCSYSTEM"):
            return "SEGA CD"
        if chunk.startswith(b"SEGA GENESIS") or chunk.startswith(b"SEGA MEGA DRIVE"):
            return "GENESIS"
    if reader is not None:
        for off, label in _XBOX_OFFSETS:
            if size and off + len(_XBOX_MAGIC) > size:
                continue
            if reader(off, len(_XBOX_MAGIC)) == _XBOX_MAGIC:
                return label
    for base, sector, data_off, raw in _PVD_LOCATIONS:
        pvd = head[base:base + 2048] if len(head) >= base + 2048 else (
            reader(base, 2048) if reader is not None else b""
        )
        if len(pvd) < 190 or pvd[0] != 1 or pvd[1:6] != b"CD001":
            continue
        sysid = pvd[8:40].decode("ascii", "ignore").strip().upper()
        volid = pvd[40:72].decode("ascii", "ignore").strip().upper()
        if sysid.startswith("PSP"):
            return "PSP"
        if sysid.startswith("PLAYSTATION"):
            if "PS3" in volid:
                return "PS3"
            if raw:
                return "PS1"
            cnf = _read_iso_file(pvd, reader, sector, data_off, b"SYSTEM.CNF")
            if cnf is not None:
                return "PS2" if b"BOOT2" in cnf.upper() else "PS1"
            return "PS2" if size >= _PS2_SIZE_HINT else "PS1"
        if sysid.startswith("SEGA"):
            return "SATURN" if "SATURN" in sysid else CONSOLE
        return WEAK_PC
    return None


def _read_iso_file(pvd: bytes, reader, sector: int, data_off: int, name: bytes) -> bytes | None:
    if reader is None:
        return None
    root = pvd[156:190]
    lba = _u32le(root, 2)
    length = min(_u32le(root, 10), 64 * 1024)
    if not lba or not length:
        return None
    directory = b"".join(
        reader(lba * sector + i * sector + data_off, 2048)
        for i in range((length + 2047) // 2048)
    )
    pos = 0
    target = name.upper()
    while pos < len(directory):
        rec_len = directory[pos]
        if rec_len == 0:
            pos = (pos // 2048 + 1) * 2048
            continue
        rec = directory[pos:pos + rec_len]
        if len(rec) < 34:
            break
        name_len = rec[32]
        rec_name = rec[33:33 + name_len].split(b";")[0].upper()
        if rec_name == target:
            file_lba = _u32le(rec, 2)
            file_len = min(_u32le(rec, 10), 4096)
            return reader(file_lba * sector + data_off, file_len)
        pos += rec_len
    return None


def sniff_disc(path: Path) -> str | None:
    """Read a disc image's header and return its platform (see :func:`sniff_buffer`)."""
    suffix = path.suffix.lower()
    if suffix == ".cue":
        target = _cue_target(path)
        return sniff_disc(target) if target else None
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(_SNIFF_BYTES)

            def reader(offset: int, length: int) -> bytes:
                fh.seek(offset)
                return fh.read(length)

            return sniff_buffer(head, size, reader)
    except (OSError, struct.error, ValueError) as e:
        log.debug("Cannot sniff disc image %s: %s", path, e)
        return None


def _cue_target(cue: Path) -> Path | None:
    try:
        text = cue.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'FILE\s+"([^"]+)"', text, re.IGNORECASE) or re.search(
        r"FILE\s+(\S+)", text, re.IGNORECASE
    )
    if not m:
        return None
    target = cue.parent / m.group(1)
    return target if target.is_file() else None


def peek_zip(path: Path) -> str | None:
    """Platform of a zip archive judged by its member names (and disc headers)."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()[:_ZIP_MEMBER_LIMIT]
            verdict = classify_names(i.filename for i in infos)
            if verdict not in (None, WEAK_PC):
                return verdict
            for info in infos:
                ext = os.path.splitext(info.filename)[1].lower()
                if ext in (".iso", ".img", ".bin", ".gcm") and info.file_size > 0x10000:
                    with zf.open(info) as member:
                        head = member.read(_SNIFF_BYTES)
                    found = sniff_buffer(head, info.file_size)
                    if found:
                        return found
            return verdict
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError,
            ValueError, EOFError) as e:
        log.debug("Cannot read zip %s: %s", path, e)
        return None


def classify_names(names: Iterable[str]) -> str | None:
    """Platform verdict from a list of file names (archive members)."""
    consoles: Counter[str] = Counter()
    pc = linux = android = False
    for name in names:
        ext = os.path.splitext(name)[1].lower()
        if ext in ROM_EXTENSIONS:
            consoles[ROM_EXTENSIONS[ext]] += 1
        elif ext in ANDROID_EXTENSIONS:
            android = True
        elif ext in PC_BINARY_EXTENSIONS:
            pc = True
        elif ext in LINUX_BINARY_EXTENSIONS:
            linux = True
    if pc:
        return PC
    if consoles:
        return consoles.most_common(1)[0][0]
    if linux:
        return PC_LINUX
    if android:
        return ANDROID
    return None


def _is_elf(path: Path) -> bool:
    if sys.platform == "win32" or path.suffix:
        return False
    try:
        if not os.access(path, os.X_OK):
            return False
        with open(path, "rb") as fh:
            return fh.read(4) == b"\x7fELF"
    except OSError:
        return False


def file_content(path: Path, *, peek: bool = True) -> str | None:
    """Content verdict for one file, without looking at its folder names.

    Returns a platform label, :data:`WEAK_PC`, :data:`CONSOLE` (a console
    image of unknown system) or ``None`` when the file says nothing.
    """
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix in ROM_EXTENSIONS:
        return ROM_EXTENSIONS[suffix]
    if suffix in ANDROID_EXTENSIONS:
        return ANDROID
    if suffix in GENERIC_CONSOLE_EXTENSIONS:
        return CONSOLE
    if suffix in PC_BINARY_EXTENSIONS:
        return PC
    if suffix in LINUX_BINARY_EXTENSIONS or name.endswith((".tar.gz", ".tar.xz", ".tgz")):
        return PC_LINUX
    if suffix in SNIFF_EXTENSIONS:
        return sniff_disc(path) if peek else None
    if suffix == ".bin":
        cue = path.with_suffix(".cue")
        if cue.exists():
            return sniff_disc(path) if peek else None
        if re.match(r"^(?:fg|setup)-", name) or re.match(r"^setup_.+\(\d+\)-\d+\.bin$", name):
            return PC
        return None
    if suffix == ".zip" and peek:
        return peek_zip(path)
    if _is_elf(path):
        return PC_LINUX
    return None


def combine(verdicts: Iterable[str | None]) -> str | None:
    """Merge per-file verdicts for one game folder into a single verdict."""
    seen: Counter[str] = Counter(v for v in verdicts if v)
    if not seen:
        return None
    if seen[PC]:
        return PC
    consoles = [(n, p) for p, n in seen.items()
                if p not in PC_PLATFORMS and p not in (WEAK_PC, CONSOLE, ANDROID)]
    if consoles:
        return max(consoles)[1]
    if seen[PC_LINUX]:
        return PC_LINUX
    if seen[CONSOLE]:
        return CONSOLE
    if seen[WEAK_PC]:
        return WEAK_PC
    return ANDROID
