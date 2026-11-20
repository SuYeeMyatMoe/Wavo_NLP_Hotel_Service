"""Evidence-based conversation features. These rules are not trained classifiers."""

import re
from pathlib import Path
from hotel.resources import singleton

ROOT = Path(__file__).resolve().parents[1]
FRUSTRATION = re.compile(
    r"\b(?:frustrat\w*|furious|unacceptable|ridiculous|again|third time|still waiting|fed up)\b",
    re.I,
)
NEGATED = re.compile(
    r"\b(?:no longer|no (?:sign of )?|without |not any |not a |never )(?:\w+\s+){0,2}(?:leak\w*|smoke|fire|gas|sparks|problem\w*|issue\w*)|\b(?:is|are|was) not (?:leak\w*|broken|dirty|on fire)",
    re.I,
)
RESOLVED = re.compile(
    r"\b(?:fixed|resolved|working (?:now|again)|works(?: fine)?|cooling (?:now|again)|no longer|stopped leaking|connected now|online now)\b",
    re.I,
)
ACTIVE = re.compile(
    r"\b(?:not (?:\w+\s+){0,2}(?:cooling|working|fixed|resolved)|isn['’]t (?:cooling|working)|broken|leak\w*|dirty|missing|smoke|sparks|gas|fire|blocked|cold|hot|no (?:hot water|power|towels)|cannot|can['’]t)\b",
    re.I,
)


def clauses(text):
    return [m for m in re.finditer(r"[^.!?;\n]+(?:[.!?]|$)", text)]


def issue_state(text):
    if re.search(r"\b(?:not|never)\s+(?:fixed|resolved|working|cooling)\b", text, re.I):
        return "active"
    if RESOLVED.search(text):
        return "resolved"
    if NEGATED.search(text) or re.search(
        r"\b(?:do not|don['’]t) (?:smell|see) (?:any )?(?:gas|smoke|fire|sparks)\b",
        text,
        re.I,
    ):
        return "denied"
    return "active" if ACTIVE.search(text) else "uncertain"


def hazard_active(text, match):
    start = max(text.rfind(x, 0, match.start()) for x in ".!?;\n") + 1
    end_candidates = [p for x in ".!?;\n" if (p := text.find(x, match.end())) >= 0]
    segment = text[start : min(end_candidates) if end_candidates else len(text)]
    # Scope negation to the hazard's local clause, not another issue in the sentence.
    for part in re.split(r"\bbut\b|\bhowever\b", segment, flags=re.I):
        if match.group().lower() in part.lower():
            return issue_state(part) not in {"denied", "resolved"}
    return True


@singleton
def vader():
    import nltk
    from nltk.sentiment import SentimentIntensityAnalyzer

    nltk.data.path.insert(0, str(ROOT))
    return SentimentIntensityAnalyzer(lexicon_file="artifacts/vader_lexicon.txt")


def inspect(text, context=""):
    from hotel.extraction import TOPICS, extract

    ex = extract(text)
    issues = []
    for sentence in clauses(text):
        for part in re.finditer(
            r".+?(?=\bbut\b|\bhowever\b|$)", sentence.group(), re.I
        ):
            line = part.group().strip(" ,")
            if not line:
                continue
            for topic, pattern in TOPICS:
                if (
                    topic == "Plumbing"
                    and re.search(r"\bgas leak\b", line, re.I)
                    and not re.search(
                        r"\b(?:water|shower|toilet|tap|drain)\b", line, re.I
                    )
                ):
                    continue
                if re.search(pattern, line, re.I):
                    issues.append(
                        {
                            "topic": topic,
                            "state": issue_state(line),
                            "evidence": line,
                            "start": sentence.start() + part.start(),
                            "end": sentence.start() + part.end(),
                        }
                    )
    active = [i for i in issues if i["state"] == "active"]
    if active:
        ex["topic"], ex["issue"] = active[0]["topic"], active[0]["evidence"]
    normalized = text.strip().lower()
    confirmation = re.match(
        r"^(?:yes|yeah|okay|ok|sure|go ahead|no|that worked|it works|it is fixed|thanks)\b",
        normalized,
    )
    followup = re.search(
        r"\b(?:still|again|update|when will|how long|not fixed|not resolved)\b",
        text,
        re.I,
    )
    request = re.search(
        r"\b(?:please|could you|can (?:you|someone)|need|send|bring|how (?:do|can))\b",
        text,
        re.I,
    )
    if followup:
        label, evidence = "follow-up", followup.group()
    elif confirmation and not active:
        label, evidence = "confirmation", confirmation.group()
    elif active:
        label, evidence = "complaint", active[0]["evidence"]
    elif request:
        label, evidence = "request", request.group()
    else:
        label, evidence = "uncertain", ""
    ambiguous = label == "uncertain" or (label == "confirmation" and not context)
    try:
        scored = [
            {"text": m.group().strip(), **vader().polarity_scores(m.group())}
            for m in clauses(text)
        ]
        score = vader().polarity_scores(text)["compound"]
        sentiment = {
            "label": "positive"
            if score >= 0.05
            else "negative"
            if score <= -0.05
            else "neutral",
            "compound": score,
            "sentences": scored,
            "available": True,
        }
    except (LookupError, OSError):
        sentiment = {
            "label": "unavailable",
            "compound": None,
            "sentences": [],
            "available": False,
        }
    sentiment.update(
        method="NLTK VADER heuristic on English working text",
        frustration=[m.group() for m in FRUSTRATION.finditer(text)],
        limitation="Sentiment is separate from urgency. Sarcasm, dialect and translation can change these scores.",
    )
    ex["issues"] = issues
    return {
        "intent": {
            "label": label,
            "evidence": evidence,
            "ambiguous": ambiguous,
            "method": "Conversation-aware rules",
            "question": "Could you explain what you need help with?"
            if ambiguous
            else "",
        },
        "extraction": ex,
        "issues": issues,
        "sentiment": sentiment,
        "provenance": {
            "evidence_language": "en",
            "evidence_source": "original",
            "method": "rules-and-vader-v1",
        },
    }


def mask_pii(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", "[email]", text)
    return re.sub(r"(?<!\w)(?:\+?\d[\s().-]*){8,}(?!\w)", "[phone]", text)
