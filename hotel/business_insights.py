"""Read-only operational metrics with explicit scope, denominators and missing data."""

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median

from hotel import operations
from hotel.issue_labels import problem_label, MISSING
from hotel.work_orders import PRIORITY

CLOSED = {"Resolved", "Closed"}
CONFIRMED = {"Guest confirmed completion", "Manager verified completion"}


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        return None


def summarize(tickets, events, states, calls, days=30, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = (
        (now - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if days
        else None
    )

    def in_period(value):
        at = timestamp(value)
        return bool(at and at <= now and (cutoff is None or at >= cutoff))

    grouped = defaultdict(list)
    for event in events:
        grouped[event["ticket"]].append(event)
    cohort = [t for t in tickets if in_period(t["created"])]
    current = [t for t in tickets if t["status"] not in CLOSED]
    categories, sentiments, durations = Counter(), Counter(), []
    reopened = confirmed = missing_problem = missing_completion = 0
    demand = defaultdict(lambda: {"Opened": 0, "Confirmed": 0})
    for t in tickets:
        confirmations = [
            e
            for e in grouped[t["id"]]
            if e["action"] in CONFIRMED and timestamp(e["created"])
        ]
        # Count each request once at its latest explicit confirmation, not once
        # per repair attempt, and never treat a generic Resolved status as proof.
        if confirmations and t["status"] in CLOSED:
            final = max(confirmations, key=lambda e: timestamp(e["created"]))
            if in_period(final["created"]):
                demand[timestamp(final["created"]).date().isoformat()]["Confirmed"] += 1
        if not in_period(t["created"]):
            continue
        demand[timestamp(t["created"]).date().isoformat()]["Opened"] += 1
        analysis = json.loads(t["analysis"])
        ex = analysis.get("extraction", {})
        label = problem_label(ex)
        missing_problem += label == MISSING
        category = ex.get("topic", "Not recorded")
        categories[
            "Needs clarification" if category == "General request" else category
        ] += 1
        sentiments[analysis.get("sentiment", {}).get("label", "Not recorded")] += 1
        reopened += any(
            e["action"] == "Guest requested more help" for e in grouped[t["id"]]
        )
        if confirmations and t["status"] in CLOSED:
            elapsed = (
                timestamp(final["created"]) - timestamp(t["created"])
            ).total_seconds() / 60
            if elapsed >= 0 and timestamp(final["created"]) <= now:
                confirmed += 1
                durations.append(elapsed)
        elif t["status"] in CLOSED:
            missing_completion += 1

    alerts, workloads, problems = [], {}, Counter()
    overdue = unacknowledged = awaiting = unassigned = missing_deadlines = escalated = 0
    for t in sorted(
        current, key=lambda t: (PRIORITY.get(t["urgency"], 5), t["created"], t["id"])
    ):
        state = states.get(t["id"], {})
        assignment = state.get("assignment") or {}
        pending = (
            state.get("awaiting_confirmation") or t["status"] == "Awaiting confirmation"
        )
        awaiting += bool(pending)
        escalated += t["status"] == "Escalated"
        service_due = timestamp(assignment.get("service_due"))
        ack_due = timestamp(assignment.get("ack_due"))
        service_late = bool(not pending and service_due and service_due < now)
        ack_late = bool(
            not pending
            and not assignment.get("acknowledged")
            and t["status"] != "In progress"
            and ack_due
            and ack_due < now
        )
        overdue += service_late
        unacknowledged += ack_late
        missing_deadlines += not pending and service_due is None
        no_owner = not assignment and not t.get("owner")
        unassigned += no_owner and not pending
        analysis = json.loads(t["analysis"])
        label = problem_label(analysis.get("extraction", {}))
        problems[label] += 1
        worker = assignment.get("name") or (
            "Assigned staff (legacy record)"
            if t.get("owner")
            else "Unassigned / reception"
        )
        group = (worker, t["department"])
        bucket = workloads.setdefault(
            group,
            {
                "Team member": worker,
                "Department": t["department"],
                "Open": 0,
                "In progress": 0,
                "Awaiting guest": 0,
                "Overdue": 0,
            },
        )
        bucket["Open"] += 1
        bucket["In progress"] += t["status"] == "In progress"
        bucket["Awaiting guest"] += bool(pending)
        bucket["Overdue"] += service_late
        reasons = []
        action = "Review request and coordinate the next step"
        if t["urgency"] in {"Critical", "Unassessed"}:
            reasons.append("Immediate human review")
            action = "Review safety / urgency with reception"
        if service_late:
            reasons.append("Service target missed")
            action = "Check progress and update the guest; do not assume completion"
        if ack_late:
            reasons.append("Not acknowledged on time")
        if pending:
            reasons.append("Guest confirmation needed")
            action = "Follow up with the guest; silence does not close the request"
        elif no_owner:
            reasons.append("No assigned worker")
            action = "Review guidance, guest agreement and roster availability"
        if t["status"] == "Escalated":
            reasons.append("Escalated to reception")
        if t["urgency"] in {"Critical", "Unassessed"}:
            action = "Review safety / urgency with reception immediately"
        created = timestamp(t["created"])
        if reasons:
            alerts.append(
                {
                    "id": t["id"],
                    "Room": t["room"],
                    "Problem": label,
                    "Priority": t["urgency"],
                    "Needs attention": " · ".join(reasons),
                    "Next step": action,
                    "Open (min)": max(0, int((now - created).total_seconds() / 60))
                    if created
                    else None,
                }
            )

    call_cohort = [
        c for c in calls if in_period(c["created"]) and c["direction"] == "Inbound"
    ]
    ended = [c for c in call_cohort if c["status"] == "Ended"]
    self_service = sum(
        c.get("outcome") == "Resolved by guest"
        and not c.get("ticket")
        and not c.get("staff_id")
        for c in ended
    )
    if cutoff:
        for offset in range(days):
            demand[(cutoff + timedelta(days=offset)).date().isoformat()]
    return {
        "scope": "",
        "days": days,
        "as_of": now.isoformat(),
        "tickets": len(cohort),
        "unresolved": len(current),
        "reopened": reopened,
        "categories": dict(categories),
        "sentiments": dict(sentiments),
        "call_sentiment": [],
        "resolution_minutes": mean(durations) if durations else None,
        "median_resolution_minutes": median(durations) if durations else None,
        "resolution_sample": len(durations),
        "confirmed": confirmed,
        "confirmation_rate": confirmed / len(cohort) if cohort else None,
        "reopen_rate": reopened / len(cohort) if cohort else None,
        "missing_problem": missing_problem,
        "missing_completion": missing_completion,
        "current": {
            "attention": len(alerts),
            "overdue_service": overdue,
            "overdue_ack": unacknowledged,
            "awaiting_guest": awaiting,
            "unassigned": unassigned,
            "missing_deadlines": missing_deadlines,
            "escalated": escalated,
        },
        "attention": alerts,
        "workload": sorted(
            workloads.values(),
            key=lambda r: (-r["Overdue"], -r["Open"], r["Team member"]),
        ),
        "open_problems": [
            {"Problem": name, "Requests": count}
            for name, count in problems.most_common()
        ],
        "daily": [{"Date": day, **counts} for day, counts in sorted(demand.items())],
        "calls": {
            "total": len(call_cohort),
            "ended": len(ended),
            "self_service": self_service,
        },
        "repeat_rooms": [
            {"Room": room, "Requests": count}
            for room, count in Counter(t["room"] for t in cohort).most_common()
            if count > 1
        ],
    }


def report(db, profile, days=30):
    args = [profile["hotel"]]
    scope = "t.hotel=?"
    if profile["role"] == "staff":
        scope += (
            " AND EXISTS(SELECT 1 FROM ticket_work w WHERE w.ticket=t.id AND w.owner=?)"
        )
        args.append(profile["id"])
    tickets = db.all(
        "SELECT t.id,t.room,t.created,t.status,t.urgency,t.department,t.analysis,(SELECT owner FROM ticket_work w WHERE w.ticket=t.id) AS owner FROM tickets t WHERE "
        + scope,
        args,
    )
    events = db.all(
        "SELECT e.ticket,e.action,e.created FROM events e JOIN tickets t ON t.id=e.ticket WHERE "
        + scope,
        args,
    )
    call_scope = "c.hotel=?"
    if profile["role"] == "staff":
        call_scope += " AND EXISTS(SELECT 1 FROM ticket_work w WHERE w.ticket=c.ticket AND w.owner=?)"
    calls = db.all(
        "SELECT c.created,c.status,c.direction,c.ticket,n.outcome,n.staff_id FROM calls c LEFT JOIN call_notes n ON n.id=c.id WHERE "
        + call_scope,
        args,
    )
    data = summarize(
        tickets,
        events,
        operations.snapshots(db, [t["id"] for t in tickets]),
        calls,
        days,
    )
    data["scope"] = "Your assigned work" if profile["role"] == "staff" else "Hotel-wide"
    return data
