"""Staff intelligence tools and guest-owned transcript preferences."""

import json
from uuid import uuid4
from fastapi import Depends, Query
from pydantic import BaseModel, Field
from hotel import store, concierge, case_notes
from hotel.procedures import CATEGORIES, DEPARTMENTS


class Question(BaseModel):
    field: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=300)


class Procedure(BaseModel):
    id: str = Field(default="", max_length=100)
    version: int = Field(default=0, ge=0)
    category: str
    department: str
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=6000)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    questions: list[Question] = Field(default_factory=list, max_length=10)
    approval: str = Field(default="", max_length=600)
    enabled: bool = True
    completion_minutes: int | None = Field(default=None, ge=1, le=1440)


class Review(BaseModel):
    version: int = Field(ge=0)
    issue: str = Field(min_length=1, max_length=1000)
    next_step: str = Field(min_length=1, max_length=1000)
    constraints: list[str] = Field(default_factory=list, max_length=20)


def register(app, context, identity, staff):
    @app.get("/calls/{key}/transcript-consent")
    def privacy(key: str, ctx=Depends(context)):
        db, p = ctx
        call = db.one("SELECT * FROM calls WHERE id=?", (key,))
        if (
            not call
            or call["hotel"] != p["hotel"]
            or (p["role"] not in store.STAFF and call["guest"] != p["id"])
        ):
            raise PermissionError("Call unavailable.")
        if p["role"] == "staff":
            store.ticket(db, p, call["ticket"])
        return {"consent": case_notes.consented(db, key)}

    @app.get("/procedures")
    def procedures(ctx=Depends(context)):
        db, p = ctx
        staff(p)
        return {
            "procedures": db.all(
                "SELECT * FROM service_procedures WHERE hotel=? ORDER BY category,title",
                (p["hotel"],),
            ),
            "legacy": db.all(
                "SELECT * FROM policies WHERE hotel=? ORDER BY title", (p["hotel"],)
            ),
        }

    @app.post("/procedures")
    def save_procedure(body: Procedure, ctx=Depends(context)):
        db, p = ctx
        if p["role"] != "manager":
            raise PermissionError("Manager access required.")
        if body.category not in CATEGORIES or body.department not in DEPARTMENTS:
            raise ValueError("Choose a supported category and department.")
        if (
            any(len(c) > 100 for c in body.constraints)
            or not body.body.strip()
            or not body.title.strip()
        ):
            raise ValueError("Enter a title, action and concise conditions.")
        key = body.id or str(uuid4())
        row = db.one(
            "SELECT * FROM service_procedures WHERE id=?"
            + (" FOR UPDATE" if db.pg else ""),
            (key,),
        )
        if row and (row["hotel"] != p["hotel"] or row["version"] != body.version):
            raise ValueError("Procedure changed or unavailable. Refresh first.")
        if not row and body.version:
            raise ValueError("Procedure unavailable.")
        values = (
            body.category,
            body.department,
            body.title.strip(),
            body.body.strip(),
            json.dumps(body.constraints),
            json.dumps([q.model_dump() for q in body.questions]),
            body.approval,
            int(body.enabled),
            row["completion_minutes"]
            if row and "completion_minutes" not in body.model_fields_set
            else body.completion_minutes,
        )
        if row:
            db.run(
                "UPDATE service_procedures SET category=?,department=?,title=?,body=?,constraints=?,questions=?,approval=?,enabled=?,completion_minutes=?,version=version+1 WHERE id=?",
                (*values, key),
            )
        else:
            db.run(
                "INSERT INTO service_procedures(id,hotel,category,department,title,body,constraints,questions,approval,enabled,completion_minutes) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (key, p["hotel"], *values),
            )
        return {"id": key}

    @app.put("/calls/{key}/transcript-consent")
    def consent(key: str, value: bool, actor=Depends(identity)):
        # Only this authenticated backend operation may erase retained evidence.
        with store.transaction() as db:
            p = store.profile(db, actor)
            call = db.one(
                "SELECT * FROM calls WHERE id=?",
                (key,),
            )
            if (
                not call
                or call["guest"] != actor
                or call["hotel"] != p["hotel"]
                or p["role"] != "guest"
            ):
                raise PermissionError("Only the guest controls transcript storage.")
            if value and call["status"] not in concierge.ACTIVE:
                raise ValueError("Consent can be enabled only during an active call.")
            if db.one("SELECT id FROM call_notes WHERE id=?", (key,)):
                concierge.note(db, key, lock=True)
            db.run(
                "INSERT INTO call_privacy(call_id,consent,updated) VALUES(?,?,?) ON CONFLICT(call_id) DO UPDATE SET consent=excluded.consent,updated=excluded.updated",
                (key, int(value), store.now()),
            )
            if not value:
                case_notes.purge_evidence(db, key)
            return {"consent": value}

    @app.post("/calls/{key}/note-review")
    def review(key: str, body: Review, ctx=Depends(context)):
        db, p = ctx
        staff(p)
        n = concierge.note(db, key, lock=True)
        if n["hotel"] != p["hotel"]:
            raise PermissionError("Call unavailable.")
        if p["role"] == "staff":
            store.ticket(db, p, n["ticket"])
        current = case_notes.structured(db, n)
        if current["version"] != body.version:
            raise ValueError("The note changed. Refresh before saving.")
        if any(len(c) > 150 for c in body.constraints):
            raise ValueError("Keep each constraint under 150 characters.")
        db.run(
            "INSERT INTO note_revisions VALUES(?,?,?,?,?,?)",
            (
                str(uuid4()),
                key,
                body.version + 1,
                p["id"],
                json.dumps(body.model_dump(exclude={"version"})),
                store.now(),
            ),
        )
        if n["ticket"]:
            store.record(db, n["ticket"], "Service note reviewed", p["id"])
        return case_notes.structured(db, n)

    @app.get("/insights")
    def insights(days: int = Query(default=30, ge=0, le=365), ctx=Depends(context)):
        db, p = ctx
        staff(p)
        from hotel.business_insights import report

        return report(db, p, days)
