"""Bundled LiveKit component; the browser owns its cancellable media session."""

import streamlit as st
from hotel.nlp import ROOT
from hotel.vintage_ui import concierge_asset

CALL_STYLES = "\n".join(
    concierge_asset(name)
    for name in ("call.css", "mascot.css")
)
CALL_HTML = concierge_asset("call.html").replace(
    "<!-- concierge -->", concierge_asset("mascot.html")
)
MASCOT_JS = concierge_asset("vintage_build/concierge.js") + "\n"

PHONE = st.components.v2.component(
    "hotel_audio",
    html=CALL_HTML,
    js=MASCOT_JS + (ROOT / "static/livekit-client.umd.min.js").read_text(encoding="utf8")
    + "\n"
    + (ROOT / "hotel/phone.js").read_text(encoding="utf8"),
    css=CALL_STYLES,
)

LOCAL_PHONE = st.components.v2.component(
    "concierge_microphone",
    html=CALL_HTML,
    js=MASCOT_JS + concierge_asset("concierge_audio.js"),
    css=CALL_STYLES,
)
PEER = st.components.v2.component(
    "reception_handoff",
    html='<div class="peer"><button></button><small role="status"></small><audio autoplay></audio></div>',
    js=(ROOT / "hotel/handoff.js").read_text(encoding="utf8"),
    css="""
    button {
        padding: .8rem 1.4rem;
        border: 1px solid var(--line, #a47d53);
        border-radius: 8px;
        background: var(--accent, #e0b476);
        color: var(--accent-ink, #241409);
        cursor: pointer;
    }
    small { color: var(--muted, #c8ab8c); }
    """,
)
