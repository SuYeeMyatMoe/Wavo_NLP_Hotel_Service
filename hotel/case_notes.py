"""Minimal service records and consent-controlled conversation evidence."""

import json
from uuid import uuid4
from hotel import store


def consented(db, key):
    row = db.one("SELECT consent FROM call_privacy WHERE call_id=?", (key,))
    return bool(row and row["consent"])


def minimal(a):
    from hotel.issue_labels import problem_label

    ex = a.get("extraction", {})
    topics = [{"topic": i["topic"], "state": i["state"]} for i in a.get("issues", [])]
    label = problem_label(ex)
    summary = label
    if len(topics) > 1:
        summary += "; " + "; ".join(i["topic"] + ": " + i["state"] for i in topics)
    constraints = [
        {"constraint": c["constraint"], "evidence": ""}
        for c in ex.get("constraints", [])
    ]
    return {
        "text": summary,
        "room": "",
        "version": a.get("version", ""),
        "urgency": a.get("urgency", "Unassessed"),
        "department": a.get("department", "Front Desk"),
        "rule": "Safety review required" if a.get("rule") else None,
        "predictions": {},
        "retention": "Service record only; transcript storage declined",
        "pending_question": a.get("pending_question", {}),
        "reception_followup": bool(a.get("reception_followup")),
        "service_agreement": bool(a.get("service_agreement")),
        "intent": {"label": a.get("intent", {}).get("label", "uncertain")},
        "sentiment": {
            "label": a.get("sentiment", {}).get("label", "unavailable"),
            "compound": a.get("sentiment", {}).get("compound"),
            "method": "VADER heuristic",
        },
        "issues": topics,
        "extraction": {
            "service_label": label,
            "topic": ex.get("topic", "General request"),
            "issue": summary,
            "constraints": constraints,
            "topics": [],
            "issues": topics,
            "locations": ex.get("locations", []),
            "reported_room": ex.get("reported_room", ""),
            "verified_room": "",
            "method": "Minimal service record",
        },
    }


def record_turn(db, n, turn_id, original, english, analysis, *, keep):
    payload = analysis if keep else minimal(analysis)
    db.run(
        "INSERT INTO nlp_analysis VALUES(?,?,?,?,?,?,?)",
        (
            str(uuid4()),
            n["hotel"],
            n["id"],
            n.get("ticket"),
            turn_id,
            json.dumps(payload),
            store.now(),
        ),
    )
    if keep:
        from hotel.intelligence import mask_pii

        turns = [
            ("guest", original, english, n["language"]),
            ("assistant", n["reply"], n["reply"], "en"),
        ]
        if n["engine"] == "live":
            turns = turns[:1]  # Actual assistant speech arrives from the LiveKit event.
        for speaker, original_text, working, lang in turns:
            db.run(
                "INSERT INTO call_transcripts VALUES(?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (
                    str(uuid4()),
                    n["id"],
                    turn_id,
                    speaker,
                    mask_pii(original_text),
                    mask_pii(working),
                    lang,
                    store.now(),
                ),
            )
        rows = db.all(
            "SELECT speaker,original FROM call_transcripts WHERE call_id=? ORDER BY created,id",
            (n["id"],),
        )
        db.run(
            "UPDATE calls SET transcript=? WHERE id=?",
            ("\n".join(r["speaker"] + ": " + r["original"] for r in rows), n["id"]),
        )
    else:
        saved = minimal(json.loads(n["analysis"])) if n["analysis"] != "{}" else {}
        db.run(
            "UPDATE call_notes SET issue=?,analysis=? WHERE id=?",
            (saved.get("text", ""), json.dumps(saved), n["id"]),
        )
        n.update(issue=saved.get("text", ""), analysis=json.dumps(saved))


def structured(db, n):
    a = json.loads(n.get("analysis") or "{}")
    ex = a.get("extraction", {})
    from hotel.procedures import select

    solution = (
        select(db, n["hotel"], ex, a.get("urgency", "Unassessed"))
        if ex.get("topic")
        else {}
    )
    note = {
        "issue": n["issue"],
        "room": n["room"],
        "equipment": ex.get("topic", "Unspecified"),
        "constraints": [c["constraint"] for c in ex.get("constraints", [])],
        "facts": [
            {"field": "Room", "value": n["room"], "source": "Verified reservation"}
        ],
        "options": n["options"],
        "actions": "Service task " + n["ticket"]
        if n.get("ticket")
        else "No task dispatched",
        "outcome": n["outcome"],
        "questions": [q["question"] for q in solution.get("questions", [])],
        "next_step": solution.get("next_action", "Review with reception"),
        "evidence": ex.get("issues", []) if consented(db, n["id"]) else [],
        "version": 0,
    }
    if ex.get("reported_room") and ex["reported_room"] != n["room"]:
        note["facts"].append(
            {
                "field": "Conflicting room mentioned",
                "value": ex["reported_room"],
                "source": "Guest message; verify before dispatch",
            }
        )
    if n.get("ticket"):
        outcomes = db.all(
            "SELECT action,outcome,created FROM service_outcomes WHERE ticket=? ORDER BY created,id",
            (n["ticket"],),
        )
        note["service_outcomes"] = outcomes
    latest = db.one(
        "SELECT version,payload,author,created FROM note_revisions WHERE call_id=? ORDER BY version DESC LIMIT 1",
        (n["id"],),
    )
    if latest:
        note.update(json.loads(latest["payload"]))
        note.update(
            version=latest["version"],
            reviewed_by=latest["author"],
            reviewed_at=latest["created"],
        )
    return note


def purge_evidence(db, key):
    # Trusted backend only, after authenticating the guest and locking the call.
    n = db.one("SELECT * FROM call_notes WHERE id=?", (key,))
    db.run("DELETE FROM call_transcripts WHERE call_id=?", (key,))
    for row in db.all("SELECT id,payload FROM nlp_analysis WHERE call_id=?", (key,)):
        db.run(
            "UPDATE nlp_analysis SET payload=? WHERE id=?",
            (json.dumps(minimal(json.loads(row["payload"]))), row["id"]),
        )
    db.run("UPDATE calls SET transcript='' WHERE id=?", (key,))
    if n:
        a = minimal(json.loads(n["analysis"]))
        db.run(
            "UPDATE call_notes SET analysis=?,issue=? WHERE id=?",
            (json.dumps(a), a["text"], key),
        )
    call = db.one("SELECT ticket FROM calls WHERE id=?", (key,))
    if call and call["ticket"]:
        t = db.one("SELECT analysis,source FROM tickets WHERE id=?", (call["ticket"],))
        if t and t["source"] == "Voice":
            a = minimal(json.loads(t["analysis"]))
            for snapshot in db.all(
                "SELECT id,payload FROM nlp_analysis WHERE ticket=?", (call["ticket"],)
            ):
                db.run(
                    "UPDATE nlp_analysis SET payload=? WHERE id=?",
                    (
                        json.dumps(minimal(json.loads(snapshot["payload"]))),
                        snapshot["id"],
                    ),
                )
            db.run(
                "UPDATE tickets SET complaint=?,analysis=? WHERE id=?",
                (a["text"], json.dumps(a), call["ticket"]),
            )
