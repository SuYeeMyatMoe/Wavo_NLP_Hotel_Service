"""Authenticated operational interfaces; actor is never accepted from request data."""

import json
from datetime import datetime, timezone
from uuid import UUID
from fastapi import Depends
from pydantic import BaseModel, Field
from hotel import store, work_assistant


class WorkTurn(BaseModel):
    turn_id: UUID
    text: str = Field(default="", max_length=4000)
    audio: str = Field(default="", max_length=2700000)
    ref: str = Field(default="", max_length=30)
    version: int | None = Field(default=None, ge=0)


class Clarification(BaseModel):
    key: UUID
    version: int = Field(ge=0)
    text: str = Field(min_length=3, max_length=4000)
    agreement: bool = False


class Roster(BaseModel):
    staff: str
    name: str = Field(min_length=1, max_length=80)
    department: str
    skills: list[str]
    shift_start: str
    shift_end: str
    available: bool
    capacity: int = Field(ge=1, le=30)
    version: int = Field(ge=0)


class Policy(BaseModel):
    priority: str
    ack_minutes: int = Field(ge=1, le=120)
    service_minutes: int = Field(ge=2, le=1440)
    version: int = Field(ge=0)


class Reservation(BaseModel):
    guest: str
    room: str = Field(min_length=1, max_length=12)
    starts: str
    ends: str
    version: int = Field(ge=0)


def manager(db, actor):
    p = store.profile(db, actor)
    if p["role"] != "manager":
        raise PermissionError("Supervisor access required.")
    return p


def register(app, context, identity):
    @app.post("/tickets/{ref}/clarify")
    def clarify_request(ref: str, body: Clarification, actor=Depends(identity)):
        from hotel.request_updates import clarify

        return clarify(
            actor, ref, str(body.key), body.version, body.text, body.agreement
        )

    @app.post("/tickets/{ref}/ask-details")
    def ask_details(ref: str, actor=Depends(identity)):
        from hotel import operations, work_orders

        with store.transaction() as db:
            p = store.profile(db, actor)
            t = work_orders.locked(db, p, ref)
            if p["role"] not in store.STAFF:
                raise PermissionError("Staff access required.")
            a = json.loads(t["analysis"])
            if a.get("service_mode") != "reception_review":
                raise ValueError("This request already has an approved service action.")
            operations.notify(
                db,
                t["hotel"],
                t["guest"],
                ref,
                "clarification",
                "Reception needs more information. Open this request, describe the issue and confirm whether you want service.",
                f"clarification:{ref}:{work_orders.current(db, ref)['version']}",
            )
        return {"sent": True}

    @app.get("/work-history")
    def work_history(actor=Depends(identity)):
        with store.transaction() as db:
            p = store.profile(db, actor)
            if p["role"] not in store.STAFF:
                raise PermissionError("Staff access required.")
            return db.all(
                "SELECT a.ticket,a.staff,a.attempt,a.assigned,a.acknowledged,a.ended,a.reason,t.room FROM task_assignments a JOIN tickets t ON t.id=a.ticket WHERE a.hotel=? AND a.active=0"
                + (" AND a.staff=?" if p["role"] == "staff" else "")
                + " ORDER BY a.ended DESC LIMIT 100",
                (p["hotel"], p["id"]) if p["role"] == "staff" else (p["hotel"],),
            )

    @app.post("/work-assistant/turns")
    def work_turn(body: WorkTurn, actor=Depends(identity)):
        with store.transaction(actor) as db:
            if store.profile(db, actor)["role"] not in store.STAFF:
                raise PermissionError("Staff access required.")
        text = body.text.strip()
        if body.audio:
            from hotel.languages import transcribe_auto, wav_bytes, to_english

            original, language = transcribe_auto(wav_bytes(body.audio), "en")
            text = to_english(original, language)
        if not text:
            raise ValueError("Speak or type a work update.")
        return work_assistant.submit(
            actor, str(body.turn_id), text, body.ref, body.version
        )

    @app.get("/notifications")
    def notifications(ctx=Depends(context)):
        db, p = ctx
        return db.all(
            "SELECT id,ticket,kind,message,created,delivery,published,read_at FROM notifications WHERE hotel=? AND recipient=? ORDER BY created DESC,id DESC LIMIT 100",
            (p["hotel"], p["id"]),
        )

    @app.post("/notifications/{key}/read")
    def read(key: str, ctx=Depends(context)):
        db, p = ctx
        row = db.one(
            "SELECT id FROM notifications WHERE id=? AND recipient=? AND hotel=?",
            (key, p["id"], p["hotel"]),
        )
        if not row:
            raise PermissionError("Notification unavailable.")
        db.run(
            "UPDATE notifications SET read_at=CASE WHEN read_at='' THEN ? ELSE read_at END WHERE id=?",
            (store.now(), key),
        )
        return {"read": True}

    @app.get("/agent-actions")
    def activity(ref: str = "", ctx=Depends(context)):
        db, p = ctx
        if p["role"] not in store.STAFF:
            raise PermissionError("Staff access required.")
        query = "SELECT a.* FROM agent_actions a WHERE a.hotel=?"
        args = [p["hotel"]]
        if ref:
            store.ticket(db, p, ref)
            query += " AND a.ticket=?"
            args.append(ref)
        if p["role"] != "manager":
            query += " AND EXISTS(SELECT 1 FROM ticket_work w WHERE w.ticket=a.ticket AND w.owner=?)"
            args.append(p["id"])
        return db.all(query + " ORDER BY a.created DESC LIMIT 100", args)

    @app.get("/tickets/{ref}/assignments")
    def assignments(ref: str, ctx=Depends(context)):
        db, p = ctx
        store.ticket(db, p, ref)
        return db.all(
            "SELECT id,staff,attempt,assigned,acknowledged,ack_due,service_due,ended,reason FROM task_assignments WHERE ticket=? ORDER BY attempt",
            (ref,),
        )

    @app.get("/operations/settings")
    def settings(actor=Depends(identity)):
        with store.transaction() as db:
            p = manager(db, actor)
            return {
                "roster": db.all(
                    "SELECT * FROM staff_roster WHERE hotel=? ORDER BY name",
                    (p["hotel"],),
                ),
                "policies": db.all(
                    "SELECT * FROM service_policies WHERE hotel=? ORDER BY priority",
                    (p["hotel"],),
                ),
                "reservations": db.all(
                    "SELECT * FROM reservations WHERE hotel=? ORDER BY room",
                    (p["hotel"],),
                ),
            }

    @app.get("/profile/details")
    def profile_details(ctx=Depends(context)):
        db, p = ctx
        return {
            "reservation": db.one(
                "SELECT * FROM reservations WHERE guest=?", (p["id"],)
            ),
            "roster": db.one("SELECT * FROM staff_roster WHERE staff=?", (p["id"],)),
        }

    @app.put("/operations/roster")
    def roster(body: Roster, actor=Depends(identity)):
        from hotel.procedures import CATEGORIES, DEPARTMENTS

        if (
            body.department not in DEPARTMENTS
            or not body.skills
            or not set(body.skills) <= set(CATEGORIES + ["Reception review"])
        ):
            raise ValueError("Choose approved departments and equipment skills.")
        start, end = (
            datetime.fromisoformat(body.shift_start),
            datetime.fromisoformat(body.shift_end),
        )
        if not start.tzinfo or not end.tzinfo or start >= end:
            raise ValueError("Provide a valid shift with timezones.")
        with store.transaction() as db:
            p = manager(db, actor)
            person = store.profile(db, body.staff)
            if person["hotel"] != p["hotel"] or person["role"] not in store.STAFF:
                raise PermissionError("Choose a staff profile in your hotel.")
            old = db.one(
                "SELECT * FROM staff_roster WHERE staff=?"
                + (" FOR UPDATE" if db.pg else ""),
                (body.staff,),
            )
            if (old["version"] if old else 0) != body.version:
                raise ValueError("Roster changed. Refresh first.")
            values = (
                body.name,
                body.department,
                json.dumps(body.skills),
                start.astimezone(timezone.utc).isoformat(),
                end.astimezone(timezone.utc).isoformat(),
                int(body.available),
                body.capacity,
            )
            if old:
                db.run(
                    "UPDATE staff_roster SET name=?,department=?,skills=?,shift_start=?,shift_end=?,available=?,capacity=?,version=version+1 WHERE staff=?",
                    (*values, body.staff),
                )
            else:
                db.run(
                    "INSERT INTO staff_roster(staff,hotel,name,department,skills,shift_start,shift_end,available,capacity) VALUES(?,?,?,?,?,?,?,?,?)",
                    (body.staff, p["hotel"], *values),
                )
            return {"saved": True}

    @app.put("/operations/policies")
    def policy(body: Policy, actor=Depends(identity)):
        if (
            body.priority not in {"Urgent", "Moderate", "Low"}
            or body.service_minutes <= body.ack_minutes * 2
        ):
            raise ValueError("Service target must exceed two acknowledgment intervals.")
        with store.transaction() as db:
            p = manager(db, actor)
            old = db.one(
                "SELECT * FROM service_policies WHERE hotel=? AND priority=?"
                + (" FOR UPDATE" if db.pg else ""),
                (p["hotel"], body.priority),
            )
            if (old["version"] if old else 0) != body.version:
                raise ValueError("Policy changed. Refresh first.")
            db.run(
                "INSERT INTO service_policies VALUES(?,?,?,?,1) ON CONFLICT(hotel,priority) DO UPDATE SET ack_minutes=excluded.ack_minutes,service_minutes=excluded.service_minutes,version=service_policies.version+1",
                (p["hotel"], body.priority, body.ack_minutes, body.service_minutes),
            )
            return {"saved": True}

    @app.put("/operations/reservations")
    def reservation(body: Reservation, actor=Depends(identity)):
        from datetime import date

        body.room = body.room.strip()
        if not body.room:
            raise ValueError("Enter a verified room.")
        if date.fromisoformat(body.starts) >= date.fromisoformat(body.ends):
            raise ValueError("Check the stay dates.")
        with store.transaction() as db:
            p = manager(db, actor)
            guest = store.profile(db, body.guest)
            if guest["role"] != "guest" or guest["hotel"] != p["hotel"]:
                raise PermissionError("Guest unavailable.")
            old = db.one(
                "SELECT * FROM reservations WHERE guest=?"
                + (" FOR UPDATE" if db.pg else ""),
                (body.guest,),
            )
            if (old["version"] if old else 0) != body.version:
                raise ValueError("Reservation changed. Refresh first.")
            db.run(
                "INSERT INTO reservations VALUES(?,?,?,?,?,1) ON CONFLICT(guest) DO UPDATE SET room=excluded.room,starts=excluded.starts,ends=excluded.ends,version=reservations.version+1",
                (body.guest, p["hotel"], body.room, body.starts, body.ends),
            )
            db.run(
                "UPDATE profiles SET room=?,staying_until=? WHERE id=?",
                (body.room, body.ends, body.guest),
            )
            return {"saved": True}
