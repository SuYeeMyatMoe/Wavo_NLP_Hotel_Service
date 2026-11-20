"""One staff call list, with optional live handovers and permitted callbacks."""

import streamlit as st
from hotel.ui_client import request
from hotel import desk, studio


def staff_calls(profile, evidence, jump):
    with st.popover(
        "Call a guest", icon=":material/call:", on_change="rerun"
    ) as callback:
        if callback.open:
            if not profile["voice"]:
                st.info(
                    "Live calling is not configured. Follow up through the service request."
                )
            else:
                options = request("GET", "/callback-options")
                if options:
                    labels = {
                        o["id"]: f"Room {o['room']} · {o['complaint'][:65]}"
                        for o in options
                    }
                    ref = st.selectbox(
                        "Guest request", list(labels), format_func=labels.get
                    )
                    if st.button("Call guest", type="primary", icon=":material/call:"):
                        request("POST", "/calls", params={"ref": ref})
                        st.success("The guest has an incoming call.")
                else:
                    st.caption(
                        "No eligible callbacks. The guest must give callback permission and have an open request."
                    )
    if profile["role"] == "manager":
        with st.expander("Live calls & handovers", on_change="rerun") as live:
            if live.open:
                desk.call_notes(
                    evidence,
                    lambda ref: jump("My work", ref),
                    profile["id"],
                    active_only=True,
                )
    history = request("GET", "/calls")
    st.subheader("Call history")
    if not history:
        st.caption("No calls yet.")
        return
    search = st.text_input("Find a call", placeholder="Room or summary", key="call_search")
    query = search.strip().casefold()
    if query:
        history = [
            c for c in history
            if query in f"{c['room']} {c['summary'] or ''}".casefold()
        ]
    if not history:
        st.info("No calls match your search.")
        return
    ids = tuple(c["id"] for c in history)

    def open_record():
        click = st.session_state.get("call_record_action")
        if click and 0 <= click["row"] < len(ids):
            st.session_state.staff_call_record = ids[click["row"]]

    st.dataframe(
        [
            {
                "Room": c["room"],
                "Date (UTC)": c["created"][:16].replace("T", " "),
                "Direction": c["direction"],
                "Summary": c["summary"] or "No issue recorded",
                "Outcome": c["outcome"] or c["status"],
                "Action": "Open call",
            }
            for c in history
        ],
        hide_index=True,
        column_order=["Room", "Action", "Summary", "Outcome", "Date (UTC)", "Direction"],
        row_height=48,
        height=min(460, 55 + len(history) * 48),
        alt="Call history with room, summary, outcome and an Open call button",
        column_config={
            "Action": st.column_config.ButtonColumn(
                key="call_record_action", on_click=open_record, width=110
            )
        },
    )
    key = st.session_state.get("staff_call_record")
    if key not in ids:
        return
    record = request("GET", f"/calls/{key}/record")
    with st.container(border=True):
        st.subheader("Room " + (record["room"] or "unavailable"))
        st.caption(
            record["direction"]
            + " · "
            + record["created"][:16].replace("T", " ")
            + " UTC"
        )
        st.write(record["outcome"])
        if record["eta"] is not None:
            st.caption(f"Service estimate · {record['eta']} minutes")
        if record["ticket"] and st.button("Open service task"):
            jump("My work", record["ticket"])
        studio.note_review(key, record)
        if record["options"]:
            with st.expander("Options discussed"):
                st.write(record["options"])
        with st.expander("Call transcript"):
            st.text(
                record["transcript"]
                or "No transcript retained. The service note is shown above."
            )
