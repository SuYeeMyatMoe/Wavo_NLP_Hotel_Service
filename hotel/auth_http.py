"""Reuse TLS connections while validating every bearer token with Supabase."""

import os
from threading import local

import requests

_thread = local()


def user(authorization):
    if not hasattr(_thread, "session"):
        _thread.session = requests.Session()
    session = _thread.session
    try:
        return session.get(
            os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/user",
            headers={
                "apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"],
                "Authorization": authorization,
            },
            timeout=8,
        )
    finally:
        # Only the transport is reused. Never carry cookies or a stored bearer
        # header from one authenticated request to another.
        session.cookies.clear()
