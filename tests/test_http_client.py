from types import SimpleNamespace

import pytest
import requests

from hotel import http_client


@pytest.mark.parametrize("fail", [False, True])
def test_transport_reuses_connections_without_retaining_identity(monkeypatch, fail):
    calls = []
    cookies = {}

    def send(method, url, **kwargs):
        assert not cookies
        calls.append(kwargs)
        cookies["provider_cookie"] = "must-not-survive"
        if fail:
            raise requests.Timeout()
        return SimpleNamespace(status_code=200)

    session = SimpleNamespace(cookies=cookies, request=send)
    made = []
    monkeypatch.setattr(http_client, "_thread", SimpleNamespace())
    monkeypatch.setattr(
        http_client.requests, "Session", lambda: made.append(session) or session
    )
    for actor in ("first", "second"):
        try:
            http_client.request(
                "GET", "https://hotel.test/me", headers={"Authorization": actor}
            )
        except requests.Timeout:
            assert fail
        assert not cookies
    assert len(made) == 1
    assert [call["headers"]["Authorization"] for call in calls] == ["first", "second"]
