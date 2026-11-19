"""Repair unowned demo follow-ups through the real dispatcher; dry run by default.

Does not infer discarded complaint text, guest consent, or completed work.
"""

import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def recover(apply=False):
    from hotel import store, operations
    from hotel.issue_labels import problem_label, MISSING

    load_dotenv(ROOT / ".env", override=True)
    if (
        os.getenv("SUPABASE_URL", "").rstrip("/")
        != "https://kerxsqouptjqguoeivto.supabase.co"
        or os.getenv("HOTEL_MODE") != "connected"
    ):
        raise RuntimeError(
            "Recovery is restricted to the configured Wavo demo project."
        )
    with store.transaction() as db:
        if db.one(
            "SELECT COUNT(*) AS n FROM calls WHERE hotel='demo' AND status IN ('Connected','Connecting','Ringing')"
        )["n"]:
            raise RuntimeError("A demo call is active; retry after it ends.")
        rows = db.all(
            "SELECT t.* FROM tickets t WHERE t.hotel='demo' AND t.status='Escalated' AND NOT EXISTS(SELECT 1 FROM task_assignments a WHERE a.ticket=t.id AND a.active=1) ORDER BY t.id FOR UPDATE OF t"
        )
        assigned = 0
        for t in rows:
            if not apply:
                continue
            a = json.loads(t["analysis"])
            # Old hang-up code asked for a room visit even for remote Wi-Fi help.
            if (
                a.get("extraction", {}).get("topic") == "Wi-Fi"
                and a.get("pending_question", {}).get("field") == "service_agreement"
            ):
                a.pop("pending_question")
                a["reception_followup"] = True
                db.run(
                    "UPDATE tickets SET analysis=? WHERE id=?", (json.dumps(a), t["id"])
                )
            operations.audit(
                db,
                t["hotel"],
                t["id"],
                "Service recovery",
                "Rechecked unowned follow-up",
                "Restored ownership using trusted roster; no physical consent inferred",
                "recovery-v1:" + t["id"],
            )
            if operations.dispatch(db, t["id"]):
                assigned += 1
            if problem_label(a.get("extraction", {})) == MISSING or a.get(
                "pending_question"
            ):
                operations.notify(
                    db,
                    t["hotel"],
                    t["guest"],
                    t["id"],
                    "clarification",
                    "Reception needs more information. Open this request in My requests to describe the issue and confirm whether you want service.",
                    "recovery-clarify:" + t["id"],
                )
        # Approved remote guidance can be delivered by its reception owner now;
        # it does not authorize a physical room visit or claim guest resolution.
        from hotel.procedures import select

        guidance_ready = 0
        for t in db.all(
            "SELECT t.* FROM tickets t JOIN task_assignments a ON a.ticket=t.id AND a.active=1 WHERE t.hotel='demo' AND t.department='Front Desk' AND t.status IN ('Assigned','In progress') ORDER BY t.id FOR UPDATE OF t"
        ):
            a = json.loads(t["analysis"])
            if (
                a.get("service_mode") != "reception_review"
                or a.get("extraction", {}).get("topic") != "Wi-Fi"
                or a.get("pending_question")
            ):
                continue
            solution = select(db, t["hotel"], a["extraction"], t["urgency"])
            if (
                not solution.get("procedures")
                or solution.get("questions")
                or solution["procedures"][0]["department"] != "Front Desk"
            ):
                continue
            if apply:
                a.update(
                    service_mode="service", reception_followup=False, solution=solution
                )
                a["routing"]["reason"] = "Approved procedure department"
                db.run(
                    "UPDATE tickets SET analysis=? WHERE id=?", (json.dumps(a), t["id"])
                )
                db.run(
                    "UPDATE ticket_work SET version=version+1,updated=? WHERE ticket=?",
                    (store.now(), t["id"]),
                )
                operations.audit(
                    db,
                    t["hotel"],
                    t["id"],
                    "Service recovery",
                    "Approved reception guidance ready",
                    "Existing owner can provide approved Wi-Fi guidance; guest confirmation still required",
                    "recovery-guidance-v1:" + t["id"],
                )
                guidance_ready += 1
        print(
            json.dumps(
                {
                    "eligible_unowned_records": len(rows),
                    "assigned": assigned,
                    "reception_guidance_ready": guidance_ready,
                    "applied": apply,
                }
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    try:
        recover(parser.parse_args().apply)
    except Exception as exc:
        print(
            str(exc)
            if isinstance(exc, RuntimeError)
            else f"Recovery failed ({type(exc).__name__}); transaction rolled back.",
            file=sys.stderr,
        )
        sys.exit(1)
