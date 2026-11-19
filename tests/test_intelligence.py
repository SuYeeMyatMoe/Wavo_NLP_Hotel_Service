import json
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from hotel.service import app
from hotel import store
from hotel.nlp import analyze

GUEST = {"x-preview-user": "demo-guest"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "intelligence.sqlite"))
    return TestClient(app)


def call(client, consent=False):
    key = client.post("/calls", headers=GUEST).json()["id"]
    if consent:
        client.put(
            f"/calls/{key}/transcript-consent?value=true", headers=GUEST
        ).raise_for_status()
    return key


def turn(client, key, text):
    r = client.post(
        f"/calls/{key}/turn",
        headers=GUEST,
        json={"text": text, "turn_id": str(uuid4())},
    )
    r.raise_for_status()
    return r.json()


@pytest.mark.parametrize(
    "text,states",
    [
        ("The AC is not cooling.", {"Air conditioning": "active"}),
        ("The shower is no longer leaking.", {"Plumbing": "resolved"}),
        (
            "The AC works, but the shower leaks.",
            {"Air conditioning": "resolved", "Plumbing": "active"},
        ),
        ("There is no gas leak.", {"Safety": "denied"}),
        ("The AC is not fixed.", {"Air conditioning": "active"}),
    ],
)
def test_issue_scope(text, states):
    a = analyze(text)
    assert {i["topic"]: i["state"] for i in a["issues"]} == states
    assert a["sentiment"]["available"]
    for p in a["predictions"].values():
        assert sum(f["contribution"] for f in p["features"]) + p[
            "bias"
        ] == pytest.approx(p["score"])


def test_hazards_are_clause_scoped():
    assert analyze("There is no gas leak.")["urgency"] == "Low"
    assert (
        analyze("There is no gas leak, but sparks flying from the socket.")["urgency"]
        == "Critical"
    )
    assert analyze("The room is on fire.")["urgency"] == "Critical"
    assert analyze("Yes")["intent"]["ambiguous"]


def test_readonly_simulation_and_rules(client):
    result = client.post(
        "/analyze", json={"text": "The AC works, but the shower leaks."}
    ).json()
    assert result["solution"]["procedures"][0]["category"] == "Plumbing"
    assert not client.get("/tickets").json()
    body = {
        "title": "Another plumbing rule",
        "category": "Plumbing",
        "department": "Maintenance",
        "body": "Review with technician.",
    }
    assert client.post("/procedures", headers=GUEST, json=body).status_code == 403
    client.post("/procedures", json=body).raise_for_status()
    result = client.post("/analyze", json={"text": "The shower leaks."}).json()
    assert (
        not result["solution"]["procedures"]
        and "Conflicting" in result["solution"]["reason"]
    )
    result = client.post("/analyze", json={"text": "My room light is broken."}).json()
    assert not result["solution"]["procedures"]


def test_case_only_retention_and_room305(client):
    key = call(client)
    private = "The AC is not cooling. My child is asleep. My secret code is pineapple-moon. Can someone help without us having to move?"
    turn(client, key, private)
    response = turn(client, key, "Yes, send maintenance.")
    ref = response["ticket"]
    assert ref
    row = client.get(f"/tickets/{ref}").json()
    assert row["room"] == "305"
    assert row["work"]["extraction"]["service_label"] == "AC not cooling"
    assert {c["constraint"] for c in row["work"]["extraction"]["constraints"]} >= {
        "Child sleeping",
        "Prefers to stay in room",
    }
    record = client.get(f"/calls/{key}/record").json()
    assert not record["transcript"] and not record["turns"]
    assert "pineapple-moon" not in json.dumps(record)
    with store.transaction() as db:
        for table in (
            "calls",
            "call_notes",
            "call_transcripts",
            "nlp_analysis",
            "tickets",
            "events",
            "agent_actions",
            "notifications",
            "operation_jobs",
        ):
            assert "pineapple-moon" not in json.dumps(db.all("SELECT * FROM " + table))
    client.post(f"/calls/{key}/end", headers=GUEST).raise_for_status()
    client.post(
        f"/tickets/{ref}/status",
        headers={"x-preview-user": "demo-maintenance"},
        json={"value": "In progress"},
    ).raise_for_status()
    version = client.get(f"/tickets/{ref}").json()["work"]["version"]
    client.post(
        f"/tickets/{ref}/outcome",
        headers={"x-preview-user": "demo-maintenance"},
        json={
            "key": str(uuid4()),
            "version": version,
            "outcome": "Fixed",
            "action": "Repaired and verified cooling.",
        },
    ).raise_for_status()
    version = client.get(f"/tickets/{ref}").json()["work"]["version"]
    client.post(
        f"/tickets/{ref}/confirm",
        headers=GUEST,
        json={"version": version, "resolved": True},
    ).raise_for_status()
    assert client.get("/insights").json()["resolution_sample"] == 1


def test_consent_revocation_and_note_review(client):
    key = call(client, True)
    turn(client, key, "The AC is broken. The private marker is lilac-river.")
    ref = turn(client, key, "Yes, send maintenance.")["ticket"]
    record = client.get(f"/calls/{key}/record").json()
    assert len(record["turns"]) == 4 and record["analyses"][0]["predictions"]
    review = {
        "version": 0,
        "issue": "AC needs repair",
        "next_step": "Quiet inspection",
        "constraints": ["Child sleeping"],
    }
    assert (
        client.post(f"/calls/{key}/note-review", headers=GUEST, json=review).status_code
        == 403
    )
    client.post(f"/calls/{key}/note-review", json=review).raise_for_status()
    assert client.post(f"/calls/{key}/note-review", json=review).status_code == 422
    assert client.put(f"/calls/{key}/transcript-consent?value=false").status_code == 403
    client.put(
        f"/calls/{key}/transcript-consent?value=false", headers=GUEST
    ).raise_for_status()
    record = client.get(f"/calls/{key}/record").json()
    assert not record["turns"] and not record["transcript"]
    assert "lilac-river" not in json.dumps(record)
    assert "lilac-river" not in json.dumps(client.get(f"/tickets/{ref}").json())
    assert record["note"]["version"] == 1


def test_clarification_and_ambiguous_confirmation(client):
    key = call(client)
    result = turn(client, key, "Yes")
    assert not result["ticket"] and "explain" in result["reply"]
    result = turn(client, key, "The AC is broken. Do not enter my room.")
    assert result["outcome"] == "Clarification needed"
    result = turn(client, key, "You can enter after 3 pm.")
    assert result["outcome"] == "Service offered"
    assert turn(client, key, "Yes, send maintenance.")["ticket"]


def test_preferences_added_later_reach_staff(client):
    key = call(client)
    turn(client, key, "The AC is broken.")
    ref = turn(client, key, "Yes, send maintenance.")["ticket"]
    turn(client, key, "My child is asleep. Please be quiet.")
    record = client.get(f"/calls/{key}/record").json()
    assert "Child sleeping" in record["note"]["constraints"]
    task = client.get(f"/tickets/{ref}").json()
    assert "Child sleeping" in [
        c["constraint"] for c in task["work"]["extraction"]["constraints"]
    ]
    assert not record["transcript"]
