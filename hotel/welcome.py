"""Public hotel entrance and local demonstration sign-in."""

import streamlit as st
import hmac

from hotel.demo_accounts import ACCOUNTS as DEMO_ACCOUNTS, GUESTS
from hotel.vintage_ui import room

WORDMARK = '<span class="wavo-lockup" aria-hidden="true"><img src="app/static/wavo-icon.png" alt=""><span>avo</span></span>'
BRAND = f'<a class="hotel-mark" href="./" target="_self" aria-label="Wavo">{WORDMARK}</a>'


def landing():
    with st.container(key="vintage_arrival"):
        room(entrance="?login=guest")
    st.html(f"""<section class="service-shortcuts" id="hotel-services">
          <div data-wavo-reveal="0"><p class="hotel-overline">Hotel services</p><h2>How can we help?</h2></div>
          <div class="shortcut-grid">
            <div data-wavo-card data-wavo-reveal="1"><a href="?login=guest&amp;service=comfort" target="_self">{service_icon("bed")}<span>Room comfort</span></a></div>
            <div data-wavo-card data-wavo-reveal="2"><a href="?login=guest&amp;service=housekeeping" target="_self">{service_icon("sparkle")}<span>Housekeeping</span></a></div>
            <div data-wavo-card data-wavo-reveal="3"><a href="?login=guest&amp;service=wifi" target="_self">{service_icon("wifi")}<span>Wi-Fi help</span></a></div>
            <div data-wavo-card data-wavo-reveal="4"><a href="?login=guest&amp;service=special" target="_self">{service_icon("bell")}<span>Special requests</span></a></div>
          </div></section>
        <section class="hotel-services"><div class="section-head" data-wavo-reveal="0"><div><p class="hotel-overline">Hotel services</p><h2>During your stay</h2></div></div>
        <div class="service-images">
          <div data-wavo-card data-wavo-reveal="1"><a href="?login=guest&amp;service=comfort" target="_self"><img src="app/static/room-detail.jpg" alt="Guest room with a wood-panelled headboard" loading="lazy" decoding="async"><div><strong>In-room service</strong><span>Repairs and housekeeping</span><b>Request room service</b></div></a></div>
          <div data-wavo-card data-wavo-reveal="2"><a href="?login=guest" target="_self"><img src="app/static/reception.jpg" alt="Seating and warm lights in the hotel lobby" loading="lazy" decoding="async"><div><strong>Reception</strong><span>Hotel information and guest support</span><b>Contact reception</b></div></a></div>
        </div></section>
        <footer class="hotel-footer" data-wavo-reveal="0"><span role="img" aria-label="Wavo">{WORDMARK}</span></footer>""")
    st.stop()


def service_icon(name):
    return (
        f'<span class="service-icon" aria-hidden="true" '
        f'style="--service-icon:url(app/static/service-{name}.svg)"></span>'
    )


def fill_demo_account(role):
    account = (
        st.session_state.get("staff_demo_kind", "staff")
        if role == "staff"
        else st.session_state.get("guest_demo_kind", "guest")
    )
    email, password, _ = DEMO_ACCOUNTS[account]
    st.session_state["demo_email_" + role] = email
    st.session_state["demo_password_" + role] = password


def demo_login(role):
    guest = role == "guest"
    who = "Guest" if guest else "Staff"
    st.html(
        f'<header class="public-nav">{BRAND}<a href="./" target="_self">Back to hotel</a></header>'
    )
    left, right = st.columns([1, 1], gap="large", vertical_alignment="center")
    with left:
        img = "guest-suite" if guest else "reception"
        st.html(
            f'<img class="login-photo" src="app/static/{img}.jpg" alt="Hotel interior" loading="lazy" decoding="async">'
        )
    with right:
        st.caption("LOCAL DEMO")
        st.title(who + " sign in")
        st.write(
            "Sign in to get help for the room linked to your reservation."
            if guest
            else "View assigned work or sign in as a supervisor."
        )
        if guest:
            from hotel import store

            with store.transaction() as db:
                rooms = {
                    key: store.profile(db, values[2])["room"]
                    for key, values in GUESTS.items()
                }
            st.selectbox(
                "Demo reservation",
                list(GUESTS),
                format_func=lambda key: f"Room {rooms[key]} · {GUESTS[key][0]}",
                key="guest_demo_kind",
            )
        else:
            st.selectbox(
                "Demo role",
                ["staff", "backup", "supervisor"],
                format_func=lambda r: {
                    "staff": "Maintenance worker",
                    "backup": "Backup maintenance",
                    "supervisor": "Supervisor",
                }[r],
                key="staff_demo_kind",
            )
        st.button(
            "Use demo account",
            on_click=fill_demo_account,
            args=(role,),
            icon=":material/person:",
        )
        with st.form("demo_login_" + role):
            email = st.text_input(
                "Email", key="demo_email_" + role, autocomplete="username"
            )
            password = st.text_input(
                "Password",
                type="password",
                key="demo_password_" + role,
                autocomplete="current-password",
            )
            submitted = st.form_submit_button(
                "Sign in", type="primary", icon=":material/login:", width="stretch"
            )
        account_email, account_password, actor = DEMO_ACCOUNTS[
            st.session_state.get("staff_demo_kind", "staff")
            if role == "staff"
            else st.session_state.get("guest_demo_kind", "guest")
        ]
        if submitted:
            candidates = (
                [DEMO_ACCOUNTS[k] for k in GUESTS]
                if guest
                else [DEMO_ACCOUNTS[k] for k in DEMO_ACCOUNTS if k not in GUESTS]
            )
            for candidate_email, candidate_password, candidate_actor in candidates:
                if hmac.compare_digest(
                    email.strip().casefold().encode(), candidate_email.encode()
                ) and hmac.compare_digest(
                    password.encode(), candidate_password.encode()
                ):
                    st.session_state.preview_actor = candidate_actor
                    st.query_params.clear()
                    st.rerun()
            st.error("Check your email and password for this demo account.")
        with st.expander("Demo account"):
            st.write("Email · " + account_email)
            st.write("Password · " + account_password)
            st.caption("Local demonstration account")
        other = "staff" if guest else "guest"
        st.html(
            f'<a class="other-entrance" href="?login={other}" target="_self">{other.title()} entrance ↗</a>'
        )
    st.stop()
