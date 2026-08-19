"""TheGamesDB API client (https://api.thegamesdb.net/).

Free key required (https://thegamesdb.net/, requires a free account registration). Used as the **fallback**
metadata source when RAWG returns no confident match; RAWG is the primary.

Response shape (abbreviated):

  GET /v1/Games/ByGameName?apikey=...&name=...&fields=...
  { "code":200, "data":{ "count":N, "games":[
      { "id", "game_title", "release_date", "overview",
        "rating": "E - Everyone" (ESRB, NOT a numeric score),
        "platform": <id>, "developers":[<id>], "publishers":[<id>],
        "genres":[<id>] } ] },
    "include":{ "platform":{"<id>":{"name"}}, "boxart":{...} } }

  NOTE: ``include`` only supports ``boxart`` and ``platform`` — NOT genres,
  developers, or publishers. Those are returned as ID arrays and must be
  resolved via separate calls to /v1/Genres, /v1/Developers/ByDeveloperID,
  and /v1/Publishers/ByPublisherID. This client caches those lookups.
"""
from __future__ import annotations

import logging
import re
import time

import requests

from .config import APIKeyMissingError, Config
from .models import GameRecord
from .textutils import (
    best_match,
    clean_search_query,
    strip_html,
    truncate,
)

log = logging.getLogger(__name__)

BASE_URL = "https://api.thegamesdb.net/v1"

# Fields to request on game searches. ``rating`` is ESRB (e.g. "E - Everyone"),
# not a numeric score — stored in esrb_rating, not user_rating.
FIELDS = "players,publishers,genres,overview,rating,platform,developers,release_date"


class TheGamesDBClient:
    name = "thegamesdb"

    def __init__(self, config: Config, session: requests.Session | None = None):
        self.config = config
        self.api_key = config.thegamesdb_api_key
        self.timeout = config.request_timeout
        self.delay = config.request_delay
        self.max_retries = max(1, config.max_retries)
        self.threshold = config.fuzzy_threshold
        self.desc_max = config.description_max_chars
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "playcache/1.0", "Accept": "application/json"})
        # Lookup caches (id -> name), populated lazily and reused for the session
        self._genres: dict[int, str] | None = None
        self._developers: dict[int, str] = {}
        self._publishers: dict[int, str] = {}
        # Rate-limit quota (populated from API response fields)
        self.remaining_monthly_allowance: int | None = None
        self.extra_allowance: int | None = None
        self.allowance_refresh_timer: int | None = None  # seconds until reset
        self.request_count: int = 0

    def is_available(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------ #
    # Low-level HTTP with retry/backoff
    # ------------------------------------------------------------------ #
    def _get(self, path: str, params: dict) -> dict:
        if not self.api_key:
            raise APIKeyMissingError("TheGamesDB")
        self.request_count += 1
        params = {**params, "apikey": self.api_key}
        url = f"{BASE_URL}{path}"
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    # Honor Retry-After header if present (don't burn retries).
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait = min(int(retry_after), 60)
                        except ValueError:
                            wait = min(2 ** attempt, 10)
                    else:
                        wait = min(2 ** attempt, 10)
                    last_exc = requests.HTTPError("HTTP 429 Too Many Requests")
                    log.warning("TGDB %s -> 429, waiting %ds", path, wait)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    last_exc = requests.HTTPError(f"HTTP {resp.status_code}")
                    wait = min(2 ** attempt, 10)
                    log.warning("TGDB %s -> %s, retry %d/%d", path, resp.status_code, attempt, self.max_retries)
                    time.sleep(wait)
                    continue
                # 4xx (except 429) is non-retryable: bad key, forbidden, not found.
                if 400 <= resp.status_code < 500:
                    raise RuntimeError(f"HTTP {resp.status_code} from TheGamesDB")
                resp.raise_for_status()
                data = resp.json()
                self._capture_quota(data)
                return data
            except (requests.RequestException, ValueError) as e:
                last_exc = e
                wait = min(2 ** attempt, 10)
                log.warning("TGDB request error (%s), retry %d/%d", e, attempt, self.max_retries)
                time.sleep(wait)
        raise RuntimeError(f"TheGamesDB request failed after {self.max_retries} retries: {last_exc}")

    def _capture_quota(self, data: dict) -> None:
        """Track rate-limit fields from the API response (if present)."""
        if not isinstance(data, dict):
            return
        rma = data.get("remaining_monthly_allowance")
        if isinstance(rma, int):
            self.remaining_monthly_allowance = rma
        ea = data.get("extra_allowance")
        if isinstance(ea, int):
            self.extra_allowance = ea
        art = data.get("allowance_refresh_timer")
        if isinstance(art, int):
            self.allowance_refresh_timer = art

    def quota_info(self) -> dict:
        """Return a snapshot of the current TGDB rate-limit quota.

        Keys: ``remaining`` (int|None), ``extra`` (int|None),
        ``reset_seconds`` (int|None), ``monthly_limit`` (int|None).
        The monthly limit is inferred as ``remaining + (requests made so far)``
        only on the very first call; otherwise we report ``None``. In practice
        the documented public-tier limit is 1000 requests/month.
        """
        return {
            "remaining": self.remaining_monthly_allowance,
            "extra": self.extra_allowance,
            "reset_seconds": self.allowance_refresh_timer,
            "monthly_limit": 1000,  # TGDB public-tier documented limit
        }

    # ------------------------------------------------------------------ #
    # Lookup caches for genres, developers, publishers
    # ------------------------------------------------------------------ #
    def _load_genres(self) -> dict[int, str]:
        """Fetch and cache all genres (small list, ~30 entries).

        On failure, leaves ``self._genres`` as ``None`` so the next call retries
        (instead of permanently caching an empty dict).
        """
        if self._genres is not None:
            return self._genres
        try:
            data = self._get("/Genres", {})
            raw = (data.get("data") or {}).get("genres", {}) or {}
            self._genres = {int(k): v.get("name", "") for k, v in raw.items()}
            time.sleep(self.delay)
        except (requests.RequestException, ValueError, RuntimeError) as e:
            log.warning("TGDB genre lookup failed (will retry next call): %s", e)
            # Leave _genres as None so the next call retries.
        return self._genres or {}

    def _resolve_ids(self, ids: list[int] | None, kind: str,
                     endpoint: str, cache: dict[int, str]) -> str:
        """Resolve a list of IDs to names, fetching any unknown ones in one batch.

        ``kind`` is "developers" or "publishers" (for logging).
        ``endpoint`` is "/Developers/ByDeveloperID" or "/Publishers/ByPublisherID".
        ``cache`` is the dict to read from / write to.
        """
        if not ids:
            return ""
        unknown = [i for i in ids if i not in cache]
        if unknown:
            try:
                data = self._get(endpoint, {"id": ",".join(str(i) for i in unknown)})
                raw = (data.get("data") or {}).get(kind, {}) or {}
                for k, v in raw.items():
                    cache[int(k)] = v.get("name", "")
                time.sleep(self.delay)
            except (requests.RequestException, ValueError, RuntimeError) as e:
                log.warning("TGDB %s lookup failed for ids %s: %s", kind, unknown, e)
        names = [cache[i] for i in ids if cache.get(i)]
        return " / ".join(names)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def search(self, query: str) -> tuple[list[dict], dict]:
        """Return (games, includes) for a name search."""
        data = self._get("/Games/ByGameName", {
            "name": query, "fields": FIELDS, "include": "boxart",
        })
        games = (data.get("data") or {}).get("games", []) or []
        includes = data.get("include") or {}
        time.sleep(self.delay)
        return games, includes

    def fetch(self, record: GameRecord) -> GameRecord:
        if not self.api_key:
            record.fetch_status = "error"
            record.fetch_message = "TheGamesDB API key missing"
            return record

        query = clean_search_query(record.game_name or record.folder_name)
        if not query:
            record.fetch_status = "error"
            record.fetch_message = "Empty game name"
            return record

        try:
            games, includes = self.search(query)
        except (requests.RequestException, ValueError, RuntimeError) as e:
            record.fetch_status = "error"
            record.fetch_message = f"TGDB search error: {e}"
            return record

        candidate = best_match(
            query,
            ((g.get("game_title", ""), g) for g in games),
            threshold=self.threshold,
        )
        if not candidate:
            record.fetch_status = "not_found"
            record.fetch_message = f"TGDB: no match for '{query}'"
            return record

        self._apply(record, candidate, includes)
        record.fetch_status = "ok"
        record.data_source = self.name
        record.fetch_message = ""
        return record

    # ------------------------------------------------------------------ #
    # Normalisation
    # ------------------------------------------------------------------ #
    def _apply(self, record: GameRecord, game: dict, includes: dict) -> None:
        record.thegamesdb_id = game.get("id")
        record.game_name = game.get("game_title") or record.game_name
        record.release_date = self._normalise_date(game.get("release_date")) or record.release_date

        overview = strip_html(game.get("overview"))
        record.short_description = truncate(overview, self.desc_max)

        # ESRB age rating (e.g. "T - Teen"). This is NOT a numeric score.
        record.esrb_rating = game.get("rating") or ""

        # Genres: resolve IDs to names via cached /v1/Genres lookup.
        # API returns null (not []) when data is missing — coerce to list.
        genre_ids = [int(g) for g in (game.get("genres") or []) if g]
        if genre_ids:
            genres_map = self._load_genres()
            names = [genres_map[gid] for gid in genre_ids if genres_map.get(gid)]
            if names:
                record.game_type = " / ".join(names)

        # Developers / publishers: resolve IDs via batch lookups.
        # Same null-safety as genres above.
        dev_ids = [int(d) for d in (game.get("developers") or []) if d]
        record.developer = self._resolve_ids(
            dev_ids, "developers", "/Developers/ByDeveloperID", self._developers
        )
        pub_ids = [int(p) for p in (game.get("publishers") or []) if p]
        record.publisher = self._resolve_ids(
            pub_ids, "publishers", "/Publishers/ByPublisherID", self._publishers
        )

        # Platform: the ``include.platform`` shape differs between v1 (keys are
        # platform IDs directly) and v1.1 (wrapped in a ``data`` key). Handle both.
        plat_include = includes.get("platform") or {}
        plat_map = plat_include.get("data") or plat_include
        plat_id = game.get("platform")
        plat_name = (plat_map.get(str(plat_id)) or {}).get("name", "") if plat_id else ""
        if plat_name:
            record.platform = self._platform_label(plat_name)

        if not record.store:
            record.store = "Other"

        # Cover image: extract front boxart from the include block.
        # Structure: include.boxart.{base_url: {large: "..."}, data: {<gid>: [{filename, side, ...}]}}
        cover = self._extract_boxart(game.get("id"), includes)
        if cover:
            record.cover_url = cover

    @staticmethod
    def _extract_boxart(game_id, includes: dict) -> str | None:
        """Build a full cover URL from the TGDB boxart include block."""
        ba = includes.get("boxart") or {}
        base = (ba.get("base_url") or {}).get("large")
        if not base or not game_id:
            return None
        entries = (ba.get("data") or {}).get(str(game_id)) or []
        for entry in entries:
            if entry.get("side") == "front" and entry.get("filename"):
                return base + entry["filename"]
        return None

    @staticmethod
    def _normalise_date(value: str | None) -> str | None:
        if not value:
            return None
        v = str(value).strip()
        return v if re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", v) else None

    @staticmethod
    def _platform_label(name: str) -> str:
        n = name.lower().strip()
        # Match tokens, not substrings — "PC Engine" / "PC-FX" must NOT become "PC".
        # Accept exact "pc", "windows", or "pc (..." variants like "pc (microsoft windows)".
        if n == "pc" or "windows" in n or n.startswith("pc ("):
            return "PC"
        return name

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()
