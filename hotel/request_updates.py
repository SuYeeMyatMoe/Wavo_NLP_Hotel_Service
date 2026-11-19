"""Guest clarification of an existing service record, with immutable NLP history."""

import hashlib
import json
from uuid import uuid4

from hotel import store, operations, work_orders, case_notes


def can_clarify(t):
    a = json.loads(t["analysis"]) if isinstance(t["analysis"], str) else t["analysis"]
    return t["status"] not in {"Resolved", "Closed", "Awaiting confirmation"} and (
        a.get("service_mode") == "reception_review"
        or (t["status"] == "Escalated" and a.get("service_mode") != "service")
    )


def clarify(actor, ref, key, version, text, agreement):
    from hotel.languages import guest_analysis
    from hotel.procedures import select

    digest = hashlib.sha256(
        json.dumps(["clarify", ref, version, text, agreement]).encode()
    ).hexdigest()

    def authorize(db):
        p = store.profile(db, actor)
        t = work_orders.locked(db, p, ref)
        if p["role"] != "guest" or t["guest"] != actor or not store.active(p):
            raise PermissionError(
                "Only the guest on this reservation can update the request."
            )
        prior = db.one(
            "SELECT * FROM work_turns WHERE actor=? AND turn_id=?", (actor, key)
        )
        if prior:
            if prior["digest"] != digest:
                raise ValueError("This update identifier is already used.")
            return p, t, json.loads(prior["response"])
        old = json.loads(t["analysis"])
        active = db.one(
            "SELECT id FROM task_assignments WHERE ticket=? AND active=1", (ref,)
        )
        if not can_clarify(t) or (
            active and old.get("service_mode") != "reception_review"
        ):
            raise ValueError(
                "Service is already underway. Contact the assigned team for changes."
            )
        if work_orders.current(db, ref)["version"] != version:
            raise ValueError("This request changed. Refresh before updating.")
        if p["room"] != t["room"]:
            raise ValueError(
                "Your reservation room changed. Reception must verify the service destination."
            )
        return p, t, None

    with store.transaction() as db:
        _, _, prior = authorize(db)
        if prior:
            return prior
    # Translation and inference run outside the write transaction.
    analysis = guest_analysis(text, "auto")
    with store.transaction() as db:
        p, t, prior = authorize(db)
        if prior:
            return prior
        a = case_notes.minimal(analysis)
        a["extraction"]["verified_room"] = t["room"]
        a["solution"] = select(db, p["hotel"], a["extraction"], a["urgency"])
        physical = any(
            r["department"] in {"Maintenance", "Housekeeping"}
            for r in a["solution"].get("procedures", [])
        )
        if physical and not agreement:
            a["pending_question"] = {
                "field": "service_agreement",
                "question": "May the hotel arrange physical service?",
            }
        a["service_agreement"] = bool(agreement)
        at = store.now()
        previous = db.one(
            "SELECT staff,id FROM task_assignments WHERE ticket=? AND active=1", (ref,)
        )
        db.run(
            "UPDATE task_assignments SET active=0,ended=? WHERE ticket=? AND active=1",
            (at, ref),
        )
        db.run(
            "INSERT INTO ticket_work(ticket,updated) VALUES(?,?) ON CONFLICT(ticket) DO UPDATE SET owner='',version=ticket_work.version+1,updated=excluded.updated",
            (ref, at),
        )
        db.run(
            "UPDATE tickets SET complaint=?,analysis=?,urgency=?,department=? WHERE id=?",
            (a["text"], json.dumps(a), a["urgency"], a["department"], ref),
        )
        db.run(
            "INSERT INTO nlp_analysis VALUES(?,?,?,?,?,?,?)",
            (str(uuid4()), p["hotel"], None, ref, key, json.dumps(a), at),
        )
        store.record(db, ref, "Guest clarified request", actor)
        operations.audit(
            db,
            p["hotel"],
            ref,
            "Service recovery",
            "Guest clarification",
            "New structured analysis; original evidence preserved",
            key,
            actor,
            at,
        )
        if previous:
            operations.notify(
                db,
                p["hotel"],
                previous["staff"],
                ref,
                "updated",
                "Guest updated the request. Check the new assignment before continuing.",
                key + ":previous",
                at,
            )
        assigned = operations.dispatch(db, ref, at=at)
        response = {"id": ref, "assigned": bool(assigned), "saved": True}
        db.run(
            "INSERT INTO work_turns VALUES(?,?,?,?,?)",
            (actor, key, digest, json.dumps(response), at),
        )
        return response
