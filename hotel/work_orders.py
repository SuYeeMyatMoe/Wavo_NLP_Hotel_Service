"""Two staff actions followed by auditable guest confirmation."""

import json
from hotel import store
from hotel.extraction import extract, suggest

PRIORITY = {"Critical": 0, "Unassessed": 1, "Urgent": 2, "Moderate": 3, "Low": 4}


def current(db, ref):
    return db.one("SELECT * FROM ticket_work WHERE ticket=?", (ref,)) or empty_work(ref)


def empty_work(ref):
    return {
        "ticket": ref,
        "owner": "",
        "version": 0,
        "outcome": "",
        "action": "",
        "note": "",
        "updated": "",
    }


def locked(db, p, ref):
    query = "SELECT t.* FROM tickets t WHERE t.id=? AND t.hotel=?"
    args = [ref, p["hotel"]]
    if p["role"] == "staff":
        query += (
            " AND EXISTS(SELECT 1 FROM ticket_work w WHERE w.ticket=t.id AND w.owner=?)"
        )
        args.append(p["id"])
    elif p["role"] not in store.STAFF:
        query += " AND t.guest=?"
        args.append(p["id"])
    ticket = db.one(query + (" FOR UPDATE OF t" if db.pg else ""), args)
    if not ticket:
        raise PermissionError("Request unavailable.")
    return ticket


def guest_rating(db, ref):
    row = db.one(
        "SELECT action FROM events WHERE ticket=? AND action IN ("
        "'Guest feedback: 1/5','Guest feedback: 2/5','Guest feedback: 3/5',"
        "'Guest feedback: 4/5','Guest feedback: 5/5') ORDER BY created DESC,id DESC LIMIT 1",
        (ref,),
    )
    return int(row["action"][-3]) if row else None


def start(db, p, ref):
    if p["role"] not in store.STAFF:
        raise PermissionError("Staff access required.")
    t = locked(db, p, ref)
    w = current(db, ref)
    if t["status"] == "In progress" and w["owner"] == p["id"]:
        return w
    if t["status"] not in {"Assigned", "In progress"} or (
        w["owner"] and w["owner"] != p["id"]
    ):
        raise ValueError(
            "This request is already being handled. Refresh to see its owner."
        )
    if db.one("SELECT id FROM task_assignments WHERE ticket=? AND active=1", (ref,)):
        from hotel.operations import reported
        from uuid import uuid4

        reported(db, p, t, "start", str(uuid4()))
        return current(db, ref)
    db.run("INSERT INTO ticket_work(ticket) VALUES(?) ON CONFLICT DO NOTHING", (ref,))
    db.run(
        "UPDATE ticket_work SET owner=?,version=version+1,updated=? WHERE ticket=?",
        (p["id"], store.now(), ref),
    )
    db.run("UPDATE tickets SET status='In progress' WHERE id=?", (ref,))
    store.record(db, ref, "In progress", p["id"])
    store.record(db, ref, "Work started by " + p["id"], p["id"])
    return current(db, ref)


def submit(db, p, ref, key, version, outcome, action, note):
    if p["role"] not in store.STAFF:
        raise PermissionError("Staff access required.")
    t = locked(db, p, ref)
    prior = db.one("SELECT * FROM service_outcomes WHERE id=?", (key,))
    if prior:
        if (
            prior["ticket"],
            prior["staff"],
            prior["outcome"],
            prior["action"],
            prior["note"],
        ) != (ref, p["id"], outcome, action, note):
            raise ValueError("This submission key is already used.")
        return {"status": t["status"], "work": current(db, ref)}
    w = current(db, ref)
    if t["status"] != "In progress" or not w["owner"] or w["owner"] != p["id"]:
        raise ValueError("Start work before submitting an outcome.")
    if w["version"] != version:
        raise ValueError("This request changed. Refresh before submitting.")
    if outcome == "Fixed":
        from hotel.operations import validate_completion

        validate_completion(t)
    status = "Awaiting confirmation" if outcome == "Fixed" else "In progress"
    db.run(
        "INSERT INTO service_outcomes VALUES(?,?,?,?,?,?,?)",
        (key, ref, p["id"], outcome, action, note, store.now()),
    )
    db.run(
        "UPDATE ticket_work SET outcome=?,action=?,note=?,version=version+1,updated=? WHERE ticket=?",
        (outcome, action, note, store.now(), ref),
    )
    db.run("UPDATE tickets SET status=? WHERE id=?", (status, ref))
    store.record(db, ref, "Outcome submitted: " + outcome, p["id"])
    store.record(db, ref, status, p["id"])
    from hotel import operations as op

    op.state(
        db,
        t,
        "awaiting_confirmation" if outcome == "Fixed" else "in_progress",
        "Authorized worker outcome recorded",
    )
    if outcome == "Fixed":
        op.notify(
            db,
            t["hotel"],
            t["guest"],
            ref,
            "confirmation",
            "The team reports completion. Please confirm whether the issue is fixed.",
            key + ":confirmation",
        )
    return {"status": status, "work": current(db, ref)}


def confirm(db, p, ref, version, resolved, note=""):
    t = locked(db, p, ref)
    guest = p["role"] == "guest" and t["guest"] == p["id"]
    manager = p["role"] == "manager" and not t["guest"]
    if not (guest or manager):
        raise PermissionError("The linked guest confirms this request.")
    from hotel import operations

    work = db.one(
        "SELECT COALESCE(w.version,0) AS version,w.outcome,l.state,l.reason,a.staff "
        "FROM tickets t LEFT JOIN ticket_work w ON w.ticket=t.id "
        "LEFT JOIN service_lifecycle l ON l.ticket=t.id "
        "LEFT JOIN task_assignments a ON a.ticket=t.id AND a.active=1 WHERE t.id=?",
        (ref,),
    )

    pending = t["status"] == "Awaiting confirmation" or (
        work["outcome"] == "Fixed" and operations.awaiting_confirmation(work)
    )
    if not pending or work["version"] != version:
        raise ValueError("This outcome changed. Refresh before confirming.")
    if manager and not note.strip():
        raise ValueError("Record how completion was verified.")
    label = (
        ("Guest confirmed completion" if resolved else "Guest requested more help")
        if guest
        else (
            "Manager verified completion"
            if resolved
            else "Manager requested further work"
        )
    )
    if note.strip():
        label += ": " + note.strip()
    operations.confirmed(db, p, t, version, resolved, work["staff"], label)
    if resolved:
        return {"status": "Resolved"}
    return {"status": db.one("SELECT status FROM tickets WHERE id=?", (ref,))["status"]}


LATEST_NOTE = "SELECT n.analysis FROM call_notes n JOIN calls c ON c.id=n.id WHERE c.ticket=? ORDER BY n.updated DESC LIMIT 1"


def ticket_extraction(t, latest):
    a = t["analysis"]
    if isinstance(a, str):
        a = json.loads(a)
    text = a.get("english") or t["complaint"]
    extracted = a.get("extraction") or extract(text, t["room"])
    extracted = {**extracted, "verified_room": t["room"]}
    if latest:
        live_ex = json.loads(latest["analysis"]).get("extraction", {})
        extracted = {
            **extracted,
            "constraints": live_ex.get("constraints", extracted["constraints"]),
        }
    return extracted


def guest_work(t, work, extracted):
    from hotel.request_updates import can_clarify
    from hotel.issue_labels import problem_label

    return {
        **{k: work[k] for k in ("version", "action", "outcome", "updated")},
        "can_clarify": can_clarify(t),
        "problem": problem_label(extracted),
        "constraints": [c["constraint"] for c in extracted.get("constraints", [])],
    }


def context(db, p, t, *, include_outcomes=True):
    latest = db.one(LATEST_NOTE, (t["id"],))
    extracted = ticket_extraction(t, latest)
    work = current(db, t["id"])
    if p["role"] not in store.STAFF:
        return guest_work(t, work, extracted)
    return {
        **work,
        "extraction": extracted,
        "solution": suggest(db, p["hotel"], extracted, t["urgency"]),
        "outcomes": outcomes(db, t["id"]) if include_outcomes else [],
    }


def outcomes(db, ref):
    return db.all(
        "SELECT staff,outcome,action,note,created FROM service_outcomes WHERE ticket=? ORDER BY created,id",
        (ref,),
    )


def seed_demo(db):
    for key, title, body in [
        (
            "demo-ac",
            "Air conditioning service",
            "Confirm permission to enter and any quiet-room preference. Send a maintenance technician to inspect the cooling problem. Record the inspection, action taken and a cooling test. A room move requires front-desk approval.",
        ),
        (
            "demo-plumbing",
            "Plumbing service",
            "Confirm the location and extent of the water problem with the guest. Assign Maintenance to inspect and repair it. Record the action taken and verify the fixture works before requesting guest confirmation.",
        ),
        (
            "demo-housekeeping",
            "Housekeeping and amenities",
            "Confirm the requested cleaning or amenities and room access preferences. Assign Housekeeping. Record the items delivered or cleaning completed and ask the guest to confirm.",
        ),
    ]:
        db.run(
            "INSERT INTO policies VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
            (key, "demo", title, body),
        )
