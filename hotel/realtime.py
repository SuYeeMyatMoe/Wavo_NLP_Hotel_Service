"""Private notification invalidations. Only publishable key + user's JWT reach JS."""

import os
from pathlib import Path
import streamlit as st


@st.cache_resource
def component():
    root = Path(__file__).resolve().parents[1]
    return st.components.v2.component(
        "wavo_notifications",
        html="<small role='status'>Connecting updates…</small>",
        js=(root / "static/supabase-2.119.0.js").read_text(encoding="utf8")
        + "\n"
        + (root / "hotel/realtime.js").read_text(encoding="utf8"),
    )


def connect(profile=None):
    auth = st.session_state.get("auth")
    if not auth:
        return
    from hotel.ui_client import request, invalidate

    component()(
        data={
            "url": os.environ.get("SUPABASE_URL", ""),
            "key": os.environ.get("SUPABASE_PUBLISHABLE_KEY", ""),
            "token": auth["access_token"],
            "user": (profile or request("GET", "/me"))["id"],
        },
        key="notification_socket",
        on_revision_change=invalidate,
    )
