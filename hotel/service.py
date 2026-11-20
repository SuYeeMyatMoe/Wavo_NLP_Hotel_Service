import json
import base64
import hashlib
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal
from uuid import UUID, uuid4

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from hotel import store as s
from hotel import concierge
from hotel.operations_api import register as register_operations
from hotel.voice_api import register as register_voice_tools
from hotel.concierge_api import register
from hotel.intelligence_api import register as register_intelligence
from hotel.completion import register as register_completion
from hotel.nlp import ROOT
from hotel.demo_accounts import PREVIEW_ACTORS
from hotel.languages import Language, InputLanguage, guest_analysis, wav_bytes

from hotel.privacy_logging import install as private_logs

private_logs()


@asynccontextmanager
async def lifespan(app):
    from hotel.nlp import bundle, lexicon

    bundle()
    lexicon()
    from hotel.intelligence import vader
    from hotel.languages import text_detector

    vader()
    text_detector()
    if s.voice_ready():
        # Import protobuf/token dependencies before the first guest clicks Call.
        from livekit import api  # noqa: F401
    yield


app = FastAPI(title="Wavo hotel operations", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "WAVO_BROWSER_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501"
        ).split(",")
        if origin.strip() and origin.strip() != "*"
    ],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)


class Intake(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class Save(Intake):
    key: UUID
    source: Literal["Staff analysis", "Guest request", "Public review"] = (
        "Staff analysis"
    )
    room: str = Field(default="", max_length=12)
    language: InputLanguage = "auto"


class VoiceMessage(BaseModel):
    key: UUID
    language: InputLanguage = "auto"
    audio: str = Field(min_length=1, max_length=2_700_000)


class Change(BaseModel):
    value: str = Field(max_length=300)


class Outcome(BaseModel):
    key: UUID
    version: int = Field(ge=0)
    outcome: Literal["Fixed", "Needs follow-up", "Guest unavailable"]
    action: str = Field(min_length=3, max_length=600)
    note: str = Field(default="", max_length=1600)


class Confirmation(BaseModel):
    version: int = Field(ge=0)
    resolved: bool
    note: str = Field(default="", max_length=600)


class Note(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=6000)


def assign(state):
    with s.transaction() as db:
        p = s.profile(db, state["actor"])
        t = s.create(
            db, p, state["analysis"], state["key"], state["source"], state["room"]
        )
        return {"ref": t["id"]}


class IntakeController:
    def invoke(self, state):
        state["analysis"] = guest_analysis(state["text"], state.get("language", "auto"))
        return {**state, **assign(state)}


controller = IntakeController()


@app.exception_handler(ValueError)
async def invalid(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(PermissionError)
async def denied(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=403)


def identity(
    authorization: str = Header(default=""),
    x_preview_user: str = Header(default="demo-staff"),
):
    if not s.connected():
        if x_preview_user not in PREVIEW_ACTORS:
            raise PermissionError("Unknown preview account.")
        return x_preview_user
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please sign in.")
    try:
        from hotel.auth_http import user

        r = user(authorization)
    except requests.RequestException:
        raise HTTPException(503, "Identity service unavailable.")
    if not r.ok:
        raise HTTPException(401, "Sign in again.")
    return r.json()["id"]


def context(actor=Depends(identity)):
    with s.transaction(actor) as db:
        yield db, s.profile(db, actor)


def staff(p):
    if p["role"] not in s.STAFF:
        raise PermissionError("Staff access required.")


@app.get("/me")
def me(ctx=Depends(context)):
    from hotel.work_assistant import test_mode

    db, p = ctx
    pref = (
        db.one("SELECT language FROM guest_languages WHERE guest=?", (p["id"],))
        if p["role"] == "guest"
        else None
    )
    return {
        **ctx[1],
        "mode": "Supabase" if s.connected() else "Local preview",
        "voice": s.voice_ready(),
        "work_assistant_test_mode": test_mode(),
        "language": pref["language"] if pref else "en",
    }


@app.put("/language")
def set_language(value: Language, ctx=Depends(context)):
    db, p = ctx
    if p["role"] != "guest":
        raise PermissionError("Guest access required.")
    db.run(
        "INSERT INTO guest_languages VALUES(?,?) ON CONFLICT(guest) DO UPDATE SET language=excluded.language",
        (p["id"], value),
    )
    return {"language": value}


@app.post("/voice-messages")
def voice_message(body: VoiceMessage, actor=Depends(identity)):
    raw = wav_bytes(body.audio)
    digest = hashlib.sha256(raw).hexdigest()
    key = str(body.key)
    with s.transaction(actor) as db:
        p = s.profile(db, actor)
        if not s.active(p):
            raise PermissionError("An active guest stay is required.")
        prior = db.one(
            "SELECT id,analysis FROM tickets WHERE author=? AND request_key=?",
            (actor, key),
        )
        if prior:
            if json.loads(prior["analysis"]).get("audio_sha256") != digest:
                raise ValueError("Request key already used.")
            return {"id": prior["id"]}
    a = guest_analysis("", body.language, raw)
    with s.transaction() as db:
        t = s.create(db, s.profile(db, actor), a, key, "Voice message", "")
        if json.loads(t["analysis"]).get("audio_sha256") != digest:
            raise ValueError("Request key already used.")
        db.run(
            "INSERT INTO voice_messages VALUES(?,?) ON CONFLICT(ticket) DO NOTHING",
            (t["id"], raw),
        )
        return {"id": t["id"]}


@app.get("/tickets/{ref}/audio")
def recording(ref: str, ctx=Depends(context)):
    db, p = ctx
    s.ticket(db, p, ref)
    row = db.one("SELECT audio FROM voice_messages WHERE ticket=?", (ref,))
    if not row:
        raise HTTPException(404, "No recording.")
    return {"audio": base64.b64encode(row["audio"]).decode("ascii")}


@app.post("/analyze")
def classify(body: Intake, ctx=Depends(context)):
    staff(ctx[1])
    from hotel.extraction import extract, suggest

    a = guest_analysis(body.text, "auto")
    if "extraction" not in a:
        a["extraction"] = extract(a.get("english") or body.text)
    a["solution"] = suggest(ctx[0], ctx[1]["hotel"], a["extraction"], a["urgency"])
    return a


@app.get("/evaluation")
def evaluation(ctx=Depends(context)):
    staff(ctx[1])
    report = json.loads((ROOT / "artifacts/evaluation.json").read_text(encoding="utf8"))
    for target in report.get("targets", {}).values():
        selected = [r for r in target["runs"] if r.get("selected")]
        target["runs"] = (
            selected or [r for r in target["runs"] if r["model"] == target["champion"]]
        )[:1]
    comparison = report.pop("urgency_comparison", {})
    report["safety_challenge"] = comparison.get("After", {}).get("challenge", {})
    return report


@app.post("/tickets")
def save(body: Save, actor=Depends(identity)):
    with s.transaction(actor) as db:
        s.profile(db, actor)
    return {
        "id": controller.invoke(
            {**body.model_dump(), "key": str(body.key), "actor": actor}
        )["ref"]
    }


@app.get("/tickets")
def listing(ctx=Depends(context)):
    return s.queue(*ctx)


@app.get("/alerts")
def alerts(ctx=Depends(context)):
    db, p = ctx
    staff(p)
    return db.all(
        "SELECT id,room FROM tickets WHERE hotel=? AND urgency='Critical' AND status='Assigned' ORDER BY created",
        (p["hotel"],),
    )


@app.get("/tickets/{ref}")
def detail(ref: str, ctx=Depends(context), prepare_recorder: bool = False):
    db, p = ctx
    t = s.ticket(db, p, ref)
    if p["role"] == "guest":
        from hotel.guest_activity import request_detail

        return request_detail(db, p, t)
    from hotel.work_orders import context as work_context

    t["work"] = work_context(db, p, t, include_outcomes=not prepare_recorder)
    if (
        prepare_recorder
        and p["role"] in s.STAFF
        and t["work"]["owner"] == p["id"]
        and t["status"] in {"Assigned", "In progress", "Escalated"}
    ):
        from hotel.languages import warm_staff_recorder

        warm_staff_recorder()
    from hotel.operations import snapshot

    t.update(snapshot(db, ref))
    from hotel.completion import for_ticket

    t["completion_estimate"] = for_ticket(db, ref)
    t["events"] = db.all(
        "SELECT action,created FROM events WHERE ticket=? ORDER BY created,id", (ref,)
    )
    t["analysis"] = json.loads(t["analysis"])
    t["calls"] = db.all(
        "SELECT id,direction,status,transcript,created FROM calls WHERE ticket=? ORDER BY created",
        (ref,),
    )
    return t


@app.post("/tickets/{ref}/status")
def update(ref: str, body: Change, actor=Depends(identity)):
    with s.transaction() as db:
        s.advance(db, s.profile(db, actor), ref, body.value)
    return {"status": body.value}


@app.get("/tickets/{ref}/state")
def work_state(ref: str, ctx=Depends(context)):
    from hotel.work_orders import current

    db, p = ctx
    t = s.ticket(db, p, ref)
    return {"status": t["status"], "version": current(db, ref)["version"]}


@app.post("/tickets/{ref}/outcome")
def submit_outcome(ref: str, body: Outcome, actor=Depends(identity)):
    from hotel.work_orders import submit

    action = body.action.strip()
    if len(action) < 3:
        raise ValueError("Describe the action taken.")
    with s.transaction() as db:
        return submit(
            db,
            s.profile(db, actor),
            ref,
            str(body.key),
            body.version,
            body.outcome,
            action,
            body.note.strip(),
        )


@app.post("/tickets/{ref}/confirm")
def confirm_outcome(ref: str, body: Confirmation, actor=Depends(identity)):
    from hotel.work_orders import confirm

    # The authenticated guest is re-authorized here. Trusted backend writes the
    # limited confirmation transition without granting guest SQL update access.
    with s.transaction() as db:
        return confirm(
            db, s.profile(db, actor), ref, body.version, body.resolved, body.note
        )


@app.post("/tickets/{ref}/feedback")
def feedback(ref: str, body: Change, actor=Depends(identity)):
    from hotel.work_orders import guest_rating, locked

    with s.transaction() as db:
        p = s.profile(db, actor)
        t = locked(db, p, ref)
        if (
            p["role"] != "guest"
            or t["guest"] != actor
            or t["status"] not in {"Resolved", "Closed"}
        ):
            raise PermissionError(
                "The linked guest can rate the service after resolution."
            )
        if body.value in {"1/5", "2/5", "3/5", "4/5", "5/5"}:
            prior = guest_rating(db, ref)
            if prior is not None:
                if prior != int(body.value[0]):
                    raise ValueError(
                        "A rating has already been saved for this request."
                    )
                return {"saved": True}
        elif body.value not in {"Satisfied", "Needs attention"}:
            raise ValueError("Choose a rating from one to five stars.")
        s.record(db, ref, "Guest feedback: " + body.value, actor)
    return {"saved": True}


@app.put("/consent")
def consent(value: bool, ctx=Depends(context)):
    db, p = ctx
    if not s.active(p):
        raise PermissionError("An active stay is required.")
    db.run("UPDATE profiles SET consent=? WHERE id=?", (int(value), p["id"]))
    if not value:
        db.run(
            "UPDATE calls SET status='Declined' WHERE guest=? AND direction='Outbound' AND status IN ('Ringing','Connecting')",
            (p["id"],),
        )
    return {"consent": value}


@app.get("/calls")
def calls(ctx=Depends(context), active_only: bool = False):
    db, p = ctx
    s.expire_invitations(db, p["hotel"])
    args = [p["hotel"]]
    where = "hotel=?"
    if active_only:
        where += " AND status IN ('Ringing','Connecting','Connected')"
    if p["role"] == "guest":
        where += " AND guest=?"
        args.append(p["id"])
    elif p["role"] == "staff":
        where += " AND EXISTS(SELECT 1 FROM ticket_work w WHERE w.ticket=calls.ticket AND w.owner=?)"
        args.append(p["id"])
    return db.all(
        "SELECT id,guest,ticket,status,direction,operator,created,"
        "(SELECT engine FROM call_notes WHERE call_notes.id=calls.id) AS engine,"
        "(SELECT outcome FROM call_notes WHERE call_notes.id=calls.id) AS outcome,"
        "COALESCE((SELECT room FROM call_notes WHERE call_notes.id=calls.id),(SELECT room FROM tickets WHERE tickets.id=calls.ticket),(SELECT room FROM profiles WHERE profiles.id=calls.guest),'') AS room,"
        "COALESCE(NULLIF((SELECT issue FROM call_notes WHERE call_notes.id=calls.id),''),(SELECT complaint FROM tickets WHERE tickets.id=calls.ticket),NULLIF(SUBSTR(calls.transcript,1,240),''),'') AS summary,"
        "(SELECT reply FROM call_notes WHERE call_notes.id=calls.id) AS reply FROM calls WHERE "
        + where
        + " ORDER BY created DESC",
        args,
    )


@app.get("/workspace/updates")
def workspace_updates(ctx=Depends(context)):
    """One authorized refresh for the shell; no full ticket/NLP history load."""
    db, p = ctx
    result = {
        "profile": me(ctx),
        "notifications": db.all(
            "SELECT id,ticket,kind,message,created,delivery,published,read_at FROM notifications "
            "WHERE hotel=? AND recipient=? ORDER BY created DESC,id DESC LIMIT 100",
            (p["hotel"], p["id"]),
        ),
        "confirmations": [],
        "active_calls": [],
        "handoffs": [],
        "alerts": [],
    }
    if p["role"] == "guest":
        result["confirmations"] = db.all(
            "SELECT t.id FROM tickets t LEFT JOIN service_lifecycle l ON l.ticket=t.id "
            "WHERE t.hotel=? AND t.guest=? AND (t.status='Awaiting confirmation' "
            "OR (l.state='escalated' AND l.reason='Guest confirmation is overdue; do not assume resolution.')) ORDER BY t.created",
            (p["hotel"], p["id"]),
        )
        result["active_calls"] = calls(ctx, active_only=True)
    else:
        result["alerts"] = alerts(ctx)
        if p["role"] == "manager":
            result["handoffs"] = db.all(
                "SELECT n.room FROM call_notes n JOIN calls c ON c.id=n.id "
                "WHERE n.hotel=? AND n.outcome='Waiting for reception' AND c.status='Connected' ORDER BY n.updated",
                (p["hotel"],),
            )
    return result


@app.get("/callback-options")
def callbacks(ctx=Depends(context)):
    db, p = ctx
    staff(p)
    return db.all(
        "SELECT t.id,t.room,t.complaint FROM tickets t JOIN profiles g ON t.guest=g.id WHERE t.hotel=? AND g.hotel=t.hotel AND g.consent=1 AND g.staying_until>? AND t.source<>'Public review' ORDER BY t.created DESC",
        (p["hotel"], s.now()[:10]),
    )


@app.post("/calls")
def call(ref: str = "", ctx=Depends(context)):
    db, p = ctx
    if not ref:
        local = os.getenv("CONCIERGE_MODE", "auto") == "local" or not s.voice_ready()
        pending = db.one(
            "SELECT id FROM calls WHERE guest=? AND direction='Inbound' AND status IN ('Ringing','Connecting','Connected')",
            (p["id"],),
        )
        if not s.active(p):
            raise PermissionError("An active guest stay is required.")
        key = (
            pending["id"]
            if pending
            else s.start_call(db, p, None, "Inbound", "AI Reception", local=local)
        )
        n = concierge.ensure_note(db, key, p, "local" if local else "live")
        return {"id": key, "engine": n["engine"]}
    staff(p)
    t = s.ticket(db, p, ref)
    if not t["guest"] or t["source"] == "Public review":
        raise ValueError("No verified guest is linked to this request.")
    return {
        "id": s.start_call(
            db, s.profile(db, t["guest"]), ref, "Outbound", t["operator"]
        )
    }


@app.post("/calls/{key}/join")
def join(key: str, ctx=Depends(context)):
    db, p = ctx
    c = db.one("SELECT * FROM calls WHERE id=? AND guest=?", (key, p["id"]))
    if (
        not c
        or c["status"] not in {"Ringing", "Connecting", "Connected"}
        or not s.active(p)
    ):
        raise PermissionError("This call is unavailable.")
    if c["direction"] == "Outbound" and not p["consent"]:
        raise PermissionError("Callback permission was withdrawn.")
    db.run(
        "UPDATE calls SET status='Connecting' WHERE id=? AND status='Ringing'", (key,)
    )
    return call_credentials(key, p)


def call_credentials(key, p):
    from livekit import api

    token = (
        api.AccessToken()
        .with_identity(p["id"])
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
    )
    return {"url": os.environ["LIVEKIT_URL"], "token": token.to_jwt()}


@app.post("/calls/{key}/end")
def end(key: str, actor=Depends(identity)):
    # Ending may create a supervisor-review record. Like processing a call
    # turn, this is a trusted workflow after explicit ownership verification;
    # guest RLS intentionally cannot create operational/audit records directly.
    with s.transaction() as db:
        c = db.one("SELECT * FROM calls WHERE id=? AND guest=?", (key, actor))
        if not c:
            raise PermissionError("Call unavailable.")
        if db.one("SELECT id FROM call_notes WHERE id=?", (key,)):
            concierge.finish(db, key)
        else:
            db.run(
                "UPDATE calls SET status=? WHERE id=? AND status IN ('Ringing','Connecting','Connected')",
                ("Declined" if c["status"] == "Ringing" else "Ended", key),
            )
    from hotel.completion import ended_receipt

    return ended_receipt(actor, key)


@app.get("/tools")
def tools(ctx=Depends(context)):
    db, p = ctx
    staff(p)
    return {
        "operators": db.all(
            "SELECT department,name FROM operators WHERE hotel=?", (p["hotel"],)
        ),
        "policies": db.all(
            "SELECT title,body FROM policies WHERE hotel=?", (p["hotel"],)
        ),
    }


@app.post("/tools/{kind}")
def configure(kind: Literal["operators", "policies"], body: Note, ctx=Depends(context)):
    db, p = ctx
    if p["role"] != "manager":
        raise PermissionError("Manager access required.")
    if kind == "operators":
        db.run(
            "INSERT INTO operators VALUES(?,?,?) ON CONFLICT(hotel,department) DO UPDATE SET name=excluded.name",
            (p["hotel"], body.title, body.body),
        )
    else:
        db.run(
            "INSERT INTO policies VALUES(?,?,?,?)",
            (str(uuid4()), p["hotel"], body.title, body.body),
        )
    return {"saved": True}


register(app, context, identity, staff)

register_intelligence(app, context, identity, staff)

register_operations(app, context, identity)
register_completion(app, identity)

register_voice_tools(app, identity)

from hotel.call_start import register as register_call_start

register_call_start(app, identity, call_credentials)

from hotel.guest_activity import register as register_guest_activity

register_guest_activity(app, context)
