"""Explainable word-pattern extraction and category-based approved procedures."""

import re
from hotel.nlp import ROOM

TOPICS = [
    (
        "Safety",
        r"\b(?:gas leak|smell (?:of )?gas|smoke|fire|electric shock|sparks|exposed (?:live )?wires?)\b",
    ),
    (
        "Air conditioning",
        r"\b(?:a/c|ac|air[\s-]?con(?:dition(?:er|ing))?|cooling|heater|heating)\b",
    ),
    (
        "Plumbing",
        r"\b(?:leak(?:ing)?|flood(?:ing)?|toilet|shower|drain|hot water|tap|plumbing)\b",
    ),
    ("Wi-Fi", r"\b(?:wi[\s-]?fi|internet|network|wireless)\b"),
    (
        "Housekeeping",
        r"\b(?:dirty|clean(?:ing)?|towels?|bedding|sheets?|housekeeping|rubbish|trash|blanket)\b",
    ),
    ("Billing", r"\b(?:refund|bill(?:ing)?|charged?|payment|invoice|deposit)\b"),
    ("Electrical", r"\b(?:socket|power|electric(?:al)?|wires?|sparks|lights?)\b"),
    (
        "Food and drink",
        r"\b(?:breakfast|lunch|dinner|meal|food|hungry|room service|drinks?)\b",
    ),
]
CONSTRAINTS = [
    (
        "Child sleeping",
        r"\b(?:child|baby|son|daughter|kid).{0,35}\b(?:asleep|sleeping)\b",
    ),
    (
        "Prefers to stay in room",
        r"\b(?:without.{0,25}mov(?:e|ing)|(?:do not|don't|not|cannot|can't|avoid).{0,20}(?:mov(?:e|ing)|change rooms?)|stay(?:ing)? in (?:the |our |my )?room)\b",
    ),
    (
        "Quiet service requested",
        r"\b(?:quiet(?:ly)?|keep.{0,15}noise.{0,10}down|do not disturb|don't disturb)\b",
    ),
    (
        "Access assistance requested",
        r"\b(?:wheelchair|limited mobility|cannot walk|can't walk|mobility assistance)\b",
    ),
    (
        "Access permission needs clarification",
        r"\b(?:do not|don't|cannot|can't).{0,18}\b(?:enter|come in)\b",
    ),
    (
        "Access permission granted",
        r"\b(?:you (?:can|may) enter|permission to enter|come in now)\b",
    ),
]
QUERIES = {
    "Air conditioning": "air conditioner cooling maintenance room",
    "Plumbing": "plumbing water leak toilet shower",
    "Wi-Fi": "Wi-Fi internet connection",
    "Housekeeping": "housekeeping cleaning towels bedding",
    "Billing": "billing refund payment",
    "Electrical": "electrical power light socket",
}


def extract(text, verified_room=""):
    topic_matches = [
        {"topic": label, "evidence": m.group()}
        for label, pattern in TOPICS
        if (m := re.search(pattern, text, re.I))
    ]
    constraints = [
        {"constraint": label, "evidence": m.group()}
        for label, pattern in CONSTRAINTS
        if (m := re.search(pattern, text, re.I))
    ]
    room = ROOM.search(text)
    sentences = [
        s.strip() for s in re.split(r"(?<=[.!?])\s+|[\r\n]+", text) if s.strip()
    ]
    issue = next(
        (
            s
            for s in sentences
            if any(re.search(pattern, s, re.I) for _, pattern in TOPICS)
        ),
        text.strip(),
    )
    locations = [
        m.group()
        for m in re.finditer(
            r"\b(?:bathroom|bedroom|balcony|hallway|corridor|kitchen|lobby)\b",
            text,
            re.I,
        )
    ]
    return {
        "topic": topic_matches[0]["topic"] if topic_matches else "General request",
        "topics": topic_matches,
        "issue": issue,
        "constraints": constraints,
        "locations": list(dict.fromkeys(locations)),
        "reported_room": room.group(1) if room else "",
        "verified_room": verified_room,
        "method": "Word-pattern extraction with exact text evidence",
    }


def suggest(db, hotel, extracted, urgency):
    from hotel.procedures import select

    return select(db, hotel, extracted, urgency)
