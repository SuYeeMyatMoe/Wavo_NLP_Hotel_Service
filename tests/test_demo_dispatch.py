from uuid import uuid4

import pytest
from hotel import store, operations
from hotel.nlp import analyze


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "preferred.sqlite"))
    monkeypatch.setenv("WAVO_DEMO_MAINTENANCE_STAFF_ID", "demo-maintenance")
    monkeypatch.setenv("WAVO_DEMO_MAINTENANCE_ACK_MINUTES", "0")
    with store.transaction() as connection:
        yield connection


def create(db, text="The toilet is blocked."):
    analysis = analyze(text)
    analysis["service_agreement"] = True
    ticket = store.create(
        db,
        store.profile(db, "demo-guest"),
        analysis,
        str(uuid4()),
        "Guest request",
        "305",
    )
    return ticket["id"], operations.snapshot(db, ticket["id"])["assignment"]


def test_new_maintenance_requests_prefer_aung_despite_higher_load(db):
    first, owner = create(db)
    second, next_owner = create(db)
    assert first != second
    assert owner["staff"] == next_owner["staff"] == "demo-maintenance"
    assert "demo Maintenance preference" in next_owner["reason"]


@pytest.mark.parametrize(
    "condition", ["unavailable", "off_shift", "missing_skill", "full"]
)
def test_preference_never_bypasses_eligibility(db, condition):
    if condition == "unavailable":
        db.run("UPDATE staff_roster SET available=0 WHERE staff='demo-maintenance'")
    elif condition == "off_shift":
        db.run(
            "UPDATE staff_roster SET shift_end='2020-01-02' WHERE staff='demo-maintenance'"
        )
    elif condition == "missing_skill":
        db.run("UPDATE staff_roster SET skills='[]' WHERE staff='demo-maintenance'")
    else:
        db.run("UPDATE staff_roster SET capacity=1 WHERE staff='demo-maintenance'")
        create(db)
    _, owner = create(db)
    assert owner["staff"] == "demo-maintenance-2"


def test_other_departments_and_safety_still_route_normally(db):
    _, owner = create(db, "Please bring extra towels.")
    assert owner["staff"] == "demo-housekeeping"
    _, owner = create(db, "I smell gas in my room.")
    assert owner["staff"] == "demo-staff"


def test_disabled_preference_restores_balancing(db, monkeypatch):
    monkeypatch.delenv("WAVO_DEMO_MAINTENANCE_STAFF_ID")
    _, first = create(db)
    _, second = create(db)
    assert first["staff"] != second["staff"]


def test_existing_assignment_and_replacement_exclusion_are_preserved(db):
    ref, old = create(db)
    assert operations.dispatch(db, ref)["id"] == old["id"]
    db.run("UPDATE task_assignments SET active=0 WHERE id=?", (old["id"],))
    new = operations.dispatch(db, ref, exclude=["demo-maintenance"])
    assert new["staff"] == "demo-maintenance-2"


def test_demo_timeout_is_scoped_to_selected_maintenance_worker(db, monkeypatch):
    monkeypatch.setenv("WAVO_DEMO_MAINTENANCE_ACK_MINUTES", "30")
    policy = {"ack_minutes": 2, "service_minutes": 15}
    assert operations.assignment_windows(
        "demo", "Maintenance", "demo-maintenance", policy
    ) == (30, 61)
    for hotel, department, staff in [
        ("demo", "Maintenance", "demo-maintenance-2"),
        ("demo", "Front Desk", "demo-maintenance"),
        ("another-hotel", "Maintenance", "demo-maintenance"),
    ]:
        assert operations.assignment_windows(hotel, department, staff, policy) == (
            2,
            15,
        )
    _, assignment = create(db)
    assert assignment["ack_due"] == operations.later(assignment["assigned"], 30)
    assert assignment["service_due"] >= operations.later(assignment["assigned"], 61)


def test_demo_acknowledgment_reminder_and_replacement_windows(tmp_path, monkeypatch):
    from hotel import monitoring

    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "deadline.sqlite"))
    monkeypatch.setenv("WAVO_DEMO_MAINTENANCE_STAFF_ID", "demo-maintenance")
    monkeypatch.setenv("WAVO_DEMO_MAINTENANCE_ACK_MINUTES", "30")
    with store.transaction() as db:
        ref, assignment = create(db)
    at = assignment["assigned"]
    for minutes in (5, 29):
        monitoring.tick(operations.later(at, minutes))
        with store.transaction() as db:
            current = operations.snapshot(db, ref)
            assert current["assignment"]["staff"] == "demo-maintenance"
            assert not current["assignment"]["reminded"]
            assert current["lifecycle"]["state"] == "assigned"
    monitoring.tick(operations.later(at, 30))
    monitoring.tick(operations.later(at, 59))
    with store.transaction() as db:
        current = operations.snapshot(db, ref)["assignment"]
        assert current["staff"] == "demo-maintenance"
        assert current["reminded"] == operations.later(at, 30)
    monitoring.tick(operations.later(at, 60))
    with store.transaction() as db:
        assert (
            operations.snapshot(db, ref)["assignment"]["staff"] == "demo-maintenance-2"
        )
