from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from hotel.service import app
from hotel import store
from hotel.concierge_api import worker_token

guest = {"x-preview-user": "demo-guest"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "calls.sqlite"))
    return TestClient(app)


def start(client):
    r = client.post("/calls", headers=guest)
    r.raise_for_status()
    return r.json()["id"]


def turn(client, key, text, uid=None):
    r = client.post(
        f"/calls/{key}/turn",
        headers=guest,
        json={"text": text, "turn_id": uid or str(uuid4())},
    )
    r.raise_for_status()
    return r.json()


def test_wifi_and_ac_demo(client):
    key = start(client)
    first = turn(client, key, "How do I connect to the Wi-Fi?")
    assert "Hotel-Guest" in first["reply"] and first["ticket"] is None
    assert turn(client, key, "Yes, I'm online now.")["outcome"] == "Resolved by guest"
    client.post(f"/calls/{key}/end", headers=guest).raise_for_status()
    assert not client.get("/tickets").json()
    key = start(client)
    client.put(
        f"/calls/{key}/transcript-consent?value=true", headers=guest
    ).raise_for_status()
    first = turn(
        client,
        key,
        "The AC isn't cooling, and my child is asleep. Can someone help without us having to move?",
    )
    assert (
        "15 minutes" in first["reply"]
        and "same-category" in first["options"]
        and first["ticket"] is None
    )
    assert not turn(client, key, "Don't send someone yet.")["ticket"]
    uid = str(uuid4())
    approved = turn(client, key, "Yes, send maintenance.", uid)
    assert (
        approved["ticket"] == turn(client, key, "Yes, send maintenance.", uid)["ticket"]
    )
    task = client.get("/tickets/" + approved["ticket"]).json()
    assert (task["department"], task["room"]) == ("Maintenance", "305")
    assert task["analysis"]["predictions"]["urgency"]["features"]
    change = client.post(f"/desk/cases/{key}/eta", json={"minutes": 45}).json()
    assert "45 minutes" in change["reply"] and "same-category" in change["reply"]
    client.post(f"/calls/{key}/end", headers=guest).raise_for_status()
    assert (
        client.post(f"/calls/{key}/move-request", headers=guest).json()["outcome"]
        == "Room approval needed"
    )
    assert len(client.get("/tickets").json()) == 1
    assert (
        client.post(
            f"/desk/cases/{key}/room-decision?approve=true", headers=guest
        ).status_code
        == 403
    )
    assert (
        client.post(f"/desk/cases/{key}/room-decision?approve=true").json()["outcome"]
        == "Move approved"
    )
    rooms = client.get("/desk/availability").json()["rooms"]
    assert not next(r for r in rooms if r["room"] == "308")["ready"]
    assert client.get("/desk/cases", headers=guest).status_code == 403


def test_voice_confirmation_fallback_assigns_maintenance(client):
    from hotel.voice_input import VoiceInput

    key = start(client)
    inputs = VoiceInput()
    inputs.observe("issue", "The toilet is blocked.", False)
    offered = turn(client, key, "The toilet is blocked.", inputs.tool_key())
    assert offered["outcome"] == "Service offered"
    assert inputs.observe("issue", "The toilet is blocked.", True) is None
    # Gemini speaks without invoking the tool for the short confirmation.
    uid, text = inputs.observe("approval", "Yes, send maintenance.", True)
    assigned = turn(client, key, text, uid)
    ref = assigned["ticket"]
    assert assigned["outcome"] == "Task assigned"
    # A delayed/retried tool cannot create a second task.
    assert turn(client, key, text, inputs.tool_key())["ticket"] == ref
    client.post(f"/calls/{key}/end", headers=guest).raise_for_status()
    result = client.get(f"/calls/{key}/result", headers=guest).json()
    assert result["assignment"]["department"] == "Maintenance"
    assert result["next_step"] == ""
    assert len(client.get("/tickets", headers=guest).json()) == 1


@pytest.mark.parametrize(
    "confirmation", ["Yup.", "Please send maintenance.", '"Yes, send maintenance."']
)
def test_spoken_confirmation_dispatches_before_hangup(client, confirmation):
    key = start(client)
    offered = turn(client, key, "The AC is not cooling.")
    assert offered["outcome"] == "Service offered"
    approved = turn(client, key, confirmation)
    assert approved["outcome"] == "Task assigned"
    task = client.get("/tickets/" + approved["ticket"]).json()
    assert task["department"] == "Maintenance"
    assert task["analysis"]["service_agreement"] is True
    client.post(f"/calls/{key}/end", headers=guest).raise_for_status()
    receipt = client.get(f"/calls/{key}/result", headers=guest).json()
    assert receipt["finalized"]
    assert receipt["assignment"]["department"] == "Maintenance"


def test_no_room_and_unresolved_exit(client):
    client.put(
        "/desk/rooms", json={"room": "308", "category": "Standard", "ready": False}
    ).raise_for_status()
    client.put(
        "/desk/availability/Maintenance", json={"minutes": 28}
    ).raise_for_status()
    key = start(client)
    result = turn(client, key, "Our air conditioner has broken.")
    assert "28 minutes" in result["reply"] and "same-category" not in result["reply"]
    assert (
        client.post(
            f"/calls/{key}/end", headers={"x-preview-user": "demo-staff"}
        ).status_code
        == 403
    )
    client.post(f"/calls/{key}/end", headers=guest).raise_for_status()
    ended = client.get(f"/calls/{key}/case", headers=guest).json()
    client.post(f"/calls/{key}/end", headers=guest).raise_for_status()
    assert client.get(f"/calls/{key}/case", headers=guest).json() == ended
    assert (
        client.get(f"/calls/{key}/case", headers=guest).json()["outcome"]
        == "Follow-up required"
    )
    assert len(client.get("/tickets").json()) == 1


@pytest.mark.parametrize(
    "text",
    [
        "I want to speak with a person.",
        "Please connect me to reception.",
    ],
)
def test_real_reception_handoff(client, text):
    key = start(client)
    result = turn(client, key, text)
    assert result["outcome"] == "Waiting for reception" and result["ticket"]
    assert client.post(f"/desk/cases/{key}/accept", headers=guest).status_code == 403
    assert client.post(f"/desk/cases/{key}/accept").json()["engine"] == "local"
    for side, headers in [("offer", guest), ("answer", {})]:
        client.post(
            f"/calls/{key}/signal",
            headers=headers,
            json={"type": side, "sdp": "example " + side},
        ).raise_for_status()
    assert (
        client.get(f"/calls/{key}/signal", headers=guest).json()["answer"]
        == "example answer"
    )
    client.post(f"/calls/{key}/end", headers=guest).raise_for_status()
    assert client.get(f"/calls/{key}/signal").status_code == 403


def test_pending_handoff_does_not_repeat_announcement(client):
    key = start(client)
    first = turn(client, key, "I want to speak with a person.")
    assert "I have asked reception to join" in first["reply"]
    for text in ("Okay", "Are they coming?", "My air conditioner is still broken."):
        result = turn(client, key, text)
        assert result["outcome"] == "Waiting for reception"
        assert result["ticket"] == first["ticket"]
        assert "not accepted" in result["reply"]
        assert "I have asked reception to join" not in result["reply"]
    assert len(client.get("/tickets").json()) == 1


@pytest.mark.parametrize(
    "text", ["The light is not working", "My room light is broken"]
)
def test_lighting_offers_then_assigns_maintenance_once(client, text):
    key = start(client)
    offered = turn(client, key, text)
    assert offered["outcome"] == "Service offered" and not offered["ticket"]
    assert "Shall I send Maintenance" in offered["reply"]
    assert not turn(client, key, "Don't send anyone yet")["ticket"]
    uid = str(uuid4())
    assigned = turn(client, key, "Yes, please send maintenance", uid)
    assert assigned["outcome"] == "Task assigned"
    assert (
        turn(client, key, "Yes, please send maintenance", uid)["ticket"]
        == assigned["ticket"]
    )
    assert turn(client, key, "Okay")["ticket"] == assigned["ticket"]
    task = client.get("/tickets/" + assigned["ticket"]).json()
    assert task["department"] == "Maintenance"
    assert task["assignment"]["staff"] in {"demo-maintenance", "demo-maintenance-2"}
    assert len(client.get("/tickets").json()) == 1
    assert client.post(f"/desk/cases/{key}/accept").status_code == 422


@pytest.mark.parametrize(
    "text", ["Please give me a refund.", "I smell gas in my room."]
)
def test_reception_tasks_do_not_invite_a_live_participant(client, text):
    key = start(client)
    result = turn(client, key, text)
    assert result["outcome"] == "Reception follow-up" and result["ticket"]
    assert "join" not in result["reply"] and "stay on" not in result["reply"]
    assert client.post(f"/desk/cases/{key}/accept").status_code == 422
    task = client.get("/tickets/" + result["ticket"]).json()
    assert task["department"] == "Front Desk" and task["assignment"]
    if "gas" in text:
        assert task["urgency"] == "Critical" and task["status"] == "Escalated"
    status = turn(client, key, "Okay")
    assert status["ticket"] == result["ticket"]
    assert "not accepted" not in status["reply"]
    human = turn(client, key, "I want to speak with a person")
    assert human["outcome"] == "Waiting for reception"
    assert human["ticket"] == result["ticket"]
    assert client.post(f"/desk/cases/{key}/accept").status_code == 200


def test_unavailable_maintenance_creates_followup_not_handoff(client):
    key = start(client)
    turn(client, key, "The light is not working")
    with store.transaction() as db:
        db.run("UPDATE staff_roster SET available=0 WHERE department='Maintenance'")
    result = turn(client, key, "Yes, send maintenance")
    assert result["outcome"] == "Reception follow-up"
    task = client.get("/tickets/" + result["ticket"]).json()
    assert task["department"] == "Front Desk"
    assert task["assignment"]["staff"] in {"demo-reception", "demo-staff"}
    assert "No repair visit" in result["reply"]
    assert "not accepted" not in turn(client, key, "The light is still broken")["reply"]


def test_failed_wifi_guidance_and_missing_procedure_are_followup(client):
    key = start(client)
    turn(client, key, "How do I connect to Wi-Fi?")
    result = turn(client, key, "It still does not work")
    assert result["outcome"] == "Reception follow-up"
    assert "join" not in result["reply"]
    client.post(f"/calls/{key}/end", headers=guest)
    key = start(client)
    with store.transaction() as db:
        db.run("UPDATE service_procedures SET enabled=0 WHERE category='Electrical'")
    result = turn(client, key, "The light is not working")
    assert result["outcome"] == "Reception follow-up"
    assert "join" not in result["reply"]


def test_negated_human_request_keeps_service_flow(client):
    key = start(client)
    result = turn(client, key, "The light is not working. Don't call reception.")
    assert result["outcome"] == "Service offered"


def test_offer_uses_approved_department_even_when_prediction_disagrees(
    client, monkeypatch
):
    from hotel import concierge

    original = concierge.analyze

    def disagree(*args, **kwargs):
        return {**original(*args, **kwargs), "department": "Front Desk"}

    monkeypatch.setattr(concierge, "analyze", disagree)
    key = start(client)
    assert (
        "Shall I send Maintenance"
        in turn(client, key, "The light is not working")["reply"]
    )
    assert turn(client, key, "Yes")["outcome"] == "Task assigned"


def test_electrical_seed_preserves_customized_or_disabled_guidance(client):
    from hotel.procedures import seed_electrical

    start(client)
    with store.transaction() as db:
        db.run(
            "UPDATE service_procedures SET id='hotel-custom-electrical',body='Hotel-specific instructions',enabled=0 WHERE id='demo-electrical'"
        )
        seed_electrical(db)
        seed_electrical(db)
        rows = db.all(
            "SELECT id,body,enabled FROM service_procedures WHERE hotel='demo' AND category='Electrical'"
        )
        assert rows == [
            {
                "id": "hotel-custom-electrical",
                "body": "Hotel-specific instructions",
                "enabled": 0,
            }
        ]


def test_same_hotel_private_notes(client):
    key = start(client)
    client.post(f"/calls/{key}/end", headers=guest)
    with store.transaction() as db:
        db.run("UPDATE profiles SET hotel='elsewhere' WHERE id='demo-staff'")
    assert client.get("/desk/cases").json() == []
    assert client.get(f"/calls/{key}/case").status_code == 403


@pytest.mark.parametrize("reply", ["OK", "O.K.", "O K", "Uh... O.K.", "That's okay."])
def test_spoken_ok_confirms_pending_offer_without_restarting_intake(client, reply):
    key = start(client)
    first = turn(client, key, "The shower is leaking")
    assert first["outcome"] == "Service offered"
    approved = turn(client, key, reply)
    assert approved["outcome"] == "Task assigned" and approved["ticket"]
    for acknowledgement in ("O.K.", "Oh, okay.", "Thank you"):
        result = turn(client, key, acknowledgement)
        assert result["outcome"] == "Task assigned"
        assert result["ticket"] == approved["ticket"]
        assert result["reply"].startswith("You're welcome.")
    assert len(client.get("/tickets").json()) == 1


def test_unclear_response_keeps_the_service_question_and_refusal_does_not_dispatch(
    client,
):
    key = start(client)
    turn(client, key, "The shower is leaking")
    for reply in ("Hmm", "O.K.?", "O.K., don't send anyone"):
        result = turn(client, key, reply)
        assert result["outcome"] == "Service offered" and not result["ticket"]
        assert result["reply"] == "Shall I send Maintenance to room 305?"
    assert turn(client, key, "OK")["outcome"] == "Task assigned"


def test_ok_without_an_offer_does_not_create_work(client):
    key = start(client)
    result = turn(client, key, "O.K.")
    assert result["outcome"] == "Listening" and not result["ticket"]


def test_acknowledgement_after_resolution_does_not_restart_intake(client):
    key = start(client)
    turn(client, key, "How do I connect to Wi-Fi?")
    assert turn(client, key, "Yes, I am online")["outcome"] == "Resolved by guest"
    assert turn(client, key, "Oh, okay.")["reply"].startswith("You're welcome.")
    assert not turn(client, key, "Hmm")["ticket"]
    assert not client.get("/tickets").json()


def test_live_worker_ok_uses_pending_offer(client, monkeypatch):
    monkeypatch.setenv("CONCIERGE_MODE", "auto")
    for name in (
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "LIVEKIT_URL",
        "GOOGLE_API_KEY",
        "GEMINI_LIVE_MODEL",
    ):
        monkeypatch.setenv(name, "test")
    key = start(client)
    path = f"/internal/calls/{key}/turn"
    responses = []
    for text in ("The shower is leaking", "O.K.", "Oh, okay."):
        response = client.post(
            path,
            headers={"x-worker-token": worker_token(key)},
            json={"text": text, "turn_id": str(uuid4())},
        )
        response.raise_for_status()
        responses.append(response.json())
    assert [r["outcome"] for r in responses] == [
        "Service offered",
        "Task assigned",
        "Task assigned",
    ]
    assert responses[2]["reply"].startswith("You're welcome.")
    assert responses[1]["ticket"] == responses[2]["ticket"]


def test_worker_posts_live_transcript_to_api(client, monkeypatch):
    monkeypatch.setenv("CONCIERGE_MODE", "auto")
    for k in [
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "LIVEKIT_URL",
        "GOOGLE_API_KEY",
        "GEMINI_LIVE_MODEL",
    ]:
        monkeypatch.setenv(k, "test")
    key = start(client)
    path = f"/internal/calls/{key}/turn"
    body = {"text": "I need Wi-Fi", "turn_id": str(uuid4())}
    assert client.post(path, json=body).status_code == 403
    assert (
        client.post(
            path, json=body, headers={"x-worker-token": worker_token(key)}
        ).json()["outcome"]
        == "Awaiting Wi-Fi confirmation"
    )


def test_call_language_switches_without_display_preference(client, monkeypatch):
    from hotel import concierge_api
    from hotel.languages import detect_text_language

    monkeypatch.setattr(
        concierge_api, "to_english", lambda text, lang: "How do I connect to the Wi-Fi?"
    )
    key = start(client)
    for lang, text in [
        ("en", "How can I connect to the hotel internet?"),
        ("zh", "请问如何连接酒店的无线网络？"),
        ("hi", "होटल के वाईफाई से कैसे जुड़ें?"),
        ("ms", "Bagaimanakah saya boleh menyambung kepada internet hotel?"),
        ("my", "ဟိုတယ်ဝိုင်ဖိုင်ကို ဘယ်လိုချိတ်ဆက်ရမလဲ။"),
    ]:
        result = turn(client, key, text)
        assert result["language"] == lang
        assert client.get("/me", headers=guest).json()["language"] == "en"
    assert detect_text_language("Yes", "ms") == "ms"
    assert detect_text_language("是", "zh") == "zh"


def test_audio_language_and_replay_are_consistent(client, monkeypatch):
    import base64
    import io
    import wave
    from hotel import concierge_api

    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(3200))
    body = {"turn_id": str(uuid4()), "audio": base64.b64encode(out.getvalue()).decode()}
    key = start(client)
    monkeypatch.setattr(
        concierge_api,
        "transcribe_auto",
        lambda raw, previous: ("房间的空调坏了。", "zh"),
    )
    monkeypatch.setattr(
        concierge_api,
        "to_english",
        lambda text, lang: text if lang == "en" else "The air conditioner is broken.",
    )
    first = client.post(f"/calls/{key}/turn", headers=guest, json=body).json()
    assert first["language"] == "zh" and first["outcome"] == "Service offered"
    turn(client, key, "Yes, please send the maintenance team to my room.")
    # A retried earlier turn must preserve the latest language and outcome.
    repeat = client.post(f"/calls/{key}/turn", headers=guest, json=body).json()
    assert repeat["outcome"] == "Task assigned"
    assert repeat["language"] == "en"


def test_end_call_during_slow_audio_job(client, monkeypatch):
    import base64
    import io
    import time
    import wave
    from threading import Event
    from hotel import concierge_api

    entered, release = Event(), Event()

    def slow(raw, previous):
        entered.set()
        release.wait(10)
        return "My air conditioner is broken.", "en"

    monkeypatch.setattr(concierge_api, "transcribe_auto", slow)
    key = start(client)
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(3200))
    body = {"turn_id": str(uuid4()), "audio": base64.b64encode(out.getvalue()).decode()}
    job = client.post(f"/calls/{key}/jobs", headers=guest, json=body).json()["id"]
    from hotel.call_jobs import get

    future = get("demo-guest", key, job)
    try:
        assert entered.wait(3)
        before = time.monotonic()
        client.post(f"/calls/{key}/end", headers=guest).raise_for_status()
        assert time.monotonic() - before < 2
        assert (
            client.get(f"/calls/{key}/jobs/{job}", headers=guest).json()["status"]
            == "cancelled"
        )
    finally:
        release.set()
    with pytest.raises(Exception) as removed:
        get("demo-guest", key, job)
    assert removed.value.status_code == 404
    try:
        future.result(timeout=5)
    except ValueError:
        pass
    assert not client.get("/tickets").json()
    assert client.get(f"/calls/{key}/case", headers=guest).json()["status"] == "Ended"


def test_staff_call_history_has_room_summary_and_legacy_calls(client):
    key = start(client)
    turn(client, key, "How do I connect to the Wi-Fi?")
    turn(client, key, "Yes, I am online now.")
    client.post(f"/calls/{key}/end", headers=guest).raise_for_status()
    with store.transaction() as db:
        db.run(
            "INSERT INTO calls(id,hotel,guest,direction,status,operator,created,transcript) VALUES(?,?,?,?,?,?,?,?)",
            (
                "old-call",
                "demo",
                "demo-guest",
                "Inbound",
                "Ended",
                "Reception",
                "2025-01-01",
                "Guest asked about parking.",
            ),
        )
    rows = client.get("/calls").json()
    assert len(rows) == 2 and all(r["room"] == "305" for r in rows)
    current = next(r for r in rows if r["id"] == key)
    assert "Wi-Fi" in current["summary"] and current["outcome"] == "Resolved by guest"
    assert client.get(f"/calls/{key}/record", headers=guest).status_code == 403
    old = client.get("/calls/old-call/record").json()
    assert old["room"] == "305" and "parking" in old["transcript"]
    with store.transaction() as db:
        db.run("UPDATE profiles SET hotel='other-hotel' WHERE id='demo-staff'")
    assert client.get("/calls").json() == []
    assert client.get(f"/calls/{key}/record").status_code == 403
