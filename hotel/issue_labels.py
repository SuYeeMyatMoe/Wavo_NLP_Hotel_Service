"""Controlled service labels: useful without retaining a guest's exact words."""

import re

# Order specific symptoms before broader equipment matches. Output is always a
# fixed label, never a slice of a private conversation or a generated quotation.
LABELS = [
    ("AC not cooling", r"\b(?:not|isn['’]?t|isnt|no)\s+cooling\b"),
    (
        "AC not working",
        r"\b(?:broken|not working|isn['’]?t working)\b.*\b(?:ac|air con\w*|air conditioner)\b|\b(?:ac|air con\w*|air conditioner)\b.*\b(?:broken|not working|isn['’]?t working)\b",
    ),
    ("Shower leaking", r"\bshower\b.*\bleak\w*\b|\bleak\w*\b.*\bshower\b"),
    (
        "Toilet blocked",
        r"\btoilet\b.*\b(?:block\w*|clog\w*)\b|\b(?:block\w*|clog\w*)\b.*\btoilet\b",
    ),
    ("No hot water", r"\bno hot water\b|\bwater\b.*\b(?:not hot|cold)\b"),
    ("Water leak", r"\b(?:leak\w*|flood\w*)\b"),
    (
        "Wi-Fi connection problem",
        r"\b(?:wi[ -]?fi|internet|network)\b.*\b(?:not working|slow|disconnect\w*|cannot|can['’]?t|broken)\b|\b(?:cannot|can['’]?t|unable to)\b.*\bconnect\b",
    ),
    ("Wi-Fi connection help", r"\b(?:wi[ -]?fi|internet|wireless)\b"),
    ("Breakfast request", r"\bbreakfast\b"),
    (
        "Food or drink request",
        r"\b(?:hungry|lunch|dinner|meal|food|room service|drinks?)\b",
    ),
    ("Fresh towels requested", r"\btowels?\b"),
    ("Bedding requested", r"\b(?:blankets?|bedding|sheets?|pillows?)\b"),
    ("Room cleaning needed", r"\b(?:dirty|cleaning|rubbish|trash)\b"),
    ("Billing query", r"\b(?:bill\w*|refund|charge\w*|payment|invoice|deposit)\b"),
    ("Power or lighting problem", r"\b(?:power|lights?|socket|electric\w*)\b"),
]
FALLBACKS = {
    "Safety": "Safety concern",
    "Air conditioning": "Air conditioning issue",
    "Plumbing": "Plumbing issue",
    "Wi-Fi": "Wi-Fi connection help",
    "Housekeeping": "Housekeeping request",
    "Billing": "Billing query",
    "Electrical": "Power or lighting problem",
    "Food and drink": "Food or drink request",
}
MISSING = "Issue details unavailable"
SAFE_LABELS = {label for label, _ in LABELS} | set(FALLBACKS.values()) | {MISSING}
SUFFIXES = ("", " (reported resolved)", " (denied)", " — clarify")


def problem_label(extracted):
    """Prefer active issues, respect negation and preserve only approved labels."""
    saved = extracted.get("service_label", "")
    if saved in {label + suffix for label in SAFE_LABELS for suffix in SUFFIXES}:
        return saved
    issues = extracted.get("issues", [])
    ordered = sorted(
        issues,
        key=lambda i: {"active": 0, "uncertain": 1, "resolved": 2, "denied": 3}.get(
            i.get("state"), 4
        ),
    )
    issue = ordered[0] if ordered else {}
    topic = issue.get("topic") or extracted.get("topic", "")
    text = issue.get("evidence") or extracted.get("issue", "")
    if issue.get("evidence"):
        # "I'm hungry. Can you order breakfast?" is one service need across
        # two sentences. Combine only the same category AND state so a resolved
        # issue cannot supply the symptom of a different active one.
        text = " ".join(
            i.get("evidence", "")
            for i in ordered
            if i.get("topic") == topic and i.get("state") == issue.get("state")
        )
    # A minimal historical record has no evidence for a more specific symptom.
    if issue and not issue.get("evidence"):
        text = ""
    if topic == "Safety":
        label = "Safety concern"
    else:
        label = next(
            (label for label, pattern in LABELS if re.search(pattern, text, re.I)),
            FALLBACKS.get(topic, MISSING),
        )
    state = issue.get("state")
    if state in {"resolved", "denied"}:
        # Don't display a negated fault as an active one.
        return FALLBACKS.get(topic, label) + (
            " (reported resolved)" if state == "resolved" else " (denied)"
        )
    if state == "uncertain" and not re.search(
        r"\b(?:please|can you|could you|how|need|request|bring|send|order)\b",
        text,
        re.I,
    ):
        return label + " — clarify" if label != MISSING else label
    return label
