import logging

import requests

log = logging.getLogger(__name__)

API_URL = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"


class RateLimitReached(Exception):
    """The Strava read quota is used up; try again in the next window."""


class StravaClient:
    def __init__(self, client_id, client_secret, refresh_token, session=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.session = session or requests.Session()
        self.access_token = None
        # requests left in the tighter of the 15-minute and daily windows,
        # unknown until the first API response
        self.remaining = None

    def refresh_access_token(self):
        """Exchange the refresh token for an access token.

        Strava can hand out a new refresh token; it is stored on the client
        and returned so the caller can persist it.
        """
        response = self.session.post(TOKEN_URL, data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }, timeout=30)
        if not response.ok:
            raise RuntimeError(f"Strava token refresh failed ({response.status_code}): {response.text}")
        token = response.json()
        self.access_token = token["access_token"]
        self.refresh_token = token.get("refresh_token", self.refresh_token)
        return self.refresh_token

    def _get(self, path, params=None):
        if self.remaining is not None and self.remaining <= 0:
            raise RateLimitReached("no Strava read requests left")
        response = self.session.get(
            f"{API_URL}{path}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            params=params or {},
            timeout=30,
        )
        self._update_budget(response.headers)
        log.debug("GET %s -> %s (remaining: %s)", path, response.status_code, self.remaining)
        if response.status_code == 429:
            self.remaining = 0
            raise RateLimitReached("Strava returned 429 Too Many Requests")
        if not response.ok:
            raise RuntimeError(f"GET {path} failed ({response.status_code}): {response.text}")
        return response.json()

    def _update_budget(self, headers):
        # The read limit applies to all GET requests; older responses only
        # carry the overall limit.
        for prefix in ("X-ReadRateLimit", "X-RateLimit"):
            limit = headers.get(f"{prefix}-Limit")
            usage = headers.get(f"{prefix}-Usage")
            if limit and usage:
                limits = [int(v) for v in limit.split(",")]
                usages = [int(v) for v in usage.split(",")]
                self.remaining = min(l - u for l, u in zip(limits, usages))
                return

    def iter_activity_pages(self, after=0, per_page=200):
        """Yield pages of summary activities started after `after` (epoch seconds)."""
        page = 1
        while True:
            activities = self._get("/athlete/activities", {
                "after": after, "page": page, "per_page": per_page,
            })
            if not activities:
                return
            yield activities
            page += 1

    def get_activity(self, activity_id):
        return self._get(f"/activities/{activity_id}", {"include_all_efforts": "false"})
