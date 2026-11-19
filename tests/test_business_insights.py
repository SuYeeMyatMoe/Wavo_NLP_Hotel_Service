import json
from datetime import datetime, timezone

from hotel.business_insights import summarize

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


def ticket(key, created="2026-11-18T10:00:00+00:00", status="Assigned"):
    return {
        "id": key,
        "room": "305",
        "created": created,
        "status": status,
        "urgency": "Moderate",
        "department": "Maintenance",
        "owner": "worker",
        "analysis": json.dumps(
            {
                "extraction": {
                    "topic": "Air conditioning",
                    "service_label": "AC not cooling",
                }
            }
        ),
    }


def event(key, action, at="2026-11-18T11:00:00+00:00"):
    return {"ticket": key, "action": action, "created": at}


def test_deadlines_and_old_backlog_do_not_disappear_with_period():
    records = [
        ticket("old", "2026-10-01T10:00:00+00:00"),
        ticket("pending", status="Awaiting confirmation"),
        ticket("missing"),
    ]
    assignment = {
        "name": "Worker",
        "service_due": "2026-11-18T11:00:00+00:00",
        "ack_due": "2026-11-18T10:05:00+00:00",
        "acknowledged": "",
    }
    data = summarize(
        records,
        [],
        {
            "old": {"assignment": assignment},
            "pending": {"assignment": assignment, "awaiting_confirmation": True},
        },
        [],
        7,
        NOW,
    )
    assert data["tickets"] == 2 and data["unresolved"] == 3
    assert data["current"]["overdue_service"] == 1
    assert data["current"]["overdue_ack"] == 1
    assert data["current"]["missing_deadlines"] == 1
    assert data["current"]["awaiting_guest"] == 1
    assert data["current"]["attention"] == 2
    assert len(data["daily"]) == 7


def test_only_explicit_final_confirmation_counts_and_reopens_are_distinct():
    records = [
        ticket("confirmed", status="Resolved"),
        ticket("legacy", status="Closed"),
        ticket("reopened", status="In progress"),
    ]
    events = [
        event("confirmed", "Guest requested more help"),
        event("confirmed", "Guest requested more help"),
        event("confirmed", "Guest confirmed completion"),
        event("legacy", "Resolved"),
        event("reopened", "Guest confirmed completion"),
        event("reopened", "Guest requested more help"),
    ]
    data = summarize(records, events, {}, [], 30, NOW)
    assert data["resolution_sample"] == 1 and data["median_resolution_minutes"] == 60
    assert data["confirmed"] == 1 and data["confirmation_rate"] == 1 / 3
    assert data["missing_completion"] == 1 and data["reopened"] == 2
    assert sum(d["Confirmed"] for d in data["daily"]) == 1


def test_call_resolution_requires_guest_confirmation_no_ticket_or_staff():
    base = {
        "created": "2026-11-18T10:00:00+00:00",
        "direction": "Inbound",
        "status": "Ended",
        "outcome": "Resolved by guest",
        "ticket": "",
        "staff_id": "",
    }
    calls = [
        base,
        {**base, "ticket": "task"},
        {**base, "staff_id": "person"},
        {**base, "outcome": "No issue recorded"},
        {**base, "status": "Connected"},
    ]
    data = summarize([], [], {}, calls, 7, NOW)
    assert data["calls"] == {"total": 5, "ended": 4, "self_service": 1}
    assert data["confirmation_rate"] is None and data["resolution_minutes"] is None


def test_old_request_confirmation_appears_on_event_date_not_creation_cohort():
    data = summarize(
        [ticket("old", "2026-10-01T10:00:00+00:00", "Resolved")],
        [event("old", "Guest confirmed completion")],
        {},
        [],
        7,
        NOW,
    )
    assert data["tickets"] == 0 and data["resolution_sample"] == 0
    assert sum(d["Confirmed"] for d in data["daily"]) == 1
