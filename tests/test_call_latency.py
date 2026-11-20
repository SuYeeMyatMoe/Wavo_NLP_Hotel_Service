from uuid import uuid4
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from hotel import concierge, completion, store
from hotel.service import app
from hotel.post_call_state import accept_finalization, dismiss_pending

G = {"x-preview-user": "demo-guest"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "latency.sqlite"))
    return TestClient(app)


def turn(client, key, text, uid=None):
    return client.post(
        f"/calls/{key}/turn",
        headers=G,
        json={"text": text, "turn_id": uid or str(uuid4())},
    )


@pytest.mark.parametrize("cancel", [False, True])
def test_end_returns_committed_receipt_and_retry_is_idempotent(client, cancel):
    start = str(uuid4())
    key = client.post("/calls/start", headers=G, json={"key": start}).json()["id"]
    assert turn(client, key, "The light is not working").status_code == 200
    assert turn(client, key, "OK").status_code == 200
    path = f"/calls/start/{start}/cancel" if cancel else f"/calls/{key}/end"
    first = client.post(path, headers=G).json()
    assert first["ended"] and first["result"]["finalized"]
    assert first["result"]["assignment"]["department"] == "Maintenance"
    assert (
        client.post(path, headers=G).json()["result"]["ticket"]
        == first["result"]["ticket"]
    )
    assert client.get(f"/calls/{key}/result", headers=G).json() == first["result"]
    with store.transaction() as db:
        assert db.one("SELECT COUNT(*) AS n FROM tickets")["n"] == 1


def test_projection_failure_does_not_undo_hangup(client, monkeypatch):
    key = client.post("/calls", headers=G).json()["id"]

    def fail(*args):
        raise TimeoutError("read unavailable")

    monkeypatch.setattr(completion, "call_result", fail)
    response = client.post(f"/calls/{key}/end", headers=G)
    assert response.status_code == 200 and response.json()["result"] is None
    assert client.get(f"/calls/{key}/status", headers=G).json()["status"] == "Ended"


def test_failed_commit_cannot_return_a_success_receipt(client, monkeypatch):
    key = client.post("/calls", headers=G).json()["id"]
    original = store.transaction

    @contextmanager
    def failing_transaction(*args, **kwargs):
        with original(*args, **kwargs) as db:
            yield db
            raise RuntimeError("Simulated commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(store, "transaction", failing_transaction)
        with pytest.raises(RuntimeError, match="Simulated commit failure"):
            client.post(f"/calls/{key}/end", headers=G)
    assert client.get(f"/calls/{key}/status", headers=G).json()["status"] == "Connected"


def test_simultaneous_end_produces_one_followup(client):
    from concurrent.futures import ThreadPoolExecutor

    key = client.post("/calls", headers=G).json()["id"]
    turn(client, key, "The light is not working").raise_for_status()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: client.post(f"/calls/{key}/end", headers=G), range(2))
        )
    assert all(
        r.status_code == 200 and r.json()["result"]["finalized"] for r in results
    )
    assert (
        results[0].json()["result"]["ticket"] == results[1].json()["result"]["ticket"]
    )
    with store.transaction() as db:
        assert db.one("SELECT COUNT(*) AS n FROM tickets")["n"] == 1


def test_reclassify_changed_context_outside_lock(client, monkeypatch):
    key = client.post("/calls", headers=G).json()["id"]
    original = concierge.classify_turn
    versions = []

    def changed(case, *args):
        versions.append(case["version"])
        if len(versions) == 1:
            # This independent write would block if classification held the lock.
            with store.transaction() as db:
                n = concierge.note(db, key)
                concierge.save(db, n, reply="Context changed")
        return original(case, *args)

    monkeypatch.setattr(concierge, "classify_turn", changed)
    uid = str(uuid4())
    response = turn(client, key, "The light is not working", uid)
    assert (
        response.status_code == 200 and response.json()["outcome"] == "Service offered"
    )
    assert versions == [0, 1]
    with store.transaction() as db:
        assert (
            db.one("SELECT COUNT(*) AS n FROM concierge_turns WHERE turn_id=?", (uid,))[
                "n"
            ]
            == 1
        )


def test_hangup_during_classification_prevents_late_dispatch(client, monkeypatch):
    key = client.post("/calls", headers=G).json()["id"]
    turn(client, key, "The light is not working").raise_for_status()
    original = concierge.classify_turn

    def ended(case, *args):
        client.post(f"/calls/{key}/end", headers=G).raise_for_status()
        return original(case, *args)

    monkeypatch.setattr(concierge, "classify_turn", ended)
    assert turn(client, key, "OK").status_code == 422
    result = client.get(f"/calls/{key}/result", headers=G).json()
    assert result["assignment"]["department"] == "Front Desk"
    with store.transaction() as db:
        assert db.one("SELECT COUNT(*) AS n FROM tickets")["n"] == 1


def test_pending_dismissal_never_reopens_or_seeds_another_session():
    state, cache = {}, {}
    pending = {"key": "attempt", "call_id": "call", "status": "pending"}
    accept_finalization(state, cache, pending)
    assert state["finalizing_call"] == pending and "completed_call" not in state
    dismiss_pending(state)
    done = {
        **pending,
        "status": "complete",
        "result": {"call_id": "call", "finalized": True},
    }
    accept_finalization(state, cache, done)
    assert "completed_call" not in state and not cache
    assert state["dismissed_call"] == "call"
    other, other_cache = {}, {}
    accept_finalization(other, other_cache, done)
    assert other["completed_call"] == "call"
    assert other_cache[("receipt", "/calls/call/result")] == done["result"]
    # A subsequent rerun must not overwrite a freshly refreshed receipt.
    other_cache[("receipt", "/calls/call/result")]["outcome"] = "Updated"
    accept_finalization(other, other_cache, done)
    assert other_cache[("receipt", "/calls/call/result")]["outcome"] == "Updated"


def test_pending_dialog_renders_without_result_request(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from hotel import post_call_ui

    def no_request(*args, **kwargs):
        pytest.fail("Pending popup must not wait for a result request")

    monkeypatch.setattr(post_call_ui, "request", no_request)

    def script():
        import streamlit as st
        from hotel.post_call_ui import request_popup

        if "initialized" not in st.session_state:
            st.session_state.initialized = True
            st.session_state.finalizing_call = {
                "key": "attempt",
                "call_id": "call",
                "status": "pending",
            }
        if st.session_state.get("finalizing_call"):
            request_popup("attempt", lambda *args: None)

    view = AppTest.from_function(script, default_timeout=30).run()
    assert not view.exception
    assert any("Checking your request" in item.value for item in view.info)
    next(b for b in view.button if b.label == "Close").click().run()
    assert not view.exception
    assert view.session_state.dismissed_finalization == "attempt"
