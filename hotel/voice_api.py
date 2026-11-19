"""Call-scoped worker tools; database access stays inside the authenticated API."""

import hmac
import os
from datetime import timedelta
from uuid import uuid4
from fastapi import Depends, Header
from pydantic import BaseModel, Field
from hotel import store, concierge, case_notes
from hotel.concierge_api import worker_token, public


class WorkerInput(BaseModel):
    participant: str = Field(default="", max_length=100)
    text: str = Field(default="", max_length=8000)
    turn_id: str = Field(default="", max_length=100)


def register(app, identity):
    @app.post("/work-assistant/sessions")
    def work_session(actor=Depends(identity)):
        from livekit import api

        if not store.voice_ready():
            raise ValueError(
                "Configure LiveKit and Gemini for a live work-assistant call."
            )
        with store.transaction() as db:
            p = store.profile(db, actor)
            if p["role"] not in store.STAFF:
                raise PermissionError("Staff access required.")
            key = "work-" + str(uuid4())
            db.run(
                "INSERT INTO work_sessions VALUES(?,?,?,'Connected',?)",
                (key, p["hotel"], actor, store.now()),
            )
            token = (
                api.AccessToken()
                .with_identity(actor)
                .with_ttl(timedelta(minutes=3))
                .with_grants(
                    api.VideoGrants(
                        room_join=True,
                        room=key,
                        can_publish_data=False,
                        can_update_own_metadata=False,
                    )
                )
                .with_room_config(
                    api.RoomConfiguration(
                        agents=[api.RoomAgentDispatch(agent_name="hotel-reception")]
                    )
                )
                .to_jwt()
            )
            return {"id": key, "token": token, "url": os.environ["LIVEKIT_URL"]}

    @app.post("/work-assistant/sessions/{key}/end")
    def end_work(key: str, actor=Depends(identity)):
        with store.transaction() as db:
            if not db.one(
                "SELECT id FROM work_sessions WHERE id=? AND staff=?", (key, actor)
            ):
                raise PermissionError("Session unavailable.")
            db.run("UPDATE work_sessions SET status='Ended' WHERE id=?", (key,))
            return {"ended": True}

    @app.post("/internal/calls/{key}/tools/{tool}")
    def worker_tool(
        key: str, tool: str, body: WorkerInput, x_worker_token: str = Header(default="")
    ):
        if not hmac.compare_digest(worker_token(key), x_worker_token):
            raise PermissionError("Worker authentication required.")
        with store.transaction() as db:
            if tool == "connect" and not key.startswith("work-"):
                call = db.one(
                    "SELECT c.*,n.language,n.room,n.issue,n.engine FROM calls c LEFT JOIN call_notes n ON n.id=c.id WHERE c.id=?",
                    (key,),
                )
                if (
                    not call
                    or body.participant != call["guest"]
                    or call["status"] not in concierge.ACTIVE
                ):
                    raise PermissionError("Call unavailable.")
                p = store.profile(db, call["guest"])
                if not store.active(p) or (
                    call["direction"] == "Outbound" and not p["consent"]
                ):
                    raise PermissionError("Call unavailable.")
                n = (
                    call
                    if call["engine"]
                    else concierge.ensure_note(db, key, p, "live")
                )
                db.run("UPDATE calls SET status='Connected' WHERE id=?", (key,))
                return {
                    "role": "guest",
                    "language": n["language"],
                    "issue": n["issue"],
                    "room": n["room"],
                }
            if tool == "spoken" and not key.startswith("work-"):
                privacy = db.one(
                    "SELECT c.status,p.consent FROM calls c LEFT JOIN call_privacy p ON p.call_id=c.id WHERE c.id=?",
                    (key,),
                )
                if not privacy or privacy["status"] not in concierge.ACTIVE:
                    raise PermissionError("Call ended.")
                if not privacy["consent"]:
                    return {"processed": True}
            if tool == "state":
                row = db.one(
                    "SELECT status,0 AS version,'' AS outcome,'' AS reply FROM work_sessions WHERE id=?",
                    (key,),
                )
                if not row:
                    row = db.one(
                        "SELECT c.status,n.version,n.outcome,n.reply FROM calls c JOIN call_notes n ON n.id=c.id WHERE c.id=?",
                        (key,),
                    )
                if not row:
                    raise PermissionError("Call unavailable.")
                return row
            work = db.one("SELECT * FROM work_sessions WHERE id=?", (key,))
            if work:
                if work["status"] != "Connected" and tool != "state":
                    raise PermissionError("Work session ended.")
                p = store.profile(db, work["staff"])
                if p["role"] not in store.STAFF or p["hotel"] != work["hotel"]:
                    raise PermissionError("Staff session unavailable.")
                if tool == "connect":
                    if body.participant != work["staff"]:
                        raise PermissionError("Participant mismatch.")
                    return {"role": "staff", "language": "English", "issue": ""}
                if tool == "state":
                    return {"status": work["status"], "version": 0, "outcome": ""}
                if tool == "end":
                    db.run("UPDATE work_sessions SET status='Ended' WHERE id=?", (key,))
                    return {"ended": True}
                if tool != "work-report":
                    raise PermissionError("Tool unavailable to a staff session.")
                actor = work["staff"]
            else:
                call = db.one("SELECT * FROM calls WHERE id=?", (key,))
                if not call:
                    raise PermissionError("Call unavailable.")
                p = store.profile(db, call["guest"])
                if tool == "connect":
                    if (
                        body.participant != call["guest"]
                        or call["status"] not in concierge.ACTIVE
                        or not store.active(p)
                        or (call["direction"] == "Outbound" and not p["consent"])
                    ):
                        raise PermissionError("Call unavailable.")
                    n = concierge.ensure_note(db, key, p, "live")
                    db.run("UPDATE calls SET status='Connected' WHERE id=?", (key,))
                    return {
                        "role": "guest",
                        "language": n["language"],
                        "issue": n["issue"],
                        "room": n["room"],
                    }
                n = concierge.note(db, key, lock=True)
                if tool == "state":
                    return public(n)
                if tool == "end":
                    if (
                        n["status"] != "Ended"
                        and n["outcome"] != "Speaking with reception"
                    ):
                        concierge.finish(db, key)
                    return {"ended": True}
                if n["status"] not in concierge.ACTIVE:
                    raise PermissionError("Call ended.")
                if tool == "policy":
                    from hotel.knowledge import retrieve

                    return retrieve(db, p["hotel"], body.text)
                if tool == "spoken":
                    if case_notes.consented(db, key):
                        from hotel.intelligence import mask_pii

                        db.run(
                            "INSERT INTO call_transcripts VALUES(?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                            (
                                str(uuid4()),
                                key,
                                body.turn_id,
                                "assistant",
                                mask_pii(body.text),
                                "",
                                n["language"],
                                store.now(),
                            ),
                        )
                        rows = db.all(
                            "SELECT speaker,original FROM call_transcripts WHERE call_id=? ORDER BY created,id",
                            (key,),
                        )
                        db.run(
                            "UPDATE calls SET transcript=? WHERE id=?",
                            (
                                "\n".join(
                                    r["speaker"] + ": " + r["original"] for r in rows
                                ),
                                key,
                            ),
                        )
                    return {"processed": True}
                raise PermissionError("Unknown worker tool.")
        from hotel.work_assistant import submit

        return submit(actor, body.turn_id, body.text, session_key=key)
