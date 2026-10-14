"""The "Connect with Strava" flow and refresh token handling (needs a DB, see conftest.py)."""
import dataclasses
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from municipality_hunter import auth, web
from municipality_hunter.config import Settings
from municipality_hunter.db import get_state, set_state
from municipality_hunter.strava import TOKEN_URL


@pytest.fixture
def settings(monkeypatch, conn):
    s = dataclasses.replace(Settings.from_env(), client_id="123", client_secret="secret",
                            refresh_token="", public_url="")
    monkeypatch.setattr(web, "settings", s)
    return s


@pytest.fixture
def client(settings):
    return web.app.test_client()


def start_login(client):
    response = client.get("/auth/strava")
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["Location"]).query)
    assert query["client_id"] == ["123"]
    assert query["redirect_uri"] == ["http://localhost/auth/strava/callback"]
    assert "activity:read_all" in query["scope"][0]
    return query["state"][0]


def error_of(response):
    return parse_qs(urlparse(response.headers["Location"]).query).get("strava_error", [None])[0]


@responses.activate
def test_connect_stores_token_and_requests_sync(client, conn):
    responses.post(TOKEN_URL, json={
        "access_token": "a", "refresh_token": "from-oauth",
        "athlete": {"id": 1, "firstname": "Eddy", "lastname": "Merckx"},
    })
    assert client.get("/api/strava").json == {"configured": True, "connected": False, "athlete": None}

    state = start_login(client)
    response = client.get(f"/auth/strava/callback?state={state}&code=abc&scope=read,activity:read_all")

    assert response.headers["Location"] == "/"
    assert parse_qs(responses.calls[0].request.body)["code"] == ["abc"]
    assert get_state(conn, "strava_refresh_token") == "from-oauth"
    assert get_state(conn, "sync_requested") == "1"
    assert client.get("/api/strava").json == {"configured": True, "connected": True, "athlete": "Eddy Merckx"}


@pytest.mark.parametrize("query, error", [
    ("state=wrong&code=abc&scope=read,activity:read_all", "expired"),
    ("state={state}&error=access_denied", "denied"),
    ("state={state}&code=abc&scope=read", "allow access to your activities"),
])
def test_callback_rejects(client, conn, query, error):
    state = start_login(client)
    response = client.get("/auth/strava/callback?" + query.format(state=state))
    assert error in error_of(response)
    assert get_state(conn, "strava_refresh_token") is None


def test_state_can_only_be_used_once(client):
    state = start_login(client)
    client.get(f"/auth/strava/callback?state={state}&error=access_denied")
    response = client.get(f"/auth/strava/callback?state={state}&code=abc&scope=read,activity:read_all")
    assert "expired" in error_of(response)


def test_public_url_is_used_for_the_callback(client, settings, monkeypatch):
    monkeypatch.setattr(web, "settings", dataclasses.replace(settings, public_url="https://hunter.example.org"))
    query = parse_qs(urlparse(client.get("/auth/strava").headers["Location"]).query)
    assert query["redirect_uri"] == ["https://hunter.example.org/auth/strava/callback"]


def test_not_configured(client, settings, monkeypatch):
    monkeypatch.setattr(web, "settings", dataclasses.replace(settings, client_id=""))
    assert "CLIENT_ID" in error_of(client.get("/auth/strava"))


@pytest.mark.parametrize("env_token, stored_source, expected", [
    ("", None, None),                    # nothing configured
    ("env", None, "env"),                # only .env
    ("", "", "stored"),                  # connected with the button
    ("", "env", "stored"),               # REFRESH_TOKEN removed from .env after connecting
    ("env", "env", "stored"),            # rotated token wins over the old .env value
    ("new-env", "env", "new-env"),       # .env changed afterwards
])
def test_current_refresh_token(conn, env_token, stored_source, expected):
    settings = dataclasses.replace(Settings.from_env(), refresh_token=env_token)
    if stored_source is not None:
        set_state(conn, "strava_refresh_token", "stored")
        set_state(conn, "strava_refresh_token_source", stored_source)
    assert auth.current_refresh_token(conn, settings) == expected
