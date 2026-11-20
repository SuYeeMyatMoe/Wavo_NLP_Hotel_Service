from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from hotel import store, operations, monitoring, notifications
from hotel.service import app

G = {"x-preview-user": "demo-guest"}
W = {"x-preview-user": "demo-maintenance"}


def test_hangup_blocks_late_work_report(client, monkeypatch):
    from threading import Event
    from hotel import work_assistant

    ref = create(client)
    with store.transaction() as db:
        db.run(
            "INSERT INTO work_sessions VALUES('work-test','demo','demo-maintenance','Connected',?)",
            (store.now(),),
        )
    entered, release = Event(), Event()

    def slow(_):
        entered.set()
        assert release.wait(10)
        return "complete", "test interpreter"

    monkeypatch.setattr(work_assistant, "interpret", slow)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(
            work_assistant.submit,
            "demo-maintenance",
            str(uuid4()),
            "I repaired the AC",
            ref,
            None,
            "work-test",
        )
        assert entered.wait(10)
        assert (
            client.post("/work-assistant/sessions/work-test/end", headers=W).status_code
            == 200
        )
        release.set()
        with pytest.raises(PermissionError, match="ended"):
            pending.result()
    with store.transaction() as db:
        assert not db.all("SELECT * FROM service_outcomes")


def test_provider_logs_and_staff_insights_are_scoped(client):
    import logging

    ref = create(client)
    record = logging.getLogger("google.genai.live").makeRecord(
        "google.genai.live",
        40,
        "test",
        1,
        "secret guest statement %s",
        ("private",),
        None,
    )
    assert "secret" not in record.getMessage() and "private" not in record.getMessage()
    assert client.get("/insights", headers=W).json()["tickets"] == 1
    other = {"x-preview-user": "demo-maintenance-2"}
    assert client.get("/insights", headers=other).json()["tickets"] == 0
    assert client.get(f"/tickets/{ref}", headers=other).status_code == 403
    assert client.get("/operations/settings", headers=W).status_code == 403


def test_supervisor_can_retry_after_roster_correction(client):
    client.get("/me")
    with store.transaction() as db:
        db.run("UPDATE staff_roster SET available=0")
    ref = create(client)
    assert client.get(f"/tickets/{ref}").json()["status"] == "Escalated"
    with store.transaction() as db:
        db.run("UPDATE staff_roster SET available=1 WHERE staff='demo-maintenance'")
    result = report(client, ref, "Retry assignment", {"x-preview-user": "demo-staff"})
    assert result.status_code == 200 and result.json()["changed"]
    assert client.get(f"/tickets/{ref}", headers=W).json()["status"] == "Assigned"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "hotel.sqlite"))
    return TestClient(app)


def create(client):
    r = client.post(
        "/tickets",
        headers=G,
        json={
            "text": "The AC is not cooling. My child is asleep. Please send maintenance without us having to move.",
            "language": "en",
            "key": str(uuid4()),
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def report(client, ref, text, who=W, uid=None):
    return client.post(
        "/work-assistant/turns",
        headers=who,
        json={"text": text, "ref": ref, "turn_id": uid or str(uuid4())},
    )


def test_done_click_and_optional_rating(client):
    ref = create(client)
    ticket = "/tickets/" + ref
    version = client.get(ticket, headers=W).json()["work"]["version"]
    body = {"version": version, "key": str(uuid4())}
    assert client.post(ticket + "/done", headers=G, json=body).status_code == 403
    assert (
        client.post(
            ticket + "/done", headers={"x-preview-user": "demo-staff"}, json=body
        ).status_code
        == 403
    )
    for _ in range(2):
        client.post(ticket + "/done", headers=W, json=body).raise_for_status()
    pending = client.get(ticket, headers=G).json()
    assert pending["awaiting_confirmation"]
    notifications = client.get("/notifications", headers=G).json()
    assert (
        sum(n["ticket"] == ref and n["kind"] == "confirmation" for n in notifications)
        == 1
    )
    path = ticket + "/feedback"
    assert client.post(path, headers=G, json={"value": "1/5"}).status_code == 403
    client.post(
        ticket + "/confirm",
        headers=G,
        json={"resolved": True, "version": pending["work"]["version"]},
    ).raise_for_status()
    assert client.get(ticket, headers=G).json()["rating"] is None
    for _ in range(2):
        client.post(path, headers=G, json={"value": "1/5"}).raise_for_status()
    result = client.get(ticket, headers=G).json()
    assert result["rating"] == 1
    assert sum(e["action"] == "Guest feedback: 1/5" for e in result["events"]) == 1
    assert client.get(ticket + "/result", headers=G).json()["rating"] == 1


def test_recorded_work_update_returns_recognized_words_and_allows_typed_retry(
    client, monkeypatch
):
    import base64
    import io
    import wave
    from hotel import languages

    ref = create(client)
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", ""))
        wav.writeframes(bytes(3200))
    body = {
        "ref": ref,
        "audio": base64.b64encode(stream.getvalue()).decode(),
        "turn_id": str(uuid4()),
    }
    monkeypatch.setattr(languages, "transcribe_auto", lambda *args: ("", "en"))
    silence = client.post("/work-assistant/turns", headers=W, json=body).json()
    assert not silence["changed"] and "Record again" in silence["reply"]
    monkeypatch.setattr(
        languages, "transcribe_auto", lambda *args: ("I started the repair", "en")
    )
    result = client.post("/work-assistant/turns", headers=W, json=body).json()
    assert (
        result["recognized"] == "I started the repair" and result["action"] == "start"
    )
    body.update(turn_id=str(uuid4()), text="I finished the repair")
    assert (
        client.post("/work-assistant/turns", headers=W, json=body).json()["action"]
        == "complete"
    )


def test_room_305_reopen_and_confirm(client):
    ref = create(client)
    t = client.get("/tickets/" + ref, headers=W).json()
    assert t["assignment"]["staff"] == "demo-maintenance"
    assert any(
        c["constraint"] == "Child sleeping"
        for c in t["work"]["extraction"]["constraints"]
    )
    assert (
        client.get("/tickets", headers={"x-preview-user": "demo-maintenance-2"}).json()
        == []
    )
    assert client.get("/notifications", headers=W).json()[0]["kind"] == "assignment"
    assert report(client, ref, "I'm starting the AC repair in Room 305").json()[
        "changed"
    ]
    uid = str(uuid4())
    r = report(
        client, ref, "I repaired the AC in Room 305 and checked the cooling.", uid=uid
    )
    assert r.status_code == 200, r.text
    assert r.json()["lifecycle"]["state"] == "awaiting_confirmation"
    assert (
        report(
            client,
            ref,
            "I repaired the AC in Room 305 and checked the cooling.",
            uid=uid,
        ).json()
        == r.json()
    )
    version = client.get(f"/tickets/{ref}/state", headers=G).json()["version"]
    assert (
        client.post(
            f"/tickets/{ref}/confirm",
            headers=G,
            json={"version": version, "resolved": False},
        ).status_code
        == 200
    )
    with store.transaction() as db:
        assignment = operations.snapshot(db, ref)["assignment"]
        assert (
            db.one("SELECT COUNT(*) AS n FROM task_assignments WHERE ticket=?", (ref,))[
                "n"
            ]
            == 2
        )
    who = {"x-preview-user": assignment["staff"]}
    assert report(client, ref, "I repaired the AC and checked cooling", who).json()[
        "changed"
    ]
    version = client.get(f"/tickets/{ref}/state", headers=G).json()["version"]
    assert (
        client.post(
            f"/tickets/{ref}/confirm",
            headers=G,
            json={"version": version, "resolved": True},
        ).json()["status"]
        == "Resolved"
    )
    assert (
        client.post(
            f"/tickets/{ref}/confirm",
            headers=G,
            json={"version": version, "resolved": True},
        ).status_code
        == 422
    )


def test_ambiguous_negative_and_unauthorized_reports(client):
    ref = create(client)
    assert not report(client, ref, "I will repair the AC").json()["changed"]
    assert not report(client, ref, "I repaired the AC", G).status_code == 200
    assert not report(
        client, ref, "I repaired it", {"x-preview-user": "demo-maintenance-2"}
    ).json()["changed"]
    assert not report(client, ref, "I repaired the AC in Room 999").json()["changed"]
    r = client.post(
        "/work-assistant/turns",
        headers=W,
        json={
            "turn_id": str(uuid4()),
            "ref": ref,
            "version": 999,
            "text": "I repaired the AC",
        },
    )
    assert r.status_code == 422


def test_reminder_reassignment_and_no_reassign_in_progress(client):
    ref = create(client)
    with store.transaction() as db:
        a = operations.snapshot(db, ref)["assignment"]
    monitoring.tick(a["ack_due"])
    monitoring.tick(operations.later(a["ack_due"], 11))
    with store.transaction() as db:
        b = operations.snapshot(db, ref)["assignment"]
        assert b["staff"] != a["staff"] and b["attempt"] == 2
    who = {"x-preview-user": b["staff"]}
    assert report(client, ref, "I am starting work", who).json()["changed"]
    monitoring.tick(operations.later(b["ack_due"], 11))
    with store.transaction() as db:
        assert operations.snapshot(db, ref)["assignment"]["id"] == b["id"]
    monitoring.tick(b["service_due"])
    with store.transaction() as db:
        assert operations.snapshot(db, ref)["lifecycle"]["state"] == "escalated"
        assert operations.snapshot(db, ref)["assignment"]["id"] == b["id"]


def test_concurrent_dispatch_capacity_and_notification_retry(client):
    client.get("/me")
    with store.transaction() as db:
        db.run("UPDATE staff_roster SET capacity=1")
    with ThreadPoolExecutor(max_workers=3) as pool:
        refs = list(pool.map(lambda _: create(client), range(3)))
    with store.transaction() as db:
        assert (
            db.one(
                "SELECT COUNT(*) AS n FROM task_assignments a JOIN staff_roster r ON r.staff=a.staff WHERE a.active=1 AND r.department='Maintenance'"
            )["n"]
            == 2
        )
        assert (
            db.one(
                "SELECT COUNT(*) AS n FROM task_assignments a JOIN staff_roster r ON r.staff=a.staff WHERE a.active=1 AND r.department='Front Desk'"
            )["n"]
            == 1
        )
        first = db.one("SELECT * FROM operation_jobs ORDER BY due,id LIMIT 1")

    def fail(_):
        raise RuntimeError("secret body must not be persisted")

    notifications.publish_one(at=first["due"], transport=fail)
    with store.transaction() as db:
        n = db.one("SELECT * FROM notifications WHERE id=?", (first["id"],))
        assert n["delivery"] == "failed" and not n["published"]
        assert (
            "secret"
            not in db.one(
                "SELECT error FROM operation_jobs WHERE id=?", (first["id"],)
            )["error"]
        )
    for _ in range(20):
        if not notifications.publish_one(
            at=operations.later(first["due"], 30), transport=lambda _: None
        ):
            break
    with store.transaction() as db:
        assert (
            db.one("SELECT delivery FROM notifications WHERE id=?", (first["id"],))[
                "delivery"
            ]
            == "published"
        )
    assert len(refs) == 3


def test_privacy_and_ended_worker_session(client, monkeypatch):
    monkeypatch.setenv("LIVEKIT_API_SECRET", "unit-test-secret")
    from hotel.worker_auth import worker_token

    key = client.post("/calls", headers=G).json()["id"]
    path = f"/internal/calls/{key}/tools/"
    assert (
        client.post(path + "connect", json={"participant": "demo-guest"}).status_code
        == 403
    )
    h = {"x-worker-token": worker_token(key)}
    assert (
        client.post(
            path + "connect", headers=h, json={"participant": "someone-else"}
        ).status_code
        == 403
    )
    client.post(
        path + "spoken", headers=h, json={"text": "private speech", "turn_id": "a"}
    )
    with store.transaction() as db:
        assert not db.all("SELECT * FROM call_transcripts")
    client.post(f"/calls/{key}/end", headers=G)
    assert (
        client.post(
            path + "spoken", headers=h, json={"text": "late speech", "turn_id": "b"}
        ).status_code
        == 403
    )


def test_call_ended_before_agreement_never_assigns_physical_work(client):
    key = client.post("/calls", headers=G).json()["id"]
    result = client.post(
        f"/calls/{key}/turn",
        headers=G,
        json={"turn_id": str(uuid4()), "text": "The air conditioner is broken."},
    )
    assert result.status_code == 200 and result.json()["outcome"] == "Service offered"
    client.post(f"/calls/{key}/end", headers=G).raise_for_status()
    with store.transaction() as db:
        assert not db.all(
            "SELECT a.* FROM task_assignments a JOIN staff_roster r ON r.staff=a.staff WHERE r.department IN ('Maintenance','Housekeeping')"
        )
        t = db.one("SELECT * FROM tickets")
        assert t["status"] == "Assigned"
        assert operations.snapshot(db, t["id"])["assignment"]
        assert "agreement" in operations.snapshot(db, t["id"])["lifecycle"]["reason"]


def test_additive_migration_preserves_owned_work_and_closed_history(
    tmp_path, monkeypatch
):
    import sqlite3

    monkeypatch.setenv("HOTEL_MODE", "preview")
    path = tmp_path / "upgrade.sqlite"
    monkeypatch.setenv("PREVIEW_DB", str(path))
    with sqlite3.connect(path) as conn:
        conn.executescript(store.SCHEMA.read_text())
        conn.executescript(store.SCHEMA.with_name("work.sql").read_text())
        conn.execute(
            "INSERT INTO profiles(id,hotel,role) VALUES('old-worker','demo','staff')"
        )
        for ref, status in [
            ("old-owned", "In progress"),
            ("old-open", "Assigned"),
            ("old-closed", "Closed"),
        ]:
            conn.execute(
                "INSERT INTO tickets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ref,
                    "demo",
                    "old-worker",
                    ref,
                    None,
                    "305",
                    "Staff analysis",
                    "AC broken",
                    "Urgent",
                    "Maintenance",
                    "Worker",
                    status,
                    "{}",
                    store.now(),
                ),
            )
        conn.execute(
            "INSERT INTO ticket_work(ticket,owner) VALUES('old-owned','old-worker')"
        )
    with store.transaction() as db:
        assert (
            db.one("SELECT status FROM tickets WHERE id='old-owned'")["status"]
            == "In progress"
        )
        assert (
            db.one("SELECT owner FROM ticket_work WHERE ticket='old-owned'")["owner"]
            == "old-worker"
        )
        assert (
            db.one("SELECT status FROM tickets WHERE id='old-open'")["status"]
            == "Escalated"
        )
        assert (
            db.one("SELECT status FROM tickets WHERE id='old-closed'")["status"]
            == "Closed"
        )
        assert not db.all("SELECT * FROM task_assignments")


def test_late_guest_confirmation_remains_available_after_escalation(client):
    ref = create(client)
    report(client, ref, "I repaired the AC").raise_for_status()
    with store.transaction() as db:
        at = operations.snapshot(db, ref)["lifecycle"]["updated"]
    monitoring.tick(operations.later(at, 1441))
    item = client.get(f"/tickets/{ref}", headers=G).json()
    assert item["status"] == "Escalated" and item["awaiting_confirmation"]
    result = client.post(
        f"/tickets/{ref}/confirm",
        headers=G,
        json={"version": item["work"]["version"], "resolved": True},
    )
    assert result.status_code == 200 and result.json()["status"] == "Resolved"
