"""Guest service history and a quiet home-page progress card."""

import streamlit as st
from hotel.ui_client import request
from hotel.post_call_ui import confirmation


def estimate_text(e):
    if not e:
        return "Not set"
    if e["overdue"]:
        return "Taking longer than expected"
    return f"About {e['remaining_minutes']} min"


def staff_label(assignment):
    name, department = assignment["name"], assignment.get("department", "")
    return name if not department or department in name else name + " · " + department


@st.fragment(run_every="15s")
def history(jump):
    if st.session_state.get("destination") in {"Reception", "My requests"}:
        st.rerun()
    st.title("My requests")
    st.caption(
        "Your calls and requests, together. Follow progress and confirm when everything is fixed."
    )
    with st.container(horizontal=True):
        source = st.selectbox(
            "Source", ["All", "Call", "Text", "Voice message"], key="history_source"
        )
        state = st.selectbox(
            "Status",
            [
                "All",
                "Open",
                "Awaiting confirmation",
                "Resolved",
                "Ended without request",
            ],
            key="history_status",
        )
        search = st.text_input(
            "Search",
            placeholder="Problem, room or full ID",
            key="history_search",
            max_chars=150,
        )
    filters = (source, state, search)
    if st.session_state.get("history_filters") != filters:
        st.session_state.history_filters = filters
        st.session_state.history_page = 1
    result = request(
        "GET",
        "/guest/activity",
        params={
            "source": source,
            "state": state,
            "search": search,
            "page": st.session_state.get("history_page", 1),
        },
    )
    rows = result["items"]
    st.caption(
        f"{result['total']} matching calls and requests · Select Open to see details below."
    )
    if not rows:
        st.info("No matching calls or requests yet.")
        return

    def open_row():
        action = st.session_state.get("history_action")
        if action and 0 <= action["row"] < len(rows):
            row = rows[action["row"]]
            if row["ticket"]:
                st.session_state.selected_ticket = row["ticket"]
                st.session_state.destination = "My requests"
            else:
                st.session_state.completed_call = row["id"]
                st.session_state.destination = "Reception"

    st.dataframe(
        [
            {
                "Reference": f"{r['source']} · {r['reference'][:12]}"
                + (
                    f" (+{len(r['calls']) - 1} calls)"
                    if r["source"] == "Call" and len(r["calls"]) > 1
                    else f" (+{len(r['calls'])} calls)"
                    if r["source"] != "Call" and r["calls"]
                    else ""
                ),
                "Room": r["room"] or "—",
                "Problem": r["problem"],
                "Status": r["status"],
                "Assigned staff": staff_label(r["assignment"])
                if r["assignment"]
                else (
                    "Reception review" if r["ticket"] and r["state"] == "Open" else "—"
                ),
                "Call duration": r["duration"]["label"],
                "Expected completion": estimate_text(r["completion_estimate"])
                if r["state"] == "Open" and r["ticket"]
                else "—",
                "Action": "Selected"
                if r["ticket"]
                and r["ticket"] == st.session_state.get("selected_ticket")
                else "Open",
            }
            for r in rows
        ],
        hide_index=True,
        row_height=52,
        height=min(550, 56 + 52 * len(rows)),
        column_order=[
            "Reference",
            "Room",
            "Problem",
            "Status",
            "Action",
            "Assigned staff",
            "Call duration",
            "Expected completion",
        ],
        column_config={
            "Action": st.column_config.ButtonColumn(
                key="history_action", on_click=open_row, width=80
            ),
            "Problem": st.column_config.TextColumn(width="medium"),
        },
        alt="Guest calls and requests, with staff assignment, call duration, completion estimate and an Open action",
    )
    st.caption(
        "Newest first · Call duration measures connected time. Completion is a separate service estimate. Full IDs and related calls are inside each record."
    )
    with st.container(horizontal=True):
        if st.button("Previous", disabled=result["page"] == 1, key="history_prev"):
            st.session_state.history_page = result["page"] - 1
            st.rerun(scope="fragment")
        st.caption(f"Page {result['page']} · {result['total']} records")
        if st.button(
            "Next",
            disabled=result["page"] * result["page_size"] >= result["total"],
            key="history_next",
        ):
            st.session_state.history_page = result["page"] + 1
            st.rerun(scope="fragment")


def related_calls(ref):
    with st.expander("Reference & related calls", on_change="rerun") as panel:
        if not panel.open:
            return
        st.text("Request ID · " + ref)
        calls = request("GET", f"/guest/requests/{ref}/calls")
        if calls:
            st.dataframe(
                [
                    {
                        "Call ID": c["id"],
                        "Date (UTC)": c["created"][:19].replace("T", " "),
                        "Direction": c["direction"],
                        "Call duration": c["duration"]["label"],
                        "Outcome": c["outcome"] or c["status"],
                    }
                    for c in calls
                ],
                hide_index=True,
                alt="All calls linked to this request with their full IDs and individual durations",
            )
        else:
            st.caption("This request has no linked calls.")


@st.fragment(run_every="15s")
def home_progress(jump):
    tasks = request("GET", "/tickets")
    opened = [t for t in tasks if t["status"] not in {"Resolved", "Closed"}]
    if not opened:
        return
    recent = st.session_state.get("acknowledged_request")
    opened.sort(
        key=lambda t: (
            t["id"] != recent,
            t.get("priority_rank") or 9999,
            t["created"],
            t["id"],
        )
    )
    t = opened[0]
    with st.container(border=True, key="home_progress"):
        st.caption("YOUR ACTIVE REQUEST")
        st.subheader(t.get("problem") or "Reception follow-up")
        a = t.get("assignment")
        st.write(
            f"Room {t['room']} · {a['name'] if a else 'Reception is coordinating your request'}"
        )
        if t.get("awaiting_confirmation"):
            st.info("The team reports the work is complete. Is everything working now?")
            detail = request("GET", f"/tickets/{t['id']}")
            confirmation(t["id"], detail["work"]["version"], "home_confirm")
        else:
            st.caption(
                t["status"]
                + (
                    " · " + estimate_text(t["completion_estimate"])
                    if t.get("completion_estimate")
                    else ""
                )
            )
        with st.container(horizontal=True):
            if st.button("Track request", key="home_track"):
                jump("My requests", t["id"])
            if st.button(f"View all requests · {len(opened)} open", key="home_all"):
                jump("My requests")
