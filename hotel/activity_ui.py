"""Compact, accessible timeline of already-authorized request events."""

import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st


def event_style(action):
    if action in {"Resolved", "Closed", "Guest confirmed completion"}:
        return "success", "✓"
    if action in {"Escalated", "Guest requested more help", "Reopened"}:
        return "attention", "!"
    if action in {"Pending assignment", "Awaiting confirmation"}:
        return "waiting", "◷"
    if action == "Assigned" or action.startswith("Assigned to "):
        return "assigned", "→"
    return "neutral", "•"


def display_zone():
    try:
        return ZoneInfo(os.getenv("WAVO_TIMEZONE", "Asia/Yangon"))
    except ZoneInfoNotFoundError:
        return timezone.utc


def event_time(value, zone):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            # A historical timestamp without an offset cannot be safely localized.
            return "Time zone unavailable", stamp.strftime("%d %b %Y · %H:%M"), ""
        local = stamp.astimezone(zone)
        return local.strftime("%d %b %Y"), local.strftime("%H:%M"), stamp.isoformat()
    except (ValueError, TypeError, AttributeError):
        return "Date unavailable", "Time unavailable", ""


def timeline_html(events, translate=lambda text: text, latest=False, zone=None):
    zone = zone or display_zone()
    parts = ['<ol class="wavo-timeline">']
    previous_day = None
    for index, event in enumerate(events):
        action = event.get("action") or "Service update"
        tone, symbol = event_style(action)
        day, clock, stamp = event_time(event.get("created"), zone)
        date = (
            f'<div class="wavo-timeline-date">{escape(translate(day))}</div>'
            if day != previous_day
            else ""
        )
        previous_day = day
        badge = (
            f'<span class="wavo-timeline-latest">{escape(translate("Latest update"))}</span>'
            if latest and index == 0
            else ""
        )
        time = (
            f'<time datetime="{escape(stamp, quote=True)}" title="{escape(stamp, quote=True)}">{escape(clock)}</time>'
            if stamp
            else f"<span>{escape(translate(clock))}</span>"
        )
        parts.append(
            f'<li class="wavo-timeline-entry {tone}">{date}'
            '<div class="wavo-timeline-row">'
            f'<span class="wavo-timeline-marker" aria-hidden="true">{symbol}</span>'
            f'<div class="wavo-timeline-content"><strong>{escape(translate(action))}</strong>{badge}</div>'
            f'<div class="wavo-timeline-time">{time}</div></div></li>'
        )
    return "".join(parts) + "</ol>"


def activity(events, status, translate=lambda text: text):
    st.html(Path(__file__).with_name("activity.css"))
    st.subheader(translate("Activity"))
    # Backend order includes stable event IDs for equal timestamps. Reversing
    # preserves that ordering and does not erase repeated assignment attempts.
    recent = list(reversed(events))
    zone = display_zone()
    zone_name = getattr(zone, "key", "UTC").replace("_", " ")
    tone, _ = event_style(status)
    st.html(
        '<div class="wavo-activity-summary">'
        f'<span class="wavo-activity-state {tone}">{escape(translate(status))}</span>'
        f"<span>{len(events)} {escape(translate('updates'))} · {escape(translate('Newest first'))} · {escape(zone_name)}</span></div>"
    )
    if not recent:
        st.caption(translate("No activity yet."))
        return
    st.html(timeline_html(recent[:5], translate, latest=True, zone=zone))
    if len(recent) > 5:
        with st.expander(
            f"{translate('Earlier updates')} ({len(recent) - 5})", on_change="rerun"
        ) as earlier:
            if earlier.open:
                st.html(timeline_html(recent[5:], translate, zone=zone))
