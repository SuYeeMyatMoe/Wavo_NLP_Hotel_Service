import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import requests
from fastapi.testclient import TestClient

from hotel import readiness, startup
from hotel.resources import singleton


def test_wake_keeps_cold_request_open(monkeypatch):
    from types import SimpleNamespace
    now = [0.0]
    def request(method, url, **kwargs):
        assert method == "GET" and url.endswith("/healthz")
        assert kwargs["timeout"][1] >= 25
        assert kwargs["headers"]["Cache-Control"] == "no-cache"
        assert isinstance(kwargs["params"]["_wavo_wake"], int)
        now[0] += 25
        return SimpleNamespace(ok=True, json=lambda: {"status": "ok"})
    monkeypatch.setattr(readiness, "request", request)
    readiness.wait_for_api("https://api.test", clock=lambda: now[0], sleep=lambda _: pytest.fail("Already ready"))
    assert now[0] == 25


def test_long_wake_reads_stay_within_total_deadline(monkeypatch):
    now, timeouts = [0.0], []
    def request(method, url, **kwargs):
        timeouts.append(kwargs["timeout"])
        now[0] += sum(kwargs["timeout"])
        raise requests.Timeout("Still sleeping")
    monkeypatch.setattr(readiness, "request", request)
    with pytest.raises(requests.Timeout):
        readiness.wait_for_api("https://api.test", clock=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0] + n))
    assert now[0] == 120
    assert timeouts == [(5, 60), (5, 48)]


def test_wake_is_shared_and_reused_only_for_sixty_seconds(monkeypatch):
    entered, release = Event(), Event()
    now, calls = [0.0], []

    def wait(url):
        calls.append(url)
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(readiness, "wait_for_api", wait)
    coordinator = readiness.WakeCoordinator(clock=lambda: now[0])
    with ThreadPoolExecutor(max_workers=8) as pool:
        tasks = list(pool.map(lambda _: coordinator.begin("https://api.test/"), range(8)))
    try:
        assert entered.wait(2)
        assert all(task is tasks[0] for task in tasks)
        assert calls == ["https://api.test"]
    finally:
        release.set()
    tasks[0].result(timeout=5)
    now[0] = 59
    assert coordinator.begin("https://api.test") is tasks[0]
    now[0] = 60
    fresh = coordinator.begin("https://api.test")
    assert fresh is not tasks[0]
    fresh.result(timeout=5)
    assert len(calls) == 2


def test_only_one_visitor_gets_browser_hint_within_shared_deadline(monkeypatch):
    release = Event()
    now = [0.0]
    monkeypatch.setattr(readiness, "wait_for_api", lambda _: release.wait(5))
    coordinator = readiness.WakeCoordinator(clock=lambda: now[0])
    task = coordinator.begin("https://api.test")
    now[0] = 30
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            hints = list(pool.map(lambda _: coordinator.claim_browser_hint("https://api.test/", task), range(8)))
        sent = [hint for hint in hints if hint]
        assert len(sent) == 1
        assert sent[0]["url"] == "https://api.test/healthz"
        assert sent[0]["timeoutMs"] == 90000
        assert set(sent[0]) == {"url", "nonce", "timeoutMs"}
    finally:
        release.set()
    task.result(timeout=5)
    assert coordinator.claim_browser_hint("https://api.test", task) is None


def test_failed_wake_retries_only_when_requested(monkeypatch):
    calls = []

    def wait(url):
        calls.append(url)
        if len(calls) == 1:
            raise requests.Timeout("cold service")

    monkeypatch.setattr(readiness, "wait_for_api", wait)
    coordinator = readiness.WakeCoordinator()
    with pytest.raises(requests.Timeout):
        coordinator.begin("https://api.test").result(timeout=5)
    assert len(calls) == 1
    coordinator.begin("https://api.test").result(timeout=5)
    assert len(calls) == 2


def test_browser_hint_mounts_without_changing_login_state(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from hotel import ui_readiness

    monkeypatch.setattr(ui_readiness, "claim_browser_hint", lambda *a: {
        "url": "https://api.test/healthz", "nonce": "public", "timeoutMs": 120000,
    })
    ui = AppTest.from_string(
        "from hotel.ui_readiness import browser_hint\n"
        "browser_hint('https://api.test', None)\n",
        default_timeout=15,
    ).run()
    assert not ui.exception
    assert "auth" not in ui.session_state


def test_wait_for_ready_joins_existing_wake(monkeypatch):
    from concurrent.futures import Future

    task = Future()
    task.set_result(None)
    monkeypatch.setattr(readiness, "begin_wake", lambda _: pytest.fail("Duplicate wake"))
    readiness.wait_for_ready("https://api.test", task=task)


def test_concurrent_resource_initialization_loads_once():
    entered, release = Event(), Event()
    calls = []

    @singleton
    def resource():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return object()

    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = [pool.submit(resource) for _ in range(8)]
        try:
            assert entered.wait(2)
        finally:
            release.set()
        values = [f.result(timeout=5) for f in pending]
    assert len(calls) == 1
    assert all(value is values[0] for value in values)


def test_resource_failures_remain_retryable():
    calls = []

    @singleton
    def resource():
        calls.append(1)
        if len(calls) == 1:
            raise OSError("missing resource")
        return "loaded"

    with pytest.raises(OSError):
        resource()
    assert resource() == resource() == "loaded"
    assert len(calls) == 2


def test_api_import_does_not_load_scientific_libraries():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import hotel.service; "
         "assert not {'numpy','sklearn','joblib','nltk','langid'} & sys.modules.keys()"],
        env={**os.environ, "HOTEL_MODE": "preview"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_workspace_serves_while_models_warm(tmp_path, monkeypatch):
    from hotel.service import app

    entered, release = Event(), Event()

    def slow_model():
        entered.set()
        assert release.wait(10)

    monkeypatch.setattr(startup, "loaders", lambda: (slow_model,))
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("WAVO_RUN_OPERATIONS", "false")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "startup.sqlite"))
    with TestClient(app) as client:
        try:
            assert entered.wait(2)
            assert client.get("/healthz").json() == {"status": "ok"}
            result = client.get("/workspace/updates", headers={"x-preview-user": "demo-guest"})
            assert result.status_code == 200
            assert result.json()["profile"]["role"] == "guest"
            assert not release.is_set()
        finally:
            release.set()


def test_warmup_stops_between_resources(monkeypatch):
    entered, release = Event(), Event()
    def slow():
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(startup, "loaders", lambda: (slow, lambda: pytest.fail("Stopped")))
    runner = startup.WarmupRunner()
    runner.start()
    assert entered.wait(2)
    runner.stop.set()
    release.set()
    runner.close()
    assert not runner.thread.is_alive()
