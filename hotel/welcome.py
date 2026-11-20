"""Public hotel entrance and local demonstration sign-in."""

import streamlit as st
import hmac

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
    return f"""<div class="service-card" data-wavo-card data-wavo-reveal="{order}">
      <a href="{href}" target="_self">
        <div class="service-gallery" data-service-gallery>{slides}</div>
        <div class="service-copy"><strong>{title}</strong><span>{detail}</span><b>{action}</b></div>
      </a>
      <div class="service-gallery-controls" hidden>
        <button type="button" data-gallery-toggle aria-label="Pause {title} slideshow">Pause</button>
        <button type="button" data-gallery-next aria-label="Next {title} photo">Next photo</button>
      </div>
    </div>"""


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
          {service_card("In-room service", "Repairs and housekeeping", "Request room service", "?login=guest&amp;service=comfort", ROOM_PHOTOS, 1)}
          {service_card("Reception", "Hotel information and guest support", "Contact reception", "?login=guest", RECEPTION_PHOTOS, 2)}
        </div></section>
        <div class="hotel-guide">
          <section id="about" data-wavo-reveal="0">
            <h2>About</h2>
            <p>Wavo is your hotel concierge. Ask about the hotel, request help for your room, and follow updates as the hotel team handles your request.</p>
          </section>
          <section id="how-to-use" data-wavo-reveal="1">
            <h2>How to use</h2>
            <ol>
              <li>Press the brass phone button and sign in to your guest account.</li>
              <li>Tell the AI receptionist what you need, or choose a service from the menu.</li>
              <li>Open <strong>Track request</strong> after your call to check for updates.</li>
            </ol>
          </section>
        </div>
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
