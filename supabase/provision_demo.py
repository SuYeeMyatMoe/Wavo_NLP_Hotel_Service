"""Provision demo identities via Supabase Auth, then link verified hotel records.

Run from the project: .venv/Scripts/python.exe supabase/provision_demo.py
Reads server credentials only from .env. Does not reset existing passwords.
"""

import json
import os
import argparse
from pathlib import Path
import sys

from dotenv import load_dotenv
import requests
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def provision(auth_only=False):
    from hotel.demo_accounts import ACCOUNTS, GUESTS, ROSTER

    load_dotenv(ROOT / ".env", override=True)
    required = ["SUPABASE_URL", "SUPABASE_SECRET_KEY"]
    if not auth_only:
        required.append("DATABASE_URL")
    missing = [key for key in required if not os.getenv(key, "").strip()]
    if missing:
        raise RuntimeError("Add these settings to .env: " + ", ".join(missing))
    url = os.environ["SUPABASE_URL"].rstrip("/")
    if url != "https://kerxsqouptjqguoeivto.supabase.co":
        raise RuntimeError(
            "This provisioning script is scoped to the Wavo demo project."
        )
    secret = os.environ["SUPABASE_SECRET_KEY"]
    headers = {"apikey": secret}
    if not secret.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + secret

    def auth(method, endpoint, **kwargs):
        response = requests.request(
            method,
            url + "/auth/v1/admin/" + endpoint,
            headers=headers,
            timeout=25,
            **kwargs,
        )
        if not response.ok:
            raise RuntimeError(
                f"Supabase Auth {method} failed (HTTP {response.status_code}); no credentials or response body logged."
            )
        return response.json()

    # Validate the server connection before creating Auth identities.
    if not auth_only:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=10) as db:
            db.execute("SELECT 1 FROM hotel.profiles LIMIT 1")
    existing = {}
    for page in range(1, 101):
        users = auth("GET", "users", params={"page": page, "per_page": 100}).get(
            "users", []
        )
        existing.update({u.get("email", "").casefold(): u for u in users})
        if len(users) < 100:
            break
    else:
        raise RuntimeError("User list exceeds this demo setup's limit.")
    identities = {}
    for key, (email, password, _) in ACCOUNTS.items():
        user = existing.get(email)
        if user and not user.get("app_metadata", {}).get("wavo_demo"):
            raise RuntimeError(
                f"Existing account {email} is not tagged for this demo; left unchanged."
            )
        if not user:
            user = auth(
                "POST",
                "users",
                json={
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                    "app_metadata": {"wavo_demo": True},
                },
            )
            user = user.get("user", user)
        identities[key] = user["id"]
    if auth_only:
        destination = ROOT / ".runtime/hosted-demo-identities.json"
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(json.dumps(identities, indent=2))
        print(
            f"Created or verified {len(identities)} Auth accounts. Non-secret IDs saved to .runtime/hosted-demo-identities.json."
        )
        return
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=10) as db:
        db.execute("SET LOCAL search_path TO hotel, public")
        db.execute(
            (
                ROOT
                / "supabase/migrations/20261120053741_demo_electrical_procedure.sql"
            ).read_text(encoding="utf8")
        )
        for key, uid in identities.items():
            role = (
                "guest"
                if key in GUESTS
                else "manager"
                if key == "supervisor"
                else "staff"
            )
            room = GUESTS[key][3] if key in GUESTS else ""
            old = db.execute(
                "SELECT hotel,role FROM profiles WHERE id=%s", (uid,)
            ).fetchone()
            if old and old != ("demo", role):
                raise RuntimeError(
                    "An existing profile has a different hotel or role; left unchanged."
                )
            db.execute(
                "INSERT INTO profiles(id,hotel,role,room,staying_until) VALUES(%s,'demo',%s,%s,%s) ON CONFLICT DO NOTHING",
                (uid, role, room, "2099-01-01" if room else ""),
            )
            if room:
                db.execute(
                    "INSERT INTO reservations VALUES(%s,'demo',%s,'2020-01-01','2099-01-01',1) ON CONFLICT DO NOTHING",
                    (uid, room),
                )
        for key, name, department, skills, capacity in ROSTER:
            db.execute(
                "INSERT INTO staff_roster(staff,hotel,name,department,skills,shift_start,shift_end,available,capacity) VALUES(%s,'demo',%s,%s,%s,'2020-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00',1,%s) ON CONFLICT DO NOTHING",
                (
                    identities[key],
                    name,
                    department,
                    json.dumps(skills),
                    capacity,
                ),
            )
    print(
        f"Provisioned {len(identities)} authenticated demo accounts, 3 reservations and {len(ROSTER)} staff roster entries."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Prepare Auth accounts while the direct database connection is being configured.",
    )
    try:
        provision(parser.parse_args().auth_only)
    except Exception as exc:
        # Connection errors can include passwords/URLs; retain only intentionally safe messages.
        print(
            str(exc)
            if isinstance(exc, RuntimeError)
            else f"Setup failed ({type(exc).__name__}); check server credentials and connectivity.",
            file=sys.stderr,
        )
        sys.exit(1)
