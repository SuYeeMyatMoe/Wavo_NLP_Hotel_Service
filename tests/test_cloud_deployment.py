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
    cloud.client.cache_clear()
    monkeypatch.setenv("WAVO_LANGUAGE_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-only")
    yield
    cloud.client.cache_clear()


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
            assert kwargs["http_options"].retry_options.attempts == 2
            assert 429 not in kwargs["http_options"].retry_options.http_status_codes
            self.models = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def generate_content(self, **kwargs):
            assert kwargs["config"].response_mime_type == "application/json"
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
