"""RAWG API client (https://rawg.io/apidocs).

Free key required (https://rawg.io/apiauth). Used as the primary metadata source.
Response shape (abbreviated):

  GET /games?search=...&key=...
  { "count":N, "results":[ {id, slug, name, released, rating, rating_top,
                            metacritic, platforms:[{platform:{name}}],
                            stores:[{store:{name}}], background_image }, ...] }

  GET /games/{id}?key=...
  { ..., description_raw, description, genres:[{name}], developers:[{name}],
    publishers:[{name}], website, platforms, stores, metacritic, rating,
    rating_top, ratings_count, released, background_image }
"""
from __future__ import annotations

import logging
import time

import requests

from .config import APIKeyMissingError, Config
from .models import GameRecord
from .textutils import (
    best_match,
    clean_search_query,
    format_rating,
    join_names,
    strip_html,
    truncate,
)

log = logging.getLogger(__name__)

BASE_URL = "https://api.rawg.io/api"

# Map RAWG store names to the labels used in the reference Excel layout
STORE_NAME_MAP = {
    "steam": "Steam",
    "gog": "GOG",
    "epic games": "Epic",
    "epic": "Epic",
    "origin": "Origin",
    "ubisoft connect": "Ubisoft",
    "ubisoft": "Ubisoft",
    "battle.net": "Battle.net",
    "xbox store": "Xbox",
    "playstation store": "PlayStation",
    "nintendo store": "Nintendo",
    "itch.io": "itch.io",
    "google play": "Google Play",
    "apple app store": "App Store",
}


class RAWGClient:
    name = "rawg"

    def __init__(self, config: Config, session: requests.Session | None = None):
        self.config = config
        self.api_key = config.rawg_api_key
        self.timeout = config.request_timeout
        self.delay = config.request_delay
        self.max_retries = max(1, config.max_retries)
        self.threshold = config.fuzzy_threshold
        self.desc_max = config.description_max_chars
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "playcache/1.0", "Accept": "application/json"})

    # ------------------------------------------------------------------ #
    # Low-level HTTP with retry/backoff
    # ------------------------------------------------------------------ #
    def _get(self, path: str, params: dict) -> dict:
        if not self.api_key:
            raise APIKeyMissingError("RAWG")
        params = {**params, "key": self.api_key}
        url = f"{BASE_URL}{path}"
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    # Honor Retry-After header (don't burn retries on server-mandated waits).
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait = min(int(retry_after), 60)
                        except ValueError:
                            wait = min(2 ** attempt, 10)
                    else:
                        wait = min(2 ** attempt, 10)
                    last_exc = requests.HTTPError("HTTP 429 Too Many Requests")
                    log.warning("RAWG %s -> 429, waiting %ds", path, wait)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    last_exc = requests.HTTPError(f"HTTP {resp.status_code}")
                    wait = min(2 ** attempt, 10)
                    log.warning("RAWG %s -> %s, retry %d/%d in %ss",
                                path, resp.status_code, attempt, self.max_retries, wait)
                    time.sleep(wait)
                    continue
                # 4xx (except 429) is non-retryable: bad key, forbidden, not found.
                if 400 <= resp.status_code < 500:
                    raise RuntimeError(f"HTTP {resp.status_code} from RAWG")
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as e:
                last_exc = e
                wait = min(2 ** attempt, 10)
                log.warning("RAWG request error (%s), retry %d/%d in %ss",
                            e, attempt, self.max_retries, wait)
                time.sleep(wait)
        raise RuntimeError(f"RAWG request failed after {self.max_retries} retries: {last_exc}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        return bool(self.api_key)

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def search(self, query: str, page_size: int = 5) -> list[dict]:
        params = {
            "search": query,
            "page_size": page_size,
            "search_precise": "true",
        }
        data = self._get("/games", params)
        results = data.get("results", []) or []
        time.sleep(self.delay)
        return results

    def get_details(self, game_id: int) -> dict:
        data = self._get(f"/games/{game_id}", params={})
        time.sleep(self.delay)
        return data

    def fetch(self, record: GameRecord) -> GameRecord:
        """Search RAWG for the game and populate ``record`` with metadata.

        Returns the (mutated) record. On no match, sets fetch_status='not_found'.
        """
        if not self.api_key:
            record.fetch_status = "error"
            record.data_source = ""
            record.fetch_message = "RAWG API key missing"
            return record

        query = clean_search_query(record.game_name or record.folder_name)
        if not query:
            record.fetch_status = "error"
            record.fetch_message = "Empty game name"
            return record

        try:
            results = self.search(query)
        except (requests.RequestException, ValueError, RuntimeError) as e:
            record.fetch_status = "error"
            record.fetch_message = f"RAWG search error: {e}"
            return record

        candidate = best_match(
            query, ((r.get("name", ""), r) for r in results), threshold=self.threshold
        )
        if not candidate:
            record.fetch_status = "not_found"
            record.fetch_message = f"RAWG: no match for '{query}'"
            return record

        game_id = candidate.get("id")
        # Only fetch details for a valid integer id (avoid URL injection on
        # malformed API responses with string ids).
        valid_id = isinstance(game_id, int) and game_id > 0
        try:
            detail = self.get_details(game_id) if valid_id else candidate
        except (requests.RequestException, ValueError, RuntimeError) as e:
            log.warning("RAWG detail fetch failed for %s: %s", game_id, e)
            detail = candidate

        self._apply(record, detail)
        record.fetch_status = "ok"
        record.data_source = self.name
        record.fetch_message = ""
        return record

    # ------------------------------------------------------------------ #
    # Normalisation
    # ------------------------------------------------------------------ #
    def _apply(self, record: GameRecord, detail: dict) -> None:
        record.game_name = detail.get("name") or record.game_name
        record.rawg_id = detail.get("id")
        record.rawg_slug = detail.get("slug")
        record.release_date = detail.get("released") or record.release_date
        record.developer = join_names(detail.get("developers"))
        record.publisher = join_names(detail.get("publishers"))
        record.game_type = join_names(detail.get("genres")) or record.game_type

        mc = detail.get("metacritic")
        record.metacritic_score = int(mc) if isinstance(mc, (int, float)) else None

        # Rating: RAWG uses 0-5. Convert to /10. Skip if no ratings.
        rating = detail.get("rating")
        ratings_count = detail.get("ratings_count") or 0
        if rating and ratings_count > 0 and isinstance(rating, (int, float)):
            record.user_rating = format_rating(float(rating) * 2.0)

        # Description: prefer the plain-text raw description
        desc = detail.get("description_raw") or strip_html(detail.get("description"))
        record.short_description = truncate(desc, self.desc_max)

        record.cover_url = detail.get("background_image") or record.cover_url
        record.website = detail.get("website") or record.website

        # Store: prefer the path-detected store, else derive from API stores
        if not record.store:
            record.store = self._derive_store(detail.get("stores"))

    @staticmethod
    def _derive_store(stores: list[dict] | None) -> str:
        if not stores:
            return ""
        labels = []
        for s in stores:
            name = (s.get("store") or {}).get("name", "").strip().lower()
            if not name:
                continue
            label = STORE_NAME_MAP.get(name, name.title())
            if label not in labels:
                labels.append(label)
        return " / ".join(labels)
