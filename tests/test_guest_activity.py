import json
import sqlite3
from uuid import uuid4

from hotel import store
from hotel.guest_activity import duration
import pytest
from fastapi.testclient import TestClient
from hotel.service import app
from test_completion import repair_call, G, M


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "activity.sqlite"))
    return TestClient(app)


def test_calls_and_requests_group_without_exposing_transcripts(client):
    key, ref = repair_call(client)
    text = client.post(
        "/tickets",
        headers=G,
        json={
            "text": "Please bring extra towels",
            "language": "en",
            "key": str(uuid4()),
        },
    ).json()["id"]
    with store.transaction() as db:
        # A follow-up call is another conversation about the same service record.
        db.run(
            "INSERT INTO calls(id,hotel,guest,ticket,direction,status,operator,created,transcript) VALUES(?,?,?,?,?,'Connected','Test',?,?)",
            (
                "followup",
                "demo",
                "demo-guest",
                ref,
                "Inbound",
                store.now(),
                "PRIVATE TRANSCRIPT MARKER",
            ),
        )
        db.run("UPDATE calls SET status='Ended' WHERE id='followup'")
        db.run(
            "INSERT INTO calls(id,hotel,guest,ticket,direction,status,operator,created) VALUES('text-callback','demo','demo-guest',?,'Outbound','Connected','Test',?)",
            (text, store.now()),
        )
        db.run("UPDATE calls SET status='Ended' WHERE id='text-callback'")
    r = client.get("/guest/activity", headers=G)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["total"] == 2
    call = next(row for row in result["items"] if row["ticket"] == ref)
    assert call["source"] == "Call" and call["reference"] == key
    assert len(call["calls"]) == 2 and call["duration"]["seconds"] is not None
    assert call["completion_estimate"]["remaining_minutes"] == 15
    assert (
        next(row for row in result["items"] if row["ticket"] == text)["source"]
        == "Text"
    )
    text_row = next(row for row in result["items"] if row["ticket"] == text)
    assert text_row["reference"] == text and len(text_row["calls"]) == 1
    assert "PRIVATE TRANSCRIPT" not in json.dumps(result)
    assert "private-marker" not in json.dumps(result)
    linked = client.get(f"/guest/requests/{ref}/calls", headers=G)
    assert len(linked.json()) == 2
    assert (
        client.get("/guest/activity", headers=G, params={"search": key}).json()["total"]
        == 1
    )
    assert (
        client.get("/guest/activity", headers=G, params={"source": "Text"}).json()[
            "total"
        ]
        == 1
    )
    assert (
        client.get(
            "/guest/activity", headers=G, params={"search": "%' OR 1=1 --"}
        ).json()["total"]
        == 0
    )
    one = client.get("/guest/activity", headers=G, params={"page_size": 1}).json()
    two = client.get(
        "/guest/activity", headers=G, params={"page_size": 1, "page": 2}
    ).json()
    assert one["items"][0]["id"] != two["items"][0]["id"]


def test_timing_is_anchored_to_connection_and_retries_are_idempotent(client):
    client.get("/me", headers=G)
    with store.transaction() as db:
        db.run(
            "INSERT INTO calls(id,hotel,guest,direction,status,operator,created) VALUES('timed','demo','demo-guest','Inbound','Ringing','Test',?)",
            (store.now(),),
        )
        assert (
            db.one("SELECT connected_at FROM call_timing WHERE call_id='timed'")[
                "connected_at"
            ]
            is None
        )
        db.run("UPDATE calls SET status='Connected' WHERE id='timed'")
        db.run(
            "UPDATE call_timing SET connected_at='2026-11-18T10:00:00+00:00' WHERE call_id='timed'"
        )
        db.run("UPDATE calls SET status='Connected' WHERE id='timed'")
        db.run("UPDATE calls SET status='Ended' WHERE id='timed'")
        first = db.one("SELECT * FROM call_timing WHERE call_id='timed'")
        db.run("UPDATE calls SET status='Ended' WHERE id='timed'")
        assert db.one("SELECT * FROM call_timing WHERE call_id='timed'") == first
        assert first["connected_at"] == "2026-11-18T10:00:00+00:00"
    assert duration(
        {
            "timing_id": "timed",
            "connected_at": first["connected_at"],
            "ended_at": "2026-11-18T10:02:15+00:00",
        }
    ) == {"seconds": 135, "label": "2m 15s"}
    assert (
        duration(
            {
                "timing_id": "timed",
                "connected_at": first["connected_at"],
                "ended_at": "2026-11-18T10:02:15+00:00",
                "end_reason": "timeout",
            }
        )["label"]
        == "About 2m 15s"
    )
    assert (
        duration({"timing_id": "missed", "ended_at": store.now()})["label"]
        == "Not connected"
    )


def test_standalone_resolved_call_voice_message_and_permissions(client):
    key = client.post("/calls", headers=G).json()["id"]
    for text in ["The Wi-Fi does not connect.", "Yes, it works now."]:
        client.post(
            f"/calls/{key}/turn",
            headers=G,
            json={"text": text, "turn_id": str(uuid4())},
        ).raise_for_status()
    client.post(f"/calls/{key}/end", headers=G).raise_for_status()
    result = client.get("/guest/activity", headers=G).json()
    assert result["total"] == 1 and result["items"][0]["ticket"] is None
    assert result["items"][0]["status"] == "Resolved during your call"
    assert client.get("/guest/activity", headers=M).status_code == 403
    assert (
        client.get(
            "/guest/activity", headers={"x-preview-user": "demo-guest-402"}
        ).json()["total"]
        == 0
    )
    ref = client.post(
        "/tickets",
        headers=G,
        json={
            "text": "Please bring clean towels",
            "language": "en",
            "key": str(uuid4()),
        },
    ).json()["id"]
    with store.transaction() as db:
        db.run("UPDATE tickets SET source='Voice message' WHERE id=?", (ref,))
        db.run("UPDATE profiles SET hotel='other' WHERE id='demo-guest-402'")
    voice = client.get(
        "/guest/activity", headers=G, params={"source": "Voice message"}
    ).json()["items"][0]
    assert voice["reference"] == ref and voice["duration"]["label"] == "—"
    assert (
        client.get(
            f"/guest/requests/{ref}/calls", headers={"x-preview-user": "demo-guest-402"}
        ).status_code
        == 403
    )


def test_history_expires_unanswered_calls(client):
    client.get("/me", headers=G)
    with store.transaction() as db:
        db.run(
            "INSERT INTO calls(id,hotel,guest,direction,status,operator,created) VALUES('missed','demo','demo-guest','Inbound','Ringing','Test','2000-01-01T00:00:00+00:00')"
        )
    missed = client.get(
        "/guest/activity", headers=G, params={"state": "Ended without request"}
    ).json()["items"][0]
    assert (
        missed["status"] == "Missed" and missed["duration"]["label"] == "Not connected"
    )


def test_upgrade_does_not_invent_historical_duration(tmp_path, monkeypatch):
    path = tmp_path / "old.sqlite"
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("PREVIEW_DB", str(path))
    with sqlite3.connect(path) as db:
        db.executescript(store.SCHEMA.read_text())
        db.execute(
            "INSERT INTO profiles(id,hotel,role) VALUES('old-guest','old','guest')"
        )
        db.execute(
            "INSERT INTO calls(id,hotel,guest,direction,status,operator,created) VALUES('old-call','old','old-guest','Inbound','Ended','Test','2026-01-01')"
        )
    with store.transaction() as db:
        assert db.one("SELECT * FROM call_timing WHERE call_id='old-call'") is None
    assert duration({})["label"] == "Unavailable"
