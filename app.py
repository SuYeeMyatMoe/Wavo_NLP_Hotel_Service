"""Streamlit entry point. All ticket mutations use the FastAPI contract."""
# Render the public entrance before importing the model and API workspace.
# ruff: noqa: E402

import base64
import hashlib
import os
from html import escape
from uuid import uuid4
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
st.set_page_config(
    page_title="Wavo | Hotel operations",
    layout="wide",
    page_icon=str(ROOT / "static/wavo-brass-mark.png"),
)
st.html(ROOT / "hotel/ui.css")
st.html(ROOT / "hotel/hotel.css")
st.html(ROOT / "hotel/vintage.css")
st.html(ROOT / "hotel/mascot.css")
from hotel.vintage_ui import room as vintage_room, workspace_effects

workspace_effects()
loading_slot = st.empty()
loading_slot.html(
    '<div class="wavo-loading" role="status" aria-live="polite"><div class="wavo-loading-card"><span class="wavo-loading-bell" aria-hidden="true"></span><span>Wavo is getting things ready…</span></div></div>'
)
from dotenv import load_dotenv
from hotel import welcome

load_dotenv(ROOT / ".env")
S = st.session_state
service_hint = st.query_params.get("service")
if service_hint in {"comfort", "housekeeping", "wifi", "special"}:
    S.pending_service = service_hint
    del st.query_params["service"]


def jump(page, ref=None):
    S.destination = page
    S.selected_ticket = ref
    st.rerun()


def hero(title, subtitle):
    st.html(
        f'<section class="hero"><div class="orb" aria-hidden="true"></div><div class="ribs" aria-hidden="true"></div><h1>{title}</h1><p>{escape(subtitle)}</p></section>'
    )


def sign_in():
    import requests

    entrance = (
        st.query_params.get("login") or st.query_params.get("workspace") or "guest"
    )
    demo = os.getenv("WAVO_DEMO_LOGIN", "false").lower() == "true"
    st.html(
        f'<header class="public-nav">{welcome.BRAND}<a href="./" target="_self">Back to hotel</a></header>'
    )
    hero(
        ("Guest" if entrance == "guest" else "Staff") + " <em>sign in</em>",
        "Sign in to your hotel workspace.",
    )
    if demo:
        st.caption("Hosted demo · signs in through Supabase Auth")
        options = (
            list(welcome.GUESTS)
            if entrance == "guest"
            else ["staff", "backup", "reception", "housekeeping", "supervisor"]
        )
        st.selectbox(
            "Demo account",
            options,
            format_func=lambda key: welcome.DEMO_ACCOUNTS[key][0],
            key="guest_demo_kind" if entrance == "guest" else "staff_demo_kind",
        )
        st.button(
            "Use demo account", on_click=welcome.fill_demo_account, args=(entrance,)
        )
    with st.form("sign-in"):
        email = st.text_input("Email", key="demo_email_" + entrance)
        password = st.text_input(
            "Password", type="password", key="demo_password_" + entrance
        )
        if st.form_submit_button("Sign in", type="primary"):
            try:
                r = requests.post(
                    os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/token",
                    params={"grant_type": "password"},
                    headers={"apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"]},
                    json={"email": email, "password": password},
                    timeout=10,
                )
                if r.ok:
                    session = r.json()
                    profile = requests.get(
                        os.environ["HOTEL_API_URL"].rstrip("/") + "/workspace/updates",
                        headers={"Authorization": "Bearer " + session["access_token"]},
                        timeout=15,
                    )
                    if profile.ok:
                        updates = profile.json()
                        role = updates["profile"]["role"]
                        if (role == "guest") == (entrance == "guest"):
                            S.auth = session
                            from hotel.ui_client import remember

                            # This authenticated response already contains /me
                            # and the inbox needed by the first workspace render.
                            remember("/me", updates["profile"])
                            remember("/workspace/updates", updates)
                            st.query_params.clear()
                            st.rerun()
                        st.error(
                            "Use the guest entrance for guest accounts and the staff entrance for staff accounts."
                        )
                    else:
                        st.error(
                            "Your account needs a hotel profile before signing in."
                        )
                    st.stop()
                st.error("Check your sign-in details.")
            except (KeyError, requests.RequestException):
                st.error("The sign-in service needs configuration.")
    st.stop()


def tags(words):
    st.html(
        " ".join('<span class="token">' + escape(str(w)) + "</span>" for w in words)
        or "<p>No tokens.</p>"
    )


def evidence(a):
    if not a.get("predictions"):
        st.info(
            a.get("retention") or a.get("rule") or "Detailed evidence was not retained."
        )
        return
    stage = st.segmented_control(
        "Pipeline evidence",
        [
            "Preprocess",
            "Vectorize",
            "Classify",
            "Intent",
            "Entities",
            "Context",
            "Sentiment",
            "Explain",
        ],
        default="Preprocess",
        key="stage",
    )
    if stage == "Preprocess":
        st.caption("Cleaned text")
        st.text(a["cleaned"] or "(empty)")
        st.caption("Word tokens")
        tags(a["tokens"])
        st.caption("Lemmas used by the model")
        tags(a["lemmas"])
    elif stage in {"Intent", "Entities", "Context", "Sentiment"}:
        st.caption(
            "Evidence source · "
            + a.get("provenance", {}).get("evidence_source", "English working text")
        )
        if stage == "Intent":
            st.caption("Linguistic rules; separate from the trained classifiers")
            st.json(a.get("intent", {}))
        elif stage == "Entities":
            st.caption(
                "Rule-extracted references; the reservation determines the service room"
            )
            st.json(a.get("extraction", {}))
        elif stage == "Context":
            st.caption("Context rules · active, denied, resolved or uncertain issues")
            st.dataframe(a.get("issues", []), hide_index=True)
            st.json(a.get("extraction", {}).get("constraints", []))
        else:
            st.caption(
                "NLTK VADER heuristic; does not determine urgency or queue order"
            )
            st.json(a.get("sentiment", {}))
    elif stage == "Classify":
        st.dataframe(
            [
                {
                    "Target": k.title(),
                    "Prediction": v["label"],
                    "Model": v["model"],
                    v["score_type"]: round(v["score"], 4),
                }
                for k, v in a["predictions"].items()
            ],
            hide_index=True,
        )
        st.caption("Model version " + a["version"])
        with st.expander("All class scores"):
            for target, prediction in a["predictions"].items():
                st.caption(target.title() + " · " + prediction["score_type"])
                st.dataframe(
                    [
                        {"Class": name, "Score": score}
                        for name, score in prediction.get("class_scores", {}).items()
                    ],
                    hide_index=True,
                )
    else:
        target = st.selectbox(
            "Prediction",
            ["urgency", "department"],
            format_func=str.title,
            key="evidence_target",
        )
        v = a["predictions"][target]
        if stage == "Vectorize":
            st.caption(
                f"{len(v['features'])} matched features out of {v['vocabulary']:,} in the fitted vocabulary."
            )
            rows = [
                {"Term": f["term"], "TF-IDF weight": round(f["weight"], 5)}
                for f in sorted(v["features"], key=lambda f: -f["weight"])
            ]
        else:
            st.caption(
                f"Each contribution is TF-IDF × class coefficient. Add the intercept ({v['bias']:.3f}) to recover the class score."
            )
            rows = [
                {"Term": f["term"], "Contribution": round(f["contribution"], 5)}
                for f in v["features"]
            ]
        if rows:
            st.dataframe(rows, hide_index=True)
        else:
            st.info("No vocabulary matches. Staff review is required.")


def evaluation():
    studio.evaluation()


def reset_example():
    S.complaint = EXAMPLE
    S.pop("analysis", None)
    S.pop("saved", None)


def intelligence():
    hero(
        "NLP <em>Studio</em>",
        "Trace a guest complaint from its first words to the right hotel team.",
    )
    if S.get("call_evidence"):
        case = S.call_evidence
        st.subheader("Call from Room " + case["room"])
        st.text(case["issue"])
        st.caption(case["analysis"]["urgency"] + " · " + case["analysis"]["department"])
        if case["analysis"]["rule"]:
            st.warning(case["analysis"]["rule"])
        studio.context(case["analysis"])
        evidence(case["analysis"])
        if st.button("Analyze another complaint"):
            S.pop("call_evidence", None)
            st.rerun()
        return
    mode = st.segmented_control(
        "Workspace view",
        ["Analyze", "Evaluation"],
        default="Analyze",
        label_visibility="collapsed",
    )
    if mode == "Evaluation":
        evaluation()
        return
    left, right = st.columns([1.3, 1], gap="medium")
    with left, st.container(border=True):
        st.subheader("Guest complaint")
        text = st.text_area(
            "Complaint text",
            value=EXAMPLE,
            key="complaint",
            height=110,
            label_visibility="collapsed",
            max_chars=8000,
        )
        if S.get("analysis", {}).get("text") != text:
            S.pop("analysis", None)
            S.pop("saved", None)
        with st.container(horizontal=True):
            if st.button(
                "Analyze",
                type="primary",
                icon=":material/auto_awesome:",
                disabled=not text.strip(),
            ):
                if "analysis" not in S:
                    S.key_id = str(uuid4())
                S.analysis = request("POST", "/analyze", json={"text": text})
            st.button("Load example", on_click=reset_example)
    with right, st.container(border=True):
        st.subheader("Routing decision")
        a = S.get("analysis")
        if a:
            st.html(
                f'<div class="result"><small>{escape(a["urgency"])}</small><strong>{escape(a["department"])}</strong></div>'
            )
            if a["rule"]:
                st.warning(a["rule"])
            st.caption(
                "Analysis only. Guest service requests are created through Reception."
            )
        else:
            st.caption("Analyze the complaint to see its urgency and department.")
    if a:
        studio.context(a)
        if a.get("extraction"):
            with st.container(border=True):
                st.subheader("Extracted service details")
                ex = a["extraction"]
                st.write(ex["topic"])
                for item in ex["constraints"]:
                    st.write(item["constraint"] + " · " + item["evidence"])
                st.caption(ex["method"])
                st.subheader("Suggested solution")
                st.write(a["solution"]["next_action"])
                for doc in a["solution"]["procedures"]:
                    st.caption("Source · " + doc["title"] + " · " + doc["match_reason"])
        with st.container(border=True):
            st.subheader("Inside the prediction")
            evidence(a)


def tr(key):
    return label(key, me["language"]) if guest else key


def service_desk():
    workspace.my_work(me, jump, evidence)


@st.fragment(run_every="5s")
def ticket_list(guest=False):
    data = request("GET", "/tickets")
    if guest:
        hero(
            tr("My requests"),
            "See who is helping and confirm when the problem is solved.",
        )
    else:
        st.subheader("Request queue")
        queue = st.segmented_control(
            "Queue",
            ["Needs work", "Awaiting confirmation", "Resolved"],
            default="Needs work",
            label_visibility="collapsed",
        )
        if queue == "Needs work":
            data = [t for t in data if t["status"] in {"Assigned", "In progress"}]
            data.sort(key=lambda t: t["priority_rank"])
            st.caption(
                "Safety priority first. Oldest requests first within each priority."
            )
        elif queue == "Awaiting confirmation":
            data = [t for t in data if t["status"] == "Awaiting confirmation"]
        else:
            data = [t for t in data if t["status"] in {"Resolved", "Closed"}]
        if data:
            with st.expander("Filter queue"):
                for column, field in zip(
                    st.columns(3), ["urgency", "department", "status"]
                ):
                    choice = column.selectbox(
                        field.title(), ["All"] + sorted({t[field] for t in data})
                    )
                    if choice != "All":
                        data = [t for t in data if t[field] == choice]
    if not data:
        st.caption(tr("No requests here yet."))
    for t in data:
        ref = t["id"]
        with st.container(border=True):
            if not guest:
                st.write(
                    f"**{'#' + str(t['priority_rank']) + ' · ' if t['priority_rank'] else ''}{t['urgency']} · Room {t['room'] or 'unlinked'} · {t['department']}**"
                )
                st.caption(t["priority_reason"])
                if t.get("waiting_minutes") is not None and t["status"] in {
                    "Assigned",
                    "In progress",
                }:
                    st.caption(f"Open for {t['waiting_minutes']} min")
                ex = t["extraction"]
                st.text(ex["issue"][:220])
                if ex["constraints"]:
                    st.caption(
                        "Guest preferences · "
                        + " · ".join(c["constraint"] for c in ex["constraints"])
                    )
            else:
                st.text(t.get("problem") or t["complaint"][:230])
                if t.get("assignment"):
                    st.caption("Your contact · " + t["assignment"]["name"])
                if t.get("can_clarify"):
                    st.caption(
                        "Open this request to add details or confirm service permission."
                    )
            st.caption(
                " · ".join(
                    filter(
                        None,
                        [
                            ref,
                            tr(t["status"]),
                            f"ETA {t['eta']} min" if t.get("eta") is not None else "",
                        ],
                    )
                )
            )
            if st.button(tr("Open request"), key="open_" + ref):
                jump("My requests" if guest else "My work", ref)


def service_context(t):
    work = t["work"]
    ex = work["extraction"]
    cols = st.columns(2)
    cols[0].metric("Priority", t["urgency"])
    cols[1].caption("Assigned team")
    cols[1].write("**" + t["department"] + "**")
    st.caption(
        "Reservation linked" if t["guest"] else "Staff-entered room or public feedback"
    )
    st.subheader("NLP extraction")
    st.write("**" + ex["topic"] + "**")
    st.text(ex["issue"])
    if ex["constraints"]:
        for item in ex["constraints"]:
            st.write("**" + item["constraint"] + "**")
            st.caption("“" + item["evidence"] + "”")
    else:
        st.caption("No explicit access or comfort preferences extracted.")
    if ex["locations"]:
        st.caption("Location mentioned · " + ", ".join(ex["locations"]))
    if ex["reported_room"] and t["room"] and ex["reported_room"] != t["room"]:
        st.warning(
            "The message mentions Room "
            + ex["reported_room"]
            + ". The linked service room is "
            + t["room"]
            + "."
        )
    st.caption(ex["method"])
    a = t["analysis"]
    if a["rule"]:
        st.warning(a["rule"])
    else:
        urgency = a.get("predictions", {}).get("urgency")
        if urgency:
            st.caption(
                "Urgency model · "
                + urgency["model"]
                + " · "
                + urgency["score_type"]
                + " "
                + str(round(urgency["score"], 3))
            )
            tags([f["term"] for f in urgency["features"][:6]])
    st.subheader("Suggested solution")
    solution = work["solution"]
    st.write(solution["next_action"])
    st.caption(solution["reason"])
    for procedure in solution["procedures"]:
        with st.expander(procedure["title"] + " · category match"):
            st.text(procedure["body"])
            st.caption("Approved hotel document · " + procedure["id"])


@st.fragment(run_every="4s")
def staff_work_status(ref, version, status):
    current = request("GET", f"/tickets/{ref}/state")
    if current["version"] != version or current["status"] != status:
        st.rerun()
    st.caption(ref + " · " + status)


def ticket_view(guest):
    ref = S.get("selected_ticket")
    if not ref:
        st.rerun()
    t = request("GET", "/tickets/" + ref)
    work = t["work"]
    if st.button(tr("Close details") if guest else tr("Back to requests")):
        jump("My requests" if guest else "My work")
    heading = ("Room " + t["room"] + " · " if t["room"] else "") + t["department"]
    if guest:
        st.subheader(heading)
    else:
        st.title(heading)
    if guest:
        st.caption(ref + " · " + tr(t["status"]))
    else:
        staff_work_status(ref, work["version"], t["status"])
    st.text(work.get("problem") or t["complaint"])
    if guest:
        for constraint in work.get("constraints", []):
            st.caption(constraint)
    if guest and work.get("can_clarify"):
        st.info(
            "Reception is following up. Add the problem details here so we can arrange the right help."
        )
        with st.form("clarify_" + ref):
            detail = st.text_area(
                "What still needs help?",
                placeholder="Describe the problem and any room access or quiet-service preferences.",
            )
            agreement = st.checkbox(
                "Please arrange service for this issue", value=False
            )
            st.caption(
                "Wavo saves a structured service summary. Your original call privacy choice stays unchanged."
            )
            if st.form_submit_button("Update this request", type="primary"):
                if len(detail.strip()) < 3:
                    st.warning("Please describe the problem.")
                else:
                    update_key = "clarify_key_" + ref
                    draft = (detail, agreement, work["version"])
                    if update_key not in S or S.get(update_key + "_draft") != draft:
                        S[update_key] = str(uuid4())
                        S[update_key + "_draft"] = draft
                    request(
                        "POST",
                        f"/tickets/{ref}/clarify",
                        json={
                            "key": S[update_key],
                            "version": work["version"],
                            "text": detail,
                            "agreement": agreement,
                        },
                    )
                    del S[update_key]
                    S.pop(update_key + "_draft", None)
                    st.rerun()
    if guest and t.get("assignment"):
        assigned = t["assignment"]
        st.caption("ASSIGNED STAFF")
        st.write(assigned["name"])
        if not t.get("awaiting_confirmation") and t.get("completion_estimate"):
            from hotel.post_call_ui import estimate_line

            estimate_line(t["completion_estimate"])
    elif guest and t.get("lifecycle"):
        st.caption(t["lifecycle"]["reason"])
    if t.get("source") == "Voice message":
        raw = request("GET", f"/tickets/{ref}/audio")["audio"]
        st.audio(base64.b64decode(raw), format="audio/wav")
    if guest:
        if work["action"]:
            st.subheader(tr("Work completed"))
            st.write(work["action"])
        if t["status"] == "Awaiting confirmation" or t.get("awaiting_confirmation"):
            st.info(tr("Confirm service"))
            with st.container(horizontal=True):
                for resolved, title in [
                    (True, "Yes, fixed"),
                    (False, "Still not working"),
                ]:
                    if st.button(
                        tr(title), type="primary" if resolved else "secondary"
                    ):
                        request(
                            "POST",
                            f"/tickets/{ref}/confirm",
                            json={"version": work["version"], "resolved": resolved},
                        )
                        st.rerun()
        elif t["status"] in {"Resolved", "Closed"}:
            choice = st.selectbox(
                tr("How was the service?"),
                ["Satisfied", "Needs attention"],
                format_func=tr,
            )
            if st.button(tr("Send feedback")):
                request("POST", f"/tickets/{ref}/feedback", json={"value": choice})
                st.rerun()
        for call in request("GET", "/calls"):
            if call["ticket"] == ref and call.get("outcome") in {
                "ETA changed",
                "Room approval needed",
                "Move approved",
                "Move declined",
            }:
                case = request("GET", f"/calls/{call['id']}/utterance")
                st.info(case["reply"])
                if (
                    call["outcome"] == "ETA changed"
                    and "same-category room is ready" in call["reply"]
                    and t["status"]
                    not in {"Resolved", "Closed", "Awaiting confirmation"}
                ):
                    if st.button(tr("Request a room move")):
                        request("POST", f"/calls/{call['id']}/move-request")
                        st.rerun()
    if guest:
        from hotel.guest_history_ui import related_calls

        related_calls(ref)
    from hotel.activity_ui import activity

    activity(t["events"], t["status"], tr)


@st.fragment(run_every="4s")
def guest_ticket_view():
    ticket_view(True)


def guest_confirmation_notice(pending):
    if S.get("nav") == "Reception":
        return  # The receipt already presents confirmation controls.
    if pending and S.get("selected_ticket") != pending[0]["id"]:
        st.info(tr("Service update ready"))
        if st.button(tr("Review service")):
            jump("My requests", pending[0]["id"])


@st.fragment(run_every="3s" if S.get("call_key") or S.get("active_call") else "15s")
def phone_panel():
    calls = request("GET", "/calls", params={"active_only": True})
    pending = [
        c for c in calls if c["status"] in {"Ringing", "Connecting", "Connected"}
    ]
    if not pending:
        for state_key in list(S):
            if str(state_key).startswith(
                ("voice_ui_", "concierge_", "live_", "reply_", "transcript_")
            ):
                S.pop(state_key, None)
        was_active = S.pop("active_call", None) or S.get("call_key")
        S.pop("call_key", None)
        S.pop("audio", None)
        if was_active:
            S.completed_call = was_active
            jump("Reception")
        return
    c = pending[0]
    if not S.get("active_call"):
        S.active_call = c["id"]
        st.rerun()
    S.active_call = c["id"]
    with st.container(key="call_screen", border=True):
        st.subheader(
            tr("AI reception")
            if c["direction"] == "Inbound"
            else tr("Incoming hotel call")
        )
        st.caption(tr("Room") + " " + me["room"])
        with st.expander("Call privacy"):
            privacy_key = "privacy_" + c["id"]
            if privacy_key not in S:
                S[privacy_key] = request("GET", f"/calls/{c['id']}/transcript-consent")
            privacy = S[privacy_key]
            keep = st.checkbox(
                "Save transcript for staff review",
                value=privacy["consent"],
                key="transcript_" + c["id"],
            )
            if keep != privacy["consent"]:
                S[privacy_key] = request(
                    "PUT",
                    f"/calls/{c['id']}/transcript-consent",
                    params={"value": keep},
                )
            st.caption(
                "Turning this off removes retained call evidence. The necessary service record remains."
            )
        if c.get("engine") == "local":
            S.call_key = c["id"]
            if local_conversation(c["id"]):
                request("POST", f"/calls/{c['id']}/end")
                S.completed_call = c["id"]
                S.pop("call_key", None)
                S.pop("active_call", None)
                jump("Reception")
            return
        if S.get("call_key") != c["id"]:
            if st.button(tr("Join call"), key="join_" + c["id"]):
                S.audio = request("POST", f"/calls/{c['id']}/join")
                S.call_key = c["id"]
                st.rerun()
            if st.button(
                tr("Decline call"), icon=":material/call_end:", width="stretch"
            ):
                request("POST", f"/calls/{c['id']}/end")
                st.rerun()
        else:
            result = PHONE(
                data={
                    **S.audio,
                    "id": c["id"],
                    "microphone": tr("Enable microphone"),
                    "connected": tr("Connected"),
                    "waiting": tr("Waiting for reception"),
                    "error": tr("Audio error"),
                    "off": tr("Start speaking"),
                    "connecting": tr("Waiting for reception"),
                    "listening": tr("Listening"),
                    "speaking": tr("AI reception"),
                    "muted": tr("Microphone muted"),
                    "mute": tr("Mute microphone"),
                    "unmute": tr("Unmute microphone"),
                    "mascot": tr("Your Wavo concierge"),
                    "end": tr("End call"),
                },
                key="live_" + c["id"],
                on_ended_change=lambda: None,
            )
            if result.ended:
                request("POST", f"/calls/{c['id']}/end")
                S.completed_call = c["id"]
                S.pop("call_key", None)
                S.pop("active_call", None)
                jump("Reception")


def local_conversation(key):
    st.caption("Test mode · local speech recognition and approved response rules")
    from hotel.concierge import GREETINGS

    case = request("GET", f"/calls/{key}/case")
    if case["outcome"] == "Speaking with reception":
        st.info(tr("Speaking with reception"))
        desk.peer(key, "guest", tr("Enable microphone"), tr("Audio error"))
        return st.button(tr("End call"), icon=":material/call_end:", width="stretch")
    ui = S.setdefault(
        "voice_ui_" + key,
        {
            "job": None,
            "marker": None,
            "ready": False,
            "error": "",
            "retry": 0,
            "speech": {
                "reply": GREETINGS[case["language"]]
                if not case["issue"]
                else case["reply"],
                "wav": "",
            },
        },
    )
    if ui["job"]:
        result = request("GET", f"/calls/{key}/jobs/{ui['job']}")
        if result["status"] == "cancelled":
            return True
        if result["status"] == "complete":
            ui["job"] = None
            case = result["case"]
            ui["marker"] = case["version"]
            if result.get("retry"):
                ui["retry"] += 1
                ui["error"] = tr("Please repeat")
            else:
                ui["speech"] = result["speech"]
                ui["ready"] = True
                ui["error"] = ""
        elif result["status"] == "failed":
            ui.update(job=None, marker=case["version"], error=result["detail"])
    if ui["job"] is None and ui["marker"] != case["version"] and not ui["error"]:
        ui["job"] = request("POST", f"/calls/{key}/jobs")["id"]
    voice = LOCAL_PHONE(
        data={
            "lang": case["language"],
            "revision": f"{key}-{ui['marker']}-{ui['retry']}",
            "reply": ui["speech"]["reply"],
            "wav": ui["speech"]["wav"],
            "ready": ui["ready"],
            "busy": bool(ui["job"]),
            "failure": ui["error"],
            "microphone": tr("Enable microphone"),
            "mute": tr("Mute microphone"),
            "unmute": tr("Unmute microphone"),
            "replay": tr("Tap to hear again"),
            "error": tr("Audio error"),
            "end": tr("End call"),
            "play": tr("Play reply"),
            "send": tr("Send what I said"),
            "labels": {
                k: tr(v)
                for k, v in {
                    "listening": "Listening",
                    "speaking": "AI reception",
                    "thinking": "Checking",
                    "connecting": "Waiting for reception",
                    "muted": "Microphone muted",
                    "off": "Start speaking",
                    "paused": "Tap to play",
                }.items()
            },
        },
        key="concierge_" + key,
        on_turn_change=lambda: None,
        on_ended_change=lambda: request("POST", f"/calls/{key}/end"),
    )
    if voice.ended:
        return True
    if ui["error"]:
        st.warning(ui["error"])
        if st.button(tr("Retry reply")):
            ui.update(error="", marker=None)
            ui["job"] = request("POST", f"/calls/{key}/jobs", json=ui.get("last_body"))[
                "id"
            ]
            st.rerun()
    body = voice.turn
    with st.expander(tr("Type a reply")):
        with st.form("reply_" + key, clear_on_submit=True):
            text = st.text_input(tr("What do you need?"), max_chars=8000)
            if (
                st.form_submit_button(tr("Send request"), disabled=bool(ui["job"]))
                and text.strip()
            ):
                body = {"text": text, "turn_id": str(uuid4())}
    if body and not ui["job"] and str(body["turn_id"]) != ui.get("handled_turn"):
        ui["error"] = ""
        ui["last_body"] = body
        ui["job"] = request("POST", f"/calls/{key}/jobs", json=body)["id"]
        ui["handled_turn"] = str(body["turn_id"])
        st.rerun()
    return False


def begin_call():
    call = request("POST", "/calls")
    key = call["id"]
    request(
        "PUT",
        f"/calls/{key}/transcript-consent",
        params={"value": bool(S.get("retain_transcript", False))},
    )
    if call["engine"] == "live":
        S.audio = request("POST", f"/calls/{key}/join")
    S.call_key = key
    jump("Calls")


def guest_home():
    if not browser_voice:
        with st.container(key="guest_welcome", border=True):
            mascot, action = st.columns(
                [1, 1.3], vertical_alignment="center", gap="large"
            )
            with mascot:
                st.html(
                    '<button type="button" class="guest-mascot" data-wavo-mascot aria-label="Make Wavo jump">'
                    '<span class="wavo-mascot-actor"><img src="app/static/wavo-concierge-cutout.png" alt="" draggable="false"></span></button>'
                )
            with action:
                st.caption(tr("Room") + " " + me["room"])
                st.title(tr("AI reception"))
                st.write(tr("Speak in your language"))
                if st.button(
                    tr("Call AI Reception"),
                    icon=":material/call:",
                    type="primary",
                    width="stretch",
                ):
                    begin_call()
        st.checkbox("Save my call transcript for staff review", key="retain_transcript")
        st.caption(
            "Optional. Speech is processed to help you. With transcript storage off, Wavo keeps only the service note and task. Cloud voice providers have their own processing policies."
        )
    from hotel.guest_history_ui import home_progress

    home_progress(jump)
    pending_service = S.pop("pending_service", None)
    if pending_service:
        S.message_mode = "Text"
        S.guest_text = {
            "comfort": "I need help with my room: ",
            "housekeeping": "I need housekeeping help: ",
            "wifi": "I need help connecting to Wi-Fi: ",
            "special": "I have a special request: ",
        }[pending_service]
        S.service_form_open = True
    with st.expander(tr("Send a message"), expanded=S.get("service_form_open", False)):
        mode = st.segmented_control(
            tr("Get help"),
            ["Text", "Voice message"],
            format_func=tr,
            key="message_mode",
            default="Text",
            label_visibility="collapsed",
        )
        recording = None
        text = ""
        if mode == "Voice message":
            audio = st.audio_input(tr("Record"), sample_rate=16000, key="guest_record")
            if audio:
                recording = audio.getvalue()
        else:
            text = st.text_area(
                tr("What do you need?"), max_chars=8000, key="guest_text"
            )
        draft = (
            me["language"],
            mode,
            hashlib.sha256(recording).hexdigest() if recording else text,
        )
        if S.get("guest_draft") != draft:
            S.guest_draft, S.guest_key = draft, str(uuid4())
        with st.container(horizontal=True):
            if st.button(tr("Send request"), disabled=not (text.strip() or recording)):
                body = {"key": S.guest_key, "language": "auto"}
                if recording:
                    body["audio"] = base64.b64encode(recording).decode("ascii")
                    ref = request("POST", "/voice-messages", json=body)["id"]
                else:
                    body.update(text=text, source="Guest request")
                    ref = request("POST", "/tickets", json=body)["id"]
                S.pop("guest_draft", None)
                S.request_receipt = ref
                jump("My requests")
        permission = st.checkbox(tr("Consent"), value=bool(me["consent"]))
        if permission != bool(me["consent"]):
            request("PUT", "/consent", params={"value": permission})
            st.rerun()


def calls_page():
    hero(
        tr("Calls"),
        tr("Room") + " " + me["room"]
        if guest
        else "Call records, guest follow-ups and live handovers.",
    )
    if not guest:
        from hotel.call_workspace import staff_calls

        staff_calls(me, evidence, jump)
        return
    if guest:
        if (
            not browser_voice
            and not S.get("call_key")
            and st.button(
                tr("Call AI Reception"), type="primary", icon=":material/call:"
            )
        ):
            begin_call()
    st.subheader(tr("History"))
    history = request("GET", "/calls")
    if history:

        def view_outcome():
            click = S.get("guest_call_outcome")
            if click and 0 <= click["row"] < len(history):
                S.completed_call = history[click["row"]]["id"]
                S.destination = "Reception"

        st.dataframe(
            [
                {
                    tr("Calls"): c["direction"],
                    tr("Activity"): tr(c.get("outcome") or c["status"]),
                    "UTC": c["created"][:16],
                    "Action": "View outcome",
                }
                for c in history
            ],
            hide_index=True,
            column_config={
                "Action": st.column_config.ButtonColumn(
                    key="guest_call_outcome", on_click=view_outcome, width=130
                )
            },
        )
    else:
        st.caption(tr("No calls"))


def more():
    workspace.settings()


def safety_alerts(waiting, alerts):
    if waiting:
        st.warning(
            "Room " + waiting[0]["room"] + " is waiting to speak with reception."
        )
        if st.button("View waiting call"):
            S.desk_view = "Call notes"
            jump("My work")
    if alerts:
        first = alerts[0]
        location = " · Room " + first["room"] if first["room"] else ""
        st.error(f"{len(alerts)} safety request(s) awaiting staff action{location}.")
        if st.button("Review safety request"):
            jump("Requests", first["id"])


@st.fragment(run_every="15s")
def workspace_updates():
    from hotel.ui_client import remember

    data = request("GET", "/workspace/updates")
    remember("/me", data["profile"])
    workspace.notifications(jump, data["notifications"], data["profile"])
    if data["profile"]["role"] == "guest":
        guest_confirmation_notice(data["confirmations"])
        if (
            data["active_calls"]
            and not S.get("active_call")
            and (
                not browser_voice or data["active_calls"][0]["direction"] == "Outbound"
            )
        ):
            S.active_call = data["active_calls"][0]["id"]
            st.rerun()
    else:
        safety_alerts(data["handoffs"], data["alerts"])


if st.query_params.get("home") == "1":
    welcome.landing()
mode = os.getenv("HOTEL_MODE", "preview")
if (mode == "preview" and "preview_actor" not in S) or (
    mode == "connected" and "auth" not in S
):
    entrance = st.query_params.get("login") or st.query_params.get("workspace")
    if entrance not in {"guest", "staff"}:
        welcome.landing()
    if mode == "preview":
        welcome.demo_login(entrance)
    sign_in()

from hotel.nlp import EXAMPLE
from hotel.ui_client import request
from hotel.phone import PHONE, LOCAL_PHONE
from hotel import desk, studio, workspace
from hotel.guest_copy import label
from hotel.languages import NAMES

with st.container(key="masthead"):
    brand, account = st.columns([3, 1])
with brand:
    st.html(
        '<a class="brand" href="?home=1" target="_self"><img class="wavo-icon" src="app/static/wavo-brass-mark.png" alt="">Wavo<small>Hotel operations</small></a>'
    )
me = request("GET", "/me")
guest = me["role"] == "guest"
browser_voice = bool(
    guest
    and me["voice"]
    and mode == "connected"
    and os.getenv("CONCIERGE_MODE", "auto") != "local"
)
@st.fragment
def account_controls():
    account_menu = st.popover(
        "Guest workspace" if guest else "Staff workspace",
        icon=":material/account_circle:",
        on_change="rerun",
        key="account_menu",
    )
    with account_menu:
        st.caption(me["mode"])
        st.write(me["id"])
        details = request("GET", "/profile/details") if account_menu.open else {}
        if details.get("reservation"):
            st.caption("Verified room " + details["reservation"]["room"])
        if details.get("roster"):
            st.caption(
                details["roster"]["department"]
                + " · "
                + ("Available" if details["roster"]["available"] else "Unavailable")
            )
        if me["role"] == "manager" and st.button("Hotel settings"):
            S.settings_open = True
            st.rerun()
        if me["mode"] == "Local preview":
            if st.button("Switch to staff" if guest else "Switch to guest"):
                if guest and S.get("active_call"):
                    request("POST", f"/calls/{S.active_call}/end")
                S.clear()
                st.query_params.clear()
                st.query_params["login"] = "staff" if guest else "guest"
                st.rerun()
        if st.button("Sign out"):
            if guest and S.get("active_call"):
                request("POST", f"/calls/{S.active_call}/end")
            st.query_params.clear()
            S.clear()
            st.rerun()
        if guest:
            lang = st.selectbox(
                "App language / 语言 / भाषा / Bahasa / ဘာသာစကား",
                list(NAMES),
                index=list(NAMES).index(me["language"]),
                format_func=NAMES.get,
                key="guest_locale",
            )
            if lang != me["language"]:
                request("PUT", "/language", params={"value": lang})
                st.rerun()


with account:
    account_controls()

pages = (
    ["Reception", "My requests"]
    if guest
    else [
        "All tasks" if me["role"] == "manager" else "My work",
        "Calls",
        "NLP Studio",
        "Insights",
    ]
)
if "destination" in S:
    dest = S.pop("destination")
    if guest and dest == "Calls":
        dest = "My requests"
    S.nav = {
        "Requests": "My work",
        "Service desk": "My work",
        "Get help": "Reception",
        "NLP Intelligence": "NLP Studio",
        "More": "Insights",
    }.get(dest, dest)
    if me["role"] == "manager" and S.nav == "My work":
        S.nav = "All tasks"
    elif me["role"] == "staff" and S.nav == "All tasks":
        S.nav = "My work"
elif S.get("nav") not in pages:
    S.nav = pages[0]
page = (
    st.segmented_control(
        "Navigation",
        pages,
        key="nav",
        format_func=tr,
        label_visibility="collapsed",
        on_change=lambda: S.pop("selected_ticket", None),
    )
    or pages[0]
)
if guest and page == "Reception" and not any(
    S.get(key) for key in ("active_call", "call_key", "completed_call", "request_receipt")
):
    scene = vintage_room()
    if scene.telephone:
        if browser_voice:
            S.vintage_show_call = True
            S.vintage_focus_call = True
        else:
            begin_call()

if browser_voice:
    # This component stays at one fixed position/key on every guest page.
    # Its browser owns permission, startup and media; no rerun between clicks.
    live_result = PHONE(
        data={
            "api": os.getenv(
                "WAVO_BROWSER_API_URL", os.environ["HOTEL_API_URL"]
            ).rstrip("/"),
            "accessToken": S.auth["access_token"],
            "room": me["room"],
            "visible": page == "Reception"
            and bool(S.get("vintage_show_call"))
            and not S.get("active_call")
            and not S.get("completed_call"),
            "focusLauncher": S.pop("vintage_focus_call", False),
            "dismissedCall": S.get("dismissed_call"),
        },
        key="guest_live_reception",
        on_completed_call_change=lambda: None,
    )
    if live_result.completed_call and live_result.completed_call != S.get(
        "dismissed_call"
    ):
        if S.get("completed_call") != live_result.completed_call:
            S.vintage_show_call = False
            S.completed_call = live_result.completed_call
            jump("Reception")
if guest and (S.get("active_call") or S.get("call_key")):
    loading_slot.empty()
    phone_panel()
    if S.get("active_call"):
        st.stop()
# Show the confirmed hang-up receipt before unrelated history/inbox reads.
# Those reads can stop a rerun on a network error; they must not hide it.
if guest and (S.get("completed_call") or S.get("request_receipt")):
    from hotel.post_call_ui import request_popup

    loading_slot.empty()
    request_popup(
        S.get("completed_call") or S.request_receipt,
        jump,
        call=bool(S.get("completed_call")),
    )
inbox_slot = st.container()
if me["role"] == "manager" and S.get("settings_open"):
    if st.button("Back to workspace"):
        S.settings_open = False
        st.rerun()
    more()
    loading_slot.empty()
    st.stop()
if page == "NLP Studio":
    intelligence()
elif page == "Insights":
    studio.insights(jump)
    with st.expander("Verified agent activity", on_change="rerun") as audit_panel:
        if audit_panel.open:
            workspace.activity()
elif page == "Calls":
    calls_page()
elif page == "Reception":
    guest_home()
elif page in {"All tasks", "My work"} and S.get("selected_ticket"):
    workspace.my_work(me, jump, evidence)
elif page in {"All tasks", "My work"}:
    service_desk()
elif page == "My requests":
    from hotel.guest_history_ui import history

    history(jump)
    if S.get("selected_ticket"):
        with st.container(border=True, key="guest_request_details"):
            guest_ticket_view()
else:
    more()

# Only foreground navigation owns the large loader. Background updates have
# their own fragment and must never put the whole screen into a loading state.
loading_slot.empty()
with inbox_slot:
    workspace_updates()
