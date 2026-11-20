"""Interpret a reply to an explicit offer to send hotel staff."""

import re
import unicodedata


def normalize_reply(text):
    """Normalize common speech punctuation without removing refusals or conditions."""
    value = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    value = value.strip(" \t\r\n\"'“”‘’")
    value = re.sub(r"^(?:(?:uh|um|oh|well)[,.\s]+)+", "", value)
    return re.sub(r"\bo[.\s]+k\b\.?", "okay", value)


def service_consent(text):
    """Return True, False, or None (unclear); never infer consent from an issue."""
    value = normalize_reply(text)
    # Negation must concern the visit/permission, not the reported problem
    # ("Yes, send maintenance. The AC still doesn't work.").
    if re.search(
        r"^(?:no|nope|nah)\b|\b(?:not now|not yet|maybe|wait|hold on|cancel|later)\b"
        r"|\b(?:don't|do not|never|cannot|can't|must not|should not)\s+"
        r"(?:(?:please|want|need|allow|let|wish|to)\s+)*(?:send|come|enter|visit|anyone|someone|staff|the team|maintenance|housekeeping|consent|agree|approve|authorize)\b"
        r"|\bno\s+need\s+to\s+send\b"
        r"|\b(?:no|not)\s+(?:maintenance|housekeeping|staff|visits?|permission)\b",
        value,
    ):
        return False
    if re.search(r"\b(?:if|unless|whether)\b|\?", value) and not re.match(
        r"^(?:please\s+)?(?:can|could|would)\s+you\s+(?:please\s+)?send\b", value
    ):
        return None
    if re.match(
        r"^(?:yes|yeah|yep|yup|okay|ok|sure|certainly|absolutely|of course|"
        r"go ahead|please do|that's fine|sounds good|all right|alright|"
        r"(?:that(?:'s| is)|it(?:'s| is)) (?:okay|ok|fine))\b",
        value,
    ):
        return True
    if re.match(
        r"^(?:(?:please\s+)?(?:(?:can|could|would)\s+you\s+|you\s+(?:can|may)\s+)?)"
        r"(?:please\s+)?send\s+(?:(?:the|a)\s+)?"
        r"(?:maintenance|housekeeping|team|staff|technician|someone|them)\b",
        value,
    ):
        return True
    return None
