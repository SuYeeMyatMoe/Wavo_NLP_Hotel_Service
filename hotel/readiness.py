"""Retry only an unauthenticated readiness read before a user action."""

import os
import time
import requests
from hotel.http_client import request


def wait_for_api(url, *, timeout=120, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while clock() < deadline:
        remaining = deadline - clock()
        try:
            response = request(
                "GET", url.rstrip("/") + "/healthz", timeout=min(5, remaining / 2)
            )
            if response.ok and response.json().get("status") == "ok":
                return
        except (requests.RequestException, ValueError, AttributeError):
            pass
        sleep(max(0, min(2, deadline - clock())))
    raise requests.Timeout("Hotel service is still starting. Please try again shortly.")


def enabled():
    return os.getenv("WAVO_WAKE_API", "false").lower() == "true"
