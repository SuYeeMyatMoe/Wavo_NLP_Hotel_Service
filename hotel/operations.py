"""Transactional operational decisions. No conversational text in the action log."""

import json
from datetime import datetime, timedelta
from uuid import uuid4

from hotel import store

LABELS = {
    "new": "New",
    "needs_clarification": "Needs clarification",
    "pending_assignment": "Pending assignment",
    "assigned": "Assigned",
    "in_progress": "In progress",
    "awaiting_confirmation": "Awaiting confirmation",
    "resolved": "Resolved",
    "reopened": "Reopened",
    "escalated": "Escalated",
}


def later(at, minutes):
    return (datetime.fromisoformat(at) + timedelta(minutes=minutes)).isoformat()


def audit(db, hotel, ref, agent, action, result, key, actor="Controller", at=None):
    db.run(
        "INSERT INTO agent_actions VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(dedupe) DO NOTHING",
        (
            str(uuid4()),
            hotel,
            ref,
            agent,
            action,
            result,
            actor,
            at or store.now(),
            key,
        ),
    )


def notify(db, hotel, recipient, ref, kind, message, key, at=None):
    if not recipient:
        return
    at = at or store.now()
    uid = str(uuid4())
    if db.run(
        "INSERT INTO notifications(id,hotel,recipient,ticket,kind,message,created,dedupe) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(dedupe) DO NOTHING",
        (uid, hotel, recipient, ref, kind, message, at, key),
    ).rowcount:
        db.run("INSERT INTO operation_jobs(id,due) VALUES(?,?)", (uid, at))


def state(db, t, value, reason, at=None):
    at = at or store.now()
    db.run(
        "INSERT INTO service_lifecycle VALUES(?,?,?,1,?,?) ON CONFLICT(ticket) DO UPDATE SET state=excluded.state,version=service_lifecycle.version+1,reason=excluded.reason,updated=excluded.updated",
        (t["id"], t["hotel"], value, reason, at),
    )
    db.run("UPDATE tickets SET status=? WHERE id=?", (LABELS[value], t["id"]))
    store.record(db, t["id"], LABELS[value], "Controller")


def snapshot(db, ref):
    life = db.one("SELECT * FROM service_lifecycle WHERE ticket=?", (ref,))
    assignment = db.one(
        "SELECT a.*,r.name FROM task_assignments a JOIN staff_roster r ON r.staff=a.staff WHERE a.ticket=? AND a.active=1",
        (ref,),
    )
    return _snapshot(life, assignment)


def _snapshot(life, assignment):
    return {
        "lifecycle": life,
        "assignment": assignment,
        "awaiting_confirmation": bool(
            life
            and (
                life["state"] == "awaiting_confirmation"
                or (
                    life["state"] == "escalated"
                    and life["reason"]
                    == "Guest confirmation is overdue; do not assume resolution."
                )
            )
        ),
    }


def snapshots(db, refs):
    """Fetch list-card state in batches, not two remote queries per ticket."""
    result = {}
    for offset in range(0, len(refs), 500):
        batch = refs[offset : offset + 500]
        marks = ",".join("?" for _ in batch)
        lives = {
            r["ticket"]: r
            for r in db.all(
                f"SELECT * FROM service_lifecycle WHERE ticket IN ({marks})", batch
            )
        }
        assignments = {
            r["ticket"]: r
            for r in db.all(
                "SELECT a.*,r.name FROM task_assignments a JOIN staff_roster r ON r.staff=a.staff "
                f"WHERE a.active=1 AND a.ticket IN ({marks})",
                batch,
            )
        }
        from hotel.completion import display

        estimates = {
            r["ticket"]: display(r)
            for r in db.all(
                "SELECT e.* FROM completion_estimates e JOIN task_assignments a ON a.id=e.assignment WHERE a.active=1 AND e.ticket IN ("
                + marks
                + ")",
                batch,
            )
        }
        result.update(
            {
                ref: {
                    **_snapshot(lives.get(ref), assignments.get(ref)),
                    "completion_estimate": estimates.get(ref),
                }
                for ref in batch
            }
        )
    return result


def escalate(db, t, reason, key, at=None):
    state(db, t, "escalated", reason, at)
    audit(
        db, t["hotel"], t["id"], "Dispatch", "Human review required", reason, key, at=at
    )
    for manager in db.all(
        "SELECT id FROM profiles WHERE hotel=? AND role='manager'", (t["hotel"],)
    ):
        notify(
            db,
            t["hotel"],
            manager["id"],
            t["id"],
            "escalation",
            reason,
            key + manager["id"],
            at,
        )
    notify(
        db,
        t["hotel"],
        t["guest"],
        t["id"],
        "review",
        "Your request is waiting for reception review. No arrival time is confirmed.",
        key + ":guest",
        at,
    )


def dispatch(db, ref, *, exclude=(), at=None, review_reason=""):
    at = at or store.now()
    t = db.one(
        "SELECT * FROM tickets WHERE id=?" + (" FOR UPDATE" if db.pg else ""), (ref,)
    )
    existing = db.one(
        "SELECT * FROM task_assignments WHERE ticket=? AND active=1", (ref,)
    )
    if existing:
        return existing
    a = json.loads(t["analysis"])
    solution = a.get("solution", {})
    marker = f"dispatch:{ref}:" + str(
        db.one("SELECT COUNT(*) AS n FROM task_assignments WHERE ticket=?", (ref,))["n"]
    )
    if t["urgency"] in {"Critical", "Unassessed"}:
        review_reason = "Immediate supervisor review: " + t["urgency"]
    elif a.get("pending_question", {}).get("field") == "service_agreement":
        review_reason = "Reception must confirm guest agreement before any room visit."
    elif not t["guest"] or not t["room"]:
        review_reason = (
            "Reception must verify the guest reservation before physical service."
        )
    elif a.get("reception_followup") and not (
        solution.get("procedures")
        and not solution.get("questions")
        and solution["procedures"][0]["department"] == "Front Desk"
    ):
        review_reason = "Reception follow-up requested; check the issue and next step with the guest."
    elif not solution.get("procedures") or solution.get("questions"):
        review_reason = "Reception must clarify the issue or obtain approved guidance."
    department = (
        "Front Desk" if review_reason else solution["procedures"][0]["department"]
    )
    policy = db.one(
        "SELECT * FROM service_policies WHERE hotel=? AND priority=?",
        (
            t["hotel"],
            "Urgent" if t["urgency"] in {"Critical", "Unassessed"} else t["urgency"],
        ),
    )
    if not policy:
        escalate(db, t, "No approved monitoring policy is configured.", marker, at)
        return None
    state(db, t, "pending_assignment", "Checking trusted staff roster", at)
    # Lock in stable order before reading workload, avoiding cross-ticket capacity races.
    roster = db.all(
        "SELECT r.*,p.role FROM staff_roster r JOIN profiles p ON p.id=r.staff AND p.hotel=r.hotel WHERE r.hotel=? ORDER BY r.staff"
        + (" FOR UPDATE OF r" if db.pg else ""),
        (t["hotel"],),
    )
    category = (
        "Reception review"
        if review_reason
        else a.get("extraction", {}).get("topic", "")
    )
    candidates = []
    for r in roster:
        if (
            r["role"] not in store.STAFF
            or (t["urgency"] in {"Critical", "Unassessed"} and r["role"] != "manager")
            or r["staff"] in exclude
            or not r["available"]
            or r["department"] != department
            or not (r["shift_start"] <= at < r["shift_end"])
        ):
            continue
        if category not in json.loads(r["skills"]):
            continue
        load = db.one(
            "SELECT COUNT(*) AS n FROM task_assignments WHERE staff=? AND active=1",
            (r["staff"],),
        )["n"]
        if load < r["capacity"]:
            candidates.append((load, r["last_assigned"], r["staff"], r))
    if not candidates:
        if not review_reason:
            return dispatch(
                db,
                ref,
                exclude=exclude,
                at=at,
                review_reason="No eligible service worker; reception must coordinate availability.",
            )
        escalate(
            db,
            t,
            review_reason + " No eligible reception worker has capacity.",
            marker,
            at,
        )
        return None
    load, _, worker, r = min(candidates)
    attempt = db.one(
        "SELECT COALESCE(MAX(attempt),0)+1 AS n FROM task_assignments WHERE ticket=?",
        (ref,),
    )["n"]
    reason = f"{department} · skill: {category} · on shift and available · {load}/{r['capacity']} active tasks; least workload, oldest assignment, staff ID."
    if review_reason:
        reason = review_reason + " " + reason
    a["service_mode"] = "reception_review" if review_reason else "service"
    a["routing"] = {
        "department": department,
        "reason": review_reason or "Approved procedure department",
        "model_department": a.get("department"),
    }
    db.run(
        "UPDATE tickets SET department=?,analysis=? WHERE id=?",
        (department, json.dumps(a), ref),
    )
    t["department"] = department
    uid = str(uuid4())
    db.run(
        "INSERT INTO task_assignments(id,ticket,staff,hotel,attempt,assigned,ack_due,service_due,reason) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            uid,
            ref,
            worker,
            t["hotel"],
            attempt,
            at,
            later(at, policy["ack_minutes"]),
            later(at, policy["service_minutes"]),
            reason,
        ),
    )
    db.run("UPDATE staff_roster SET last_assigned=? WHERE staff=?", (at, worker))
    if not review_reason:
        from hotel.completion import seed_assignment

        seed_assignment(db, t, uid, solution["procedures"][0], at)
    db.run(
        "INSERT INTO ticket_work(ticket,owner,updated) VALUES(?,?,?) ON CONFLICT(ticket) DO UPDATE SET owner=excluded.owner,outcome='',action='',note='',version=ticket_work.version+1,updated=excluded.updated",
        (ref, worker, at),
    )
    db.run("UPDATE tickets SET operator=? WHERE id=?", (r["name"], ref))
    state(db, t, "assigned", reason, at)
    if t["urgency"] in {"Critical", "Unassessed"}:
        escalate(db, t, review_reason + "; reception owner assigned", marker, at)
    audit(db, t["hotel"], ref, "Dispatch", "Worker assigned", reason, uid, at=at)
    notify(
        db,
        t["hotel"],
        worker,
        ref,
        "assignment",
        f"Room {t['room']} · {t['department']} · {t['urgency']}",
        uid + ":staff",
        at,
    )
    notify(
        db,
        t["hotel"],
        t["guest"],
        ref,
        "assignment",
        f"{r['name']} from {t['department']} is assigned to your request.",
        uid + ":guest",
        at,
    )
    return db.one("SELECT * FROM task_assignments WHERE id=?", (uid,))


def reported(db, p, t, action, turn_id, at=None, details=""):
    """Record only validated structured actions, never arbitrary model SQL/status."""
    at = at or store.now()
    a = db.one("SELECT * FROM task_assignments WHERE ticket=? AND active=1", (t["id"],))
    legacy = db.one(
        "SELECT 1 FROM agent_actions WHERE dedupe=?", ("legacy:" + t["id"],)
    ) and db.one(
        "SELECT 1 FROM ticket_work WHERE ticket=? AND owner=?", (t["id"], p["id"])
    )
    if (a and a["staff"] != p["id"]) or (not a and not legacy):
        raise PermissionError("Only the assigned worker can report this work.")
    if t["status"] not in {"Assigned", "In progress", "Escalated"}:
        raise ValueError("This task is not awaiting a work report.")
    if action not in {"start", "complete", "blocked"}:
        raise ValueError("Clarify whether you are starting, finished, or need help.")
    if action == "complete":
        validate_completion(t)
    if a and action in {"start", "complete"}:
        db.run(
            "UPDATE task_assignments SET acknowledged=CASE WHEN acknowledged='' THEN ? ELSE acknowledged END WHERE id=?",
            (at, a["id"]),
        )
    if action == "complete":
        summary = details or "Assigned worker reports the repair/service is complete."
        db.run(
            "INSERT INTO service_outcomes VALUES(?,?,?,?,?,?,?)",
            (
                turn_id,
                t["id"],
                p["id"],
                "Fixed",
                summary,
                "Recorded through work assistant",
                at,
            ),
        )
        db.run(
            "UPDATE ticket_work SET outcome='Fixed',action=?,version=version+1,updated=? WHERE ticket=?",
            (summary, at, t["id"]),
        )
        state(
            db,
            t,
            "awaiting_confirmation",
            "Staff-reported completion; awaiting guest verification",
            at,
        )
        notify(
            db,
            t["hotel"],
            t["guest"],
            t["id"],
            "confirmation",
            "The team reports the work is complete. Is everything working now?",
            turn_id + ":confirm",
            at,
        )
    elif action == "start":
        db.run(
            "UPDATE ticket_work SET version=version+1,updated=? WHERE ticket=?",
            (at, t["id"]),
        )
        state(db, t, "in_progress", "Assigned worker acknowledged and started work", at)
        notify(
            db,
            t["hotel"],
            t["guest"],
            t["id"],
            "progress",
            "Your assigned worker has started work.",
            turn_id + ":progress",
            at,
        )
    else:
        escalate(
            db,
            t,
            "Assigned worker needs supervisor assistance.",
            turn_id + ":blocked",
            at,
        )
    audit(
        db,
        t["hotel"],
        t["id"],
        "Work assistant",
        action,
        "Validated assigned worker report",
        turn_id,
        p["id"],
        at,
    )


def validate_completion(t):
    a = json.loads(t["analysis"])
    if a.get("service_mode") == "reception_review":
        raise ValueError(
            "This is reception follow-up, not completed service. Ask the guest to update this request, then coordinate the approved service."
        )


def confirmed(db, p, ref, version, resolved):
    t = store.ticket(db, p, ref)
    at = store.now()
    db.run(
        "INSERT INTO guest_feedback VALUES(?,?,?,?,?,?,?)",
        (str(uuid4()), t["hotel"], ref, p["id"], int(resolved), version, at),
    )
    previous = db.one(
        "SELECT * FROM task_assignments WHERE ticket=? AND active=1", (ref,)
    )
    db.run(
        "UPDATE task_assignments SET active=0,ended=? WHERE ticket=? AND active=1",
        (at, ref),
    )
    state(
        db,
        t,
        "resolved" if resolved else "reopened",
        "Guest confirmed resolution" if resolved else "Guest reports the issue remains",
        at,
    )
    audit(
        db,
        t["hotel"],
        ref,
        "Resolution",
        "Confirmed" if resolved else "Reopened",
        "Guest feedback recorded",
        f"feedback:{ref}:{version}",
        p["id"],
        at,
    )
    if previous:
        notify(
            db,
            t["hotel"],
            previous["staff"],
            ref,
            "feedback",
            "Guest confirmed completion."
            if resolved
            else "Guest reports the issue is unresolved.",
            f"feedback:{ref}:{version}:staff",
            at,
        )
    if not resolved:
        dispatch(db, ref, at=at)


def migrate_preview(db):
    if not db.run(
        "INSERT INTO operation_migrations VALUES('autonomy-v1') ON CONFLICT DO NOTHING"
    ).rowcount:
        return
    for t in db.all("SELECT * FROM tickets"):
        work = db.one("SELECT owner FROM ticket_work WHERE ticket=?", (t["id"],))
        if t["status"] in {"Resolved", "Closed"} or (work and work["owner"]):
            value = {
                "Closed": "resolved",
                "Resolved": "resolved",
                "In progress": "in_progress",
                "Assigned": "assigned",
                "Awaiting confirmation": "awaiting_confirmation",
            }.get(t["status"], "escalated")
            db.run(
                "INSERT INTO service_lifecycle VALUES(?,?,?,1,?,?) ON CONFLICT DO NOTHING",
                (
                    t["id"],
                    t["hotel"],
                    value,
                    "Legacy record preserved; original ownership and status retained",
                    store.now(),
                ),
            )
            if work and work["owner"]:
                audit(
                    db,
                    t["hotel"],
                    t["id"],
                    "Migration",
                    "Legacy ownership preserved",
                    "No new assignment or deadline invented",
                    "legacy:" + t["id"],
                )
        else:
            state(
                db,
                t,
                "escalated",
                "Legacy request requires supervisor review; no automatic reassignment",
            )


def seed(db):
    from hotel.demo_accounts import ACCOUNTS, ROSTER

    for key, name, department, skills, capacity in ROSTER:
        uid = ACCOUNTS[key][2]
        db.run(
            "INSERT INTO profiles(id,hotel,role) VALUES(?,'demo',?) ON CONFLICT DO NOTHING",
            (uid, "manager" if key == "supervisor" else "staff"),
        )
        db.run(
            "INSERT INTO staff_roster(staff,hotel,name,department,skills,shift_start,shift_end,available,capacity) VALUES(?,'demo',?,?,?,'2020-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00',1,?) ON CONFLICT DO NOTHING",
            (uid, name, department, json.dumps(skills), capacity),
        )
    from hotel.demo_accounts import GUESTS

    for _, _, guest, room in GUESTS.values():
        db.run(
            "INSERT INTO profiles(id,hotel,role,room,staying_until) VALUES(?,'demo','guest',?,'2099-01-01') ON CONFLICT DO NOTHING",
            (guest, room),
        )
        db.run(
            "INSERT INTO reservations VALUES(?,'demo',?,'2020-01-01','2099-01-01',1) ON CONFLICT DO NOTHING",
            (guest, room),
        )
        db.run(
            "INSERT INTO room_inventory VALUES('demo',?,'Standard',0) ON CONFLICT DO NOTHING",
            (room,),
        )
    for priority, ack, service in [
        ("Urgent", 2, 15),
        ("Moderate", 5, 30),
        ("Low", 10, 60),
    ]:
        db.run(
            "INSERT INTO service_policies VALUES('demo',?,?,?,1) ON CONFLICT DO NOTHING",
            (priority, ack, service),
        )
