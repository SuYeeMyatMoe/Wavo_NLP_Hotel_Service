"""Inference shared by the Colab experiment, HTTP service, and voice worker."""

import html
import json
import re
import unicodedata
from pathlib import Path
from hotel.resources import singleton

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "artifacts" / "model.joblib"
ROOM = re.compile(r"\b(?:room|rm)\s*#?\s*(\d{1,5}[a-z]?)\b", re.I)
STOP = set(
    "a an the in of on to at for from and is are was were have has had my our we i it this that".split()
)
HAZARDS = re.compile(
    r"\b(gas leak|smell of gas|smell gas|smoke coming|smoke filling|sparks flying|electric shock|exposed (?:live )?wires?|room (?:is )?on fire)\b",
    re.I,
)
EXAMPLE = "The air conditioner in Room 305 is broken."


def clean(text):
    value = (
        unicodedata.normalize("NFKC", html.unescape(text)).casefold().replace("’", "'")
    )
    value = re.sub(r"https?://\S+|www\.\S+|<[^>]*>", " ", value)
    value = re.sub(r"[\w.+-]+@[\w.-]+\.\w+|\b(?:\+?\d[\s().-]*){8,}\b", " ", value)
    value = ROOM.sub(" ", value)
    for before, after in {
        "can't": "cannot",
        "won't": "will not",
        "n't": " not",
        "'re": " are",
        "'s": " is",
        "'m": " am",
        "a/c": "air conditioner",
    }.items():
        value = value.replace(before, after)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


@singleton
def lexicon():
    return json.loads((ROOT / "artifacts" / "lemmas.json").read_text(encoding="utf8"))


def steps(text):
    cleaned = clean(text)
    tokens = cleaned.split()
    lemmas = [lexicon().get(word, word) for word in tokens if word not in STOP]
    return {"cleaned": cleaned, "tokens": tokens, "lemmas": lemmas}


def normalize(text):
    return " ".join(steps(text)["lemmas"])


@singleton
def bundle():
    import joblib

    return joblib.load(MODEL)


def evidence(pipe, text):
    import numpy as np

    vec, model = pipe.named_steps["tfidf"], pipe.named_steps["model"]
    x = vec.transform([text])
    names = vec.get_feature_names_out()
    scores = np.ravel(model.decision_function(x))
    if len(model.classes_) == 2:
        scores = np.array([-scores[0], scores[0]])
    chosen = int(np.argmax(scores))
    coefs = (
        model.coef_[chosen]
        if len(model.classes_) > 2
        else model.coef_[0] * (1 if chosen else -1)
    )
    bias = (
        model.intercept_[chosen]
        if len(model.classes_) > 2
        else model.intercept_[0] * (1 if chosen else -1)
    )
    features = [
        {"term": str(names[i]), "weight": float(w), "contribution": float(w * coefs[i])}
        for i, w in zip(x.indices, x.data)
    ]
    features.sort(key=lambda row: -abs(row["contribution"]))
    return {
        "label": str(model.classes_[chosen]),
        "score": float(scores[chosen]),
        "bias": float(bias),
        "score_type": "Decision margin"
        if type(model).__name__ == "LinearSVC"
        else "Linear class score",
        "model": type(model).__name__,
        "features": features,
        "vocabulary": len(names),
        "class_scores": {
            str(label): float(value) for label, value in zip(model.classes_, scores)
        },
    }


def analyze(text, context=""):
    if not text.strip() or len(text) > 8000:
        raise ValueError("Enter a complaint between 1 and 8,000 characters.")
    pack = bundle()
    outputs = {target: evidence(pipe, text) for target, pipe in pack["models"].items()}
    urgency, department = (outputs[k]["label"] for k in ("urgency", "department"))
    rule = None
    from hotel.intelligence import inspect, hazard_active

    details = inspect(text, context)
    hazard = next((m for m in HAZARDS.finditer(text) if hazard_active(text, m)), None)
    if hazard:
        urgency, department, rule = (
            "Critical",
            "Front Desk",
            "Safety alert: " + hazard.group(),
        )
    elif details["issues"] and all(
        i["state"] in {"denied", "resolved"} for i in details["issues"]
    ):
        urgency, department, rule = (
            "Low",
            "Front Desk",
            "No active issue identified; confirm whether help is still needed.",
        )
    elif not all(p["features"] for p in outputs.values()):
        department, urgency, rule = (
            "Front Desk",
            "Unassessed",
            "No matched features. Staff review required.",
        )
    room = ROOM.search(text)
    return {
        "text": text,
        "room": room.group(1) if room else "",
        "version": pack["version"],
        **steps(text),
        "predictions": outputs,
        "urgency": urgency,
        "department": department,
        "rule": rule,
        **details,
    }
