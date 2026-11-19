"""Hotel-wide assignment overview using the existing authorized ticket queue."""

import streamlit as st

from hotel.issue_labels import problem_label
from hotel.procedures import CATEGORIES, DEPARTMENTS
from hotel.ui_client import request

CLOSED = {"Resolved", "Closed"}


def awaiting(t):
    return t.get("awaiting_confirmation") or t["status"] == "Awaiting confirmation"


def categories(t):
    ex = t.get("extraction") or {}
    topics = {i["topic"] for i in ex.get("issues", []) if i.get("topic")}
    return topics or {ex.get("topic") or "Uncategorized"}


def counts(rows):
    active = [t for t in rows if t["status"] not in CLOSED]
    return {
        "Open tasks": len(active),
        "Unassigned": sum(not t.get("assignment") for t in active),
        "In progress": sum(t["status"] == "In progress" for t in active),
        "Awaiting guest confirmation": sum(bool(awaiting(t)) for t in active),
    }


def filtered(
    rows, department="All", staff="All", category="All", status="Open", search=""
):
    query = search.strip().casefold()
    result = []
    for t in rows:
        a = t.get("assignment") or {}
        if department != "All" and t["department"] != department:
            continue
        if staff != "All" and (a.get("staff") or "Unassigned") != staff:
            continue
        if category != "All" and category not in categories(t):
            continue
        if status == "Open" and t["status"] in CLOSED:
            continue
        if status == "Completed" and t["status"] not in CLOSED:
            continue
        if status == "Awaiting confirmation" and not awaiting(t):
            continue
        if (
            status not in {"All", "Open", "Completed", "Awaiting confirmation"}
            and t["status"] != status
        ):
            continue
        if query and query not in f"{t['room']} {t['id']}".casefold():
            continue
        result.append(t)
    # Keep the backend's hotel-wide ranks; filtering never renumbers priority.
    return sorted(
        result,
        key=lambda t: (
            t["status"] in CLOSED,
            bool(awaiting(t)),
            t.get("priority_rank") or 999999,
            t["created"],
            t["id"],
        ),
    )


def table_row(t):
    closed = t["status"] in CLOSED
    estimate = t.get("completion_estimate")
    completion = "Not set"
    if closed:
        completion = "—"
    elif awaiting(t):
        completion = "Awaiting guest confirmation"
    elif estimate:
        completion = (
            "Overdue"
            if estimate["overdue"]
            else f"About {estimate['remaining_minutes']} min"
        )
    return {
        "Rank": None if closed or awaiting(t) else t.get("priority_rank"),
        "Room": t["room"] or "Unlinked",
        "Main problem": problem_label(t.get("extraction") or {}),
        "Department": t["department"],
        "Assigned staff": (t.get("assignment") or {}).get("name") or "Unassigned",
        "Status": "Awaiting confirmation · Escalated"
        if awaiting(t) and t["status"] == "Escalated"
        else t["status"],
        "Priority": t["urgency"],
        "Waiting (min)": None if closed or awaiting(t) else t.get("waiting_minutes"),
        "Expected completion": completion,
        "Action": "Open",
    }


def select(label, options, saved, name, **kwargs):
    # Keep a selected worker/category visible even after its last active task
    # disappears. Refresh must not silently change the user's filter.
    prior = saved.get(name, options[0])
    if prior not in options:
        options = [*options, prior]
    return st.selectbox(
        label, options, index=options.index(prior), key="admin_" + name, **kwargs
    )


@st.fragment(run_every="10s")
def overview(jump):
    if ref := st.session_state.pop("admin_open_ref", None):
        jump("My work", ref)
        return
    rows = request("GET", "/tickets")
    st.caption("Hotel-wide totals · All departments · Unresolved requests")
    with st.container(horizontal=True):
        for label, value in counts(rows).items():
            st.metric(label, value, border=True)

    saved = st.session_state.get("admin_filters", {})
    names = dict(st.session_state.get("admin_staff_names", {}))
    names.update(
        {
            t["assignment"]["staff"]: t["assignment"]["name"]
            for t in rows
            if t.get("assignment")
        }
    )
    st.session_state.admin_staff_names = names
    with st.container(horizontal=True):
        department = select(
            "Department",
            ["All", *sorted(set(DEPARTMENTS) | {t["department"] for t in rows})],
            saved,
            "department",
        )
        staff = select(
            "Assigned staff",
            ["All", "Unassigned", *sorted(names, key=lambda uid: (names[uid], uid))],
            saved,
            "staff",
            format_func=lambda uid: names.get(uid, uid),
        )
        category = select(
            "Problem category",
            [
                "All",
                *sorted(set(CATEGORIES) | {c for t in rows for c in categories(t)}),
            ],
            saved,
            "category",
        )
    with st.container(horizontal=True):
        status = select(
            "Status",
            [
                "Open",
                "All",
                "Assigned",
                "In progress",
                "Escalated",
                "Awaiting confirmation",
                "Completed",
            ],
            saved,
            "status",
        )
        search = st.text_input(
            "Room or request ID",
            value=saved.get("search", ""),
            key="admin_search",
            max_chars=150,
            placeholder="Search room or request ID",
        )
    filters = dict(
        department=department,
        staff=staff,
        category=category,
        status=status,
        search=search,
    )
    st.session_state.admin_filters = filters
    shown = filtered(rows, **filters)
    st.caption(
        f"{len(shown)} matching tasks · Hotel-wide ranks retained · Updates every 10 seconds"
    )
    if not shown:
        st.info("No tasks match these filters.")
        return
    ids = tuple(t["id"] for t in shown)

    def open_row():
        click = st.session_state.get("admin_table_action")
        if click and 0 <= click["row"] < len(ids):
            st.session_state.admin_open_ref = ids[click["row"]]

    st.dataframe(
        [table_row(t) for t in shown],
        key="admin_tasks",
        hide_index=True,
        row_height=52,
        height=min(560, 56 + 52 * len(shown)),
        column_order=[
            "Rank",
            "Room",
            "Main problem",
            "Department",
            "Assigned staff",
            "Status",
            "Action",
            "Priority",
            "Waiting (min)",
            "Expected completion",
        ],
        column_config={
            "Rank": st.column_config.NumberColumn(
                format="#%d",
                width="small",
                help="Hotel-wide queue position; filtering does not renumber tasks.",
            ),
            "Room": st.column_config.TextColumn(width="small", pinned=True),
            "Main problem": st.column_config.TextColumn(width="medium"),
            "Action": st.column_config.ButtonColumn(
                key="admin_table_action", on_click=open_row, width=80
            ),
        },
        alt="All hotel tasks with room, department, assigned worker, status and completion estimate",
    )
    st.caption(
        "Priority: Critical → Unassessed → Urgent → Moderate → Low, oldest first. Completion times are estimates, not guarantees. Open a task for review details and work history."
    )
