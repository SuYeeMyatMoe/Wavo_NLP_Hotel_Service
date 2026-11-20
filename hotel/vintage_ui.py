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
        data={"entrance": entrance},
        on_telephone_change=lambda: None,
    )


def concierge_asset(name):
    return (HERE / name).read_text(encoding="utf-8")


@st.cache_resource
def guest_concierge_component():
    return st.components.v2.component(
        "wavo_concierge",
        html=concierge_asset("mascot.html"),
        css=concierge_asset("mascot.css"),
        js=concierge_asset("vintage_build/concierge.js")
        + '\nexport default ({parentElement}) => { WavoMascot.mountMascot(parentElement.querySelector(".mascot")); };',
    )


def guest_concierge():
    guest_concierge_component()(key="wavo_guest_concierge")


@st.cache_resource
def workspace_effects_component():
    return st.components.v2.component(
        "wavo_workspace_effects",
        html='<span hidden aria-hidden="true"></span>',
        js=concierge_asset("workspace_effects.js"),
    )


def workspace_effects():
    workspace_effects_component()(key="wavo_workspace_effects", height=1)
