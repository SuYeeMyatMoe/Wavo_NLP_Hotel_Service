"""Bundled LiveKit component; the browser owns its cancellable media session."""

import streamlit as st
from hotel.nlp import ROOT

CALL_STYLES = "\n".join(
    (ROOT / "hotel" / name).read_text(encoding="utf8")
    for name in ("call.css", "mascot.css")
)

PHONE = st.components.v2.component(
    "hotel_audio",
    html=(ROOT / "hotel/call.html").read_text(encoding="utf8"),
    js=(ROOT / "static/livekit-client.umd.min.js").read_text(encoding="utf8")
    + "\n"
    + (ROOT / "hotel/phone.js").read_text(encoding="utf8"),
    css=CALL_STYLES,
)

LOCAL_PHONE = st.components.v2.component(
    "concierge_microphone",
    html=(ROOT / "hotel/call.html").read_text(encoding="utf8"),
    js=(ROOT / "hotel/concierge_audio.js").read_text(encoding="utf8"),
    css=CALL_STYLES,
)
PEER = st.components.v2.component(
    "reception_handoff",
    html='<div class="peer"><button></button><small role="status"></small><audio autoplay></audio></div>',
    js=(ROOT / "hotel/handoff.js").read_text(encoding="utf8"),
    css="button{padding:.8rem 1.4rem;border-radius:8px;background:#ede6da;cursor:pointer}",
)
