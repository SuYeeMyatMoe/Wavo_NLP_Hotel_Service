import os
import hashlib
import json
import time
from copy import deepcopy
from functools import lru_cache
import requests
import streamlit as st
from hotel.http_client import request as http_request


@lru_cache(maxsize=1)
def local():
    from fastapi.testclient import TestClient
    from hotel.service import app

    return TestClient(app, raise_server_exceptions=False)


def _cache():
    # Display-only data stays inside this browser session. Authorization and
    # current record versions are still checked by every backend mutation.
    scope = (
        os.getenv("HOTEL_MODE"),
        os.getenv("HOTEL_API_URL"),
        os.getenv("PREVIEW_DB"),
        st.session_state.get("preview_actor"),
        hashlib.sha256(
            st.session_state.get("auth", {}).get("access_token", "").encode()
        ).hexdigest(),
    )
    if st.session_state.get("_api_cache_scope") != scope:
        st.session_state._api_cache_scope = scope
        st.session_state._api_cache = {}
    return st.session_state._api_cache


def remember(path, value):
    _cache()[(path, "{}")] = (time.monotonic(), deepcopy(value))


def invalidate():
    _cache().clear()


def request(method, path, *, optional=False, **kwargs):
    cache = _cache()
    ttl = {"/me": 60, "/profile/details": 30, "/workspace/updates": 10}.get(path, 0)
    key = (path, json.dumps(kwargs, sort_keys=True))
    if method == "GET" and ttl and key in cache:
        at, value = cache[key]
        if time.monotonic() - at < ttl:
            return deepcopy(value)
    if method != "GET":
        cache.clear()
    url = os.getenv("HOTEL_API_URL", "").rstrip("/")
    if os.getenv("HOTEL_MODE") == "connected" and not url:
        st.error("Set HOTEL_API_URL to the separately running Wavo backend.")
        st.stop()
    headers = {"x-preview-user": st.session_state.get("preview_actor", "demo-staff")}
    if "auth" in st.session_state:
        headers["Authorization"] = "Bearer " + st.session_state.auth["access_token"]
    try:
        if url:
            if method == "POST" and path in {"/calls", "/calls/start", "/work-assistant/sessions"}:
                from hotel.readiness import enabled, wait_for_api

                if enabled():
                    with st.spinner("Connecting to the hotel service…"):
                        wait_for_api(url)
            r = http_request(
                method,
                url + path,
                headers=headers,
                timeout=(
                    8,
                    180
                    if method != "GET"
                    and (
                        path in {"/voice-messages", "/tickets", "/work-assistant/turns"}
                        or path.endswith(("/turn", "/utterance"))
                    )
                    else 8
                    if optional
                    else 20,
                ),
                **kwargs,
            )
        else:
            r = local().request(method, path, headers=headers, **kwargs)
    except requests.RequestException:
        if optional:
            st.warning(
                "Request updates are temporarily unavailable. You can still contact AI reception."
            )
            return None
        st.error("The hotel service is unavailable. Your input is still here.")
        st.stop()
    if not 200 <= r.status_code < 300:
        try:
            detail = r.json().get(
                "detail", "The service could not complete this action."
            )
        except ValueError:
            detail = (
                "The service could not complete this action. Check the server logs."
            )
        st.error(str(detail))
        if r.status_code == 401 and st.button("Sign in again"):
            st.session_state.clear()
            st.rerun()
        if optional:
            return None
        st.stop()
    value = r.json()
    if method == "GET" and ttl:
        cache[key] = (time.monotonic(), deepcopy(value))
    return value
