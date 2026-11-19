"""Guest-facing completion estimates, separate from arrival and SLA deadlines."""

import hashlib
import json
import math
from datetime import datetime
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel, Field
from hotel import store, operations as op, work_orders


def migrate_local(db):
    if not any(
        r["name"] == "completion_minutes"
        for r in db.all("PRAGMA table_info(service_procedures)")
    ):
        db.run(
            "ALTER TABLE service_procedures ADD COLUMN completion_minutes integer CHECK(completion_minutes BETWEEN 1 AND 1440)"
        )


def seed_assignment(db, t, assignment, procedure, at):
    current = db.one(
        "SELECT * FROM service_procedures WHERE id=? AND hotel=? AND enabled=1",
        (procedure["id"], t["hotel"]),
    )
    if (
        not current
        or current["department"] != t["department"]
        or current["category"] != procedure["category"]
    ):
        return
    procedure = current
    minutes = procedure.get("completion_minutes")
    if minutes is not None:
        db.run(
            "INSERT INTO completion_estimates(assignment,ticket,hotel,expected_at,source,updated) VALUES(?,?,?,?,?,?)",
            (
                assignment,
                t["id"],
                t["hotel"],
                op.later(at, minutes),
                f"Procedure {procedure['id']} v{procedure['version']}",
                at,
            ),
        )


def display(row, active=True, at=None):
    if not row:
        return None
    result = dict(row)
    seconds = (
        datetime.fromisoformat(row["expected_at"])
        - datetime.fromisoformat(at or store.now())
    ).total_seconds()
    result.update(
        active=active,
        remaining_minutes=max(0, math.ceil(seconds / 60)),
        overdue=active and seconds <= 0,
        team_notified=row["notified_version"] == row["version"],
    )
    return result


def for_ticket(db, ref):
    row = db.one(
        "SELECT e.* FROM completion_estimates e JOIN task_assignments a ON a.id=e.assignment WHERE e.ticket=? AND a.active=1",
        (ref,),
    )
    return display(row)


def monitor(db, at):
    # Lock the ticket first, just like staff updates and guest confirmation.
    rows = db.all(
        "SELECT t.* FROM tickets t WHERE t.status IN ('Assigned','In progress','Escalated') AND EXISTS(SELECT 1 FROM completion_estimates e JOIN task_assignments a ON a.id=e.assignment WHERE e.ticket=t.id AND a.active=1 AND e.expected_at<=? AND e.notified_version<e.version) ORDER BY t.id"
        + (" FOR UPDATE OF t SKIP LOCKED" if db.pg else ""),
        (at,),
    )
    for t in rows:
        a = db.one(
            "SELECT a.staff,e.* FROM completion_estimates e JOIN task_assignments a ON a.id=e.assignment WHERE e.ticket=? AND a.active=1",
            (t["id"],),
        )
        if not a or a["expected_at"] > at or a["notified_version"] == a["version"]:
            continue
        if op.snapshot(db, t["id"])["awaiting_confirmation"]:
            continue
        marker = f"completion-overdue:{a['assignment']}:{a['version']}"
        recipients = {a["staff"]} | {
            r["id"]
            for r in db.all(
                "SELECT id FROM profiles WHERE hotel=? AND role='manager'",
                (t["hotel"],),
            )
        }
        for recipient in recipients:
            op.notify(
                db,
                t["hotel"],
                recipient,
                t["id"],
                "completion_delay",
                "The guest-facing completion estimate has passed. Check progress and update the estimate.",
                marker + ":" + recipient,
                at,
            )
        db.run(
            "UPDATE completion_estimates SET notified_version=version WHERE assignment=?",
            (a["assignment"],),
        )
        op.audit(
            db,
            t["hotel"],
            t["id"],
            "Monitor",
            "Completion estimate exceeded",
            "Owner and supervisor notified; work remains open",
            marker,
            at=at,
        )


class EstimateChange(BaseModel):
    key: UUID
    assignment_id: str = Field(min_length=1, max_length=60)
    version: int = Field(ge=0)
    minutes: int = Field(ge=1, le=1440)


def revise(db, p, ref, body):
    t = work_orders.locked(db, p, ref)
    if p["role"] not in store.STAFF:
        raise PermissionError("Staff access required.")
    digest = hashlib.sha256(
        json.dumps(
            ["completion", ref, body.assignment_id, body.version, body.minutes]
        ).encode()
    ).hexdigest()
    prior = db.one(
        "SELECT * FROM work_turns WHERE actor=? AND turn_id=?", (p["id"], str(body.key))
    )
    if prior:
        if prior["digest"] != digest:
            raise ValueError("This update key is already used.")
        return json.loads(prior["response"])
    a = db.one("SELECT * FROM task_assignments WHERE ticket=? AND active=1", (ref,))
    if (
        not a
        or a["id"] != body.assignment_id
        or (p["role"] != "manager" and a["staff"] != p["id"])
    ):
        raise PermissionError(
            "Only the current assigned worker or supervisor can change the estimate."
        )
    if (
        t["status"] not in {"Assigned", "In progress", "Escalated"}
        or op.snapshot(db, ref)["awaiting_confirmation"]
    ):
        raise ValueError("This request no longer needs a completion estimate.")
    if json.loads(t["analysis"]).get("service_mode") != "service":
        raise ValueError("Reception review has no repair completion estimate.")
    old = db.one("SELECT * FROM completion_estimates WHERE assignment=?", (a["id"],))
    if (old["version"] if old else 0) != body.version:
        raise ValueError("The estimate changed. Refresh before updating.")
    at = store.now()
    due = op.later(at, body.minutes)
    source = "Supervisor update" if p["role"] == "manager" else "Assigned worker update"
    db.run(
        "INSERT INTO completion_estimates(assignment,ticket,hotel,expected_at,source,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(assignment) DO UPDATE SET expected_at=excluded.expected_at,source=excluded.source,version=completion_estimates.version+1,updated=excluded.updated",
        (a["id"], ref, t["hotel"], due, source, at),
    )
    result = for_ticket(db, ref)
    op.audit(
        db,
        t["hotel"],
        ref,
        "Service estimate",
        "Completion estimate updated",
        f"Expected at {due}; revision {result['version']}",
        str(body.key),
        p["id"],
        at,
    )
    store.record(db, ref, "Completion estimate updated", p["id"])
    op.notify(
        db,
        t["hotel"],
        t["guest"],
        ref,
        "completion_estimate",
        "The team updated your expected completion time. Open your request for the latest estimate.",
        str(body.key) + ":guest",
        at,
    )
    db.run(
        "INSERT INTO work_turns VALUES(?,?,?,?,?)",
        (p["id"], str(body.key), digest, json.dumps(result), at),
    )
    return result


def ticket_result(db, p, ref):
    result = {}
    t = store.ticket(db, p, ref)
    a = json.loads(t["analysis"])
    from hotel.issue_labels import problem_label

    snap = op.snapshot(db, t["id"])
    assignment = snap["assignment"]
    review = a.get("service_mode") == "reception_review"
    resolved = t["status"] in {"Resolved", "Closed"}
    result.update(
        finalized=True,
        ticket=t["id"],
        room=t["room"],
        problem=problem_label(a.get("extraction", {})),
        status=t["status"],
        work_version=work_orders.current(db, t["id"])["version"],
        awaiting_confirmation=snap["awaiting_confirmation"],
        assignment={"name": assignment["name"], "department": t["department"]}
        if assignment
        else None,
        outcome="Resolved"
        if resolved
        else "Awaiting your confirmation"
        if snap["awaiting_confirmation"]
        else "Reception is following up"
        if review
        else "In progress"
        if t["status"] == "In progress"
        else "Your request is assigned"
        if assignment
        else "Reception is coordinating your request",
        completion_estimate=for_ticket(db, t["id"])
        if assignment and not (review or resolved or snap["awaiting_confirmation"])
        else None,
        next_step=a.get("pending_question", {}).get("question")
        or a.get("routing", {}).get("reason", "")
        if review
        else "",
    )
    return result


def call_result(db, p, key):
    c = db.one("SELECT * FROM calls WHERE id=?", (key,))
    if (
        not c
        or c["hotel"] != p["hotel"]
        or (p["role"] == "guest" and c["guest"] != p["id"])
    ):
        raise PermissionError("Call unavailable.")
    if p["role"] == "staff":
        store.ticket(db, p, c["ticket"])
    n = db.one("SELECT * FROM call_notes WHERE id=?", (key,)) or {}
    from hotel.guest_activity import duration

    timing = (
        db.one(
            "SELECT call_id AS timing_id,connected_at,ended_at,end_reason FROM call_timing WHERE call_id=?",
            (key,),
        )
        or {}
    )
    result = {
        "call_id": key,
        "call_duration": duration(timing),
        "created": c["created"],
        "finalized": c["status"] not in {"Ringing", "Connecting", "Connected"},
        "ticket": c["ticket"] or None,
        "room": n.get("room", ""),
        "outcome": "No service request recorded",
        "problem": "",
        "assignment": None,
        "completion_estimate": None,
        "awaiting_confirmation": False,
    }
    if not result["finalized"]:
        result["outcome"] = "Checking your request"
        return result
    if c["ticket"]:
        result.update(ticket_result(db, p, c["ticket"]))
    elif n.get("outcome") == "Resolved by guest":
        result["outcome"] = "Resolved during your call"
    return result


def register(app, identity):
    @app.get("/tickets/{ref}/result")
    def service_result(ref: str, actor=Depends(identity)):
        with store.transaction() as db:
            return ticket_result(db, store.profile(db, actor), ref)

    @app.get("/calls/{key}/result")
    def result(key: str, actor=Depends(identity)):
        with store.transaction() as db:
            return call_result(db, store.profile(db, actor), key)

    @app.post("/tickets/{ref}/completion-estimate")
    def change(ref: str, body: EstimateChange, actor=Depends(identity)):
        with store.transaction() as db:
            return revise(db, store.profile(db, actor), ref, body)
