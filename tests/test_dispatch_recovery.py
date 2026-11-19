import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from hotel import store, operations
from hotel.service import app
from hotel.nlp import analyze

G = {"x-preview-user": "demo-guest"}
M = {"x-preview-user": "demo-staff"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "recovery.sqlite"))
    return TestClient(app)


def call(client, text):
    key = client.post("/calls", headers=G).json()["id"]
    client.post(
        f"/calls/{key}/turn", headers=G, json={"text": text, "turn_id": str(uuid4())}
    ).raise_for_status()
    client.post(f"/calls/{key}/end", headers=G).raise_for_status()
    return client.get("/tickets", headers=G).json()[0]["id"]


def report(client, ref, who, text):
    return client.post(
        "/work-assistant/turns",
        headers={"x-preview-user": who},
        json={"ref": ref, "text": text, "turn_id": str(uuid4())},
    )


def test_incomplete_call_recovered_on_same_request_to_confirmed_repair(client):
    ref = call(client, "Please help with my request.")
    t = client.get(f"/tickets/{ref}", headers=M).json()
    assert t["analysis"]["service_mode"] == "reception_review"
    assert t["assignment"]
    owner = t["assignment"]["staff"]
    assert client.post(f"/tickets/{ref}/ask-details", headers=G).status_code == 403
    assert client.post(f"/tickets/{ref}/ask-details", headers={"x-preview-user": "demo-maintenance"}).status_code == 403
    for _ in range(2):
        client.post(f"/tickets/{ref}/ask-details", headers={"x-preview-user": owner}).raise_for_status()
    with store.transaction() as db:
        assert db.one("SELECT COUNT(*) AS n FROM notifications WHERE ticket=? AND kind='clarification'", (ref,))["n"] == 1
    report(client, ref, owner, "I started the reception follow-up").raise_for_status()
    assert report(client, ref, owner, "I fixed it").status_code == 422
    t = client.get(f"/tickets/{ref}", headers=G).json()
    assert t["work"]["can_clarify"]
    body = {
        "key": str(uuid4()),
        "version": t["work"]["version"],
        "text": "The AC is not cooling. My child is asleep. Please send maintenance without us having to move. private-marker-238",
        "agreement": True,
    }
    assert (
        client.post(
            f"/tickets/{ref}/clarify",
            headers={"x-preview-user": "demo-guest-402"},
            json=body,
        ).status_code
        == 403
    )
    assert (
        client.post(f"/tickets/{ref}/clarify", headers=M, json=body).status_code == 403
    )
    before = None
    with store.transaction() as db:
        before = db.all("SELECT * FROM nlp_analysis WHERE ticket=?", (ref,))
    r = client.post(f"/tickets/{ref}/clarify", headers=G, json=body)
    assert r.status_code == 200, r.text
    assert (
        client.post(f"/tickets/{ref}/clarify", headers=G, json=body).json() == r.json()
    )
    t = client.get(f"/tickets/{ref}", headers=M).json()
    assert t["department"] == "Maintenance"
    assert t["complaint"] == "AC not cooling"
    assert t["analysis"]["service_mode"] == "service"
    assert len(client.get("/tickets", headers=G).json()) == 1
    with store.transaction() as db:
        for snapshot in before:
            assert (
                db.one("SELECT * FROM nlp_analysis WHERE id=?", (snapshot["id"],))
                == snapshot
            )
        assert "private-marker-238" not in json.dumps(
            db.all("SELECT * FROM nlp_analysis")
        )
        assert (
            db.one(
                "SELECT COUNT(*) AS n FROM task_assignments WHERE ticket=? AND active=1",
                (ref,),
            )["n"]
            == 1
        )
    assert (
        client.post(
            f"/tickets/{ref}/clarify", headers=G, json={**body, "key": str(uuid4())}
        ).status_code
        == 422
    )
    worker = t["assignment"]["staff"]
    for rejection in (True, False):
        report(client, ref, worker, "I started the repair").raise_for_status()
        report(
            client, ref, worker, "I repaired the AC and checked cooling"
        ).raise_for_status()
        t = client.get(f"/tickets/{ref}", headers=G).json()
        assert t["status"] == "Awaiting confirmation"
        client.post(
            f"/tickets/{ref}/confirm",
            headers=G,
            json={"version": t["work"]["version"], "resolved": not rejection},
        ).raise_for_status()
        if rejection:
            worker = client.get(f"/tickets/{ref}", headers=M).json()["assignment"][
                "staff"
            ]
    assert client.get(f"/tickets/{ref}", headers=G).json()["status"] == "Resolved"


def test_wifi_hangup_is_owned_reception_followup_not_room_visit(client):
    ref = call(client, "I cannot connect to the Wi-Fi.")
    t = client.get(f"/tickets/{ref}", headers=M).json()
    assert t["department"] == "Front Desk"
    assert t["assignment"]
    assert not t["analysis"].get("pending_question")
    assert t["analysis"]["service_mode"] == "service"
    assert t["department"] == "Front Desk"


@pytest.mark.parametrize(
    "agreement,text",
    [
        (False, "The AC is not cooling."),
        (True, "The AC is not cooling. Do not enter my room."),
        (True, "The AC is not cooling in Room 402."),
    ],
)
def test_permission_and_denied_access_still_protect_room_visits(
    client, agreement, text
):
    ref = call(client, "The AC is not cooling.")
    t = client.get(f"/tickets/{ref}", headers=G).json()
    body = {
        "key": str(uuid4()),
        "version": t["work"]["version"],
        "text": text,
        "agreement": agreement,
    }
    client.post(f"/tickets/{ref}/clarify", headers=G, json=body).raise_for_status()
    t = client.get(f"/tickets/{ref}", headers=M).json()
    assert t["analysis"]["service_mode"] == "reception_review"
    assert t["department"] == "Front Desk" and t["assignment"]


def test_operational_department_uses_procedure_and_safety_keeps_escalation(client):
    client.get("/me")
    with store.transaction() as db:
        a = analyze("Please bring extra towels to my room.")
        a["department"] = "Maintenance"  # Deliberately disagree with approved routing.
        a["urgency"] = "Low"
        t = store.create(
            db, store.profile(db, "demo-guest"), a, str(uuid4()), "Guest request", "305"
        )
        assert t["department"] == "Housekeeping"
        assert json.loads(t["analysis"])["department"] == "Maintenance"
        assert (
            operations.snapshot(db, t["id"])["assignment"]["staff"]
            == "demo-housekeeping"
        )
    call(client, "I smell gas in my room.")
    # The call-created safety ticket, not the earlier towel request.
    rows = client.get("/tickets", headers=M).json()
    critical = next(r for r in rows if r["urgency"] == "Critical")
    assert critical["status"] == "Escalated"
    assert critical["assignment"]["staff"] == "demo-staff"
