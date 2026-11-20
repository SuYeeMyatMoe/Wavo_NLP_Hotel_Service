"""The same conversation and dispatch decisions serve local speech and Gemini Live."""

import json
import re

from hotel import store
from hotel.knowledge import retrieve
from hotel import case_notes
from hotel.procedures import select as select_procedure
from hotel.nlp import analyze
from hotel.service_consent import normalize_reply, service_consent
from hotel.latency import measure

ACTIVE = {"Connected", "Connecting", "Ringing"}
HANDOFF = {"Waiting for reception", "Speaking with reception"}
GREETINGS = {
    "en": "Hello, welcome to Wavo. I'm your AI receptionist. How can I help with your stay?",
    "zh": "您好，欢迎使用 Wavo。我是您的智能前台助手。请问有什么可以帮您？",
    "hi": "नमस्ते, Wavo में आपका स्वागत है। मैं आपकी एआई रिसेप्शनिस्ट हूँ। मैं आपकी क्या मदद कर सकती हूँ?",
    "ms": "Helo, selamat datang ke Wavo. Saya penyambut tetamu AI anda. Bagaimana saya boleh membantu anda?",
    "my": "မင်္ဂလာပါ။ Wavo မှ ကြိုဆိုပါတယ်။ ကျွန်ုပ်က သင့်ရဲ့ AI ဧည့်ကြိုဝန်ထမ်းပါ။ ဘာကူညီပေးရမလဲ။",
}
STAFF_REQUEST = re.compile(
    r"\b(?:(?:talk|speak) (?:to|with) (?:a |the )?(?:human|real person|person|someone|reception|staff|manager)"
    r"|(?:call|connect|transfer)(?: me)? (?:to )?(?:a |the )?(?:human|real person|reception|manager)"
    r"|(?:want|need|request) (?:a |the )?(?:human|real person|manager))\b"
    r"|^(?:a )?(?:human|real person|manager)(?: please)?[.!?]*$",
    re.I,
)
WIFI = re.compile(r"\b(wi[\s-]?fi|internet|wireless|network)\b", re.I)
YES = re.compile(
    r"^(yes|yeah|yep|okay|ok|sure|please do|go ahead|send (?:them|someone|maintenance)|that worked|it work(?:s|ed)|i(?:'m| am) (?:online|connected)|connected now)\b",
    re.I,
)
MOVE = re.compile(
    r"\b(move|switch|change) (?:us |me |the |my |a |to another )?(?:rooms?|instead)\b|\bprefer to move\b",
    re.I,
)
NEG = re.compile(
    r"\b(no|not|never|don't|do not|didn't|cannot|can't|still|isn't|wasn't|wouldn't)\b",
    re.I,
)
ACKNOWLEDGEMENT = re.compile(
    r"(?:ok|okay|yes|yeah|sure|thanks|thank you|got it|understood)"
    r"(?:[,.!\s]+(?:ok|okay|thanks|thank you))*[.!\s]*$",
    re.I,
)


def note(db, key, lock=False):
    row = db.one(
        """SELECT n.*,c.ticket,c.status,c.direction FROM call_notes n JOIN calls c ON c.id=n.id
                    WHERE n.id=?"""
        + (" FOR UPDATE OF n" if db.pg and lock else ""),
        (key,),
    )
    if not row:
        raise ValueError("This call has no concierge session.")
    return row


def ensure_note(db, call, guest, engine):
    pref = db.one("SELECT language FROM guest_languages WHERE guest=?", (guest["id"],))
    lang = pref["language"] if pref else "en"
    db.run(
        """INSERT INTO call_notes(id,hotel,guest,room,language,engine,reply,updated)
              VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING""",
        (
            call,
            guest["hotel"],
            guest["id"],
            guest["room"],
            lang,
            engine,
            GREETINGS[lang],
            store.now(),
        ),
    )
    db.run(
        "INSERT INTO call_privacy(call_id,updated) VALUES(?,?) ON CONFLICT DO NOTHING",
        (call, store.now()),
    )
    return note(db, call)


def same_category(db, n):
    return db.one(
        """SELECT other.room FROM room_inventory own JOIN room_inventory other
              ON own.hotel=other.hotel AND own.category=other.category
              WHERE own.hotel=? AND own.room=? AND other.room<>own.room AND other.ready=1
              ORDER BY other.room LIMIT 1""",
        (n["hotel"], n["room"]),
    )


def wait_time(db, n, department):
    row = db.one(
        "SELECT minutes FROM service_times WHERE hotel=? AND department=?",
        (n["hotel"], department),
    )
    return row["minutes"] if row else None


def save(db, n, **changes):
    # Keys are supplied only by local workflow code.
    if (
        changes.get("options")
        and n["options"]
        and changes["options"] not in n["options"].splitlines()
    ):
        changes["options"] = "\n".join(
            [*n["options"].splitlines()[-3:], changes["options"]]
        )
    db.run(
        "UPDATE call_notes SET "
        + ",".join(k + "=?" for k in changes)
        + ",updated=?,version=version+1 WHERE id=?",
        (*changes.values(), store.now(), n["id"]),
    )
    n.update(changes)
    n["version"] += 1


def dispatch(db, n, analysis, department=None):
    if n["ticket"]:
        return n["ticket"]
    guest = store.profile(db, n["guest"])
    if guest["room"] != n["room"]:
        raise ValueError(
            "Your reservation room changed during this call. Please start a new call so service goes to the confirmed room."
        )
    analysis = (
        analysis.copy()
        if case_notes.consented(db, n["id"])
        else case_notes.minimal(analysis)
    )
    if department:
        analysis["department"] = department
    with measure("dispatch", call=n["id"]):
        item = store.create(db, guest, analysis, n["id"], "Voice", n["room"])
    db.run("UPDATE calls SET ticket=? WHERE id=?", (item["id"], n["id"]))
    n["ticket"] = item["id"]
    return item["id"]


def human_requested(text):
    # A refusal to call reception is not an invitation to join the call.
    text = text.replace("’", "'")
    for sentence in re.split(r"[.!?;]", text):
        match = STAFF_REQUEST.search(sentence.strip())
        if match and not re.search(
            r"\b(?:don't|do not|no need to|not to|never)\b",
            sentence.strip()[: match.end()],
            re.I,
        ):
            return True
    return False


def followup_reply(db, n):
    owner = db.one(
        "SELECT r.name,t.analysis,t.status FROM task_assignments a JOIN staff_roster r ON r.staff=a.staff "
        "JOIN tickets t ON t.id=a.ticket "
        "WHERE a.ticket=? AND a.active=1",
        (n["ticket"],),
    )
    if owner and json.loads(owner["analysis"]).get("service_mode") == "service":
        return (
            f"Reception follow-up is recorded. Your service request {n['ticket']} "
            f"remains with {owner['name']} ({owner['status']})."
        )
    contact = (
        f"{owner['name']} is coordinating the next step."
        if owner
        else "Reception needs to coordinate the next step; a staff assignment is not confirmed yet."
    )
    return f"Your request {n['ticket']} is recorded. {contact} No repair visit or arrival time is confirmed yet."


def handoff(db, n, analysis, reason, *, live=False):
    analysis = {**analysis, "reception_followup": True}
    ref = dispatch(db, n, analysis, "Front Desk")
    if n["outcome"] not in HANDOFF:
        store.record(db, ref, reason, "AI reception")
    save(
        db,
        n,
        outcome="Waiting for reception" if live else "Reception follow-up",
        eta=None,
        reply=(
            "I have asked reception to join. Your summary is with them. Please stay on the call."
            if live
            else followup_reply(db, n)
        ),
    )


def classify(state):
    a = analyze(
        state["english"],
        state["case"]["outcome"] if state["case"]["outcome"] != "Listening" else "",
    )
    a.update(
        text=state["original"],
        english=state["english"],
        language=state["case"]["language"],
    )
    a["provenance"]["evidence_source"] = (
        "translated English" if state["case"]["language"] != "en" else "original"
    )
    a["extraction"]["verified_room"] = state["case"]["room"]
    return {"analysis": a}


def decide(state):
    db, n, a = state["db"], state["case"], state["analysis"]
    text = state["english"].strip()
    previous = json.loads(n["analysis"])
    existing = n["outcome"]
    wants_human = human_requested(text)
    acknowledgement = bool(ACKNOWLEDGEMENT.fullmatch(normalize_reply(text)))
    consent = service_consent(text) if existing == "Service offered" else None
    prior_ex = previous.get("extraction", {})
    constraints = {c["constraint"]: c for c in prior_ex.get("constraints", [])}
    constraints.update(
        {c["constraint"]: c for c in a["extraction"].get("constraints", [])}
    )
    a["extraction"]["constraints"] = list(constraints.values())
    if previous and a["extraction"]["constraints"] != prior_ex.get("constraints", []):
        previous["extraction"] = {
            **prior_ex,
            "constraints": a["extraction"]["constraints"],
        }
        save(db, n, analysis=json.dumps(previous))
    if existing in HANDOFF and a["urgency"] != "Critical":
        # A new guest turn should get the current status, not replay the
        # initial handoff announcement or restart the clarification flow.
        save(
            db,
            n,
            reply=(
                "Reception has not accepted your call yet. Your request is still pending."
                if existing == "Waiting for reception"
                else "Reception has accepted your call. Please speak with them directly."
            ),
        )
        return {}
    if (
        existing == "Reception follow-up"
        and not wants_human
        and a["urgency"] != "Critical"
    ):
        save(db, n, reply=followup_reply(db, n))
        return {}
    if (
        existing
        not in {
            "Clarification needed",
            "Service offered",
            "Task assigned",
            "ETA changed",
            "Awaiting Wi-Fi confirmation",
            "Guidance offered",
        }
        and not (existing == "Resolved by guest" and acknowledgement)
        and consent is None
        and a["intent"]["ambiguous"]
        and not a["issues"]
        and not a["extraction"]["constraints"]
        and a["urgency"] != "Critical"
        and not wants_human
    ):
        save(db, n, reply=a["intent"]["question"])
        return {}
    if (
        a["issues"]
        and all(i["state"] in {"resolved", "denied"} for i in a["issues"])
        and not n["ticket"]
        and a["urgency"] != "Critical"
        and not wants_human
    ):
        save(
            db,
            n,
            issue=state["original"],
            analysis=json.dumps(a),
            outcome="Resolved by guest",
            reply="Thank you for the update. Is there anything else you need help with?",
        )
        return {}
    solution = select_procedure(db, n["hotel"], a["extraction"], a["urgency"])

    agreed = (
        consent is True
        if existing == "Service offered"
        else bool(YES.search(text)) and not NEG.search(text)
    )
    if a["urgency"] == "Critical" or wants_human:
        if (
            a["urgency"] == "Critical"
            and n["ticket"]
            and previous.get("urgency") != "Critical"
        ):
            old = n["ticket"]
            safety = store.create(
                db,
                store.profile(db, n["guest"]),
                a if case_notes.consented(db, n["id"]) else case_notes.minimal(a),
                n["id"] + "-safety",
                "Voice",
                n["room"],
            )
            n["ticket"] = safety["id"]
            db.run("UPDATE calls SET ticket=? WHERE id=?", (n["ticket"], n["id"]))
            store.record(
                db,
                old,
                "New safety concern escalated under " + n["ticket"],
                "AI reception",
            )
        if not previous or a["urgency"] == "Critical":
            save(db, n, issue=state["original"], analysis=json.dumps(a))
            previous = a
        handoff(
            db,
            n,
            previous,
            "Reception or safety assistance requested",
            live=wants_human or existing in HANDOFF,
        )
    elif existing == "Clarification needed":
        pending = previous.get("pending_question") or {
            "field": "Access permission needs clarification"
        }
        if pending["field"] != "Access permission needs clarification" or re.search(
            r"\b(?:after|at|before|now|may enter|can enter|come in)\b", text, re.I
        ):
            prior = previous or a
            prior["extraction"]["constraints"] = [
                c
                for c in prior.get("extraction", {}).get("constraints", [])
                if c["constraint"] != "Access permission needs clarification"
            ]
            access_time = re.search(
                r"\b(?:after|before|at)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b|\bnow\b",
                text,
                re.I,
            )
            field = (
                pending["field"]
                if pending["field"] != "Access permission needs clarification"
                else "Access time agreed"
                + (": " + access_time.group() if access_time else "")
            )
            prior["extraction"]["constraints"].append(
                {"constraint": field, "evidence": text}
            )
            save(
                db,
                n,
                analysis=json.dumps(prior),
                outcome="Service offered",
                reply=f"I have noted your access instructions. Shall I send {prior['department']} to room {n['room']}?",
            )
        else:
            save(db, n, reply="What time would you allow the team to enter?")
    elif existing in {"Awaiting Wi-Fi confirmation", "Guidance offered"}:
        if agreed:
            save(
                db,
                n,
                outcome="Resolved by guest",
                reply="Thank you for confirming. I have marked this call resolved.",
            )
        elif NEG.search(text) or "help" in text.lower():
            handoff(db, n, previous, "Approved guidance did not resolve the issue.")
        else:
            save(db, n, reply="Did the instructions resolve the issue?")
    elif existing in {"Service offered", "Task assigned", "ETA changed"}:
        if MOVE.search(text) and not NEG.search(text):
            if same_category(db, n):
                db.run(
                    "INSERT INTO move_requests(call_id,decision) VALUES(?,'Pending') ON CONFLICT DO NOTHING",
                    (n["id"],),
                )
                handoff(
                    db,
                    n,
                    previous,
                    "Guest requests a room move. Front-desk confirmation required.",
                )
            else:
                save(
                    db,
                    n,
                    reply="There is currently no same-category room marked ready. Would you like me to contact reception?",
                )
        elif existing == "Service offered" and agreed:
            previous["service_agreement"] = True
            previous.pop("pending_question", None)
            a["service_agreement"] = True
            save(db, n, analysis=json.dumps(previous))
            department = previous["department"]
            eta = wait_time(db, n, department)
            ref = dispatch(db, n, previous)
            routed = db.one(
                "SELECT department,analysis FROM tickets WHERE id=?", (ref,)
            )
            assignment = db.one(
                "SELECT a.id,r.name FROM task_assignments a JOIN staff_roster r ON r.staff=a.staff WHERE a.ticket=? AND a.active=1",
                (ref,),
            )
            if (
                not assignment
                or json.loads(routed["analysis"]).get("service_mode")
                == "reception_review"
            ):
                save(
                    db,
                    n,
                    outcome="Reception follow-up",
                    eta=None,
                    reply=followup_reply(db, n),
                )
                return {}
            department = routed["department"]
            eta_text = (
                f" The current estimate is {eta} minutes." if eta is not None else ""
            )
            save(
                db,
                n,
                outcome="Task assigned",
                eta=eta,
                reply=f"I sent {department} the request for room {n['room']}.{eta_text} Your reference is {ref}.",
            )
        elif existing == "Service offered":
            save(
                db,
                n,
                reply=f"Shall I send {previous['department']} to room {n['room']}?",
            )
        elif existing == "ETA changed" and agreed:
            save(
                db,
                n,
                outcome="Task assigned",
                reply="Your service request remains open. I have recorded that you will wait.",
            )
        elif acknowledgement:
            save(
                db,
                n,
                reply="You're welcome. You can track your request in My requests.",
            )
        else:
            save(
                db,
                n,
                reply="Your request is with the team. You can ask for reception if you need another option.",
            )
    elif existing == "Resolved by guest" and (agreed or acknowledgement):
        save(db, n, reply="You're welcome. Let me know if you need anything else.")
    else:
        # The note records the original. Model features refer to the English working text.
        save(db, n, issue=state["original"], analysis=json.dumps(a))
        guidance = solution["procedures"] if WIFI.search(text) else []
        guidance = [g for g in guidance if WIFI.search(g["title"])]
        if WIFI.search(text) and guidance:
            policy = guidance[0]["body"]
            save(
                db,
                n,
                outcome="Awaiting Wi-Fi confirmation",
                options=policy,
                reply=policy + " Were you able to connect?",
            )
        elif WIFI.search(text):
            handoff(db, n, a, "No approved Wi-Fi instructions are available.")
        else:
            department = (
                solution["procedures"][0]["department"]
                if solution["procedures"]
                else a["department"]
            )
            a = {**a, "department": department}
            if solution["questions"]:
                a["pending_question"] = solution["questions"][0]
                save(
                    db,
                    n,
                    analysis=json.dumps(a),
                    outcome="Clarification needed",
                    reply=solution["questions"][0]["question"],
                )
            elif not solution["procedures"]:
                handoff(db, n, a, solution["reason"])
            elif department in {"Housekeeping", "Maintenance"}:
                a = {**a, "department": department}
                eta = wait_time(db, n, department)
                options = (
                    f"{department} can attend in about {eta} minutes."
                    if eta is not None
                    else f"I can request {department}. An estimate is not available yet."
                )
                if department == "Maintenance" and same_category(db, n):
                    options += " A same-category room is marked ready, subject to reception confirming a move."
                save(
                    db,
                    n,
                    analysis=json.dumps(a),
                    outcome="Service offered",
                    options=options,
                    eta=eta,
                    reply=options + f" Shall I send {department} to room {n['room']}?",
                )
            else:
                guidance = retrieve(db, n["hotel"], text)
                if guidance and any(
                    word.lower() in text.lower()
                    for word in guidance[0]["title"].split()
                    if len(word) > 3
                ):
                    save(
                        db,
                        n,
                        outcome="Guidance offered",
                        options=guidance[0]["body"],
                        reply=guidance[0]["body"] + " Did that resolve the issue?",
                    )
                else:
                    handoff(db, n, a, "Reception review requested.")
    return {}


class StaleTurn(Exception):
    def __init__(self, case):
        self.case = case


def classify_turn(case, original, english, language=None):
    # Pure analysis runs without a database connection or conversation lock.
    snapshot = dict(case)
    if language:
        snapshot["language"] = language
    with measure("classification", call=case["id"]):
        return classify({"case": snapshot, "original": original, "english": english})


def process_turn(
    db,
    guest,
    key,
    turn_id,
    original,
    english,
    language=None,
    *,
    prepared=None,
    version=None,
):
    n = note(db, key, lock=True)
    if not store.active(guest) or guest["id"] != n["guest"]:
        raise PermissionError("Guest call unavailable.")
    if n["status"] not in ACTIVE:
        raise ValueError("This call has ended.")
    if not db.run(
        "INSERT INTO concierge_turns VALUES(?,?) ON CONFLICT DO NOTHING", (key, turn_id)
    ).rowcount:
        return n
    if prepared is not None and n["version"] != version:
        # Raising rolls back the turn claim as well as releasing the lock.
        raise StaleTurn(n)
    if language and language != n["language"]:
        save(db, n, language=language)
    result = {"db": db, "case": n, "original": original, "english": english}
    result.update(prepared if prepared is not None else classify(result))
    result.update(decide(result))
    case_notes.record_turn(db, n, turn_id, original, english, result["analysis"])
    from hotel.operations import audit

    final = n
    audit(
        db,
        n["hotel"],
        final["ticket"],
        "NLP / Reception",
        "Processed guest turn",
        f"{result['analysis']['urgency']} · {result['analysis']['department']} · {final['outcome']}",
        f"turn:{key}:{turn_id}",
        guest["id"],
    )
    return final


def finish(db, key):
    with measure("finalization", call=key):
        return _finish(db, key)


def _finish(db, key):
    n = note(db, key, lock=True)
    if n["status"] == "Ended":
        return
    if n["issue"] and not n["ticket"] and n["outcome"] != "Resolved by guest":
        pending = json.loads(n["analysis"])
        pending["reception_followup"] = True
        if n["outcome"] == "Service offered":
            pending["pending_question"] = {
                "field": "service_agreement",
                "question": "May we send the team to your room?",
            }
        dispatch(db, n, pending, "Front Desk")
        save(db, n, outcome="Follow-up required")
    elif n["outcome"] in HANDOFF:
        save(db, n, outcome="Reception follow-up")
    elif not n["issue"]:
        save(db, n, outcome="No issue recorded")
    db.run(
        "UPDATE calls SET status='Ended' WHERE id=? AND status IN ('Ringing','Connected','Connecting')",
        (key,),
    )
    from hotel.call_jobs import discard

    discard(key)


def update_eta(db, staff, key, minutes):
    n = note(db, key, lock=True)
    if n["hotel"] != staff["hotel"] or staff["role"] not in store.STAFF:
        raise PermissionError("Staff access required.")
    t = store.ticket(db, staff, n["ticket"])
    if t["status"] not in {"Assigned", "In progress"} or n["outcome"] in HANDOFF:
        raise ValueError("This request is no longer awaiting service.")
    if n["eta"] == minutes:
        return n
    msg = f"The updated service estimate is {minutes} minutes."
    if same_category(db, n):
        msg += " A same-category room is ready. Reception can confirm a move if you prefer."
    store.record(db, t["id"], msg, staff["id"])
    save(db, n, eta=minutes, outcome="ETA changed", options=msg, reply=msg)
    return note(db, key)
