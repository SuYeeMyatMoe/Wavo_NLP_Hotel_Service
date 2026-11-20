"""A compact service receipt using only backend-confirmed call outcomes."""

from html import escape
from uuid import uuid4
import streamlit as st
from hotel.ui_copy import words
from hotel.ui_client import request, _cache

PROGRESS = (
    ("Assigned", "Assigned"),
    ("In progress", "In progress"),
    ("Awaiting confirmation", "Your confirmation"),
    ("Resolved", "Resolved"),
)


def receipt_details(result):
    person = result["assignment"] or {}
    name = person.get("name", "")
    team = person.get("department", "")
    handler = f"{name} · {team}" if team and team not in name else name
    fields = (
        ("receipt-problem", "Request", words(result["problem"])),
        ("receipt-room", "Room", result["room"]),
        ("receipt-handler", "Handled by", handler),
    )
    details = "".join(
        f'<div class="{cls}"><dt>{label}</dt><dd>{escape(str(value))}</dd></div>'
        for cls, label, value in fields
        if value
    )
    if details:
        st.markdown(f'<dl class="receipt-details">{details}</dl>', unsafe_allow_html=True)


def receipt_progress(result):
    stage = (
        "Awaiting confirmation"
        if result.get("awaiting_confirmation")
        else "Resolved"
        if result["outcome"] == "Resolved"
        else result.get("status")
    )
    states = [status for status, _ in PROGRESS]
    if stage not in states or result["outcome"] == "Reception is following up":
        return
    current = states.index(stage)
    items = []
    for index, (_, label) in enumerate(PROGRESS):
        attributes = ' aria-current="step" data-reached' if index == current else (
            " data-reached" if index < current else ""
        )
        items.append(f"<li{attributes}>{label}</li>")
    st.html('<ol class="receipt-progress" aria-label="Request progress">' + "".join(items) + "</ol>")


def estimate_line(estimate):
    if not estimate:
        st.caption("The team will confirm the completion estimate.")
    elif estimate["overdue"]:
        st.warning(
            "Taking longer than expected — the team has been notified."
            if estimate["team_notified"]
            else "Taking longer than expected — checking with the team."
        )
    else:
        st.subheader(
            f"Expected completion in about {estimate['remaining_minutes']} minutes"
        )
        st.caption("An estimate, not a guarantee. Updated as the work progresses.")


def confirmation(ref, version, prefix):
    with st.container(horizontal=True):
        for resolved, title in [(True, "Yes, fixed"), (False, "Still not working")]:
            if st.button(
                title,
                type="primary" if resolved else "secondary",
                key=f"{prefix}_{resolved}",
            ):
                request(
                    "POST",
                    f"/tickets/{ref}/confirm",
                    json={"version": version, "resolved": resolved},
                )
                st.rerun()


def dismiss_receipt():
    state = st.session_state
    cache = _cache()
    for key in list(cache):
        if key[0] == "receipt":
            del cache[key]
    if call := state.pop("completed_call", None):
        state.dismissed_call = call
    state.pop("request_receipt", None)
    state.pop("receipt_seen", None)
    state.selected_ticket = None
    state.destination = "My requests"


@st.dialog("Request update", width="medium", on_dismiss=dismiss_receipt)
def request_popup(key, jump, call=True):
    receipt(key, jump, call)


@st.fragment(run_every="5s")
def receipt(key, jump, call=True):
    if st.session_state.get("completed_call" if call else "request_receipt") != key:
        return
    with st.container(border=True, key="post_call_receipt"):
        body = st.container()
        actions = st.container(horizontal=True, vertical_alignment="center")
        with actions:
            track = st.empty()
            close = st.empty()
            refresh = st.button(
                "Refresh status",
                key="receipt_refresh_" + key,
                icon=":material/refresh:",
                type="tertiary",
            )
        loading = body.empty()
        if st.session_state.get("receipt_seen") != key:
            loading.caption("Checking your request…")
        path = f"/{'calls' if call else 'tickets'}/{key}/result"
        cache = _cache()
        cache_key = ("receipt", path)
        # A finalized receipt is a snapshot. Keep it usable during timer/widget
        # reruns; Refresh status explicitly requests the latest work status.
        result = cache.get(cache_key)
        if refresh or not result or not result["finalized"]:
            result = request("GET", path)
            cache[cache_key] = result
        loading.empty()
        if not result["finalized"]:
            body.info("Checking your request…")
            return
        st.session_state.receipt_seen = key
        st.session_state.acknowledged_request = result["ticket"]
        with body:
            st.subheader(result["outcome"])
            receipt_details(result)
            receipt_progress(result)
            if result.get("awaiting_confirmation"):
                st.info("The team reports the work is complete. Is everything working now?")
                confirmation(result["ticket"], result["work_version"], "receipt_" + key)
            elif result["outcome"] in {"Your request is assigned", "In progress"}:
                estimate_line(result["completion_estimate"])
            elif result["outcome"] == "Reception is following up":
                step = result.get("next_step") or ""
                st.info(
                    step
                    if step.startswith("Open this request") or step.endswith("?")
                    else "Reception will follow up with you. Open the request to see any updates."
                )
            elif result["outcome"] == "Reception is coordinating your request":
                st.info("Reception is finding the right team. You can track updates here.")
        if result["ticket"] and track.button(
            "Track request", type="primary", key="receipt_track_" + key
        ):
            dismiss_receipt()
            jump("My requests", result["ticket"])
        if close.button(
            "Close", type="secondary" if result["ticket"] else "primary", key="receipt_dismiss_" + key
        ):
            dismiss_receipt()
            jump("My requests")
        with st.expander("Reference", on_change="rerun") as reference:
            if reference.open:
                if call:
                    st.text("Call ID · " + key)
                    st.caption("Call duration · " + result["call_duration"]["label"])
                if result["ticket"]:
                    st.text("Request ID · " + result["ticket"])


def edit_estimate(t, me):
    a = t.get("assignment")
    if (
        not a
        or t["status"] not in {"Assigned", "In progress", "Escalated"}
        or t.get("awaiting_confirmation")
        or t["analysis"].get("service_mode") != "service"
    ):
        return
    estimate_line(t.get("completion_estimate"))
    if me["role"] != "manager" and a["staff"] != me["id"]:
        return
    with st.expander("Update completion estimate", on_change="rerun") as panel:
        if not panel.open:
            return
        e = t.get("completion_estimate") or {}
        with st.form("estimate_" + t["id"]):
            minutes = st.number_input(
                "Expected completion in minutes from now",
                min_value=1,
                max_value=1440,
                value=None,
                placeholder="Enter an estimate",
            )
            st.caption(
                "This updates the guest's estimate; it does not change internal deadlines."
            )
            submitted = st.form_submit_button("Update estimate")
        if submitted and minutes is not None:
            draft = (a["id"], e.get("version", 0), minutes)
            if st.session_state.get("estimate_draft") != draft:
                st.session_state.estimate_draft = draft
                st.session_state.estimate_key = str(uuid4())
            request(
                "POST",
                f"/tickets/{t['id']}/completion-estimate",
                json={
                    "key": st.session_state.estimate_key,
                    "assignment_id": a["id"],
                    "version": e.get("version", 0),
                    "minutes": minutes,
                },
            )
            st.rerun()
