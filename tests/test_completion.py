import json
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from hotel.service import app
from hotel import store, operations, monitoring

G = {"x-preview-user": "demo-guest"}
W = {"x-preview-user": "demo-maintenance"}
M = {"x-preview-user": "demo-staff"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "completion.sqlite"))
    return TestClient(app)


def turn(client, key, text):
    r = client.post(
        f"/calls/{key}/turn", headers=G, json={"text": text, "turn_id": str(uuid4())}
    )
    r.raise_for_status()
    return r.json()


def repair_call(client):
    key = client.post("/calls", headers=G).json()["id"]
    turn(
        client,
        key,
        "The AC is not cooling. My child is asleep. We want to stay in the room. private-marker-329",
    )
    ref = turn(client, key, "Yes, send maintenance.")["ticket"]
    client.post(f"/calls/{key}/end", headers=G).raise_for_status()
    return key, ref


def report(client, ref, who, text):
    response = client.post(
        "/work-assistant/turns",
        headers={"x-preview-user": who},
        json={"ref": ref, "text": text, "turn_id": str(uuid4())},
    )
    response.raise_for_status()


def test_post_call_estimate_survives_refresh_and_full_repair_cycle(client):
    key, ref = repair_call(client)
    result = client.get(f"/calls/{key}/result", headers=G).json()
    assert result["finalized"] and result["outcome"] == "Your request is assigned"
    assert result["room"] == "305" and result["problem"] == "AC not cooling"
    assert result["assignment"]["name"] == "Aung · Maintenance"
    assert result["completion_estimate"]["remaining_minutes"] == 15
    assert "private-marker" not in json.dumps(result)
    due = result["completion_estimate"]["expected_at"]
    client.post(f"/calls/{key}/end", headers=G).raise_for_status()
    assert (
        client.get(f"/calls/{key}/result", headers=G).json()["completion_estimate"][
            "expected_at"
        ]
        == due
    )
    assert (
        client.get("/tickets", headers=G).json()[0]["completion_estimate"][
            "expected_at"
        ]
        == due
    )
    for resolved in (False, True):
        t = client.get(f"/tickets/{ref}", headers=M).json()
        report(client, ref, t["assignment"]["staff"], "I started the AC repair")
        assert (
            client.get(f"/calls/{key}/result", headers=G).json()["outcome"]
            == "In progress"
        )
        report(
            client,
            ref,
            t["assignment"]["staff"],
            "I repaired the AC and checked cooling",
        )
        r = client.get(f"/calls/{key}/result", headers=G).json()
        assert (
            r["outcome"] == "Awaiting your confirmation"
            and r["completion_estimate"] is None
        )
        client.post(
            f"/tickets/{ref}/confirm",
            headers=G,
            json={"version": r["work_version"], "resolved": resolved},
        ).raise_for_status()
        if not resolved:
            reopened = client.get(f"/calls/{key}/result", headers=G).json()
            assert (
                reopened["completion_estimate"]["assignment"]
                != result["completion_estimate"]["assignment"]
            )
    assert client.get(f"/calls/{key}/result", headers=G).json()["outcome"] == "Resolved"


def test_estimate_update_authorization_version_and_idempotency(client):
    key, ref = repair_call(client)
    r = client.get(f"/calls/{key}/result", headers=G).json()
    e = r["completion_estimate"]
    body = {
        "key": str(uuid4()),
        "assignment_id": e["assignment"],
        "version": 1,
        "minutes": 45,
    }
    route = f"/tickets/{ref}/completion-estimate"
    for who in [
        G,
        {"x-preview-user": "demo-maintenance-2"},
        {"x-preview-user": "demo-guest-402"},
    ]:
        assert client.post(route, headers=who, json=body).status_code == 403
    changed = client.post(route, headers=W, json=body)
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2 and changed.json()["remaining_minutes"] == 45
    assert client.post(route, headers=W, json=body).json() == changed.json()
    assert (
        client.post(route, headers=W, json={**body, "key": str(uuid4())}).status_code
        == 422
    )
    assert (
        client.post(route, headers=W, json={**body, "minutes": 46}).status_code == 422
    )
    assert (
        client.post(
            route,
            headers=M,
            json={**body, "key": str(uuid4()), "version": 2, "minutes": 20},
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/calls/{key}/result", headers={"x-preview-user": "demo-guest-402"}
        ).status_code
        == 403
    )
    with store.transaction() as db:
        assert (
            db.one(
                "SELECT COUNT(*) AS n FROM notifications WHERE ticket=? AND kind='completion_estimate'",
                (ref,),
            )["n"]
            == 2
        )
        db.run("UPDATE profiles SET hotel='other-hotel' WHERE id='demo-staff'")
    assert client.get(f"/calls/{key}/result", headers=M).status_code == 403
    assert (
        client.post(
            route, headers=M, json={**body, "key": str(uuid4()), "version": 3}
        ).status_code
        == 403
    )


def test_overdue_notifies_once_per_revision_without_resolving(client):
    key, ref = repair_call(client)
    e = client.get(f"/calls/{key}/result", headers=G).json()["completion_estimate"]
    at = operations.later(e["expected_at"], 1)
    monitoring.tick(at)
    monitoring.tick(at)
    with store.transaction() as db:
        assert (
            db.one(
                "SELECT COUNT(*) AS n FROM notifications WHERE ticket=? AND kind='completion_delay'",
                (ref,),
            )["n"]
            == 2
        )
        assert (
            db.one("SELECT status FROM tickets WHERE id=?", (ref,))["status"]
            != "Resolved"
        )
        assert (
            db.one(
                "SELECT notified_version FROM completion_estimates WHERE assignment=?",
                (e["assignment"],),
            )["notified_version"]
            == 1
        )
    response = client.post(
        f"/tickets/{ref}/completion-estimate",
        headers=M,
        json={
            "key": str(uuid4()),
            "assignment_id": e["assignment"],
            "version": 1,
            "minutes": 25,
        },
    )
    response.raise_for_status()
    monitoring.tick(operations.later(response.json()["expected_at"], 1))
    monitoring.tick(operations.later(response.json()["expected_at"], 1))
    with store.transaction() as db:
        assert (
            db.one(
                "SELECT COUNT(*) AS n FROM notifications WHERE ticket=? AND kind='completion_delay'",
                (ref,),
            )["n"]
            == 4
        )


def test_wifi_and_reception_review_do_not_get_repair_estimates(client):
    key = client.post("/calls", headers=G).json()["id"]
    assert not client.get(f"/calls/{key}/result", headers=G).json()["finalized"]
    turn(client, key, "How do I connect to Wi-Fi?")
    turn(client, key, "Yes, I am online now.")
    client.post(f"/calls/{key}/end", headers=G).raise_for_status()
    r = client.get(f"/calls/{key}/result", headers=G).json()
    assert r["outcome"] == "Resolved during your call" and r["ticket"] is None
    assert r["completion_estimate"] is None
    key = client.post("/calls", headers=G).json()["id"]
    turn(client, key, "The AC is not cooling.")
    client.post(f"/calls/{key}/end", headers=G).raise_for_status()
    r = client.get(f"/calls/{key}/result", headers=G).json()
    assert r["outcome"] == "Reception is following up" and r["assignment"]
    assert r["completion_estimate"] is None
    t = client.get(f"/tickets/{r['ticket']}", headers=M).json()
    assert (
        client.post(
            f"/tickets/{r['ticket']}/completion-estimate",
            headers=M,
            json={
                "key": str(uuid4()),
                "assignment_id": t["assignment"]["id"],
                "version": 0,
                "minutes": 15,
            },
        ).status_code
        == 422
    )


def test_missing_estimate_and_procedure_change_affects_future_assignments(client):
    client.get("/me")
    with store.transaction() as db:
        db.run(
            "UPDATE service_procedures SET completion_minutes=NULL WHERE id='demo-ac'"
        )
    key, ref = repair_call(client)
    assert (
        client.get(f"/calls/{key}/result", headers=G).json()["completion_estimate"]
        is None
    )
    t = client.get(f"/tickets/{ref}", headers=M).json()
    assert (
        client.post(
            f"/tickets/{ref}/completion-estimate",
            headers=W,
            json={
                "key": str(uuid4()),
                "assignment_id": t["assignment"]["id"],
                "version": 0,
                "minutes": 12,
            },
        ).status_code
        == 200
    )
    with store.transaction() as db:
        db.run("UPDATE service_procedures SET completion_minutes=40 WHERE id='demo-ac'")
    assert (
        client.get(f"/calls/{key}/result", headers=G).json()["completion_estimate"][
            "remaining_minutes"
        ]
        == 12
    )


def test_sqlite_upgrade_keeps_old_records_and_no_fabricated_estimates(
    tmp_path, monkeypatch
):
    path = tmp_path / "old.sqlite"
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("PREVIEW_DB", str(path))
    with sqlite3.connect(path) as db:
        db.executescript(store.SCHEMA.read_text())
        db.executescript(store.SCHEMA.with_name("intelligence.sql").read_text())
        db.execute(
            "INSERT INTO service_procedures(id,hotel,category,department,title,body) VALUES('custom','other','Plumbing','Maintenance','Keep','Keep original')"
        )
    with store.transaction() as db:
        assert db.one(
            "SELECT body,completion_minutes FROM service_procedures WHERE id='custom'"
        ) == {"body": "Keep original", "completion_minutes": None}
        assert (
            db.one(
                "SELECT completion_minutes FROM service_procedures WHERE id='demo-ac'"
            )["completion_minutes"]
            == 15
        )
        assert not db.all("SELECT * FROM completion_estimates")
