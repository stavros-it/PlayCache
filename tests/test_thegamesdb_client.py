"""TheGamesDB client tests with a canned session layer (no network)."""
from __future__ import annotations

import logging

import pytest
import requests

from playcache.config import Config
from playcache.models import GameRecord
from playcache.thegamesdb_client import TheGamesDBClient

TGDB_GAME = {
    "id": 123, "game_title": "Some Game", "release_date": "2001-03-15",
    "overview": "An overview.", "rating": "T - Teen", "platform": 1,
    "developers": [10], "publishers": [20], "genres": [3, 5],
}

TGDB_BODY = {
    "code": 200,
    "remaining_monthly_allowance": 950,
    "extra_allowance": 10,
    "allowance_refresh_timer": 12345,
    "data": {"count": 1, "games": [dict(TGDB_GAME)]},
    "include": {
        "boxart": {
            "base_url": {"large": "https://cdn.thegamesdb.net/images/large/"},
            "data": {"123": [
                {"filename": "boxart/front/123-1.jpg", "side": "front"},
                {"filename": "boxart/back/123-1.jpg", "side": "back"},
            ]},
        },
        "platform": {"1": {"id": 1, "name": "PC (Microsoft Windows)"}},
    },
}

LEAK_MESSAGE = (
    "HTTPSConnectionPool(host='api.thegamesdb.net', port=443): Max retries exceeded "
    "with url: /v1/Games/ByGameName?apikey=SUPERSECRET123&name=Some+Game (Caused by None)"
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
        "thegamesdb_api_key": "TESTKEY",
        "request_delay": 0.0,
        "max_retries": 3,
    }
    defaults.update(overrides)
    return Config(**defaults)


def _record(**fields) -> GameRecord:
    base = {"folder_name": "Some Game", "game_name": "Some Game"}
    base.update(fields)
    return GameRecord(**base)


class TestQuotaCapture:
    def test_quota_captured_from_200_body(self):
        session = FakeSession([FakeResponse(200, dict(TGDB_BODY))])
        client = TheGamesDBClient(_cfg(), session=session)

        client.search("Some Game")

        assert client.remaining_monthly_allowance == 950
        assert client.extra_allowance == 10
        assert client.allowance_refresh_timer == 12345

    def test_quota_captured_from_200_body_via_quota_info(self):
        session = FakeSession([FakeResponse(200, dict(TGDB_BODY))])
        client = TheGamesDBClient(_cfg(), session=session)

        client.search("Some Game")

        quota = client.quota_info()
        assert quota["remaining"] == 950
        assert quota["extra"] == 10
        assert quota["reset_seconds"] == 12345
        assert quota["monthly_limit"] == 1000

    def test_quota_captured_from_403_body_before_runtime_error(self):
        body = {
            "code": 403,
            "remaining_monthly_allowance": 0,
            "extra_allowance": 0,
            "allowance_refresh_timer": 999,
        }
        session = FakeSession([FakeResponse(403, body)])
        client = TheGamesDBClient(_cfg(), session=session)

        with pytest.raises(RuntimeError, match="403"):
            client.search("Some Game")

        assert client.remaining_monthly_allowance == 0
        assert client.allowance_refresh_timer == 999

    def test_quota_capture_from_403_with_garbage_body_does_not_raise(self):
        session = FakeSession([FakeResponse(403, object())])
        client = TheGamesDBClient(_cfg(), session=session)

        with pytest.raises(RuntimeError, match="403"):
            client.search("Some Game")


class TestMalformedBody:
    def test_malformed_200_body_raises_runtime_error(self):
        session = FakeSession([FakeResponse(200, None)])
        client = TheGamesDBClient(_cfg(), session=session)

        with pytest.raises(RuntimeError, match="malformed"):
            client.search("Some Game")


class TestIncludeParams:
    def test_search_requests_boxart_and_platform(self):
        session = FakeSession([FakeResponse(200, dict(TGDB_BODY))])
        client = TheGamesDBClient(_cfg(), session=session)

        client.search("Some Game")

        assert session.calls[0][1]["include"] == "boxart,platform"
        assert session.calls[0][1]["apikey"] == "TESTKEY"

    def test_get_by_id_requests_boxart_and_platform(self):
        session = FakeSession([FakeResponse(200, dict(TGDB_BODY))])
        client = TheGamesDBClient(_cfg(), session=session)

        client.get_by_id(123)

        assert session.calls[0][1]["include"] == "boxart,platform"

    def test_platform_include_populates_record_platform(self):
        client = TheGamesDBClient(_cfg(), session=FakeSession([]))
        record = _record()
        game = dict(TGDB_GAME, developers=None, publishers=None, genres=None)

        client._apply(record, game, TGDB_BODY["include"])

        assert record.platform == "PC"


class TestApply:
    def test_null_developers_publishers_genres_handled(self):
        client = TheGamesDBClient(_cfg(), session=FakeSession([]))
        game = dict(TGDB_GAME, developers=None, publishers=None, genres=None)
        record = _record()

        client._apply(record, game, {})

        assert record.developer == ""
        assert record.publisher == ""
        assert record.game_type == ""
        assert record.thegamesdb_id == 123
        assert record.esrb_rating == "T - Teen"

    def test_boxart_front_url_built_from_base_url_and_filename(self):
        client = TheGamesDBClient(_cfg(), session=FakeSession([]))
        record = _record()
        game = dict(TGDB_GAME, developers=None, publishers=None, genres=None)

        client._apply(record, game, TGDB_BODY["include"])

        assert record.cover_url == "https://cdn.thegamesdb.net/images/large/boxart/front/123-1.jpg"


class TestLookupFailureSleep:
    def test_genre_load_failure_sleeps_before_returning(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr("playcache.thegamesdb_client.time.sleep", sleeps.append)
        session = FakeSession([FakeResponse(403, {})])
        client = TheGamesDBClient(_cfg(request_delay=0.3), session=session)

        genres = client._load_genres()

        assert genres == {}
        assert sleeps == [0.3]

    def test_resolve_ids_failure_sleeps_before_returning(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr("playcache.thegamesdb_client.time.sleep", sleeps.append)
        session = FakeSession([FakeResponse(403, {})])
        client = TheGamesDBClient(_cfg(request_delay=0.3), session=session)

        names = client._resolve_ids(
            [10], "developers", "/Developers/ByDeveloperID", client._developers
        )

        assert names == ""
        assert sleeps == [0.3]


class TestKeyLeakPrevention:
    def test_connection_error_never_leaks_key_in_runtime_error(self, monkeypatch):
        monkeypatch.setattr("playcache.thegamesdb_client.time.sleep", lambda _s: None)
        session = FakeSession([requests.ConnectionError(LEAK_MESSAGE)] * 3)
        client = TheGamesDBClient(_cfg(max_retries=3), session=session)

        with pytest.raises(RuntimeError) as excinfo:
            client.search("Some Game")

        assert "SUPERSECRET123" not in str(excinfo.value)
        assert "TESTKEY" not in str(excinfo.value)

    def test_connection_error_never_leaks_key_in_fetch_message(self, monkeypatch):
        monkeypatch.setattr("playcache.thegamesdb_client.time.sleep", lambda _s: None)
        session = FakeSession([requests.ConnectionError(LEAK_MESSAGE)] * 3)
        client = TheGamesDBClient(_cfg(max_retries=3), session=session)

        record = client.fetch(_record())

        assert record.fetch_status == "error"
        assert "SUPERSECRET123" not in record.fetch_message
        assert "TESTKEY" not in record.fetch_message
        assert "TGDB search error" in record.fetch_message

    def test_connection_error_never_leaks_key_in_logs(self, monkeypatch, caplog):
        monkeypatch.setattr("playcache.thegamesdb_client.time.sleep", lambda _s: None)
        session = FakeSession([requests.ConnectionError(LEAK_MESSAGE)] * 3)
        client = TheGamesDBClient(_cfg(max_retries=3), session=session)

        with (
            caplog.at_level(logging.WARNING, logger="playcache.thegamesdb_client"),
            pytest.raises(RuntimeError),
        ):
            client.search("Some Game")

        assert "SUPERSECRET123" not in caplog.text
