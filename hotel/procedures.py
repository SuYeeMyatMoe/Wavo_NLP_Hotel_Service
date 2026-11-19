"""Hotel-scoped category and condition matching. No vector retrieval."""

import json

CATEGORIES = [
    "Air conditioning",
    "Plumbing",
    "Wi-Fi",
    "Housekeeping",
    "Billing",
    "Electrical",
    "Food and drink",
]
DEPARTMENTS = ["Maintenance", "Housekeeping", "Front Desk"]


def seed(db):
    examples = [
        (
            "ac",
            "Air conditioning",
            "Maintenance",
            "Quiet AC repair",
            "Confirm access and quiet-service preferences. Inspect the AC and test cooling after repair. Record the action taken and ask the guest to confirm.",
            "Room moves require front-desk approval.",
        ),
        (
            "plumbing",
            "Plumbing",
            "Maintenance",
            "Plumbing repair",
            "Confirm the affected fixture and access permission. Inspect and repair the fault, test for leaks and ask the guest to confirm.",
            "",
        ),
        (
            "wifi",
            "Wi-Fi",
            "Front Desk",
            "Guest Wi-Fi connection",
            "Select Hotel-Guest in Wi-Fi settings. Open a browser and choose Guest access on the welcome page.",
            "",
        ),
        (
            "housekeeping",
            "Housekeeping",
            "Housekeeping",
            "Housekeeping service",
            "Confirm the requested items and access permission. Deliver the items or complete cleaning, then request guest confirmation.",
            "",
        ),
    ]
    for key, category, team, title, body, approval in examples:
        db.run(
            "INSERT INTO service_procedures(id,hotel,category,department,title,body,approval,completion_minutes) VALUES(?,'demo',?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (
                "demo-" + key,
                category,
                team,
                title,
                body,
                approval,
                15 if key == "ac" else None,
            ),
        )
    if db.run(
        "INSERT INTO operation_migrations VALUES('completion-demo-default-v1') ON CONFLICT DO NOTHING"
    ).rowcount:
        db.run(
            "UPDATE service_procedures SET completion_minutes=15 WHERE id='demo-ac' AND hotel='demo' AND completion_minutes IS NULL"
        )


def select(db, hotel, extracted, urgency="Moderate"):
    base = {
        "procedures": [],
        "questions": [],
        "approval": "",
        "method": "Category and hotel rules",
    }
    if urgency in {"Critical", "Unassessed"}:
        return {
            **base,
            "next_action": "Front desk must review the original complaint and coordinate a safe response.",
            "reason": "Safety escalation"
            if urgency == "Critical"
            else "Urgency requires staff review",
        }
    if (
        extracted.get("reported_room")
        and extracted.get("verified_room")
        and extracted["reported_room"] != extracted["verified_room"]
    ):
        return {
            **base,
            "next_action": "Confirm the room reference with the guest. The verified reservation remains the destination.",
            "reason": "Reported room differs from verified reservation.",
            "questions": [
                {
                    "field": "room_reference",
                    "question": "Is this problem in your reserved room?",
                }
            ],
        }
    issues = extracted.get("issues", [])
    active = {i["topic"] for i in issues if i["state"] == "active"}
    if len(active) > 1:
        return {
            **base,
            "next_action": "Ask reception to coordinate the multiple active issues.",
            "reason": "Multiple issue categories need review.",
        }
    if issues and all(i["state"] in {"resolved", "denied"} for i in issues):
        return {
            **base,
            "next_action": "Confirm whether any help is still needed.",
            "reason": "No active issue was identified.",
        }
    labels = {c["constraint"] for c in extracted.get("constraints", [])}
    rows = db.all(
        "SELECT * FROM service_procedures WHERE hotel=? AND category=? AND enabled=1 ORDER BY id",
        (hotel, extracted["topic"]),
    )
    rows = [r for r in rows if set(json.loads(r["constraints"])) <= labels]
    if rows:
        specificity = max(len(json.loads(r["constraints"])) for r in rows)
        rows = [r for r in rows if len(json.loads(r["constraints"])) == specificity]
    if len(rows) != 1:
        return {
            **base,
            "next_action": "Ask reception to confirm the next action.",
            "reason": "Conflicting approved procedures."
            if rows
            else "No approved category procedure is available.",
        }
    row = rows[0]
    conditions = json.loads(row["constraints"])
    known = labels | {
        k
        for k in ("room", "issue", "equipment")
        if extracted.get(
            {"room": "verified_room", "issue": "issue", "equipment": "topic"}[k]
        )
    }
    questions = [q for q in json.loads(row["questions"]) if q["field"] not in known]
    reason = (
        "Exact category: "
        + row["category"]
        + (
            " · " + ", ".join(conditions)
            if conditions
            else " · default hotel procedure"
        )
    )
    if "Access permission needs clarification" in labels:
        questions.insert(
            0,
            {
                "field": "Access permission needs clarification",
                "question": "What time would you allow the team to enter?",
            },
        )
    return {
        **base,
        "procedures": [{**row, "match_reason": reason}],
        "next_action": row["body"],
        "reason": reason,
        "questions": questions,
        "approval": row["approval"],
    }
