from streamlit.testing.v1 import AppTest


def button(app, label):
    return next(b for b in app.button if b.label == label)


def staff_demo(timeout=90):
    app = AppTest.from_file("../app.py", default_timeout=timeout)
    app.query_params["login"] = "staff"
    app.run()
    button(app, "Use demo account").click().run()
    button(app, "Sign in").click().run()
    return app


def test_presentation_and_guest_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "ui.sqlite"))
    from hotel.ui_client import local
    from uuid import uuid4

    ref = (
        local()
        .post(
            "/tickets",
            headers={"x-preview-user": "demo-guest"},
            json={
                "text": "The air conditioner is broken.",
                "language": "en",
                "key": str(uuid4()),
            },
        )
        .json()["id"]
    )
    staff = staff_demo()
    assert not staff.exception
    assert all(
        b.label not in {"Start work", "Submit outcome", "Create and assign"}
        for b in staff.button
    )
    queue = next(d.value for d in staff.dataframe if "Main problem" in d.value.columns)
    assert queue.iloc[0]["Main problem"] == "AC not working"
    assert queue.iloc[0]["Action"] == "Open request"
    # AppTest has no ButtonColumn click API; the browser check covers the actual
    # cell button. Exercise the same queued navigation intent here.
    staff.session_state.work_open_ref = ref
    staff.run()
    next(w for w in staff.text_area if w.label == "Your work update").input(
        "I repaired the AC in Room 305 and checked cooling."
    )
    button(staff, "Send update").click().run()
    assert not staff.exception
    guest = AppTest.from_file("../app.py", default_timeout=60)
    guest.session_state.preview_actor = "demo-guest"
    guest.session_state.destination = "My requests"
    guest.session_state.selected_ticket = ref
    guest.run()
    assert not guest.exception
    button(guest, "Yes, fixed").click().run()
    assert any("Resolved" in c.value for c in guest.caption)
    assert any(b.label == "Send feedback" for b in guest.button)


def test_edit_invalidates_prediction(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "ui.sqlite"))
    app = staff_demo()
    app.session_state.destination = "NLP Intelligence"
    app.run()
    assert all("What-if" not in widget.options for widget in app.get("button_group"))
    button(app, "Analyze").click().run()
    app.text_area(key="complaint").input("Missing towels in room 305").run()
    assert not app.exception
    assert all(b.label != "Create ticket" for b in app.button)


def test_staff_insights_and_single_call_history(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "insights.sqlite"))
    app = staff_demo()
    app.session_state.destination = "Insights"
    app.run()
    assert not app.exception
    assert any(m.label == "Need attention" for m in app.metric)
    app.session_state.destination = "Calls"
    app.run()
    assert not app.exception
    assert sum(s.value == "Call history" for s in app.subheader) == 1
    assert all(
        getattr(widget, "label", "") != "Calls view"
        for widget in app.get("button_group")
    )


def test_guest_can_clarify_the_existing_request(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "clarify-ui.sqlite"))
    from hotel.ui_client import local
    from uuid import uuid4

    headers = {"x-preview-user": "demo-guest"}
    ref = (
        local()
        .post(
            "/tickets",
            headers=headers,
            json={
                "text": "Please help with my request",
                "language": "en",
                "key": str(uuid4()),
            },
        )
        .json()["id"]
    )
    guest = AppTest.from_file("../app.py", default_timeout=60)
    guest.session_state.preview_actor = "demo-guest"
    guest.session_state.destination = "My requests"
    guest.session_state.selected_ticket = ref
    guest.run()
    assert not guest.exception
    next(w for w in guest.text_area if w.label == "What still needs help?").input(
        "The AC is not cooling. Please send maintenance."
    )
    next(
        w for w in guest.checkbox if w.label == "Please arrange service for this issue"
    ).check()
    button(guest, "Update this request").click().run()
    assert not guest.exception
    assert not any(b.label == "Update this request" for b in guest.button)
    assert any("Maintenance" in i.value for i in guest.markdown)
    assert len(local().get("/tickets", headers=headers).json()) == 1


def test_post_call_receipt_tracks_and_confirms_same_request(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "receipt-ui.sqlite"))
    from hotel.ui_client import local
    from uuid import uuid4

    headers = {"x-preview-user": "demo-guest"}
    key = local().post("/calls", headers=headers).json()["id"]
    for text in [
        "The AC is not cooling. My child is asleep.",
        "Yes, send maintenance.",
    ]:
        result = local().post(
            f"/calls/{key}/turn",
            headers=headers,
            json={"text": text, "turn_id": str(uuid4())},
        )
        result.raise_for_status()
    ref = result.json()["ticket"]
    local().post(f"/calls/{key}/end", headers=headers).raise_for_status()
    guest = AppTest.from_file("../app.py", default_timeout=90)
    guest.session_state.preview_actor = "demo-guest"
    guest.session_state.destination = "Reception"
    guest.session_state.completed_call = key
    guest.run()
    assert not guest.exception
    assert any("15 minutes" in s.value for s in guest.subheader)
    assert any("Your request is assigned" in s.value for s in guest.subheader)
    # Timer and widget reruns must not repeat a slow finalized-result fetch.
    from hotel import post_call_ui

    original_request = post_call_ui.request
    reads = []

    def counted(method, path, **kwargs):
        if path.endswith("/result"):
            reads.append(path)
        return original_request(method, path, **kwargs)

    monkeypatch.setattr(post_call_ui, "request", counted)
    guest.run()
    assert not reads
    button(guest, "Refresh status").click().run()
    assert reads == [f"/calls/{key}/result"]
    guest.button(key="receipt_track_" + key).click().run()
    assert guest.session_state.selected_ticket == ref
    assert not any(k[0] == "receipt" for k in guest.session_state._api_cache)
    guest.session_state.destination = "Reception"
    guest.session_state.completed_call = key
    local().post(
        "/work-assistant/turns",
        headers={"x-preview-user": "demo-maintenance"},
        json={
            "ref": ref,
            "text": "I repaired the AC and checked cooling",
            "turn_id": str(uuid4()),
        },
    ).raise_for_status()
    guest.run()
    assert any("Awaiting your confirmation" in s.value for s in guest.subheader), [
        s.value for s in guest.subheader
    ]
    assert not any("Expected completion" in s.value for s in guest.subheader)
    button(guest, "Yes, fixed").click().run()
    assert any(s.value == "Resolved" for s in guest.subheader)
    button(guest, "Close").click().run()
    assert not guest.exception
    assert "completed_call" not in guest.session_state


def test_handoff_popup_survives_unavailable_home_progress(tmp_path, monkeypatch):
    from uuid import uuid4
    import streamlit as st
    from hotel import guest_history_ui
    from hotel.ui_client import local

    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "handoff-popup.sqlite"))
    headers = {"x-preview-user": "demo-guest"}
    key = local().post("/calls", headers=headers).json()["id"]
    local().post(
        f"/calls/{key}/turn",
        headers=headers,
        json={"text": "I want to speak with a person.", "turn_id": str(uuid4())},
    ).raise_for_status()
    local().post(f"/calls/{key}/end", headers=headers).raise_for_status()

    def unavailable(*args):
        st.error("Progress refresh unavailable")
        st.stop()

    monkeypatch.setattr(guest_history_ui, "home_progress", unavailable)
    guest = AppTest.from_file("../app.py", default_timeout=90)
    guest.session_state.preview_actor = "demo-guest"
    guest.session_state.completed_call = key
    guest.run()
    assert not guest.exception
    assert any("Reception is following up" in s.value for s in guest.subheader)
    assert button(guest, "Track request")
    button(guest, "Close").click().run()
    assert not guest.exception
    assert "completed_call" not in guest.session_state
    assert guest.session_state.nav == "My requests"


def test_summary_ok_keeps_work_open_and_unified_history(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "ack-ui.sqlite"))
    from hotel.ui_client import local
    from test_completion import repair_call, G

    key, ref = repair_call(local())
    guest = AppTest.from_file("../app.py", default_timeout=90)
    guest.session_state.preview_actor = "demo-guest"
    guest.session_state.completed_call = key
    guest.run()
    button(guest, "Close").click().run()
    assert not guest.exception
    assert "completed_call" not in guest.session_state
    assert guest.session_state.nav == "My requests"
    assert guest.session_state.acknowledged_request == ref
    assert local().get(f"/tickets/{ref}", headers=G).json()["status"] == "Assigned"
    assert not guest.session_state.get("selected_ticket")
    guest.segmented_control(key="nav").set_value("My requests").run()
    assert not guest.exception
    table = next(d.value for d in guest.dataframe if "Reference" in d.value.columns)
    assert len(table) == 1 and key[:12] in table.iloc[0]["Reference"]
    assert "Call duration" in table.columns and "Expected completion" in table.columns
    assert "Calls" not in guest.segmented_control(key="nav").options

    # A selected request must never replace the guest's complete history table.
    from uuid import uuid4

    second = (
        local()
        .post(
            "/tickets",
            headers=G,
            json={
                "text": "Please bring extra towels",
                "language": "en",
                "key": str(uuid4()),
            },
        )
        .json()["id"]
    )
    guest.session_state.selected_ticket = ref
    guest.session_state.destination = "My requests"
    guest.run()
    assert not guest.exception
    table = next(d.value for d in guest.dataframe if "Reference" in d.value.columns)
    assert len(table) == 2
    assert "Selected" in table["Action"].values
    assert any(second[:12] in r for r in table["Reference"])
    assert any(s.value.startswith("Room 305") for s in guest.subheader)
    button(guest, "Close details").click().run()
    assert not guest.exception
    assert guest.session_state.get("selected_ticket") is None
    table = next(d.value for d in guest.dataframe if "Reference" in d.value.columns)
    assert len(table) == 2 and all(table["Action"] == "Open")


def test_text_request_popup_uses_service_estimate_and_preserves_history(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "text-popup.sqlite"))
    from hotel.ui_client import local
    from hotel import store
    from test_completion import repair_call, G

    _, first = repair_call(local())
    with store.transaction() as db:
        db.run(
            "UPDATE service_procedures SET completion_minutes=8 WHERE id='demo-housekeeping'"
        )
    guest = AppTest.from_file("../app.py", default_timeout=90)
    guest.session_state.preview_actor = "demo-guest"
    guest.session_state.destination = "Reception"
    guest.run()
    guest.text_area(key="guest_text").input("Please bring extra towels.").run()
    button(guest, "Send request").click().run()
    assert not guest.exception
    ref = guest.session_state.request_receipt
    assert ref != first
    assert any("8 minutes" in s.value for s in guest.subheader)
    assert any("Nora" in m.value for m in guest.markdown)
    result = local().get(f"/tickets/{ref}/result", headers=G)
    assert (
        result.status_code == 200
        and result.json()["outcome"] == "Your request is assigned"
    )
    assert (
        local()
        .get(f"/tickets/{ref}/result", headers={"x-preview-user": "demo-guest-402"})
        .status_code
        == 403
    )
    assert (
        local()
        .get(f"/tickets/{ref}/result", headers={"x-preview-user": "demo-maintenance"})
        .status_code
        == 403
    )
    assert "transcript" not in result.json()
    button(guest, "Close").click().run()
    assert not guest.exception
    assert "request_receipt" not in guest.session_state
    assert guest.session_state.nav == "My requests"
    table = next(d.value for d in guest.dataframe if "Reference" in d.value.columns)
    assert len(table) == 2
    assert local().get(f"/tickets/{ref}", headers=G).json()["status"] == "Assigned"


def test_service_shortcut_survives_login_without_submitting(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("CONCIERGE_MODE", "local")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "shortcut-ui.sqlite"))
    guest = AppTest.from_file("../app.py", default_timeout=90)
    guest.query_params["login"] = "guest"
    guest.query_params["service"] = "wifi"
    guest.run()
    button(guest, "Use demo account").click().run()
    button(guest, "Sign in").click().run()
    assert not guest.exception
    assert "Wi-Fi" in guest.text_area(key="guest_text").value
    from hotel.ui_client import local

    assert (
        local().get("/tickets", headers={"x-preview-user": "demo-guest"}).json() == []
    )


def test_work_workspace_and_guest_recording_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "desk.sqlite"))
    staff = staff_demo()
    assert not staff.exception
    assert staff.session_state.preview_actor == "demo-maintenance"
    assert any(t.value == "My work" for t in staff.title)
    button(staff, "Switch to guest").click().run()
    button(staff, "Use demo account").click().run()
    button(staff, "Sign in").click().run()
    assert any(b.label == "Call AI Reception" for b in staff.button)
    staff.session_state.message_mode = "Voice message"
    staff.run()
    assert not staff.exception and staff.get("audio_input")
    staff.selectbox(key="guest_locale").set_value("hi").run()
    assert not staff.exception and staff.get("audio_input")


def test_demo_login_validates_credentials_and_role(monkeypatch, tmp_path):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "login.sqlite"))
    app = AppTest.from_file("../app.py", default_timeout=90)
    app.query_params["login"] = "guest"
    app.run()
    button(app, "Sign in").click().run()
    assert app.error and not any(b.label == "Call AI Reception" for b in app.button)
    app.text_input(key="demo_email_guest").input("staff@wavo.demo")
    app.text_input(key="demo_password_guest").input("Staff123!")
    button(app, "Sign in").click().run()
    assert app.error and "preview_actor" not in app.session_state
    button(app, "Use demo account").click().run()
    assert app.text_input(key="demo_email_guest").value == "guest@wavo.demo"
    assert app.text_input(key="demo_password_guest").value == "Guest305!"
    assert "preview_actor" not in app.session_state
    button(app, "Sign in").click().run()
    assert not app.exception and app.session_state.preview_actor == "demo-guest"
    button(app, "Sign out").click().run()
    assert "preview_actor" not in app.session_state


def test_demo_guest_can_select_another_reservation(monkeypatch, tmp_path):
    monkeypatch.setenv("HOTEL_MODE", "preview")
    monkeypatch.setenv("HOTEL_API_URL", "")
    monkeypatch.setenv("PREVIEW_DB", str(tmp_path / "other-room.sqlite"))
    app = AppTest.from_file("../app.py", default_timeout=90)
    app.query_params["login"] = "guest"
    app.run()
    app.selectbox(key="guest_demo_kind").select("guest402").run()
    button(app, "Use demo account").click().run()
    assert app.text_input(key="demo_email_guest").value == "guest402@wavo.demo"
    button(app, "Sign in").click().run()
    assert not app.exception and app.session_state.preview_actor == "demo-guest-402"
    assert any("Room 402" in c.value for c in app.caption)
