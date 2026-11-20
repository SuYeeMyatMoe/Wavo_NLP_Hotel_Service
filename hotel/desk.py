"""Service desk panels for concierge cases and hotel confirmation data."""

import json
import streamlit as st
from hotel.ui_client import request
from hotel.phone import PHONE, PEER


@st.fragment(run_every="4s")
def call_notes(evidence, open_ticket, staff_id, active_only=False):
    cases = request("GET", "/desk/cases")
    if active_only:
        cases = [
            n
            for n in cases
            if n["status"] in {"Ringing", "Connecting", "Connected"}
            or n["move_decision"] == "Pending"
        ]
    if not cases:
        st.caption("Case notes appear here during a guest call.")
    cases.sort(
        key=lambda n: (
            n["outcome"] not in {"Waiting for reception", "Room approval needed"},
        )
    )
    for n in cases:
        key = n["id"]
        with st.container(border=True):
            st.subheader(f"Room {n['room']} · {n['outcome']}")
            st.text(n["issue"] or "Waiting for the guest to describe the issue.")
            if n["options"]:
                st.caption(n["options"])
            if n["move_decision"] == "Pending":
                with st.container(horizontal=True):
                    for approve, label in [
                        (True, "Approve room move"),
                        (False, "Decline move"),
                    ]:
                        if st.button(label, key=label + key):
                            request(
                                "POST",
                                f"/desk/cases/{key}/room-decision",
                                params={"approve": approve},
                            )
                            st.rerun()
            if n["eta"] is not None:
                st.caption(f"Service estimate · {n['eta']} min")
            if n["ticket"] and st.button("Open task", key="task_" + key):
                open_ticket(n["ticket"])
            if (
                n["status"] == "Connected"
                and n["outcome"] in {"Waiting for reception", "Speaking with reception"}
                and n["staff_id"] in {"", staff_id}
            ):
                if st.button("Join guest call", key="accept_" + key):
                    st.session_state["handoff_" + key] = request(
                        "POST", "/desk/cases/" + key + "/accept"
                    )
                    st.rerun()
                session = st.session_state.get("handoff_" + key)
                if session:
                    if session["engine"] == "local":
                        peer(
                            key,
                            "staff",
                            "Enable microphone",
                            "Check microphone permission.",
                        )
                    else:
                        PHONE(
                            data={
                                **session,
                                "id": key,
                                "microphone": "Enable microphone",
                                "connected": "Connected",
                                "waiting": "Waiting for the guest",
                                "error": "Check microphone permission.",
                            },
                            key="desk_live_" + key,
                            on_ended_change=lambda: None,
                        )
            if (
                n["ticket"]
                and n["task_status"] in {"Assigned", "In progress"}
                and n["outcome"] in {"Task assigned", "ETA changed"}
            ):
                with st.expander("Update task ETA"):
                    with st.form("eta_" + key):
                        mins = st.number_input(
                            "Minutes", 0, 1440, value=int(n["eta"] or 0)
                        )
                        if st.form_submit_button("Send updated ETA"):
                            request(
                                "POST", f"/desk/cases/{key}/eta", json={"minutes": mins}
                            )
                            st.rerun()
            if n["analysis"] != "{}":
                if st.button("Open complaint analysis", key="inspect_" + key):
                    st.session_state.call_evidence = {
                        "room": n["room"],
                        "issue": n["issue"],
                        "analysis": json.loads(n["analysis"]),
                    }
                    st.session_state.destination = "NLP Studio"
                    st.rerun()


def peer(key, side, microphone, error):
    remote = request("GET", f"/calls/{key}/signal")
    result = PEER(
        data={**remote, "side": side, "microphone": microphone, "error": error},
        key=side + "_peer_" + key,
        on_signal_change=lambda: None,
    )
    if result.signal:
        request("POST", f"/calls/{key}/signal", json=result.signal)


def availability():
    data = request("GET", "/desk/availability")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Service estimates")
        times = {r["department"]: r["minutes"] for r in data["times"]}
        dept = st.selectbox("Team", ["Maintenance", "Housekeeping"])
        with st.form("time_" + dept):
            mins = st.number_input(
                "Estimated wait in minutes", 0, 1440, value=times.get(dept, 0)
            )
            if st.form_submit_button("Save estimate"):
                request("PUT", "/desk/availability/" + dept, json={"minutes": mins})
                st.success("Estimate saved.")
    with right, st.container(border=True):
        st.subheader("Room availability")
        if data["rooms"]:
            st.dataframe(
                [
                    {
                        "Room": r["room"],
                        "Category": r["category"],
                        "Status": "Ready" if r["ready"] else "Unavailable",
                    }
                    for r in data["rooms"]
                ],
                hide_index=True,
            )
        with st.form("room_inventory"):
            room = st.text_input("Room number", max_chars=12)
            category = st.text_input("Room category", max_chars=50)
            ready = st.checkbox("Ready for a move")
            if st.form_submit_button("Save room") and room.strip() and category.strip():
                request(
                    "PUT",
                    "/desk/rooms",
                    json={"room": room, "category": category, "ready": ready},
                )
                st.rerun()
