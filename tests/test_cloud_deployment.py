import io
import wave
from threading import Event
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient
from hotel import cloud_languages as cloud, languages, operations_worker, readiness


def wav():
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 1600)
    return out.getvalue()


@pytest.fixture
def gemini(monkeypatch):
    clear = cloud.client.cache_clear
    clear()
    monkeypatch.setenv("WAVO_LANGUAGE_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-only")
    monkeypatch.delenv("GEMINI_LANGUAGE_FALLBACK_MODEL", raising=False)
    yield
    clear()


@pytest.mark.parametrize("language", ["en", "zh", "hi", "ms", "my"])
def test_cloud_interfaces_preserve_languages(gemini, monkeypatch, language):
    monkeypatch.setattr(
        cloud,
        "generate",
        lambda *a: {"text": "The AC is broken.", "language": language},
    )
    assert languages.transcribe(wav(), language) == "The AC is broken."
    assert languages.transcribe_auto(wav()) == ("The AC is broken.", language)
    assert languages.to_english("The AC is broken.", language) == "The AC is broken."
    monkeypatch.setattr(
        languages, "_load_recognizer", lambda: pytest.fail("Local model loaded")
    )
    languages.warm_staff_recorder()


@pytest.mark.parametrize(
    "result", [{}, {"text": ""}, {"text": 4}, {"text": "x" * 8001}]
)
def test_malformed_translation_is_rejected(gemini, monkeypatch, result):
    monkeypatch.setattr(cloud, "generate", lambda *a: result)
    with pytest.raises(RuntimeError, match="Language processing"):
        languages.to_english("空调坏了", "zh")


def test_failed_cloud_analysis_requires_review(gemini, monkeypatch):
    monkeypatch.setattr(cloud, "generate", lambda *a: {})
    result = languages.guest_analysis("空调坏了", "zh")
    assert result["urgency"] == "Unassessed"
    assert result["text"] == "空调坏了"
    assert result["predictions"] == {}


def test_translation_keeps_classifier_and_provenance(gemini, monkeypatch):
    monkeypatch.setattr(cloud, "generate", lambda *a: {"text": "The AC is broken."})
    result = languages.guest_analysis("空调坏了", "zh")
    assert result["department"] == "Maintenance"
    assert result["provenance"]["evidence_source"] == "translated English"


def test_invalid_audio_never_reaches_provider(gemini, monkeypatch):
    monkeypatch.setattr(cloud, "generate", lambda *a: pytest.fail("Invalid audio sent"))
    with pytest.raises(ValueError):
        languages.transcribe(b"invalid", "en")


@pytest.mark.parametrize("body", ["not-json", "[]", '{"text":"ok"}'])
def test_sdk_response_validation(gemini, monkeypatch, body):
    from google import genai

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["http_options"].retry_options.attempts == 1
            self.models = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def generate_content(self, **kwargs):
            assert kwargs["config"].response_mime_type == "application/json"
            assert kwargs["config"].temperature is None
            return SimpleNamespace(text=body)

    monkeypatch.setattr(genai, "Client", Client)
    if body.startswith("{"):
        assert cloud.translate("test", "en", "my") == "ok"
    else:
        with pytest.raises(RuntimeError, match="Language processing"):
            cloud.translate("test", "en", "my")


def test_quota_failure_is_sanitized(gemini, monkeypatch):
    from google import genai

    def denied(**kwargs):
        raise RuntimeError("429 secret-provider-payload")

    monkeypatch.setattr(genai, "Client", denied)
    with pytest.raises(RuntimeError) as error:
        cloud.translate("test", "en", "my")
    assert "secret-provider" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize(
    "code,expected", [(503, 3), (500, 3), (429, 1), (401, 1), (400, 1)]
)
def test_provider_retries_only_transient_errors(gemini, monkeypatch, code, expected):
    calls, sleeps, now = [], [], [0.0]

    class Failure(Exception):
        pass

    def fail(**kwargs):
        calls.append(kwargs)
        error = Failure("private provider response")
        error.code = code
        raise error

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(
        cloud,
        "client",
        lambda _: SimpleNamespace(models=SimpleNamespace(generate_content=fail)),
    )
    monkeypatch.setattr(cloud.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(cloud.time, "sleep", sleep)
    monkeypatch.setattr(cloud.random, "uniform", lambda *args: 0)
    with pytest.raises(cloud.LanguageUnavailable):
        cloud.translate("空调坏了", "zh", "en")
    assert len(calls) == expected
    assert sleeps == ([1, 2] if expected == 3 else [])
    assert [c["config"].http_options.timeout for c in calls] == (
        [25000, 24000, 22000] if expected == 3 else [25000]
    )


def test_transient_recovery_preserves_result(gemini, monkeypatch):
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            import httpx

            raise httpx.ConnectError("temporary")
        return SimpleNamespace(text='{"text":"The AC is broken."}')

    monkeypatch.setattr(
        cloud,
        "client",
        lambda _: SimpleNamespace(models=SimpleNamespace(generate_content=generate)),
    )
    monkeypatch.setattr(cloud.time, "sleep", lambda _: None)
    assert cloud.translate("空调坏了", "zh", "en") == "The AC is broken."
    assert len(calls) == 2


def test_provider_deadline_prevents_another_attempt(gemini, monkeypatch):
    now, calls = [0.0], []

    def generate(**kwargs):
        import httpx

        calls.append(kwargs)
        now[0] = 25
        raise httpx.ReadTimeout("deadline")

    monkeypatch.setattr(
        cloud,
        "client",
        lambda _: SimpleNamespace(models=SimpleNamespace(generate_content=generate)),
    )
    monkeypatch.setattr(cloud.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        cloud.time, "sleep", lambda _: pytest.fail("Deadline exhausted")
    )
    with pytest.raises(cloud.LanguageUnavailable):
        cloud.translate("空调坏了", "zh", "en")
    assert len(calls) == 1


def test_free_model_fallback_only_after_transient_failures(gemini, monkeypatch):
    calls = []

    def generate(**kwargs):
        calls.append(kwargs["model"])
        if len(calls) < 3:
            error = RuntimeError("unavailable")
            error.code = 503
            raise error
        return SimpleNamespace(text='{"text":"The AC is broken."}')

    monkeypatch.setenv("GEMINI_LANGUAGE_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setattr(
        cloud,
        "client",
        lambda _: SimpleNamespace(models=SimpleNamespace(generate_content=generate)),
    )
    monkeypatch.setattr(cloud.time, "sleep", lambda _: None)
    assert cloud.translate("空调坏了", "zh", "en") == "The AC is broken."
    assert calls == [
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
    ]


def test_rejects_unapproved_fallback_model(gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_LANGUAGE_FALLBACK_MODEL", "gemini-4-carbon")
    monkeypatch.setattr(cloud, "client", lambda _: SimpleNamespace())
    with pytest.raises(cloud.LanguageUnavailable):
        cloud.translate("空调坏了", "zh", "en")


def test_readiness_only_retries_get(monkeypatch):
    now, methods = [0.0], []

    def request(method, url, **kwargs):
        methods.append(method)
        assert url == "https://hotel.test/healthz"
        if len(methods) == 1:
            raise requests.Timeout()
        return SimpleNamespace(ok=True, json=lambda: {"status": "ok"})

    monkeypatch.setattr(readiness, "request", request)
    readiness.wait_for_api(
        "https://hotel.test/",
        clock=lambda: now[0],
        sleep=lambda n: now.__setitem__(0, now[0] + n),
    )
    assert methods == ["GET", "GET"]


def test_readiness_has_a_deadline(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(readiness, "request", lambda *a, **k: SimpleNamespace(ok=False))
    with pytest.raises(requests.Timeout):
        readiness.wait_for_api(
            "https://hotel.test",
            timeout=6,
            clock=lambda: now[0],
            sleep=lambda n: now.__setitem__(0, now[0] + n),
        )
    assert now[0] == 6


def test_operations_catch_up_retry_and_stop(monkeypatch):
    called, done = [], Event()

    def cycle(stop):
        called.append(1)
        if len(called) == 1:
            raise RuntimeError("temporary")
        done.set()

    monkeypatch.setattr(operations_worker, "cycle", cycle)
    runner = operations_worker.OperationsRunner(interval=0.01)
    runner.start()
    try:
        assert done.wait(2)
    finally:
        runner.close()
    assert not runner.thread.is_alive()
    assert len(called) >= 2


def test_lifespan_health_and_operations(monkeypatch):
    from hotel.service import app

    calls = []

    class Runner:
        def start(self):
            calls.append("start")

        def close(self):
            calls.append("close")

    monkeypatch.setenv("WAVO_RUN_OPERATIONS", "true")
    monkeypatch.setattr(operations_worker, "OperationsRunner", Runner)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert calls == ["start"]
    assert calls == ["start", "close"]


def test_worker_auth_survives_cloud_credential_rotation(monkeypatch):
    from hotel.worker_auth import worker_token

    monkeypatch.setenv("WAVO_WORKER_SECRET", "test-shared-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "backend-project-key")
    expected = worker_token("call-1")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "cloud-generated-key")
    assert worker_token("call-1") == expected
    assert worker_token("call-2") != expected
