"""Reuse TLS connections while validating every bearer token with Supabase."""

import os
from hotel.http_client import request


def user(authorization):
    return request(
        "GET",
        os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/user",
        headers={
            "apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"],
            "Authorization": authorization,
        },
        timeout=8,
    )
