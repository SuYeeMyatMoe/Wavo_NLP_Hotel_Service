"""Public hotel entrance and local demonstration sign-in."""

import hmac
from contextlib import contextmanager

import streamlit as st

from hotel.demo_accounts import ACCOUNTS as DEMO_ACCOUNTS, GUESTS
from hotel.vintage_ui import room

WORDMARK = '<span class="wavo-lockup" aria-hidden="true"><span>avo</span></span>'
BRAND = f'<a class="hotel-mark" href="./" target="_self" aria-label="Wavo">{WORDMARK}</a>'

ROOM_PHOTOS = (
    ("suite-lounge.jpg", "Suite lounge overlooking the city"),
    ("suite-bedroom.webp", "Suite bedroom with a sitting area"),
    ("guest-bedroom.jpg", "Guest bedroom lit by bedside lamps"),
)
RECEPTION_PHOTOS = (
    ("lobby-lounge.jpg", "Hotel lobby seating around an indoor tree"),
    ("reception-desk.jpg", "Reception desk beneath a hanging light installation"),
)


def service_card(title, detail, action, href, photos, order):
    slides = "".join(
        f'<img src="app/static/guest-gallery/{file}" alt="{alt}" decoding="async" '
        f'aria-hidden="{str(index != 0).lower()}">'
        for index, (file, alt) in enumerate(photos)
    )
    return f"""<div data-wavo-card data-wavo-reveal="{order}">
      <a href="{href}" target="_self">
        <div class="service-gallery" data-service-gallery>{slides}</div>
        <div class="service-copy"><strong>{title}</strong><span>{detail}</span><b>{action}</b></div>
      </a>
    </div>"""


def landing():
    with st.container(key="vintage_arrival"):
        room(entrance="?login=guest")
    st.html(f"""<section class="service-shortcuts" id="hotel-services">
          <div data-wavo-reveal="0"><p class="hotel-overline">Hotel services</p><h2>How can we help?</h2></div>
          <div class="shortcut-grid">
            <div data-wavo-card data-wavo-reveal="1"><a href="?login=guest&amp;service=comfort" target="_self">{service_icon("bed")}<span>Room comfort</span></a></div>
            <div data-wavo-card data-wavo-reveal="2"><a href="?login=guest&amp;service=housekeeping" target="_self">{service_icon("sparkle")}<span>Housekeeping</span></a></div>
            <div data-wavo-card data-wavo-reveal="3"><a href="?login=guest&amp;service=wifi" target="_self">{service_icon("wifi")}<span>WiFi help</span></a></div>
            <div data-wavo-card data-wavo-reveal="4"><a href="?login=guest&amp;service=special" target="_self">{service_icon("bell")}<span>Special requests</span></a></div>
          </div></section>
        <section class="hotel-services"><div class="section-head" data-wavo-reveal="0"><div><p class="hotel-overline">Hotel services</p><h2>During your stay</h2></div></div>
        <div class="service-images">
          {service_card("Room service", "Repairs and housekeeping", "Request room service", "?login=guest&amp;service=comfort", ROOM_PHOTOS, 1)}
          {service_card("Reception", "Hotel information and guest support", "Contact reception", "?login=guest", RECEPTION_PHOTOS, 2)}
        </div></section>
        <footer class="hotel-footer" data-wavo-reveal="0">
          {BRAND}
          <nav aria-label="Footer navigation">
            <a href="#hotel-services">Hotel services</a>
            <a href="?login=guest" target="_self">Guest sign in</a>
            <a href="?login=staff" target="_self">Staff entrance</a>
          </nav>
        </footer>""")
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


@contextmanager
def login_card(role):
    guest = role == "guest"
    who, other = ("Guest", "staff") if guest else ("Staff", "guest")
    with st.container(key="hotel_login", border=True):
        st.html(
            f'<header class="login-banner" data-entrance="{role}">{BRAND}'
            f'<h1>{who} sign in</h1><p>Sign in to your hotel workspace.</p></header>'
        )
        with st.container(key="login_fields"):
            yield
            st.html(
                '<nav class="login-links" aria-label="Hotel entrances">'
                '<a href="./" target="_self">Back to hotel</a>'
                f'<a href="?login={other}" target="_self">{other.title()} entrance</a>'
                '</nav>'
            )


def demo_login(role):
    guest = role == "guest"
    with login_card(role):
        st.caption("LOCAL DEMO")
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
        with st.form("demo_login_" + role, border=False):
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
    st.stop()
