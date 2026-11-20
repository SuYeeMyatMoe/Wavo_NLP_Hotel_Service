"""Authenticated turn-taking, hotel availability, case notes and reception handoff."""

import hashlib
import hmac
import os
import logging
import json
from uuid import UUID
from typing import Literal
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field
from hotel import concierge as c, store
from hotel.worker_auth import worker_token
from hotel.languages import to_english, transcribe_auto, detect_text_language, wav_bytes
from hotel.latency import measure


class GuestTurn(BaseModel):
    turn_id: UUID
    text: str = Field(default="", max_length=8000)
    audio: str = Field(default="", max_length=2700000)


class Estimate(BaseModel):
    minutes: int = Field(ge=0, le=1440)


class HotelRoom(BaseModel):
    room: str = Field(min_length=1, max_length=12)
    category: str = Field(min_length=1, max_length=50)
    ready: bool


class Signal(BaseModel):
    type: Literal["offer", "answer"]
    sdp: str = Field(min_length=5, max_length=64000)


def public(row):
    return {
        k: row[k]
        for k in (
            "id",
            "room",
            "language",
            "engine",
            "issue",
            "options",
            "outcome",
            "reply",
            "eta",
            "ticket",
            "version",
            "status",
        )
    }


def authorized(db, p, key, lock=False):
    n = c.note(db, key, lock)
    if n["hotel"] != p["hotel"] or (
        p["role"] not in store.STAFF and n["guest"] != p["id"]
    ):
        raise PermissionError("Call unavailable.")
    if p["role"] == "staff":
        store.ticket(db, p, n["ticket"])
    return n


def apply_turn(actor, key, body):
    with measure("turn", call=key, turn=str(body.turn_id)):
        return _apply_turn(actor, key, body)


def _apply_turn(actor, key, body):
    with store.transaction(actor) as db:
        if actor is None:
            # Only the HMAC-authenticated worker route uses this branch.
            n = c.note(db, key)
            if n["engine"] != "live":
                raise PermissionError("Live call required.")
            actor = n["guest"]
            p = store.profile(db, actor)
            if n["hotel"] != p["hotel"]:
                raise PermissionError("Call unavailable.")
        else:
            p = store.profile(db, actor)
            n = authorized(db, p, key)
        if not store.active(p) or n["status"] not in c.ACTIVE:
            raise PermissionError("Guest call unavailable.")
        if db.one(
            "SELECT 1 FROM concierge_turns WHERE call_id=? AND turn_id=?",
            (key, str(body.turn_id)),
        ):
            return public(n)
        lang = n["language"]
    if body.audio:
        original, lang = transcribe_auto(wav_bytes(body.audio), lang)
    else:
        original = body.text.strip()
        lang = detect_text_language(original, lang)
    if not original:
        return {**public(n), "retry": True}
    with measure("translation", call=key):
        english = to_english(original, lang)
    if not english.strip():
        raise ValueError("Please repeat the message or use the text option.")
    for _ in range(4):
        prepared = c.classify_turn(n, original, english, lang)
        try:
            with store.transaction() as db:
                result = public(
                    c.process_turn(
                        db,
                        store.profile(db, actor),
                        key,
                        str(body.turn_id),
                        original,
                        english,
                        lang,
                        prepared=prepared,
                        version=n["version"],
                    )
                )
            return result
        except c.StaleTurn as stale:
            n = stale.case
            if not body.audio:
                lang = detect_text_language(original, n["language"])
                with measure("translation", call=key):
                    english = to_english(original, lang)
                if not english.strip():
                    raise ValueError(
                        "Please repeat the message or use the text option."
                    )
    raise HTTPException(409, "The conversation changed. Please retry this turn.")


def register(app, context, identity, staff):
    def prepare_reply(actor, key):
        from hotel.languages import translate
        from hotel.speech import speak

        with store.transaction(actor) as db:
            n = authorized(db, store.profile(db, actor), key)
        lang = n["language"]
        line = n["reply"]
        if line != c.GREETINGS[lang] and lang != "en":
            line = translate(line, "en", lang)
        try:
            audio = speak(line, lang)
        except (OSError, RuntimeError, TimeoutError):
            audio = ""
        return {
            "case": public(n),
            "speech": {"reply": line, "wav": audio, "version": n["version"]},
        }

    @app.post("/calls/{key}/jobs")
    def submit_job(key: str, body: GuestTurn | None = None, actor=Depends(identity)):
        from hotel import call_jobs

        with store.transaction(actor) as db:
            p = store.profile(db, actor)
            n = authorized(db, p, key)
            if not store.active(p) or n["status"] not in c.ACTIVE:
                raise PermissionError("This call has ended.")
        fingerprint = (
            hashlib.sha256(body.model_dump_json().encode()).hexdigest()
            if body
            else "reply-" + str(n["version"])
        )

        def run():
            if body:
                result = apply_turn(actor, key, body)
                if result.get("retry"):
                    return {"case": result, "retry": True}
            return prepare_reply(actor, key)

        return {"id": call_jobs.submit(actor, key, fingerprint, run)}

    @app.get("/calls/{key}/jobs/{job}")
    def poll_job(key: str, job: str, ctx=Depends(context)):
        from hotel import call_jobs

        db, p = ctx
        n = authorized(db, p, key)
        if n["status"] not in c.ACTIVE:
            return {"status": "cancelled"}
        try:
            future = call_jobs.get(p["id"], key, job)
        except HTTPException:
            return {
                "status": "failed",
                "detail": "This audio request expired. Please retry your reply.",
            }
        if n["status"] not in c.ACTIVE:
            future.cancel()
            return {"status": "cancelled"}
        if not future.done():
            return {"status": "pending"}
        try:
            return {"status": "complete", **future.result()}
        except Exception:
            logging.getLogger(__name__).warning(
                "Call reply processing failed; content omitted"
            )
            return {
                "status": "failed",
                "detail": "I could not process that reply. Please try again or type your message.",
            }

    @app.post("/calls/{key}/turn")
    def turn(key: str, body: GuestTurn, actor=Depends(identity)):
        return apply_turn(actor, key, body)

    @app.post("/internal/calls/{key}/turn")
    def worker_turn(
        key: str, body: GuestTurn, x_worker_token: str = Header(default="")
    ):
        if not hmac.compare_digest(worker_token(key), x_worker_token):
            raise PermissionError("Worker authentication required.")
        return apply_turn(None, key, body)

    @app.get("/calls/{key}/case")
    def case(key: str, ctx=Depends(context)):
        db, p = ctx
        n = authorized(db, p, key)
        return public(n)

    @app.get("/calls/{key}/record")
    def record(key: str, ctx=Depends(context)):
        db, p = ctx
        staff(p)
        row = db.one(
            """SELECT c.id,c.created,c.direction,c.status,c.ticket,c.transcript,
                 COALESCE(n.room,t.room,g.room,'') AS room,n.issue,n.options,n.outcome,n.eta,n.language
                 FROM calls c JOIN profiles g ON g.id=c.guest LEFT JOIN call_notes n ON n.id=c.id
                 LEFT JOIN tickets t ON t.id=c.ticket WHERE c.id=? AND c.hotel=?""",
            (key, p["hotel"]),
        )
        if not row:
            raise PermissionError("Call record unavailable.")
        if p["role"] == "staff":
            store.ticket(db, p, row["ticket"])
        if not row["issue"] and row["ticket"]:
            t = store.ticket(db, p, row["ticket"])
            row["issue"] = t["complaint"]
        row["issue"] = row["issue"] or (
            "Transcript excerpt — " + row["transcript"][:350]
            if row["transcript"]
            else "No issue recorded."
        )
        row["outcome"] = row["outcome"] or row["status"]
        from hotel import case_notes

        row["transcript_consent"] = case_notes.consented(db, key)
        row["consent_recorded"] = bool(
            db.one("SELECT call_id FROM call_privacy WHERE call_id=?", (key,))
        )
        n = db.one("SELECT id FROM call_notes WHERE id=?", (key,))
        row["note"] = case_notes.structured(db, c.note(db, key)) if n else {}
        row["turns"] = db.all(
            "SELECT speaker,original,english,language,created FROM call_transcripts WHERE call_id=? ORDER BY created,id",
            (key,),
        )
        row["analyses"] = [
            json.loads(r["payload"])
            for r in db.all(
                "SELECT payload FROM nlp_analysis WHERE call_id=? ORDER BY created,id",
                (key,),
            )
        ]
        row["revisions"] = db.all(
            "SELECT version,author,created,payload FROM note_revisions WHERE call_id=? ORDER BY version",
            (key,),
        )
        return row

    @app.get("/desk/handoffs")
    def handoffs(ctx=Depends(context)):
        db, p = ctx
        if p["role"] != "manager":
            return []
        return db.all(
            "SELECT n.room FROM call_notes n JOIN calls c ON c.id=n.id WHERE n.hotel=? AND n.outcome='Waiting for reception' AND c.status='Connected' ORDER BY n.updated",
            (p["hotel"],),
        )

    @app.get("/desk/cases")
    def desk(ctx=Depends(context)):
        db, p = ctx
        if p["role"] != "manager":
            raise PermissionError("Supervisor access required.")
        return db.all(
            """SELECT n.id,n.room,n.issue,n.options,n.outcome,n.eta,n.analysis,n.engine,n.staff_id,n.updated,
                        c.status,c.ticket,t.status AS task_status,(SELECT decision FROM move_requests m WHERE m.call_id=n.id) AS move_decision FROM call_notes n JOIN calls c ON c.id=n.id
                        LEFT JOIN tickets t ON t.id=c.ticket WHERE n.hotel=? ORDER BY n.updated DESC LIMIT 100""",
            (p["hotel"],),
        )

    @app.get("/calls/{key}/utterance")
    def utterance(key: str, actor=Depends(identity)):
        from hotel.languages import translate
        from hotel.speech import speak

        with store.transaction(actor) as db:
            n = authorized(db, store.profile(db, actor), key)
        lang = n["language"]
        line = n["reply"]
        if line != c.GREETINGS[lang] and lang != "en":
            line = translate(line, "en", lang)
        return {"reply": line, "wav": speak(line, lang), "version": n["version"]}

    @app.post("/desk/cases/{key}/eta")
    def eta(key: str, body: Estimate, ctx=Depends(context)):
        db, p = ctx
        authorized(db, p, key)
        return public(c.update_eta(db, p, key, body.minutes))

    @app.post("/calls/{key}/move-request")
    def move(key: str, ctx=Depends(context)):
        db, p = ctx
        n = authorized(db, p, key, True)
        if (
            not store.active(p)
            or n["outcome"] != "ETA changed"
            or not c.same_category(db, n)
        ):
            raise ValueError("This room option is no longer available.")
        t = store.ticket(db, p, n["ticket"])
        if t["status"] in {"Closed", "Resolved"}:
            raise ValueError("This service is complete.")
        db.run(
            "INSERT INTO move_requests(call_id,decision) VALUES(?,'Pending') ON CONFLICT DO NOTHING",
            (key,),
        )
        store.record(
            db,
            n["ticket"],
            "Guest requested a room move. Front-desk approval needed.",
            p["id"],
        )
        c.save(
            db,
            n,
            outcome="Room approval needed",
            reply="Reception has your room move request. Your current room is unchanged until they confirm.",
        )
        return public(c.note(db, key))

    @app.post("/desk/cases/{key}/room-decision")
    def decide_move(key: str, approve: bool, ctx=Depends(context)):
        db, p = ctx
        if p["role"] != "manager":
            raise PermissionError("Supervisor access required.")
        n = authorized(db, p, key, True)
        pending = db.one("SELECT decision FROM move_requests WHERE call_id=?", (key,))
        if not pending or pending["decision"] != "Pending":
            raise ValueError("No room move is awaiting approval.")
        reserved = ""
        if approve:
            candidate = c.same_category(db, n)
            if not candidate:
                raise ValueError("No same-category room is currently ready.")
            reserved = candidate["room"]
            if not db.run(
                "UPDATE room_inventory SET ready=0 WHERE hotel=? AND room=? AND ready=1",
                (p["hotel"], reserved),
            ).rowcount:
                raise ValueError("The room was assigned. Check availability again.")
        outcome = "Move approved" if approve else "Move declined"
        message = (
            f"Reception approved the move and reserved room {reserved}. Please contact reception for the key."
            if approve
            else "Reception could not approve a move. Your service task remains with the team."
        )
        db.run(
            "UPDATE move_requests SET decision=?,room=? WHERE call_id=?",
            (outcome, reserved, key),
        )
        store.record(db, n["ticket"], message, p["id"])
        c.save(
            db,
            n,
            reply=message,
            options=message,
            outcome=n["outcome"]
            if n["outcome"] in c.HANDOFF and n["status"] in c.ACTIVE
            else outcome,
        )
        return public(c.note(db, key))

    @app.post("/desk/cases/{key}/accept")
    def accept(key: str, ctx=Depends(context)):
        from livekit import api
        from datetime import timedelta

        db, p = ctx
        staff(p)
        n = authorized(db, p, key, True)
        if (
            n["status"] not in c.ACTIVE
            or n["outcome"] not in c.HANDOFF
            or n["staff_id"] not in {"", p["id"]}
        ):
            raise ValueError("This call is no longer waiting for you.")
        c.save(
            db,
            n,
            outcome="Speaking with reception",
            staff_id=p["id"],
            reply="Reception has accepted your call.",
        )
        if n["engine"] == "live":
            jwt = (
                api.AccessToken()
                .with_identity("staff-" + p["id"])
                .with_ttl(timedelta(minutes=3))
                .with_grants(api.VideoGrants(room_join=True, room=key))
            )
            return {
                "engine": "live",
                "url": os.environ["LIVEKIT_URL"],
                "token": jwt.to_jwt(),
            }
        return {"engine": "local"}

    @app.api_route("/calls/{key}/signal", methods=["GET", "POST"])
    def signal(key: str, body: Signal | None = None, ctx=Depends(context)):
        db, p = ctx
        n = authorized(db, p, key, True)
        is_guest = p["id"] == n["guest"]
        if (
            n["engine"] != "local"
            or n["status"] not in c.ACTIVE
            or n["outcome"] != "Speaking with reception"
            or not (is_guest or p["id"] == n["staff_id"])
        ):
            raise PermissionError("Human call unavailable.")
        if body:
            field = "offer" if is_guest else "answer"
            if field != body.type:
                raise PermissionError("Incorrect participant.")
            if field == "offer" and n["offer"] != body.sdp:
                c.save(db, n, offer=body.sdp, answer="")
            elif field == "answer":
                c.save(db, n, answer=body.sdp)
        return {"offer": n["offer"], "answer": n["answer"]}

    @app.get("/desk/availability")
    def availability(ctx=Depends(context)):
        db, p = ctx
        if p["role"] != "manager":
            raise PermissionError("Supervisor access required.")
        return {
            "times": db.all(
                "SELECT department,minutes FROM service_times WHERE hotel=? ORDER BY department",
                (p["hotel"],),
            ),
            "rooms": db.all(
                "SELECT room,category,ready FROM room_inventory WHERE hotel=? ORDER BY room",
                (p["hotel"],),
            ),
        }

    @app.put("/desk/availability/{department}")
    def update_time(
        department: Literal["Maintenance", "Housekeeping"],
        body: Estimate,
        ctx=Depends(context),
    ):
        db, p = ctx
        staff(p)
        db.run(
            "INSERT INTO service_times VALUES(?,?,?) ON CONFLICT(hotel,department) DO UPDATE SET minutes=excluded.minutes",
            (p["hotel"], department, body.minutes),
        )
        return {"saved": True}

    @app.put("/desk/rooms")
    def room(body: HotelRoom, ctx=Depends(context)):
        db, p = ctx
        staff(p)
        db.run(
            "INSERT INTO room_inventory VALUES(?,?,?,?) ON CONFLICT(hotel,room) DO UPDATE SET category=excluded.category,ready=excluded.ready",
            (p["hotel"], body.room.strip(), body.category.strip(), int(body.ready)),
        )
        return {"saved": True}
