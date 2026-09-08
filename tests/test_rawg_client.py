"""RAWG client tests with a canned session layer (no network)."""
from __future__ import annotations

import logging

import pytest
import requests

from playcache.config import Config
from playcache.models import GameRecord
from playcache.rawg_client import RAWGClient

RAWG_DETAIL = {
    "id": 11226, "slug": "hollow-knight", "name": "Hollow Knight",
    "released": "2017-02-24", "rating": 4.50, "ratings_count": 5000,
    "metacritic": 90,
    "description_raw": "A beautifully crafted action-adventure.",
    "genres": [{"id": 4, "name": "Action"}, {"id": 51, "name": "Indie"}],
    "developers": [{"id": 123, "name": "Team Cherry"}],
    "publishers": [{"id": 123, "name": "Team Cherry"}],
    "stores": [{"store": {"id": 1, "name": "Steam"}}],
    "background_image": "https://media.rawg.io/media/hollow.jpg",
    "website": "https://hollowknight.com",
}

SEARCH_PROJECTION = {
    k: RAWG_DETAIL[k] for k in (
        "id", "slug", "name", "released", "rating", "ratings_count",
        "metacritic", "background_image",
    )
}

SEARCH_BODY = {"count": 1, "results": [dict(SEARCH_PROJECTION)]}

LEAK_MESSAGE = (
    "HTTPSConnectionPool(host='api.rawg.io', port=443): Max retries exceeded "
    "with url: /api/games?search=Hollow+Knight&key=SUPERSECRET123 (Caused by None)"
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []
        self.headers: dict = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if not self.responses:
            raise AssertionError("no canned response left")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


def _cfg(**overrides) -> Config:
    defaults = {
        "rawg_api_key": "TESTKEY",
        "request_delay": 0.0,
        "max_retries": 3,
    }
    defaults.update(overrides)
    return Config(**defaults)


def _record(**fields) -> GameRecord:
    base = {"folder_name": "Hollow Knight", "game_name": "Hollow Knight"}
    base.update(fields)
    return GameRecord(**base)


class TestFetchHappyPath:
    def test_search_then_details_populates_record(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr("playcache.rawg_client.time.sleep", sleeps.append)
        session = FakeSession([
            FakeResponse(200, SEARCH_BODY),
            FakeResponse(200, dict(RAWG_DETAIL)),
        ])
        client = RAWGClient(_cfg(), session=session)
        record = client.fetch(_record())

        assert record.fetch_status == "ok"
        assert record.data_source == "rawg"
        assert record.rawg_id == 11226
        assert record.rawg_slug == "hollow-knight"
        assert record.game_name == "Hollow Knight"
        assert record.release_date == "2017-02-24"
        assert record.developer == "Team Cherry"
        assert record.publisher == "Team Cherry"
        assert record.game_type == "Action / Indie"
        assert record.metacritic_score == 90
        assert record.user_rating == "9/10"
        assert record.short_description == "A beautifully crafted action-adventure."
        assert record.cover_url == "https://media.rawg.io/media/hollow.jpg"
        assert record.website == "https://hollowknight.com"
        assert record.store == "Steam"
        assert session.calls[0][1]["key"] == "TESTKEY"


class TestRetryBehaviour:
    def test_429_retry_after_honored_and_capped(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr("playcache.rawg_client.time.sleep", sleeps.append)
        session = FakeSession([
            FakeResponse(429, None, {"Retry-After": "120"}),
            FakeResponse(200, SEARCH_BODY),
        ])
        client = RAWGClient(_cfg(), session=session)

        results = client.search("Hollow Knight")

        assert sleeps[0] == 60
        assert 120 not in sleeps
        assert [r["id"] for r in results] == [11226]

    def test_5xx_retried_exactly_max_retries_then_runtime_error(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr("playcache.rawg_client.time.sleep", sleeps.append)
        session = FakeSession([FakeResponse(500)] * 3)
        client = RAWGClient(_cfg(max_retries=3), session=session)

        with pytest.raises(RuntimeError, match="3 retries"):
            client.search("Hollow Knight")

        assert len(session.calls) == 3
        assert len(sleeps) == 3

    def test_404_raises_immediately_without_retry(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr("playcache.rawg_client.time.sleep", sleeps.append)
        session = FakeSession([FakeResponse(404)])
        client = RAWGClient(_cfg(max_retries=3), session=session)

        with pytest.raises(RuntimeError, match="404"):
            client.search("Hollow Knight")

        assert len(session.calls) == 1
        assert sleeps == []


class TestMalformedBody:
    def test_malformed_200_body_raises_runtime_error(self):
        session = FakeSession([FakeResponse(200, None)])
        client = RAWGClient(_cfg(), session=session)

        with pytest.raises(RuntimeError, match="malformed"):
            client.search("Hollow Knight")

    def test_malformed_detail_falls_back_to_search_without_attribute_error(self, monkeypatch):
        monkeypatch.setattr("playcache.rawg_client.time.sleep", lambda _s: None)
        session = FakeSession([
            FakeResponse(200, None),
            FakeResponse(200, SEARCH_BODY),
            FakeResponse(200, dict(RAWG_DETAIL)),
        ])
        client = RAWGClient(_cfg(), session=session)
        record = _record(rawg_id=11226)

        record = client.fetch(record)

        assert record.fetch_status == "ok"
        assert record.developer == "Team Cherry"

    def test_malformed_search_body_degrades_to_error_record(self, monkeypatch):
        monkeypatch.setattr("playcache.rawg_client.time.sleep", lambda _s: None)
        session = FakeSession([FakeResponse(200, None)])
        client = RAWGClient(_cfg(), session=session)

        record = client.fetch(_record())

        assert record.fetch_status == "error"
        assert "malformed" in record.fetch_message


class TestDetailFallbackPreservesFields:
    def test_detail_get_failure_keeps_existing_developer_publisher_description(
        self, monkeypatch,
    ):
        monkeypatch.setattr("playcache.rawg_client.time.sleep", lambda _s: None)
        session = FakeSession([
            FakeResponse(200, SEARCH_BODY),
            FakeResponse(404),
        ])
        client = RAWGClient(_cfg(), session=session)
        record = _record(
            developer="Old Dev",
            publisher="Old Pub",
            short_description="Old description",
        )

        record = client.fetch(record)

        assert record.fetch_status == "ok"
        assert record.developer == "Old Dev"
        assert record.publisher == "Old Pub"
        assert record.short_description == "Old description"
        assert record.rawg_id == 11226
        assert record.game_name == "Hollow Knight"


class TestKeyLeakPrevention:
    def test_connection_error_never_leaks_key_in_runtime_error(self, monkeypatch):
        monkeypatch.setattr("playcache.rawg_client.time.sleep", lambda _s: None)
        session = FakeSession([requests.ConnectionError(LEAK_MESSAGE)] * 3)
        client = RAWGClient(_cfg(max_retries=3), session=session)

        with pytest.raises(RuntimeError) as excinfo:
            client.search("Hollow Knight")

        assert "SUPERSECRET123" not in str(excinfo.value)
        assert "TESTKEY" not in str(excinfo.value)

    def test_connection_error_never_leaks_key_in_fetch_message(self, monkeypatch):
        monkeypatch.setattr("playcache.rawg_client.time.sleep", lambda _s: None)
        session = FakeSession([requests.ConnectionError(LEAK_MESSAGE)] * 3)
        client = RAWGClient(_cfg(max_retries=3), session=session)

        record = client.fetch(_record())

        assert record.fetch_status == "error"
        assert "SUPERSECRET123" not in record.fetch_message
        assert "TESTKEY" not in record.fetch_message
        assert "RAWG search error" in record.fetch_message

    def test_connection_error_never_leaks_key_in_logs(
        self, monkeypatch, caplog,
    ):
        monkeypatch.setattr("playcache.rawg_client.time.sleep", lambda _s: None)
        session = FakeSession([requests.ConnectionError(LEAK_MESSAGE)] * 3)
        client = RAWGClient(_cfg(max_retries=3), session=session)

        with (
            caplog.at_level(logging.WARNING, logger="playcache.rawg_client"),
            pytest.raises(RuntimeError),
        ):
            client.search("Hollow Knight")

        assert "SUPERSECRET123" not in caplog.text
