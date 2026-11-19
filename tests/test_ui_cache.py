from types import SimpleNamespace

from hotel import ui_client


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def test_display_cache_is_scoped_to_session_token_and_invalidated_on_write(monkeypatch):
    state = State(auth={"access_token": "guest-a"})
    monkeypatch.setattr(ui_client, "st", SimpleNamespace(session_state=state))
    monkeypatch.setenv("HOTEL_MODE", "connected")
    monkeypatch.setenv("HOTEL_API_URL", "http://test")
    calls = []

    def transport(method, url, **kwargs):
        actor = kwargs["headers"]["Authorization"]
        calls.append((method, actor))
        return SimpleNamespace(status_code=200, json=lambda: {"actor": actor})

    monkeypatch.setattr(ui_client.requests, "request", transport)
    first = ui_client.request("GET", "/me")
    first["actor"] = "edited display"
    assert ui_client.request("GET", "/me")["actor"] == "Bearer guest-a"
    assert len(calls) == 1
    state.auth = {"access_token": "guest-b"}
    assert ui_client.request("GET", "/me")["actor"] == "Bearer guest-b"
    ui_client.request("PUT", "/language", params={"value": "hi"})
    ui_client.request("GET", "/me")
    assert len(calls) == 4


def test_display_cache_expires_and_operational_records_are_never_cached(monkeypatch):
    state = State(auth={"access_token": "guest-a"})
    monkeypatch.setattr(ui_client, "st", SimpleNamespace(session_state=state))
    monkeypatch.setenv("HOTEL_MODE", "connected")
    monkeypatch.setenv("HOTEL_API_URL", "http://test")
    clock = [0]
    monkeypatch.setattr(ui_client.time, "monotonic", lambda: clock[0])
    calls = []

    def transport(method, url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=200, json=lambda: {"version": len(calls)})

    monkeypatch.setattr(ui_client.requests, "request", transport)
    ui_client.request("GET", "/me")
    clock[0] = 61
    assert ui_client.request("GET", "/me")["version"] == 2
    ui_client.request("GET", "/tickets/example")
    assert ui_client.request("GET", "/tickets/example")["version"] == 4
