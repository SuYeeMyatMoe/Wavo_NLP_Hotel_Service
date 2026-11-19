"""Transactional outbox with leases. Broadcast is an invalidation, never the record."""

import os
from uuid import uuid4
import requests
from hotel import store, operations as op


def publish_one(at=None, transport=None):
    at = at or store.now()
    token = str(uuid4())
    with store.transaction() as db:
        job = db.one(
            "SELECT j.*,n.recipient,n.hotel,n.ticket FROM operation_jobs j JOIN notifications n ON n.id=j.id WHERE j.due<=? AND j.lease_until<=? AND j.attempts<6 AND n.published='' ORDER BY j.due,j.id LIMIT 1"
            + (" FOR UPDATE OF j SKIP LOCKED" if db.pg else ""),
            (at, at),
        )
        if not job:
            return False
        db.run(
            "UPDATE operation_jobs SET lease_until=?,lease_token=?,attempts=attempts+1 WHERE id=?",
            (op.later(at, 1), token, job["id"]),
        )
    success = False
    try:
        if transport:
            transport(job)
        elif store.connected():
            secret = os.environ["SUPABASE_SECRET_KEY"]
            headers = {"apikey": secret}
            if not secret.startswith("sb_secret_"):
                headers["Authorization"] = "Bearer " + secret
            response = requests.post(
                os.environ["SUPABASE_URL"].rstrip("/") + "/realtime/v1/api/broadcast",
                headers=headers,
                json={
                    "messages": [
                        {
                            "topic": "wavo:user:" + job["recipient"],
                            "event": "notification",
                            "private": True,
                            "payload": {"id": job["id"]},
                        }
                    ]
                },
                timeout=10,
            )
            response.raise_for_status()
        # Preview delivery is to the durable polling inbox, not a fake cloud broadcast.
        success = True
    except (requests.RequestException, KeyError, OSError, RuntimeError):
        pass  # No response body, user text, or credentials in persistent errors.
    with store.transaction() as db:
        current = db.one("SELECT * FROM operation_jobs WHERE id=?", (job["id"],))
        if current["lease_token"] != token:
            return True
        db.run(
            "UPDATE notifications SET delivery=?,published=? WHERE id=?",
            ("published" if success else "failed", at if success else "", job["id"]),
        )
        db.run(
            "UPDATE operation_jobs SET lease_until='',lease_token='',error=?,due=? WHERE id=?",
            (
                ""
                if success
                else "Delivery unavailable; retry scheduled or limit reached",
                op.later(at, min(30, 2 ** current["attempts"] / 4)),
                job["id"],
            ),
        )
        op.audit(
            db,
            job["hotel"],
            job["ticket"],
            "Notifications",
            "Published" if success else "Delivery failed",
            "Local polling inbox" if not store.connected() else "Private Broadcast",
            f"notify:{job['id']}:{current['attempts']}",
        )
    return True
