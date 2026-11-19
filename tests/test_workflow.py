from concurrent.futures import ThreadPoolExecutor
import base64
import io
import wave
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from hotel import store
from hotel.nlp import EXAMPLE, analyze, bundle, clean
from hotel.service import app
from hotel.report import ticket_pdf

GUEST = {"X-Preview-User": "demo-guest"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "hotel.sqlite"))
    for key in (
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "GOOGLE_API_KEY",
        "GEMINI_LIVE_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    return TestClient(app)


def test_real_features_and_class_scores():
    result = analyze(EXAMPLE)
    assert (result["urgency"], result["department"], result["rule"]) == (
        "Urgent",
        "Maintenance",
        None,
    )
    assert result["room"] == "305" and "305" not in result["tokens"]
    for target, details in result["predictions"].items():
        pipe = bundle()["models"][target]
        score = max(pipe.decision_function([EXAMPLE])[0])
        assert np.isclose(
            score, details["bias"] + sum(f["contribution"] for f in details["features"])
        )
        assert len(details["features"]) == pipe["tfidf"].transform([EXAMPLE]).nnz
    assert "not" in clean("My heater isn't working")
    assert analyze("qxxq qzzq")["urgency"] == "Unassessed"
    assert analyze("I smell gas in Room 305")["urgency"] == "Critical"
    assert analyze("There is no gas leak")["urgency"] == "Low"
    assert "No active issue" in analyze("There is no gas leak")["rule"]


def test_recording_survives_unavailable_speech_model(client, monkeypatch):
    from hotel import languages

    def unavailable(*args):
        raise OSError("Model offline")

    monkeypatch.setattr(languages, "transcribe", unavailable)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(3200))
    audio = base64.b64encode(buffer.getvalue()).decode()
    body = {"key": str(uuid4()), "language": "hi", "audio": audio}
    assert client.post("/voice-messages", json=body).status_code == 403
    ref = client.post("/voice-messages", headers=GUEST, json=body).json()["id"]
    assert client.post("/voice-messages", headers=GUEST, json=body).json()["id"] == ref
    assert client.get(f"/tickets/{ref}/audio", headers=GUEST).json()["audio"] == audio
    ticket = client.get(f"/tickets/{ref}").json()
    assert (ticket["source"], ticket["urgency"], ticket["department"]) == (
        "Voice message",
        "Unassessed",
        "Front Desk",
    )
    assert ticket_pdf(ticket).startswith(b"%PDF")
    assert (
        client.post(f"/tickets/{ref}/status", json={"value": "Resolved"}).status_code
        == 422
    )
    assert (
        client.post(
            "/voice-messages", headers=GUEST, json={**body, "audio": "bad"}
        ).status_code
        == 422
    )


def test_translated_request_keeps_original(client, monkeypatch):
    from hotel import languages

    monkeypatch.setattr(
        languages, "to_english", lambda text, lang: "My air conditioner is broken."
    )
    assert client.put("/language?value=hi", headers=GUEST).is_success
    assert client.get("/me", headers=GUEST).json()["language"] == "hi"
    msg = "मेरे कमरे का एसी खराब है।"
    ref = client.post(
        "/tickets",
        headers=GUEST,
        json={"language": "hi", "text": msg, "key": str(uuid4())},
    ).json()["id"]
    ticket = client.get(f"/tickets/{ref}").json()
    assert ticket["department"] == "Maintenance" and ticket["complaint"] == msg
    assert ticket["analysis"]["english"] == "My air conditioner is broken."
    assert ticket_pdf(ticket).startswith(b"%PDF")


def test_staff_guest_round_trip(client):
    payload = {"text": EXAMPLE, "key": str(uuid4()), "room": "305"}
    ref = client.post("/tickets", json=payload).json()["id"]
    assert client.post("/tickets", json=payload).json()["id"] == ref
    assert (
        client.post("/tickets", json={**payload, "text": "Different issue"}).status_code
        == 422
    )
    assert len(client.get("/tickets").json()) == 1
    guest_view = client.get("/tickets/" + ref, headers=GUEST).json()
    assert "analysis" not in guest_view and guest_view["status"] == "Assigned"
    assert (
        client.post(
            "/tickets/" + ref + "/status", headers=GUEST, json={"value": "In progress"}
        ).status_code
        == 403
    )
    assert client.post(
        "/tickets/" + ref + "/status",
        headers={"x-preview-user": "demo-maintenance"},
        json={"value": "In progress"},
    ).is_success
    assert (
        client.post(
            "/tickets/" + ref + "/status", json={"value": "Resolved"}
        ).status_code
        == 422
    )
    version = client.get("/tickets/" + ref).json()["work"]["version"]
    payload = {
        "key": str(uuid4()),
        "version": version,
        "outcome": "Fixed",
        "action": "Inspected and tested the repaired AC.",
        "note": "Internal technician note",
    }
    assert client.post(
        "/tickets/" + ref + "/outcome",
        headers={"x-preview-user": "demo-maintenance"},
        json=payload,
    ).is_success
    assert client.post(
        "/tickets/" + ref + "/outcome",
        headers={"x-preview-user": "demo-maintenance"},
        json=payload,
    ).is_success
    view = client.get("/tickets/" + ref, headers=GUEST).json()
    assert view["status"] == "Awaiting confirmation" and "note" not in view["work"]
    assert client.post(
        "/tickets/" + ref + "/confirm",
        headers=GUEST,
        json={"version": view["work"]["version"], "resolved": True},
    ).is_success
    assert client.post(
        "/tickets/" + ref + "/feedback", headers=GUEST, json={"value": "Satisfied"}
    ).is_success
    assert client.get("/tickets/" + ref, headers=GUEST).json()["status"] == "Resolved"
    assert ticket_pdf(client.get("/tickets/" + ref).json()).startswith(b"%PDF")


def test_concurrency_and_privacy(client):
    payload = {
        "text": EXAMPLE,
        "key": str(uuid4()),
        "source": "Public review",
        "room": "305",
    }
    with ThreadPoolExecutor(2) as pool:
        refs = list(
            pool.map(
                lambda _: client.post("/tickets", json=payload).json()["id"], range(2)
            )
        )
    assert refs[0] == refs[1]
    assert client.get("/tickets/" + refs[0], headers=GUEST).status_code == 403
    assert client.post("/calls", params={"ref": refs[0]}).status_code == 422
    assert client.get("/evaluation", headers=GUEST).status_code == 403
    with store.transaction() as db:
        p = store.profile(db, "demo-staff")
        with pytest.raises(PermissionError):
            store.ticket(db, {**p, "hotel": "other"}, refs[0])


def test_callbacks_require_current_consent(client, monkeypatch):
    for key in (
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "GOOGLE_API_KEY",
        "GEMINI_LIVE_MODEL",
    ):
        monkeypatch.setenv(key, "test-only")
    ref = client.post(
        "/tickets", json={"text": EXAMPLE, "key": str(uuid4()), "room": "305"}
    ).json()["id"]
    assert client.get("/calls").json() == []
    assert client.post("/calls", params={"ref": ref}).status_code == 422
    assert client.put("/consent", headers=GUEST, params={"value": "true"}).is_success
    cid = client.post("/calls", params={"ref": ref}).json()["id"]
    assert client.put("/consent", headers=GUEST, params={"value": "false"}).is_success
    assert client.post(f"/calls/{cid}/join", headers=GUEST).status_code == 403
    assert client.get("/tickets/" + ref).json()["status"] == "Assigned"


def test_guest_intake_uses_verified_room(client):
    result = client.post(
        "/tickets",
        headers=GUEST,
        json={"text": "Smell gas in Room 999", "room": "999", "key": str(uuid4())},
    )
    ticket = client.get("/tickets/" + result.json()["id"]).json()
    assert ticket["room"] == "305" and ticket["urgency"] == "Critical"
    assert any("safety alert" in e["action"] for e in ticket["events"])


def test_empty_and_expired_stay(client):
    assert client.post("/analyze", json={"text": " "}).status_code == 422
    with store.transaction() as db:
        db.run("UPDATE profiles SET staying_until='2000-01-01' WHERE id='demo-guest'")
    assert (
        client.post(
            "/tickets", headers=GUEST, json={"text": EXAMPLE, "key": str(uuid4())}
        ).status_code
        == 403
    )


def test_extraction_solution_and_priority_are_grounded(client):
    text = "The AC is not cooling in Room 999. My child is asleep and we need help without us having to move."
    a = client.post("/analyze", json={"text": text}).json()
    assert a["extraction"]["topic"] == "Air conditioning"
    assert {x["constraint"] for x in a["extraction"]["constraints"]} >= {
        "Child sleeping",
        "Prefers to stay in room",
    }
    assert a["solution"]["procedures"][0]["id"] == "demo-ac"
    ref = client.post(
        "/tickets",
        headers=GUEST,
        json={"text": text, "room": "999", "key": str(uuid4())},
    ).json()["id"]
    detail = client.get("/tickets/" + ref).json()
    assert detail["room"] == "305"
    assert detail["work"]["extraction"]["reported_room"] == "999"
    assert detail["work"]["extraction"]["verified_room"] == "305"
    client.post(
        "/tickets", json={"text": "qxxq qzzq", "key": str(uuid4())}
    ).raise_for_status()
    critical = client.post(
        "/tickets", json={"text": "I smell gas in Room 305", "key": str(uuid4())}
    ).json()["id"]
    rows = client.get("/tickets").json()
    assert next(r for r in rows if r["id"] == critical)["priority_rank"] == 1
    assert next(r for r in rows if r["id"] == ref)["priority_rank"] > 1


def test_outcome_requires_work_then_guest_can_reopen(client):
    ref = client.post(
        "/tickets", json={"text": EXAMPLE, "room": "305", "key": str(uuid4())}
    ).json()["id"]
    body = {
        "key": str(uuid4()),
        "version": 0,
        "outcome": "Fixed",
        "action": "Tested the cooling.",
    }
    assert (
        client.post(
            f"/tickets/{ref}/outcome",
            headers={"x-preview-user": "demo-maintenance"},
            json=body,
        ).status_code
        == 422
    )
    assert (
        client.post(f"/tickets/{ref}/outcome", headers=GUEST, json=body).status_code
        == 403
    )
    client.post(
        f"/tickets/{ref}/status",
        headers={"x-preview-user": "demo-maintenance"},
        json={"value": "In progress"},
    ).raise_for_status()
    version = client.get(f"/tickets/{ref}").json()["work"]["version"]
    body.update(version=version)
    client.post(
        f"/tickets/{ref}/outcome",
        headers={"x-preview-user": "demo-maintenance"},
        json=body,
    ).raise_for_status()
    view = client.get(f"/tickets/{ref}", headers=GUEST).json()
    confirmation = {"version": view["work"]["version"], "resolved": False}
    assert client.post(f"/tickets/{ref}/confirm", json=confirmation).status_code == 403
    client.post(
        f"/tickets/{ref}/confirm", headers=GUEST, json=confirmation
    ).raise_for_status()
    assert client.get(f"/tickets/{ref}").json()["status"] == "Assigned"
    assert (
        client.post(
            f"/tickets/{ref}/confirm", headers=GUEST, json=confirmation
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/tickets/{ref}/outcome", json={**body, "key": str(uuid4())}
        ).status_code
        == 422
    )
    # Reopening reassigned the request. The previous worker cannot access or replay outcomes.
    assert (
        client.post(
            f"/tickets/{ref}/outcome",
            headers={"x-preview-user": "demo-maintenance"},
            json=body,
        ).status_code
        == 403
    )


def test_unlinked_feedback_requires_reservation_review(client):
    ref = client.post(
        "/tickets",
        json={"text": EXAMPLE, "source": "Public review", "key": str(uuid4())},
    ).json()["id"]
    item = client.get(f"/tickets/{ref}").json()
    assert item["status"] == "Escalated" and item["assignment"] is None
    assert client.get(f"/tickets/{ref}", headers=GUEST).status_code == 403


def test_competing_guest_confirmations_have_one_result(client):
    ref = client.post(
        "/tickets", headers=GUEST, json={"text": EXAMPLE, "key": str(uuid4())}
    ).json()["id"]
    client.post(
        f"/tickets/{ref}/status",
        headers={"x-preview-user": "demo-maintenance"},
        json={"value": "In progress"},
    )
    version = client.get(f"/tickets/{ref}").json()["work"]["version"]
    client.post(
        f"/tickets/{ref}/outcome",
        headers={"x-preview-user": "demo-maintenance"},
        json={
            "key": str(uuid4()),
            "version": version,
            "outcome": "Fixed",
            "action": "Completed and tested the service.",
        },
    )
    version = client.get(f"/tickets/{ref}").json()["work"]["version"]
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda value: client.post(
                    f"/tickets/{ref}/confirm",
                    headers=GUEST,
                    json={"version": version, "resolved": value},
                ).status_code,
                [True, False],
            )
        )
    assert sorted(results) == [200, 422]
