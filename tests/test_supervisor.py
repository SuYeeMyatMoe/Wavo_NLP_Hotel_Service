from uuid import uuid4

from streamlit.testing.v1 import AppTest

from hotel.supervisor_ui import counts, filtered, table_row


def test_filters_preserve_rank_and_distinguish_confirmation():
    rows = [
        dict(
            id="a",
            room="305",
            department="Maintenance",
            status="Assigned",
            urgency="Urgent",
            created="2026-01-01",
            priority_rank=3,
            extraction={"topic": "Air conditioning"},
            assignment={"staff": "aung", "name": "Aung"},
            completion_estimate={"overdue": True, "remaining_minutes": 0},
        ),
        dict(
            id="b",
            room="402",
            department="Housekeeping",
            status="In progress",
            urgency="Low",
            created="2026-01-02",
            priority_rank=4,
            extraction={"topic": "Housekeeping"},
            assignment={"staff": "nora", "name": "Nora"},
        ),
        dict(
            id="c",
            room="512",
            department="Front Desk",
            status="Escalated",
            urgency="Unassessed",
            created="2026-01-03",
            priority_rank=1,
            extraction={},
        ),
        dict(
            id="d",
            room="305",
            department="Maintenance",
            status="Escalated",
            urgency="Moderate",
            created="2026-01-04",
            priority_rank=2,
            awaiting_confirmation=True,
            extraction={},
            assignment={"staff": "aung", "name": "Aung"},
            completion_estimate={"overdue": True, "remaining_minutes": 0},
        ),
        dict(
            id="e",
            room="402",
            department="Housekeeping",
            status="Resolved",
            urgency="Low",
            created="2026-01-05",
            extraction={},
        ),
    ]
    assert counts(rows) == {
        "Open tasks": 4,
        "Unassigned": 1,
        "In progress": 1,
        "Awaiting guest confirmation": 1,
    }
    assert [r["id"] for r in filtered(rows)] == ["c", "a", "b", "d"]
    match = filtered(
        rows,
        department="Maintenance",
        staff="aung",
        category="Air conditioning",
        search="305",
    )
    assert len(match) == 1 and match[0]["priority_rank"] == 3
    assert filtered(rows, department="Maintenance", staff="nora") == []
    assert filtered(rows, status="Completed")[0]["id"] == "e"
    assert filtered(rows, staff="Unassigned")[0]["id"] == "c"
    assert filtered(rows, status="Awaiting confirmation")[0]["id"] == "d"
    assert table_row(rows[0])["Expected completion"] == "Overdue"
    assert table_row(rows[1])["Expected completion"] == "Not set"
    assert table_row(rows[2])["Assigned staff"] == "Unassigned"
    assert table_row(rows[3])["Expected completion"] == "Awaiting guest confirmation"
    assert table_row(rows[3])["Rank"] is None
    assert table_row(rows[4])["Waiting (min)"] is None


def test_supervisor_overview_navigation_filters_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "supervisor.sqlite"))
    from hotel.ui_client import local
    from hotel import store

    client = local()
    refs = []
    for guest, text in [
        ("demo-guest", "The AC is not cooling. Please send maintenance."),
        ("demo-guest-402", "Please bring extra towels."),
        ("demo-guest-512", "Please help me with my bill."),
    ]:
        response = client.post(
            "/tickets",
            headers={"x-preview-user": guest},
            json={"text": text, "language": "en", "key": str(uuid4())},
        )
        assert response.status_code == 200, response.text
        refs.append(response.json()["id"])
    supervisor = {"x-preview-user": "demo-staff"}
    rows = client.get("/tickets", headers=supervisor).json()
    assert {t["department"] for t in rows} == {
        "Maintenance",
        "Housekeeping",
        "Front Desk",
    }
    assert all(t.get("assignment") for t in rows)
    worker = {"x-preview-user": rows[0]["assignment"]["staff"]}
    own = client.get("/tickets", headers=worker).json()
    assert all(t["assignment"]["staff"] == worker["x-preview-user"] for t in own)
    foreign_ref = next(
        t["id"] for t in rows if t["assignment"]["staff"] != worker["x-preview-user"]
    )
    assert client.get("/tickets/" + foreign_ref, headers=worker).status_code == 403
    guest_rows = client.get("/tickets", headers={"x-preview-user": "demo-guest"}).json()
    assert [t["id"] for t in guest_rows] == [refs[0]]

    ui = AppTest.from_file("../app.py", default_timeout=90)
    ui.session_state.preview_actor = "demo-staff"
    ui.session_state.destination = "My work"  # existing notification links
    ui.run()
    assert not ui.exception
    assert ui.session_state.nav == "All tasks"
    assert next(m.value for m in ui.metric if m.label == "Open tasks") == "3"
    ui.selectbox(key="admin_department").select("Maintenance").run()
    table = next(d.value for d in ui.dataframe if "Main problem" in d.value.columns)
    assert len(table) == 1 and table.iloc[0]["Department"] == "Maintenance"
    assert next(m.value for m in ui.metric if m.label == "Open tasks") == "3"
    ui.run()  # timer-equivalent rerender must retain filters
    assert ui.selectbox(key="admin_department").value == "Maintenance"
    ui.session_state.admin_open_ref = refs[0]
    ui.run()
    assert not ui.exception
    back = next(b for b in ui.button if b.label == "Back to all tasks")
    back.click().run()
    assert ui.selectbox(key="admin_department").value == "Maintenance"
    ui.text_input(key="admin_search").input("no-such-request").run()
    assert any("No tasks match" in i.value for i in ui.info)

    # Existing manager access remains hotel-scoped, including direct detail URLs.
    with store.transaction() as db:
        db.run("UPDATE tickets SET hotel='another-hotel' WHERE id=?", (refs[2],))
    assert refs[2] not in {
        t["id"] for t in client.get("/tickets", headers=supervisor).json()
    }
    assert client.get("/tickets/" + refs[2], headers=supervisor).status_code == 403
