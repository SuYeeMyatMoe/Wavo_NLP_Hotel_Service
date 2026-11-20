"""Small staff workspace: assigned work, conversational updates and an audit trail."""

import base64
import hashlib
import json
import os
from uuid import uuid4
import streamlit as st
from hotel.ui_client import request
from hotel.issue_labels import problem_label, MISSING


def work_receipt(ref):
    result = st.session_state.get("work_reply_" + ref)
    if result:
        if result.get("recognized"):
            st.text("You said: " + result["recognized"])
        if result.get("changed"):
            st.success(result["reply"])
        else:
            st.info(result["reply"])


def submit_report(ref, version, form_key, ticket):
    text = st.session_state[form_key + "_text"]
    audio = st.session_state[form_key + "_audio"]
    draft = (
        ref,
        version,
        text,
        hashlib.sha256(audio.getbuffer()).digest() if audio else None,
    )
    if st.session_state.get("work_draft") != draft:
        st.session_state.work_draft = draft
        st.session_state.work_turn_id = str(uuid4())
    with st.spinner("Processing your work update…"):
        result = request(
            "POST",
            "/work-assistant/turns",
            json={
                "turn_id": st.session_state.work_turn_id,
                "text": text,
                "audio": base64.b64encode(audio.getvalue()).decode()
                if audio and not text.strip()
                else "",
                "ref": ref,
                "version": version,
            },
        )
    st.session_state["work_reply_" + ref] = result
    if result.get("changed"):
        st.session_state["work_epoch_" + ref] = st.session_state.work_turn_id
        st.session_state.pop("work_draft", None)
        if ticket is not None:
            if result.get("action") in {"start", "complete", "blocked"}:
                ticket.update(
                    status=result["status"],
                    lifecycle=result["lifecycle"],
                    assignment=result["assignment"],
                    awaiting_confirmation=result["awaiting_confirmation"],
                )
                ticket["work"]["version"] = result["version"]
            else:
                ticket.update(request("GET", "/tickets/" + ref))


def assistant(ref="", version=None, room="", ticket=None):
    st.subheader("Work assistant")
    st.caption(
        "Tell Wavo what you started, finished, or need help with. Completion stays open until the guest confirms."
    )
    assistant_profile = request("GET", "/me")
    if assistant_profile["voice"] and not assistant_profile.get(
        "work_assistant_test_mode"
    ):
        if not st.session_state.get("work_live") and st.button(
            "Talk to work assistant", icon=":material/call:"
        ):
            st.session_state.work_live = request("POST", "/work-assistant/sessions")
        if live := st.session_state.get("work_live"):
            from hotel.phone import PHONE

            def end():
                request("POST", f"/work-assistant/sessions/{live['id']}/end")

            result = PHONE(
                data={
                    **live,
                    "microphone": "Enable microphone",
                    "off": "Start speaking",
                    "connecting": "Connecting",
                    "listening": "Listening",
                    "speaking": "Work assistant",
                    "error": "Audio unavailable. Try a typed update.",
                    "end": "End call",
                },
                key="work_live_" + live["id"],
                on_ended_change=lambda: None,
            )
            if result.ended:
                end()
                st.session_state.pop("work_live", None)
                st.rerun()
            return
    if assistant_profile.get("work_assistant_test_mode"):
        st.caption(
            "Test mode · local speech recognition and rule-based report interpretation"
        )
    form_key = (
        "work_report_" + ref + "_" + st.session_state.get("work_epoch_" + ref, "")
    )
    with st.form(form_key):
        st.text_area(
            "Your work update",
            placeholder=(
                f"I started work in Room {room}. / I completed the work and checked the result."
                if room
                else "I started the repair in Room [room number]."
            ),
            max_chars=4000,
            key=form_key + "_text",
        )
        st.audio_input(
            "Or record an update", sample_rate=16000, key=form_key + "_audio"
        )
        st.form_submit_button(
            "Send update",
            type="primary",
            on_click=submit_report,
            args=(ref, version, form_key, ticket),
        )
    work_receipt(ref)


def notifications(jump, rows=None, profile=None):
    from hotel.realtime import connect

    connect(profile)
    if rows is None:
        rows = request("GET", "/notifications")
    unread = sum(not r["read_at"] for r in rows)
    with st.popover(
        f"Notifications{f' · {unread}' if unread else ''}",
        icon=":material/notifications:",
    ):
        if not rows:
            st.caption("You're up to date.")
        for row in rows[:20]:
            st.write(row["message"])
            st.caption(row["created"][:16].replace("T", " ") + " UTC")
            if row.get("ticket") and st.button(
                "Open request", key="notification_open_" + row["id"]
            ):
                jump(
                    "My requests"
                    if (profile or {}).get("role") == "guest"
                    else "My work",
                    row["ticket"],
                )
            if not row["read_at"] and st.button("Mark read", key="read_" + row["id"]):
                request("POST", f"/notifications/{row['id']}/read")
                st.rerun(scope="fragment")


def activity(ref=""):
    rows = request("GET", "/agent-actions", params={"ref": ref})
    if rows:
        st.dataframe(
            [{k: r[k] for k in ("created", "agent", "action", "result")} for r in rows],
            hide_index=True,
        )
    else:
        st.caption("No automated actions recorded yet.")


def mark_done(ticket):
    ref = ticket["id"]
    version = ticket["work"]["version"]
    click_key = f"done_key_{ref}_{version}"
    request(
        "POST",
        f"/tickets/{ref}/done",
        json={
            "key": st.session_state.setdefault(click_key, str(uuid4())),
            "version": version,
        },
    )
    ticket.update(status="Awaiting confirmation", awaiting_confirmation=True)
    st.session_state.pop("work_reply_" + ref, None)


@st.fragment
def task_panel(t, me, evidence):
    ref = t["id"]
    w = t["work"]
    label = problem_label(w["extraction"])
    st.subheader(f"Room {t['room']} · {label}")
    st.caption(f"{ref} · {t['urgency']} · {t['status']}")
    if label == MISSING:
        st.caption(
            "The earlier record contains no specific problem detail. Reception needs to clarify with the guest."
        )
    with st.expander("Problem details and priority"):
        issue = w["extraction"].get("issue", "")
        if issue and issue not in {label, "General request"}:
            st.write(issue)
        st.write(
            t["analysis"].get("rule")
            or (
                "Urgency is unassessed and needs immediate human review."
                if t["urgency"] == "Unassessed"
                else f"{t['urgency']} priority from the urgency classifier."
            )
        )
        st.caption(
            "Critical → Unassessed → Urgent → Moderate → Low; oldest first within each priority. Sentiment does not change the rank."
        )
    for c in w["extraction"].get("constraints", []):
        st.write("• " + c["constraint"])
    st.info(w["solution"]["next_action"])
    st.caption(w["solution"]["reason"])
    assignment = t.get("assignment")
    from hotel.post_call_ui import edit_estimate

    edit_estimate(t, me)
    if t["analysis"].get("service_mode") == "reception_review":
        st.warning(
            "Reception follow-up · clarify the issue or permission before arranging physical work."
        )
        if st.button("Ask guest for details", key="ask_details_" + ref):
            request("POST", f"/tickets/{ref}/ask-details")
            st.success("Sent. The guest can update this same request in My requests.")
        st.caption(
            "Start work to acknowledge the follow-up. A review cannot be submitted as a completed repair."
        )
        if st.button("Check service assignment", key="recheck_" + ref):
            result = request(
                "POST",
                "/work-assistant/turns",
                json={
                    "turn_id": str(uuid4()),
                    "text": "Retry assignment",
                    "ref": ref,
                    "version": w["version"],
                },
            )
            if result.get("changed"):
                st.rerun()
            st.info(result["reply"])
    if assignment:
        st.caption(
            f"Assigned to {assignment['name']} · Service target {assignment['service_due'][:16]} UTC"
        )
    if (
        (
            assignment
            and assignment["staff"] == me["id"]
            or not assignment
            and w["owner"] == me["id"]
        )
        and t["status"] in {"Assigned", "In progress", "Escalated"}
        and not t.get("awaiting_confirmation")
    ):
        if t["analysis"].get("service_mode") != "reception_review":
            st.button(
                "Mark as done",
                key="done_" + ref,
                type="primary",
                on_click=mark_done,
                args=(t,),
            )
        assistant(ref, w["version"], t["room"], t)
    elif t["status"] == "Awaiting confirmation" or t.get("awaiting_confirmation"):
        st.button(
            "Marked as done",
            icon=":material/check:",
            disabled=True,
            key="done_recorded_" + ref,
        )
        st.info(
            "Staff marked the work as done. The guest has been asked to confirm whether the issue is fixed."
        )
        work_receipt(ref)
    elif t["status"] == "Escalated":
        st.warning(t["lifecycle"]["reason"])
        if me["role"] == "manager" and not assignment:
            st.caption(
                "After correcting guidance or roster availability, tell the assistant: retry assignment."
            )
            assistant(ref, w["version"], t["room"], t)
    with st.expander("NLP evidence", on_change="rerun") as panel:
        if panel.open:
            evidence(t["analysis"])
    with st.expander("Assignment and work history", on_change="rerun") as panel:
        if panel.open:
            st.dataframe(request("GET", f"/tickets/{ref}/assignments"), hide_index=True)
            outcomes = request("GET", f"/tickets/{ref}/outcomes")
            if outcomes:
                st.dataframe(outcomes, hide_index=True)
    with st.expander("Verified agent activity", on_change="rerun") as panel:
        if panel.open:
            activity(ref)


def my_work(me, jump, evidence):
    manager = me["role"] == "manager"
    st.title("All tasks" if manager else "My work")
    st.caption(
        "Every guest request, across your hotel’s teams."
        if manager
        else "Assigned automatically. Report your progress in your own words."
    )
    if ref := st.session_state.get("selected_ticket"):
        if st.button("Back to all tasks" if manager else "Back to my work"):
            jump("My work")
        t = request("GET", "/tickets/" + ref, params={"prepare_recorder": True})
        task_panel(t, me, evidence)
        return
    if manager:
        from hotel.supervisor_ui import overview

        overview(jump)
        return
    mode = st.segmented_control(
        "Work view",
        ["Active work", "Work assistant", "History"],
        default="Active work",
        label_visibility="collapsed",
    )
    if mode == "Work assistant":
        assistant()
        return
    if mode == "History":
        history = request("GET", "/work-history")
        if history:
            st.dataframe(history, hide_index=True)
        else:
            st.caption("Completed or released assignments will appear here.")
        return
    task_cards(mode == "History", jump)


@st.fragment(run_every="10s" if os.getenv("HOTEL_MODE") == "connected" else "5s")
def task_cards(history, jump):
    if ref := st.session_state.pop("work_open_ref", None):
        jump("My work", ref)
        return
    rows = request("GET", "/tickets")
    rows = [t for t in rows if (t["status"] in {"Resolved", "Closed"}) == history]
    rows.sort(key=lambda t: (t.get("priority_rank") or 999999, t["created"]))
    if not rows:
        st.caption(
            "No completed work yet."
            if history
            else "No assignments waiting. New work will appear here."
        )
        return
    st.caption(
        f"{len(rows)} open requests · Ranked by urgency, then oldest first. Open a request to report work."
    )
    table = [
        {
            "Rank": t.get("priority_rank"),
            "Room": t["room"],
            "Main problem": problem_label(t["extraction"]),
            "Priority": t["urgency"],
            "Status": t["status"],
            "Waiting (min)": t.get("waiting_minutes"),
            "Assigned to": (t.get("assignment") or {}).get("name", "Reception review"),
            "Action": "Open request",
        }
        for t in rows
    ]
    # Capture the displayed IDs. A timer refresh must not remap a click against
    # a newly ordered queue; column-click row indices refer to the source data.
    displayed_ids = tuple(t["id"] for t in rows)

    def open_row():
        click = st.session_state.get("work_table_action")
        if click and 0 <= click["row"] < len(displayed_ids):
            st.session_state.work_open_ref = displayed_ids[click["row"]]

    st.dataframe(
        table,
        key="ranked_work_table",
        hide_index=True,
        row_height=52,
        height=min(560, 55 + 52 * len(table)),
        alt="Service queue ranked by urgency and waiting time, with an Open request action for each room",
        column_config={
            "Rank": st.column_config.NumberColumn(
                width="small",
                format="#%d",
                help="Queue position, not a confidence score. Awaiting-confirmation requests have no active rank.",
            ),
            "Room": st.column_config.TextColumn(width="small", pinned=True),
            "Main problem": st.column_config.TextColumn(width="large"),
            "Action": st.column_config.ButtonColumn(
                on_click=open_row, key="work_table_action", width=135
            ),
        },
    )
    with st.expander("How priority is ranked"):
        st.write(
            "Critical → Unassessed → Urgent → Moderate → Low. Within each priority, the oldest request comes first. Awaiting-confirmation requests follow active work."
        )
        st.caption(
            "A short problem label describes the issue; it does not replace the urgency model. Open a request for its evidence and constraints."
        )


def settings():
    from hotel import studio

    st.title("Hotel settings")
    mode = st.segmented_control(
        "Settings",
        ["Procedures", "Staff roster", "Deadlines", "Reservations"],
        default="Procedures",
    )
    if mode == "Procedures":
        studio.procedures(True)
        return
    data = request("GET", "/operations/settings")
    if mode == "Staff roster":
        st.caption(
            "Only a supervisor can verify availability. Changes affect future assignments."
        )
        rows = data["roster"]
        choice = st.selectbox(
            "Staff profile", ["Add staff"] + [r["staff"] for r in rows]
        )
        row = next((r for r in rows if r["staff"] == choice), {})
        with st.form("roster_editor"):
            uid = st.text_input(
                "Existing staff profile ID",
                value=row.get("staff", ""),
                disabled=bool(row),
            )
            name = st.text_input("Display name", value=row.get("name", ""))
            from hotel.procedures import CATEGORIES, DEPARTMENTS

            dep = st.selectbox(
                "Department",
                DEPARTMENTS,
                index=DEPARTMENTS.index(row.get("department", "Maintenance")),
            )
            skills = st.multiselect(
                "Approved equipment skills",
                CATEGORIES + ["Reception review"],
                default=json.loads(row.get("skills", "[]")),
            )
            start = st.text_input(
                "Shift start (ISO timestamp with timezone)",
                value=row.get("shift_start", ""),
            )
            end = st.text_input(
                "Shift end (ISO timestamp with timezone)",
                value=row.get("shift_end", ""),
            )
            available = st.checkbox("Available", value=bool(row.get("available")))
            capacity = st.number_input(
                "Maximum active tasks",
                min_value=1,
                max_value=30,
                value=row.get("capacity", 3),
            )
            if st.form_submit_button("Save roster"):
                request(
                    "PUT",
                    "/operations/roster",
                    json={
                        "staff": uid,
                        "name": name,
                        "department": dep,
                        "skills": skills,
                        "shift_start": start,
                        "shift_end": end,
                        "available": available,
                        "capacity": capacity,
                        "version": row.get("version", 0),
                    },
                )
                st.rerun()
    elif mode == "Deadlines":
        st.caption(
            "Demo defaults are internal targets, not guest arrival promises. Critical and Unassessed always escalate."
        )
        priority = st.selectbox("Priority", ["Urgent", "Moderate", "Low"])
        row = next((r for r in data["policies"] if r["priority"] == priority), {})
        with st.form("deadline_editor"):
            ack = st.number_input(
                "Acknowledge within (minutes)",
                min_value=1,
                max_value=120,
                value=row.get("ack_minutes", 5),
            )
            service = st.number_input(
                "Service target (minutes)",
                min_value=2,
                max_value=1440,
                value=row.get("service_minutes", 30),
            )
            if st.form_submit_button("Save deadlines"):
                request(
                    "PUT",
                    "/operations/policies",
                    json={
                        "priority": priority,
                        "ack_minutes": ack,
                        "service_minutes": service,
                        "version": row.get("version", 0),
                    },
                )
                st.rerun()
    else:
        rows = data["reservations"]
        labels = {r["guest"]: f"Room {r['room']} · {r['guest']}" for r in rows}
        st.caption(
            "Set the verified room for each guest. New requests use this room; existing service records keep their original destination."
        )
        choice = st.selectbox(
            "Reservation",
            ["Add reservation"] + [r["guest"] for r in rows],
            format_func=lambda value: labels.get(value, value),
        )
        row = next((r for r in rows if r["guest"] == choice), {})
        with st.form("reservation_editor"):
            guest = st.text_input(
                "Existing guest profile ID",
                value=row.get("guest", ""),
                disabled=bool(row),
            )
            room = st.text_input("Verified room", value=row.get("room", ""))
            start = st.text_input("Arrival YYYY-MM-DD", value=row.get("starts", ""))
            end = st.text_input("Departure YYYY-MM-DD", value=row.get("ends", ""))
            if st.form_submit_button("Save reservation"):
                request(
                    "PUT",
                    "/operations/reservations",
                    json={
                        "guest": guest,
                        "room": room,
                        "starts": start,
                        "ends": end,
                        "version": row.get("version", 0),
                    },
                )
                st.rerun()
