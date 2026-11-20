"""Visual components for the Streamlit entrance and workspace."""
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent


@st.cache_resource
def room_component():
    build = HERE / "vintage_build"
    return st.components.v2.component(
        "wavo_vintage_room",
        html='<div class="wavo-room-root"></div>',
        # Keep a newline even if the minifier emits one line of CSS.
        css="/* Wavo room styles */\n" + (build / "room.css").read_text(encoding="utf-8"),
        js=(build / "room.js").read_text(encoding="utf-8"),
    )


def room(*, entrance=None):
    """Open guest sign-in from the public scene or the authenticated call controls."""
    return room_component()(
        key="public_vintage_room" if entrance else "guest_vintage_room",
        data={"entrance": entrance, "compact": entrance is None},
        on_telephone_change=lambda: None,
    )


@st.cache_resource
def cursor_component():
    return st.components.v2.component(
        "wavo_cursor_embers",
        html='<span hidden aria-hidden="true"></span>',
        js=(HERE / "cursor_embers.js").read_text(encoding="utf-8"),
    )


def cursor_embers():
    cursor_component()(key="wavo_cursor_embers", height=1)
