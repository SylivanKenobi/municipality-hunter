"""Strava OAuth: authorize URL, code exchange and refresh token storage."""
from urllib.parse import urlencode

import requests

from .db import get_state, set_state
from .strava import TOKEN_URL

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
REQUIRED_SCOPE = "activity:read_all"


def authorize_url(client_id, redirect_uri, state):
    return f"{AUTHORIZE_URL}?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": f"read,{REQUIRED_SCOPE}",
        "state": state,
    })


def exchange_code(client_id, client_secret, code):
    """Exchange the code from the OAuth callback for tokens and athlete info."""
    response = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
    }, timeout=30)
    if not response.ok:
        raise RuntimeError(f"Strava code exchange failed ({response.status_code}): {response.text}")
    return response.json()


def current_refresh_token(conn, settings):
    """The refresh token to use, or None if Strava isn't connected yet.

    The latest token (from the "Connect with Strava" button or rotated by
    Strava) is kept in the database. REFRESH_TOKEN from the environment is
    optional and only wins when it was changed after that token was stored.
    """
    stored = get_state(conn, "strava_refresh_token")
    stored_source = get_state(conn, "strava_refresh_token_source") or ""
    if stored and (not settings.refresh_token or stored_source == settings.refresh_token):
        return stored
    return settings.refresh_token or None


def store_refresh_token(conn, settings, token):
    set_state(conn, "strava_refresh_token", token)
    # remember which REFRESH_TOKEN was configured, so a changed one wins again
    set_state(conn, "strava_refresh_token_source", settings.refresh_token)


def request_sync(conn):
    """Ask the collector loop to sync right away instead of waiting."""
    set_state(conn, "sync_requested", "1")
