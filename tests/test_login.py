from types import SimpleNamespace
from concurrent.futures import Future

import pytest
import requests
from streamlit.testing.v1 import AppTest
from hotel import http_client, ui_client
from hotel import readiness


@pytest.mark.parametrize(
    "role,history_failure", [("guest", False), ("staff", False), ("guest", True)]
)
@pytest.mark.parametrize("wake_enabled", [False, True])
def test_hosted_login_reuses_verified_workspace_data(
    monkeypatch, role, history_failure, wake_enabled
):
    monkeypatch.setenv("HOTEL_MODE", "connected")
    monkeypatch.setenv("HOTEL_API_URL", "http://hotel.test")
    monkeypatch.setenv("SUPABASE_URL", "https://auth.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
    monkeypatch.setenv("WAVO_DEMO_LOGIN", "false")
    monkeypatch.setenv("WAVO_WAKE_API", str(wake_enabled).lower())
    wake = Future()
    monkeypatch.setattr(readiness, "begin_wake", lambda _: wake)
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
    cache_clock = [0.0]
    monkeypatch.setattr(
        ui_client, "time", SimpleNamespace(monotonic=lambda: cache_clock[0])
    )

    def response(value):
        return SimpleNamespace(ok=True, status_code=200, json=lambda: value)

    def post(url, **kwargs):
        # Authentication happens before waiting on the API wake task.
        assert not wake.done()
        wake.set_result(None)
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
        # History can outlast the workspace cache TTL. It must not cause a
        # second authorized workspace fetch during the first render.
        cache_clock[0] += 11
        if history_failure:
            raise requests.Timeout()
        return response([])

    monkeypatch.setattr(
        http_client,
        "request",
        lambda method, url, **kwargs: (post if method == "POST" else get)(
            url, **kwargs
        ),
    )
    monkeypatch.setattr(ui_client, "http_request", api)
    ui = AppTest.from_file("../app.py", default_timeout=90)
    ui.query_params["login"] = role
    ui.run()
    assert not ui.exception
    assert not any('class="wavo-loading"' in e.value for e in ui.get("html"))
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
    assert not any('class="wavo-loading"' in e.value for e in ui.get("html"))
    assert set(ui.session_state.login_timings) == {
        "authentication_seconds",
        "readiness_seconds",
        "workspace_seconds",
        "usable_workspace_seconds",
        "history_seconds",
    }
    if history_failure:
        assert ui.warning
        assert any(b.label == "Call AI Reception" for b in ui.button)
        assert any(t.label == "What do you need?" for t in ui.text_area)


def test_hosted_login_still_rejects_wrong_entrance(monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "connected")
    monkeypatch.setenv("HOTEL_API_URL", "http://hotel.test")
    monkeypatch.setenv("SUPABASE_URL", "https://auth.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
    monkeypatch.setenv("WAVO_DEMO_LOGIN", "false")
    monkeypatch.setattr(
        http_client,
        "request",
        lambda method, *a, **k: SimpleNamespace(
            ok=True,
            json=lambda: {"access_token": "wrong-role-token"}
            if method == "POST"
            else {"profile": {"role": "staff"}},
        ),
    )
    ui = AppTest.from_file("../app.py", default_timeout=90)
    ui.query_params["login"] = "guest"
    ui.run()
    next(b for b in ui.button if b.label == "Sign in").click().run()
    assert not ui.exception
    assert "auth" not in ui.session_state
    assert any("guest entrance" in error.value for error in ui.error)
    assert not any('class="wavo-loading"' in e.value for e in ui.get("html"))


@pytest.mark.parametrize(
    "failure", ["credentials", "timeout", "connection", "profile_timeout"]
)
def test_login_failures_clear_loader_and_allow_retry(monkeypatch, failure):
    monkeypatch.setenv("HOTEL_MODE", "connected")
    monkeypatch.setenv("HOTEL_API_URL", "http://hotel.test")
    monkeypatch.setenv("SUPABASE_URL", "https://auth.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
    monkeypatch.setenv("WAVO_DEMO_LOGIN", "false")

    def fail(method, *args, **kwargs):
        if failure == "credentials":
            return SimpleNamespace(ok=False)
        if failure == "profile_timeout" and method == "POST":
            return SimpleNamespace(ok=True, json=lambda: {"access_token": "test"})
        raise (
            requests.ConnectionError()
            if failure == "connection"
            else requests.Timeout()
        )

    monkeypatch.setattr(http_client, "request", fail)
    ui = AppTest.from_file("../app.py", default_timeout=90)
    ui.query_params["login"] = "guest"
    ui.run()
    ui.text_input(key="demo_email_guest").input("guest@test")
    next(b for b in ui.button if b.label == "Sign in").click().run()
    assert not ui.exception and ui.error
    assert "auth" not in ui.session_state
    assert not any('class="wavo-loading"' in e.value for e in ui.get("html"))
    assert ui.text_input(key="demo_email_guest").value == "guest@test"
    assert any(b.label == "Sign in" for b in ui.button)


def test_website_entry_wakes_without_blocking_and_bad_credentials_do_not_wait(monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "connected")
    monkeypatch.setenv("HOTEL_API_URL", "http://hotel.test")
    monkeypatch.setenv("SUPABASE_URL", "https://auth.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
    monkeypatch.setenv("WAVO_WAKE_API", "true")
    monkeypatch.setenv("WAVO_DEMO_LOGIN", "false")
    wake, calls = Future(), []
    def begin(url):
        calls.append(url)
        return wake
    monkeypatch.setattr(readiness, "begin_wake", begin)
    monkeypatch.setattr(http_client, "request", lambda *a, **kw: SimpleNamespace(ok=False))
    monkeypatch.setattr(readiness, "wait_for_ready", lambda *a, **kw: pytest.fail("Bad credentials must not wait"))
    ui = AppTest.from_file("../app.py", default_timeout=15)
    ui.run()
    assert not ui.exception and calls == ["http://hotel.test"]
    ui.run()
    assert len(calls) == 1
    ui.query_params["login"] = "guest"
    ui.run()
    assert len(calls) == 1 and not wake.done()
    next(b for b in ui.button if b.label == "Sign in").click().run()
    assert not ui.exception and "auth" not in ui.session_state
    assert ui.error and not wake.done()
    assert not any('class="wavo-loading"' in e.value for e in ui.get("html"))
