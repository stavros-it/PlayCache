"""Configuration loaded from config.ini and/or environment variables."""
from __future__ import annotations

import os
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path


class APIKeyMissingError(RuntimeError):
    """Raised when an API key required for a provider is not configured."""


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
        # Read config file if present (search CWD and a few defaults)
        candidates = []
        if config_path:
            candidates.append(Path(config_path))
        candidates.extend([
            Path.cwd() / "config.ini",
            Path.home() / ".playcache" / "config.ini",
        ])
        for c in candidates:
            if c.is_file():
                parser.read(c, encoding="utf-8")
                cfg.config_path = str(c)
                break

        def get(section: str, key: str, fallback: str = "") -> str:
            # Environment variables override config file: PLAYCACHE_RAWG_API_KEY etc.
            env_key = f"PLAYCACHE_{section.upper()}_{key.upper()}"
            if os.getenv(env_key):
                return os.environ[env_key]
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
                "RAWG API key is not set. Get a FREE key at https://rawg.io/apiauth "
                "and put it in config.ini under [rawg] api_key, "
                "or set the RAWG_API_KEY environment variable."
            )
