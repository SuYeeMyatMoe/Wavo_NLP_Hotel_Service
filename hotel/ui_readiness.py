"""One credential-free browser wake hint for a shared API readiness task."""

from pathlib import Path
import streamlit as st
from hotel.readiness import claim_browser_hint


@st.cache_resource
def component():
    return st.components.v2.component(
        "wavo_api_wake",
        html='<span hidden aria-hidden="true"></span>',
        js=Path(__file__).with_name("api_wake.js").read_text(encoding="utf-8"),
    )


def browser_hint(url, task):
    hint = claim_browser_hint(url, task)
    if hint:
        # Style-only st.html has no layout footprint; the hint is not a UI screen.
        st.html("<style>.st-key-wavo_api_wake {display:none}</style>")
        component()(data=hint, key="wavo_api_wake", height=1)
