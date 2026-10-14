import pytest
import responses

from municipality_hunter.strava import API_URL, RateLimitReached, StravaClient

ACTIVITIES_URL = f"{API_URL}/athlete/activities"


def client():
    c = StravaClient("id", "secret", "refresh")
    c.access_token = "token"
    return c


def read_limit_headers(usage_15m, usage_daily):
    return {
        "X-ReadRateLimit-Limit": "100,1000",
        "X-ReadRateLimit-Usage": f"{usage_15m},{usage_daily}",
    }


@responses.activate
def test_pagination_stops_on_empty_page():
    responses.get(ACTIVITIES_URL, json=[{"id": 1}, {"id": 2}])
    responses.get(ACTIVITIES_URL, json=[{"id": 3}])
    responses.get(ACTIVITIES_URL, json=[])

    pages = list(client().iter_activity_pages(after=123))

    assert pages == [[{"id": 1}, {"id": 2}], [{"id": 3}]]
    assert [c.request.params["page"] for c in responses.calls] == ["1", "2", "3"]
    assert responses.calls[0].request.params["after"] == "123"


@responses.activate
def test_stops_when_budget_is_used_up():
    responses.get(ACTIVITIES_URL, json=[{"id": 1}], headers=read_limit_headers(100, 10))

    pages = client().iter_activity_pages()
    assert next(pages) == [{"id": 1}]
    with pytest.raises(RateLimitReached):
        next(pages)
    assert len(responses.calls) == 1


@responses.activate
def test_429_raises_rate_limit_reached():
    responses.get(f"{API_URL}/activities/1", status=429, headers=read_limit_headers(100, 500))

    with pytest.raises(RateLimitReached):
        client().get_activity(1)


@pytest.mark.parametrize("headers, remaining", [
    (read_limit_headers(40, 990), 10),
    ({"X-RateLimit-Limit": "200,2000", "X-RateLimit-Usage": "20,100"}, 180),
    ({}, None),
])
def test_budget_from_headers(headers, remaining):
    c = client()
    c._update_budget(headers)
    assert c.remaining == remaining


@responses.activate
def test_refresh_returns_rotated_token():
    responses.post("https://www.strava.com/api/v3/oauth/token",
                   json={"access_token": "new-access", "refresh_token": "new-refresh"})

    c = StravaClient("id", "secret", "old-refresh")

    assert c.refresh_access_token() == "new-refresh"
    assert c.access_token == "new-access"
