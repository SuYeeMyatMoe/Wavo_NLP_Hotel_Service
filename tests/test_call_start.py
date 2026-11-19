from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from hotel.service import app
from hotel import store

GUEST = {"x-preview-user": "demo-guest"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "startup.sqlite"))
    return TestClient(app)


def test_atomic_consent_retry_and_owner(client):
    body = {"key": str(uuid4()), "transcript_consent": True}
    first = client.post("/calls/start", json=body, headers=GUEST)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["room"] == "305" and result["transcript_consent"]
    assert (
        client.post("/calls/start", json=body, headers=GUEST).json()["id"]
        == result["id"]
    )
    assert (
        client.post(
            "/calls/start", json={**body, "transcript_consent": False}, headers=GUEST
        ).status_code
        == 409
    )
    assert client.get(f"/calls/{result['id']}/status").status_code == 403
    assert client.post("/calls/start", json={"key": str(uuid4())}).status_code == 403
    assert client.get(f"/calls/{result['id']}/status", headers=GUEST).status_code == 200


def test_cancel_before_start_and_after_start(client):
    key = str(uuid4())
    assert client.post(f"/calls/start/{key}/cancel", headers=GUEST).status_code == 200
    assert (
        client.post("/calls/start", json={"key": key}, headers=GUEST).status_code == 409
    )
    assert not client.get("/calls", headers=GUEST).json()
    key = str(uuid4())
    call = client.post("/calls/start", json={"key": key}, headers=GUEST).json()
    assert not call["transcript_consent"]
    for _ in range(2):
        assert (
            client.post(f"/calls/start/{key}/cancel", headers=GUEST).status_code == 200
        )
    assert (
        client.get(f"/calls/{call['id']}/status", headers=GUEST).json()["status"]
        == "Ended"
    )
    assert (
        client.post("/calls/start", json={"key": key}, headers=GUEST).status_code == 409
    )
    assert (
        client.post(
            f"/calls/{call['id']}/turn",
            headers=GUEST,
            json={"turn_id": str(uuid4()), "text": "Yes send maintenance"},
        ).status_code
        == 403
    )


def test_concurrent_start_keys_reuse_one_call(client):
    # Seed before simultaneous SQLite schema checks.
    client.get("/me", headers=GUEST)

    def start(_):
        r = client.post("/calls/start", headers=GUEST, json={"key": str(uuid4())})
        assert r.status_code == 200, r.text
        return r.json()["id"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(start, range(4)))
    assert len(set(ids)) == 1
    with store.transaction() as db:
        assert db.one("SELECT COUNT(*) AS n FROM calls")["n"] == 1


def test_cors_explicit_origins(client):
    for origin, allowed in [
        ("http://localhost:8501", True),
        ("https://untrusted.invalid", False),
    ]:
        response = client.options(
            "/calls/start",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert (
            response.headers.get("access-control-allow-origin") == origin
        ) == allowed
