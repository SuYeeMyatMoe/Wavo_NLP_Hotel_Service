"""Bundled LiveKit component; the browser owns its cancellable media session."""

import streamlit as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PHONE = st.components.v2.component(
    "hotel_audio",
    html=(ROOT / "hotel/call.html").read_text(encoding="utf8"),
    js=(ROOT / "static/livekit-client.umd.min.js").read_text(encoding="utf8")
    + "\n"
    + (ROOT / "hotel/phone.js").read_text(encoding="utf8"),
    css=(ROOT / "hotel/call.css").read_text(encoding="utf8"),
)

LOCAL_PHONE = st.components.v2.component(
    "concierge_microphone",
    html=(ROOT / "hotel/call.html").read_text(encoding="utf8"),
    js=(ROOT / "hotel/concierge_audio.js").read_text(encoding="utf8"),
    css=(ROOT / "hotel/call.css").read_text(encoding="utf8"),
)
PEER = st.components.v2.component(
    "reception_handoff",
    html='<div class="peer"><button></button><small role="status"></small><audio autoplay></audio></div>',
    js=(ROOT / "hotel/handoff.js").read_text(encoding="utf8"),
    css="button{padding:.8rem 1.4rem;border-radius:8px;background:#ede6da;cursor:pointer}",
)
