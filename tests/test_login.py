from types import SimpleNamespace

import pytest
import requests
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize("role", ["guest", "staff"])
def test_hosted_login_reuses_verified_workspace_data(monkeypatch, role):
    monkeypatch.setenv("HOTEL_MODE", "connected")
    monkeypatch.setenv("HOTEL_API_URL", "http://hotel.test")
    monkeypatch.setenv("SUPABASE_URL", "https://auth.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
    monkeypatch.setenv("WAVO_DEMO_LOGIN", "false")
    profile = dict(
        id="test-user",
        hotel="test",
        role=role,
        mode="Supabase",
        voice=False,
        work_assistant_test_mode=True,
        language="en",
        room="305",
        consent=False,
    )
    updates = dict(
        profile=profile,
        notifications=[],
        confirmations=[],
        active_calls=[],
        handoffs=[],
        alerts=[],
    )
    calls = []

    def response(value):
        return SimpleNamespace(ok=True, status_code=200, json=lambda: value)

    def post(url, **kwargs):
        calls.append(("POST", url))
        assert kwargs["json"] == {"email": "user@test", "password": "password"}
        return response({"access_token": "test-token"})

    def get(url, **kwargs):
        calls.append(("GET", url))
        assert kwargs["headers"]["Authorization"] == "Bearer test-token"
        assert url == "http://hotel.test/workspace/updates"
        return response(updates)

    def api(method, url, **kwargs):
        calls.append((method, url))
        assert url == "http://hotel.test/tickets"
        return response([])

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "request", api)
    ui = AppTest.from_file("../app.py", default_timeout=90)
    ui.query_params["login"] = role
    ui.run()
    assert not ui.exception
    ui.text_input(key="demo_email_" + role).input("user@test")
    ui.text_input(key="demo_password_" + role).input("password")
    next(b for b in ui.button if b.label == "Sign in").click().run()
    assert not ui.exception
    assert ui.session_state.auth["access_token"] == "test-token"
    assert calls == [
        ("POST", "https://auth.test/auth/v1/token"),
        ("GET", "http://hotel.test/workspace/updates"),
        ("GET", "http://hotel.test/tickets"),
    ]


def test_hosted_login_still_rejects_wrong_entrance(monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "connected")
    monkeypatch.setenv("HOTEL_API_URL", "http://hotel.test")
    monkeypatch.setenv("SUPABASE_URL", "https://auth.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
    monkeypatch.setenv("WAVO_DEMO_LOGIN", "false")
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: SimpleNamespace(
            ok=True, json=lambda: {"access_token": "wrong-role-token"}
        ),
    )
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: SimpleNamespace(
            ok=True, json=lambda: {"profile": {"role": "staff"}}
        ),
    )
    ui = AppTest.from_file("../app.py", default_timeout=90)
    ui.query_params["login"] = "guest"
    ui.run()
    next(b for b in ui.button if b.label == "Sign in").click().run()
    assert not ui.exception
    assert "auth" not in ui.session_state
    assert any("guest entrance" in error.value for error in ui.error)
