"""Configuration loaded from config.ini and/or environment variables."""
from __future__ import annotations

import os
import shutil
import sys
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path


class APIKeyMissingError(RuntimeError):
    """Raised when an API key required for a provider is not configured."""


def _bundled_dir() -> Path:
    """Return the directory containing the executable or module.

    When running from source, this is the project root. When running as a
    PyInstaller bundle, this is the directory containing the .exe / AppImage
    contents (``sys._MEIPASS`` for onefile, or the exe's dir for onedir).
    """
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def _ensure_config_exists() -> Path | None:
    """If ``config.ini`` doesn't exist, copy ``config.example.ini`` to it.

    Searches CWD first, then ``~/.playcache/``. If neither has a
    ``config.ini``, looks for ``config.example.ini`` next to the bundled
    executable (or in CWD) and copies it to ``CWD/config.ini`` so the user
    just needs to paste their API key.

    Returns the path to the config file to load (may be ``None`` if no
    example file is found either — the app will fall back to defaults).
    """
    cwd_config = Path.cwd() / "config.ini"
    home_config = Path.home() / ".playcache" / "config.ini"

    if cwd_config.is_file():
        return cwd_config
    if home_config.is_file():
        return home_config

    example_candidates = [
        Path.cwd() / "config.example.ini",
        _bundled_dir() / "config.example.ini",
    ]
    for example in example_candidates:
        if example.is_file():
            try:
                shutil.copy2(example, cwd_config)
                return cwd_config
            except OSError:
                pass
    return None


@dataclass
class Config:
    rawg_api_key: str = ""
    thegamesdb_api_key: str = ""
    db_path: str = "game_library.db"
    request_delay: float = 0.3
    request_timeout: int = 20
    max_retries: int = 3
    fuzzy_threshold: int = 60
    description_max_chars: int = 320
    skip_folders: tuple = ()
    config_path: str = ""  # path to the config file this was loaded from

    @classmethod
    def load(cls, config_path: str | None = None) -> Config:
        cfg = cls()

        parser = ConfigParser()
        # Auto-copy config.example.ini → config.ini on first launch
        # (portable releases bundle the example alongside the executable).
        found_path = config_path or _ensure_config_exists()
        if found_path and Path(found_path).is_file():
            parser.read(found_path, encoding="utf-8-sig")
            cfg.config_path = str(found_path)

        def get(section: str, key: str, fallback: str = "") -> str:
            env_key = f"PLAYCACHE_{section.upper()}_{key.upper()}"
            val = os.getenv(env_key)
            if val:
                return val
            if parser.has_option(section, key):
                return parser.get(section, key).strip()
            return fallback

        cfg.rawg_api_key = os.getenv("RAWG_API_KEY") or get("rawg", "api_key")
        cfg.thegamesdb_api_key = os.getenv("THEGAMESDB_API_KEY") or get("thegamesdb", "api_key")
        cfg.db_path = get("catalog", "db_path", cfg.db_path) or cfg.db_path

        def to_int(key: str, default: int) -> int:
            try:
                val = get("catalog", key, str(default))
                return int(val) if val.strip() else default
            except (ValueError, TypeError):
                return default

        def to_float(key: str, default: float) -> float:
            try:
                val = get("catalog", key, str(default))
                return float(val) if val.strip() else default
            except (ValueError, TypeError):
                return default

        cfg.request_delay = to_float("request_delay", cfg.request_delay)
        cfg.request_timeout = to_int("request_timeout", cfg.request_timeout)
        cfg.max_retries = to_int("max_retries", cfg.max_retries)
        cfg.fuzzy_threshold = to_int("fuzzy_threshold", cfg.fuzzy_threshold)
        cfg.description_max_chars = to_int("description_max_chars", cfg.description_max_chars)

        skip_raw = get("catalog", "skip_folders", "")
        if skip_raw:
            cfg.skip_folders = tuple(
                s.strip() for s in skip_raw.split(",") if s.strip()
            )

        return cfg

    def require_rawg(self) -> None:
        if not self.rawg_api_key:
            raise APIKeyMissingError(
                "RAWG API key is not set. Get a FREE key at https://rawg.io/ "
                "and put it in config.ini under [rawg] api_key, "
                "or set the RAWG_API_KEY environment variable."
            )


_INT_SETTINGS = ("request_timeout", "max_retries", "fuzzy_threshold", "description_max_chars")


def catalog_settings(cfg: Config) -> dict:
    """The non-secret ``[catalog]`` settings, as stored in a backup.

    API keys and ``db_path`` are deliberately left out: a backup file is
    easy to share, and the database location belongs to the target PC.
    """
    return {
        "request_delay": cfg.request_delay,
        "request_timeout": cfg.request_timeout,
        "max_retries": cfg.max_retries,
        "fuzzy_threshold": cfg.fuzzy_threshold,
        "description_max_chars": cfg.description_max_chars,
        "skip_folders": list(cfg.skip_folders),
    }


def _valid_settings(values: dict) -> dict:
    clean: dict = {}
    delay = values.get("request_delay")
    if isinstance(delay, (int, float)) and not isinstance(delay, bool) and 0 <= delay <= 60:
        clean["request_delay"] = float(delay)
    for key in _INT_SETTINGS:
        val = values.get(key)
        if isinstance(val, int) and not isinstance(val, bool) and 0 <= val <= 100_000:
            clean[key] = val
    skip = values.get("skip_folders")
    if isinstance(skip, list) and all(isinstance(s, str) for s in skip):
        clean["skip_folders"] = tuple(s.strip() for s in skip if s.strip() and "," not in s)
    return clean


def restore_catalog_settings(cfg: Config, values: dict) -> list[str]:
    """Apply backed-up ``[catalog]`` settings to ``cfg`` and its ini file.

    Invalid values are ignored; API keys and ``db_path`` are never touched.
    Returns the names of the settings that were applied.
    """
    clean = _valid_settings(values if isinstance(values, dict) else {})
    if not clean:
        return []
    path = Path(cfg.config_path) if cfg.config_path else Path.cwd() / "config.ini"
    parser = ConfigParser()
    if path.is_file():
        parser.read(path, encoding="utf-8-sig")
    if not parser.has_section("catalog"):
        parser.add_section("catalog")
    for key, val in clean.items():
        text = ",".join(val) if key == "skip_folders" else str(val)
        parser.set("catalog", key, text)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            parser.write(fh)
        tmp.replace(path)
    except OSError:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    for key, val in clean.items():
        setattr(cfg, key, val)
    cfg.config_path = str(path)
    return list(clean)
