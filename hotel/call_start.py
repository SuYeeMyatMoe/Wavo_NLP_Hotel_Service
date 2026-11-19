"""Atomic browser call startup and cancellation. No provider secrets leave the API."""

from uuid import UUID, uuid4
import os

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from hotel import store, concierge


class StartCall(BaseModel):
    key: UUID
    transcript_consent: bool = False


def lock_guest(db, actor, require_active=True):
    # Serialize both start and cancel, including cancellation before start arrives.
    p = store.profile(db, actor, lock=True)
    if p["role"] != "guest" or (require_active and not store.active(p)):
        raise PermissionError("An active guest stay is required.")
    return p


def register(app, identity, credentials):
    @app.post("/calls/start")
    def start(body: StartCall, actor=Depends(identity)):
        with store.transaction() as db:
            p = lock_guest(db, actor)
            old = db.one(
                "SELECT * FROM call_starts WHERE actor=? AND request_key=?",
                (actor, str(body.key)),
            )
            if old:
                if old["cancelled"]:
                    raise HTTPException(
                        409, "This call attempt has ended. Start a new call."
                    )
                if old["consent"] != int(body.transcript_consent):
                    raise HTTPException(
                        409, "This startup key was used with different consent."
                    )
                key = old["call_id"]
                n = concierge.note(db, key)
                privacy = db.one(
                    "SELECT consent FROM call_privacy WHERE call_id=?", (key,)
                )
                consent = bool(privacy and privacy["consent"])
            else:
                n = db.one(
                    "SELECT c.id,c.status,n.room,n.engine,cp.consent FROM calls c JOIN call_notes n ON n.id=c.id LEFT JOIN call_privacy cp ON cp.call_id=c.id WHERE c.guest=? AND c.direction='Inbound' AND c.status IN ('Ringing','Connecting','Connected')",
                    (actor,),
                )
                if n:
                    key, consent = n["id"], bool(n["consent"])
                else:
                    key = str(uuid4())
                    local = (
                        os.getenv("CONCIERGE_MODE", "auto") == "local"
                        or not store.voice_ready()
                    )
                    n = {
                        "room": p["room"],
                        "engine": "local" if local else "live",
                        "status": "Connected" if local else "Connecting",
                    }
                    pref = db.one(
                        "SELECT language FROM guest_languages WHERE guest=?", (actor,)
                    )
                    language = pref["language"] if pref else "en"
                    consent = body.transcript_consent
                    with db.batch():
                        db.run(
                            "INSERT INTO calls(id,hotel,guest,direction,status,operator,created) VALUES(?,?,?,'Inbound',?,'AI Reception',?)",
                            (key, p["hotel"], actor, n["status"], store.now()),
                        )
                        db.run(
                            "INSERT INTO call_notes(id,hotel,guest,room,language,engine,reply,updated) VALUES(?,?,?,?,?,?,?,?)",
                            (
                                key,
                                p["hotel"],
                                actor,
                                p["room"],
                                language,
                                n["engine"],
                                concierge.GREETINGS[language],
                                store.now(),
                            ),
                        )
                        db.run(
                            "INSERT INTO call_privacy(call_id,consent,updated) VALUES(?,?,?)",
                            (key, int(consent), store.now()),
                        )
                        db.run(
                            "INSERT INTO call_starts VALUES(?,?,?,0,?,?)",
                            (
                                actor,
                                str(body.key),
                                key,
                                int(body.transcript_consent),
                                store.now(),
                            ),
                        )
                if n.get("id"):
                    db.run(
                        "INSERT INTO call_starts VALUES(?,?,?,0,?,?)",
                        (
                            actor,
                            str(body.key),
                            key,
                            int(body.transcript_consent),
                            store.now(),
                        ),
                    )
            if n["status"] not in concierge.ACTIVE:
                raise HTTPException(409, "This call has ended. Start a new call.")
            audio = credentials(key, p) if n["engine"] == "live" else {}
            return {
                "id": key,
                "room": n["room"],
                "engine": n["engine"],
                "transcript_consent": consent,
                **audio,
            }

    @app.post("/calls/start/{key}/cancel")
    def cancel(key: UUID, actor=Depends(identity)):
        with store.transaction() as db:
            lock_guest(db, actor, require_active=False)
            old = db.one(
                "SELECT * FROM call_starts WHERE actor=? AND request_key=?",
                (actor, str(key)),
            )
            if old and old["call_id"] and not old["cancelled"]:
                concierge.finish(db, old["call_id"])
            db.run(
                "INSERT INTO call_starts VALUES(?,?,NULL,1,0,?) ON CONFLICT(actor,request_key) DO UPDATE SET cancelled=1",
                (actor, str(key), store.now()),
            )
            return {"ended": True, "call_id": old["call_id"] if old else None}

    @app.get("/calls/{key}/status")
    def status(key: str, actor=Depends(identity)):
        # Safe read retry: retry a whole read-only transaction, never a mutation.
        for attempt in range(2):
            try:
                with store.transaction(actor) as db:
                    row = db.one(
                        "SELECT id,status FROM calls WHERE id=? AND guest=?",
                        (key, actor),
                    )
                    if not row:
                        raise PermissionError("Call unavailable.")
                    return row
            except Exception as exc:
                from psycopg import OperationalError

                if attempt or not isinstance(exc, OperationalError):
                    raise
