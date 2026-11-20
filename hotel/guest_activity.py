"""One authorized guest history, with no transcript or duplicated service rows."""

import json
from datetime import datetime
from typing import Literal

from fastapi import Depends, Query
from hotel import store, operations
from hotel.issue_labels import problem_label


def duration(row):
    if not row.get("timing_id"):
        return {"seconds": None, "label": "Unavailable"}
    start, end = row.get("connected_at"), row.get("ended_at")
    if not start:
        return {"seconds": None, "label": "Not connected" if end else "Connecting"}
    seconds = max(
        0,
        int(
            (
                datetime.fromisoformat(end or store.now())
                - datetime.fromisoformat(start)
            ).total_seconds()
        ),
    )
    label = f"{seconds // 60}m {seconds % 60:02d}s"
    if row.get("end_reason") == "timeout":
        label = "About " + label
    elif not end:
        label += " · live"
    return {"seconds": seconds, "label": label}


def linked_calls(db, p, refs=(), call_ids=()):
    conditions, args = [], [p["hotel"], p["id"]]
    for field, ids in [("c.ticket", refs), ("c.id", call_ids)]:
        if ids:
            conditions.append(field + " IN (" + ",".join("?" for _ in ids) + ")")
            args.extend(ids)
    if not conditions:
        return []
    rows = db.all(
        "SELECT c.id,c.ticket,c.direction,c.status,c.created,n.outcome,tm.call_id AS timing_id,tm.connected_at,tm.ended_at,tm.end_reason "
        "FROM calls c LEFT JOIN call_notes n ON n.id=c.id LEFT JOIN call_timing tm ON tm.call_id=c.id "
        "WHERE c.hotel=? AND c.guest=? AND ("
        + " OR ".join(conditions)
        + ") ORDER BY c.created,c.id",
        args,
    )
    for row in rows:
        row["duration"] = duration(row)
        row.pop("timing_id")
    return rows


def activity(db, p, source="All", state="All", search="", page=1, page_size=20):
    if p["role"] != "guest":
        raise PermissionError("Guest access required.")
    # Preserve the former Calls screen's invitation-expiry behaviour.
    store.expire_invitations(db, p["hotel"])
    cte = """WITH items AS (
      SELECT t.id,'request' AS kind,t.id AS ticket,
        CASE t.source WHEN 'Voice' THEN 'Call' WHEN 'Voice message' THEN 'Voice message' ELSE 'Text' END AS source,
        t.room,t.complaint AS problem,t.status,t.created,t.analysis,t.department,
        CASE WHEN t.status IN ('Resolved','Closed') THEN 'Resolved'
          WHEN t.status='Awaiting confirmation' OR l.reason='Guest confirmation is overdue; do not assume resolution.' THEN 'Awaiting confirmation'
          ELSE 'Open' END AS state
      FROM tickets t LEFT JOIN service_lifecycle l ON l.ticket=t.id WHERE t.hotel=? AND t.guest=?
      UNION ALL
      SELECT c.id,'call',NULL,'Call',COALESCE(n.room,''),COALESCE(NULLIF(n.issue,''),'No service request recorded'),
        CASE WHEN n.outcome='Resolved by guest' THEN 'Resolved during your call' ELSE c.status END,c.created,'{}','',
        CASE WHEN n.outcome='Resolved by guest' THEN 'Resolved' WHEN c.status IN ('Connected','Connecting','Ringing') THEN 'Open' ELSE 'Ended without request' END
      FROM calls c LEFT JOIN call_notes n ON n.id=c.id WHERE c.hotel=? AND c.guest=? AND c.ticket IS NULL
    ) """
    args = [p["hotel"], p["id"], p["hotel"], p["id"]]
    conditions = ["1=1"]
    if source != "All":
        conditions.append("source=?")
        args.append(source)
    if state != "All":
        conditions.append("state=?")
        args.append(state)
    if search.strip():
        # All values remain parameterized; wildcards are literal search text.
        term = (
            "%"
            + search.strip()
            .lower()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            + "%"
        )
        conditions.append(
            "(lower(id || ' ' || problem || ' ' || room) LIKE ? ESCAPE '\\' OR EXISTS(SELECT 1 FROM calls sc WHERE sc.ticket=items.ticket AND sc.hotel=? AND sc.guest=? AND lower(sc.id) LIKE ? ESCAPE '\\'))"
        )
        args.extend([term, p["hotel"], p["id"], term])
    where = " WHERE " + " AND ".join(conditions)
    total = db.one(cte + "SELECT COUNT(*) AS n FROM items" + where, args)["n"]
    page = min(page, max(1, (total + page_size - 1) // page_size))
    rows = db.all(
        cte
        + "SELECT * FROM items"
        + where
        + " ORDER BY created DESC,id DESC LIMIT ? OFFSET ?",
        [*args, page_size, (page - 1) * page_size],
    )
    refs = [r["id"] for r in rows if r["kind"] == "request"]
    calls = linked_calls(db, p, refs, [r["id"] for r in rows if r["kind"] == "call"])
    states = operations.snapshots(db, refs)
    for row in rows:
        analysis = json.loads(row.pop("analysis"))
        related = (
            [c for c in calls if c["ticket"] == row["ticket"]]
            if row["ticket"]
            else [c for c in calls if c["id"] == row["id"]]
        )
        row["calls"] = related
        row["reference"] = (
            related[0]["id"] if row["source"] == "Call" and related else row["id"]
        )
        row["duration"] = (
            related[0]["duration"]
            if row["source"] == "Call" and related
            else {"seconds": None, "label": "—"}
        )
        row["assignment"], row["completion_estimate"] = None, None
        if row["ticket"]:
            row["problem"] = problem_label(analysis.get("extraction", {}))
            snapshot = states[row["id"]]
            a = snapshot["assignment"]
            row["assignment"] = (
                {"name": a["name"], "department": row["department"]} if a else None
            )
            if row["state"] == "Open" and analysis.get("service_mode") == "service":
                row["completion_estimate"] = snapshot["completion_estimate"]
            if snapshot["awaiting_confirmation"]:
                row["status"] = "Awaiting your confirmation"
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def request_detail(db, p, ticket):
    """Read the related records together after the service authorizes this ticket."""
    from hotel import completion, work_orders

    ref = ticket["id"]
    with db.batch():
        work = db.run("SELECT * FROM ticket_work WHERE ticket=?", (ref,))
        note = db.run(work_orders.LATEST_NOTE, (ref,))
        life = db.run("SELECT * FROM service_lifecycle WHERE ticket=?", (ref,))
        assignment = db.run(operations.ACTIVE_ASSIGNMENT, (ref,))
        estimate = db.run(completion.ACTIVE_ESTIMATE, (ref,))
        history = db.run(
            "SELECT action,created FROM events WHERE ticket=? ORDER BY created,id",
            (ref,),
        )
        updates = db.run(
            "SELECT c.id,n.outcome,n.reply,n.language FROM calls c JOIN call_notes n ON n.id=c.id "
            "WHERE c.ticket=? AND c.hotel=? AND c.guest=? AND n.outcome IN "
            "('ETA changed','Room approval needed','Move approved','Move declined') ORDER BY c.created DESC",
            (ref, p["hotel"], p["id"]),
        )

    def first(cursor):
        row = cursor.fetchone()
        return dict(row) if row else None

    result = {
        k: ticket[k]
        for k in (
            "id",
            "room",
            "complaint",
            "status",
            "department",
            "created",
            "source",
        )
    }
    result.update(operations._snapshot(first(life), first(assignment)))
    result["work"] = work_orders.guest_work(
        ticket,
        first(work) or work_orders.empty_work(ref),
        work_orders.ticket_extraction(ticket, first(note)),
    )
    result["completion_estimate"] = completion.display(first(estimate))
    result["call_updates"] = [dict(r) for r in updates]
    guest_actions = {
        "Request received",
        "In progress",
        "Resolved",
        "Closed",
        "Awaiting confirmation",
        "Guest confirmed completion",
        "Guest requested more help",
        "Assigned",
        "Reopened",
        "Guest clarified request",
        "Completion estimate updated",
        "Pending assignment",
        "Escalated",
    }
    result["events"] = [
        dict(e)
        for e in history
        if e["action"] in guest_actions
        or e["action"].startswith(("Assigned to ", "Guest feedback:"))
    ]
    ratings = {f"Guest feedback: {stars}/5": stars for stars in range(1, 6)}
    result["rating"] = None
    if ticket["status"] in {"Resolved", "Closed"}:
        result["rating"] = next(
            (
                ratings[e["action"]]
                for e in reversed(result["events"])
                if e["action"] in ratings
            ),
            None,
        )
    return result


def register(app, context):
    @app.get("/guest/activity")
    def listing(
        source: Literal["All", "Call", "Text", "Voice message"] = "All",
        state: Literal[
            "All", "Open", "Awaiting confirmation", "Resolved", "Ended without request"
        ] = "All",
        search: str = Query(default="", max_length=150),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=50),
        ctx=Depends(context),
    ):
        return activity(*ctx, source, state, search, page, page_size)

    @app.get("/guest/requests/{ref}/calls")
    def request_calls(ref: str, ctx=Depends(context)):
        db, p = ctx
        if p["role"] != "guest":
            raise PermissionError("Guest access required.")
        store.ticket(db, p, ref)
        return linked_calls(db, p, [ref])
