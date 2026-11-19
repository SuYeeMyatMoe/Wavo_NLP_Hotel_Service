"""Durable deadline monitoring; safe to restart or run in multiple processes."""

from hotel import store, operations as op


def tick(at=None):
    at = at or store.now()
    with store.transaction() as db:
        from hotel.completion import monitor

        monitor(db, at)
        rows = db.all(
            "SELECT t.* FROM tickets t JOIN service_lifecycle l ON l.ticket=t.id WHERE l.state NOT IN ('resolved','escalated') ORDER BY t.id"
            + (" FOR UPDATE OF t SKIP LOCKED" if db.pg else "")
        )
        for t in rows:
            ref = t["id"]
            a = db.one(
                "SELECT * FROM task_assignments WHERE ticket=? AND active=1", (ref,)
            )
            if not a:
                continue
            if t["status"] == "Awaiting confirmation":
                life = db.one("SELECT * FROM service_lifecycle WHERE ticket=?", (ref,))
                if at >= op.later(life["updated"], 1440):
                    op.escalate(
                        db,
                        t,
                        "Guest confirmation is overdue; do not assume resolution.",
                        a["id"] + ":confirm-overdue",
                        at,
                    )
                elif at >= op.later(life["updated"], 30):
                    op.notify(
                        db,
                        t["hotel"],
                        t["guest"],
                        ref,
                        "reminder",
                        "Please confirm whether the service solved your problem.",
                        a["id"] + ":confirm-reminder",
                        at,
                    )
                continue
            if at >= a["service_due"]:
                op.escalate(
                    db,
                    t,
                    "Service target exceeded; assigned work remains with its owner.",
                    a["id"] + ":service-overdue",
                    at,
                )
                continue
            if a["acknowledged"] or at < a["ack_due"]:
                continue
            if not a["reminded"]:
                db.run(
                    "UPDATE task_assignments SET reminded=? WHERE id=?", (at, a["id"])
                )
                op.notify(
                    db,
                    t["hotel"],
                    a["staff"],
                    ref,
                    "reminder",
                    "Please acknowledge your assignment through the work assistant.",
                    a["id"] + ":ack-reminder",
                    at,
                )
                op.audit(
                    db,
                    t["hotel"],
                    ref,
                    "Monitor",
                    "Acknowledgment reminder",
                    "Assignment is unstarted",
                    a["id"] + ":reminder",
                    at=at,
                )
                continue
            policy = db.one(
                "SELECT ack_minutes,service_minutes FROM service_policies WHERE hotel=? AND priority=?",
                (t["hotel"], t["urgency"]),
            )
            if not policy:
                continue
            ack_minutes, _ = op.assignment_windows(
                t["hotel"], t["department"], a["staff"], policy
            )
            if at < op.later(a["reminded"], ack_minutes):
                continue
            # One automatic replacement per service attempt, reset only by guest reopening.
            feedback = db.one(
                "SELECT COUNT(*) AS n FROM guest_feedback WHERE ticket=? AND resolved=0",
                (ref,),
            )["n"]
            replacements = db.one(
                "SELECT COUNT(*) AS n FROM agent_actions WHERE ticket=? AND action=?",
                (ref, f"Reassignment cycle {feedback}"),
            )["n"]
            if replacements:
                op.escalate(
                    db,
                    t,
                    "Replacement worker has not acknowledged; supervisor review required.",
                    a["id"] + ":ack-overdue",
                    at,
                )
                continue
            db.run(
                "UPDATE task_assignments SET active=0,ended=? WHERE id=?", (at, a["id"])
            )
            db.run(
                "UPDATE ticket_work SET owner='',version=version+1 WHERE ticket=?",
                (ref,),
            )
            op.audit(
                db,
                t["hotel"],
                ref,
                "Monitor",
                f"Reassignment cycle {feedback}",
                "Unstarted assignment released after reminder",
                a["id"] + ":reassign",
                at=at,
            )
            op.notify(
                db,
                t["hotel"],
                a["staff"],
                ref,
                "reassigned",
                "Your unstarted assignment was released after the acknowledgment deadline.",
                a["id"] + ":released",
                at,
            )
            op.dispatch(db, ref, exclude=(a["staff"],), at=at)
