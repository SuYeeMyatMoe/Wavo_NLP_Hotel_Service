"""A compact service receipt using only backend-confirmed call outcomes."""

from uuid import uuid4
import streamlit as st
from hotel.ui_client import request


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
    with st.container(border=True, key="post_call_receipt"):
        st.caption("WAVO · REQUEST UPDATE")
        # This button remains usable even if the following read fails.
        retry_slot = st.empty()
        with retry_slot:
            st.button(
                "Refresh status",
                key="receipt_refresh_" + key,
                icon=":material/refresh:",
            )
        loading = st.empty()
        if st.session_state.get("receipt_seen") != key:
            loading.caption("Checking your request…")
        result = request("GET", f"/{'calls' if call else 'tickets'}/{key}/result")
        loading.empty()
        if not result["finalized"]:
            st.info("Checking your request…")
            return
        st.session_state.receipt_seen = key
        st.session_state.acknowledged_request = result["ticket"]
        retry_slot.empty()
        st.subheader(result["outcome"])
        if result["problem"]:
            st.write(f"Room {result['room']} · {result['problem']}")
        elif result["room"]:
            st.caption("Room " + result["room"])
        if result["assignment"]:
            person = result["assignment"]
            name = person["name"]
            st.write(
                name
                if person["department"] in name
                else name + " · " + person["department"]
            )
        if result.get("awaiting_confirmation"):
            st.info("The team reports the work is complete. Is everything working now?")
            confirmation(result["ticket"], result["work_version"], "receipt_" + key)
        elif result["outcome"] in {"Your request is assigned", "In progress"}:
            estimate_line(result["completion_estimate"])
            st.caption("Assigned → In progress → Awaiting your confirmation → Resolved")
        elif result.get("next_step"):
            st.write(result["next_step"])
        with st.container(horizontal=True):
            if st.button("Close", type="primary", key="receipt_dismiss_" + key):
                dismiss_receipt()
                jump("My requests")
            if result["ticket"] and st.button(
                "Track request", key="receipt_track_" + key
            ):
                dismiss_receipt()
                jump("My requests", result["ticket"])
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
