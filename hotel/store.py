import json
import os
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from time import perf_counter
from hotel.latency import database_elapsed, database_batch

from dotenv import load_dotenv

from hotel.nlp import ROOT

load_dotenv(ROOT / ".env")
SCHEMA = Path(__file__).with_name("schema.sql")
STAFF = {"staff", "manager"}


def now():
    return datetime.now(timezone.utc).isoformat()


def active(p):
    return p and p["role"] == "guest" and p["staying_until"] > now()[:10]


def connected():
    mode = os.getenv("HOTEL_MODE", "preview")
    if mode not in {"preview", "connected"}:
        raise RuntimeError("Set HOTEL_MODE to preview or connected.")
    return mode == "connected"


class DB:
    def __init__(self, connection, pg):
        self.connection, self.pg = connection, pg
        self._batch_active = False

    def run(self, query, args=()):
        started = perf_counter()
        try:
            return self.connection.execute(
                query.replace("?", "%s") if self.pg else query, args
            )
        finally:
            database_elapsed(started)

    def one(self, query, args=()):
        row = self.run(query, args).fetchone()
        return dict(row) if row else None

    def all(self, query, args=()):
        return [dict(r) for r in self.run(query, args).fetchall()]

    @contextmanager
    def batch(self):
        """Batch dependent-order writes whose results are not needed until exit."""
        if self._batch_active:
            yield
            return
        with database_batch():
            with self.connection.pipeline() if self.pg else nullcontext():
                self._batch_active = True
                try:
                    yield
                finally:
                    self._batch_active = False


@contextmanager
def transaction(actor=None):
    pg = connected()
    if pg:
        from hotel.db_pool import pool

        lease = pool()
        conn = lease.getconn()
    else:
        path = Path(os.getenv("PREVIEW_DB", ROOT / ".runtime/preview.sqlite3"))
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
    try:
        db = DB(conn, pg)
        if pg:
            # Send setup together instead of three cloud round trips. SET LOCAL
            # and the actor GUC are reverted by commit/rollback before reuse.
            with db.batch():
                db.run("SET LOCAL search_path TO hotel, public")
                if actor:
                    db.run("SET LOCAL ROLE hotel_app")
                    db.run("SELECT set_config('hotel.actor', ?, true)", (actor,))
        else:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(SCHEMA.read_text())
            conn.executescript(SCHEMA.with_name("concierge.sql").read_text())
            conn.executescript(SCHEMA.with_name("work.sql").read_text())
            conn.executescript(SCHEMA.with_name("intelligence.sql").read_text())
            conn.executescript(SCHEMA.with_name("operations.sql").read_text())
            conn.executescript(SCHEMA.with_name("call_start.sql").read_text())
            conn.executescript(SCHEMA.with_name("completion.sql").read_text())
            conn.executescript(SCHEMA.with_name("call_timing.sql").read_text())
            conn.execute("BEGIN IMMEDIATE")
            from hotel.completion import migrate_local

            migrate_local(db)
            db.run(
                "INSERT INTO service_times VALUES ('demo','Maintenance',15) ON CONFLICT DO NOTHING"
            )
            for room, ready in [("305", 0), ("308", 1)]:
                db.run(
                    "INSERT INTO room_inventory VALUES('demo',?,'Standard',?) ON CONFLICT DO NOTHING",
                    (room, ready),
                )
            db.run(
                "INSERT INTO policies VALUES('demo-wifi','demo','Guest Wi-Fi connection','Select Hotel-Guest in Wi-Fi settings. Open a browser and choose Guest access on the welcome page.') ON CONFLICT DO NOTHING"
            )
            for identity, role, room in [
                ("demo-staff", "manager", ""),
                ("demo-guest", "guest", "305"),
            ]:
                db.run(
                    "INSERT INTO profiles(id,hotel,role,room,staying_until) VALUES(?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                    (identity, "demo", role, room, "2099-01-01"),
                )
        if not pg:
            from hotel.work_orders import seed_demo

            seed_demo(db)
            from hotel.procedures import seed

            seed(db)
            from hotel import operations

            operations.seed(db)
            operations.migrate_preview(db)
        yield db
        started = perf_counter()
        try:
            conn.commit()
        finally:
            database_elapsed(started, query=False)
    except BaseException:
        conn.rollback()
        raise
    finally:
        if pg:
            lease.putconn(conn)
        else:
            conn.close()


def profile(db, actor, lock=False):
    p = db.one(
        "SELECT p.*,r.room AS reserved_room,r.starts AS reserved_start,r.ends AS reserved_end "
        "FROM profiles p LEFT JOIN reservations r ON r.guest=p.id AND r.hotel=p.hotel WHERE p.id=?"
        + (" FOR UPDATE OF p" if lock and db.pg else ""),
        (actor,),
    )
    if not p:
        raise PermissionError("No hotel profile is linked to this account.")
    room, starts, ends = (
        p.pop(k) for k in ("reserved_room", "reserved_start", "reserved_end")
    )
    if p["role"] == "guest" and room is not None:
        p["room"] = room
        p["staying_until"] = (
            min(p["staying_until"], ends) if starts <= now()[:10] else ""
        )
    return p


def allowed(p, t):
    return (
        t and p["hotel"] == t["hotel"] and (p["role"] in STAFF or p["id"] == t["guest"])
    )


def ticket(db, p, ref):
    t = db.one("SELECT * FROM tickets WHERE id=?", (ref,))
    if not allowed(p, t):
        raise PermissionError("Request unavailable.")
    if p["role"] == "staff" and not db.one(
        "SELECT 1 FROM ticket_work WHERE ticket=? AND owner=?", (ref, p["id"])
    ):
        raise PermissionError("Only your assigned work is available.")
    return t


def queue(db, p):
    query = """SELECT id,room,complaint,urgency,department,status,created,
            (SELECT n.eta FROM call_notes n JOIN calls c ON c.id=n.id WHERE c.ticket=tickets.id AND n.eta IS NOT NULL
             ORDER BY n.updated DESC LIMIT 1) AS eta,
             (SELECT owner FROM ticket_work WHERE ticket=tickets.id) AS owner,analysis FROM tickets WHERE hotel=?"""
    args = [p["hotel"]]
    if p["role"] not in STAFF:
        query += " AND guest=?"
        args.append(p["id"])
    if p["role"] == "staff":
        query += " AND EXISTS(SELECT 1 FROM ticket_work w WHERE w.ticket=tickets.id AND w.owner=?)"
        args.append(p["id"])
    rows = db.all(query + " ORDER BY created,id", args)
    from hotel.work_orders import PRIORITY

    ranked = sorted(
        (
            r
            for r in rows
            if r["status"] not in {"Awaiting confirmation", "Resolved", "Closed"}
        ),
        key=lambda r: (PRIORITY.get(r["urgency"], 5), r["created"], r["id"]),
    )
    positions = {r["id"]: i + 1 for i, r in enumerate(ranked)}
    from hotel.operations import snapshots

    states = snapshots(db, [row["id"] for row in rows])
    for row in rows:
        row.update(states[row["id"]])
        a = json.loads(row.pop("analysis"))
        from hotel.issue_labels import problem_label
        from hotel.request_updates import can_clarify

        row["problem"] = problem_label(a.get("extraction", {}))
        row["can_clarify"] = can_clarify({**row, "analysis": a})
        row["priority_rank"] = positions.get(row["id"])
        try:
            row["waiting_minutes"] = max(
                0,
                int(
                    (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(row["created"])
                    ).total_seconds()
                    / 60
                ),
            )
        except (ValueError, TypeError):
            row["waiting_minutes"] = None
        row["priority_reason"] = a.get("rule") or (
            "Urgency is unassessed; immediate human review is required."
            if row["urgency"] == "Unassessed"
            else f"{row['urgency']} priority predicted by the urgency classifier"
        )
        if p["role"] in STAFF:
            from hotel.extraction import extract

            row["extraction"] = a.get("extraction") or extract(
                a.get("english") or row["complaint"], row["room"]
            )
        else:
            row.pop("owner", None)
            row.pop("priority_reason", None)
    return rows


def record(db, ref, message, actor):
    db.run(
        "INSERT INTO events VALUES(?,?,?,?,?)",
        (str(uuid4()), ref, message, actor, now()),
    )


def voice_ready():
    return all(
        os.getenv(k)
        for k in (
            "LIVEKIT_URL",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "GOOGLE_API_KEY",
            "GEMINI_LIVE_MODEL",
        )
    )


def expire_invitations(db, hotel):
    before = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    db.run(
        "UPDATE calls SET status='Missed' WHERE hotel=? AND created<? AND status IN ('Ringing','Connecting')",
        (hotel, before),
    )


def start_call(db, guest, t, direction, operator, local=False):
    if not active(guest) or (direction == "Outbound" and not guest["consent"]):
        raise ValueError("An active stay and callback permission are required.")
    if not local and not voice_ready():
        raise ValueError("Connect the voice service to place a call.")
    expire_invitations(db, guest["hotel"])
    key = str(uuid4())
    result = db.run(
        "INSERT INTO calls(id,hotel,guest,ticket,direction,status,operator,created) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
        (
            key,
            guest["hotel"],
            guest["id"],
            t,
            direction,
            "Connected" if local else "Ringing",
            operator,
            now(),
        ),
    )
    if result.rowcount == 0:
        raise ValueError("This guest already has an active call.")
    return key


def create(db, p, analysis, key, source, room):
    prior = db.one(
        "SELECT * FROM tickets WHERE author=? AND request_key=?", (p["id"], key)
    )
    if prior:
        if prior["complaint"] != analysis["text"]:
            raise ValueError("The request key already belongs to another complaint.")
        return prior
    if p["role"] == "guest":
        if not active(p):
            raise PermissionError("This stay is inactive.")
        guest, room, source = (
            p,
            p["room"],
            source if source in {"Voice", "Voice message"} else "Guest request",
        )
    else:
        # Linking a guest requires an explicitly selected verified reservation.
        guest = None
        if room and source != "Public review":
            matches = db.all(
                "SELECT * FROM profiles WHERE hotel=? AND role='guest' AND room=? AND staying_until>?",
                (p["hotel"], room, now()[:10]),
            )
            guest = matches[0] if len(matches) == 1 else None
    from hotel.extraction import extract, suggest

    analysis = dict(analysis)
    analysis["extraction"] = {
        **(
            analysis.get("extraction")
            or extract(analysis.get("english") or analysis["text"])
        ),
        "verified_room": room,
    }
    analysis["solution"] = suggest(
        db, p["hotel"], analysis["extraction"], analysis["urgency"]
    )
    dep = analysis["department"]
    rep = db.one(
        "SELECT name FROM operators WHERE hotel=? AND department=?", (p["hotel"], dep)
    )
    operator = (
        "Safety escalation"
        if analysis["urgency"] == "Critical"
        else (rep["name"] if rep else dep + " operator")
    )
    ref = "VF-" + uuid4().hex[:12].upper()
    values = (
        ref,
        p["hotel"],
        p["id"],
        key,
        guest["id"] if guest else None,
        room,
        source,
        analysis["text"],
        analysis["urgency"],
        dep,
        operator,
        "Assigned",
        json.dumps(analysis),
        now(),
    )
    inserted = db.run(
        "INSERT INTO tickets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(author,request_key) DO NOTHING",
        values,
    )
    if not inserted.rowcount:
        return create(db, p, analysis, key, source, room)
    with db.batch():
        db.run(
            "INSERT INTO nlp_analysis VALUES(?,?,?,?,?,?,?)",
            (str(uuid4()), p["hotel"], None, ref, "", json.dumps(analysis), now()),
        )
        record(db, ref, "Request received", p["id"])
    from hotel.operations import dispatch

    dispatch(db, ref)
    if analysis["urgency"] == "Critical":
        record(db, ref, "Human safety alert raised", "Controller")
    if (
        analysis["urgency"] == "Urgent"
        and guest
        and guest["consent"]
        and voice_ready()
        and source != "Voice"
    ):
        try:
            start_call(db, guest, ref, "Outbound", operator)
            record(db, ref, "Callback requested", "Controller")
        except ValueError as error:
            record(db, ref, str(error), "Controller")
    return ticket(db, p, ref)


def advance(db, p, ref, status):
    from hotel.work_orders import start

    if status == "In progress":
        return start(db, p, ref)
    t = ticket(db, p, ref)
    if p["role"] not in STAFF:
        raise PermissionError("Staff access required.")
    if t["status"] != "Resolved" or status != "Closed":
        raise ValueError(
            "Start work and submit an outcome. The guest confirms resolution."
        )
    count = db.run(
        "UPDATE tickets SET status=? WHERE id=? AND status=?",
        (status, ref, t["status"]),
    ).rowcount
    if count != 1:
        raise ValueError("Another staff member updated this request.")
    record(db, ref, status, p["id"])
