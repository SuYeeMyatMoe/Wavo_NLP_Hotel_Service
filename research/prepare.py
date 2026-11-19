"""Prepare a reproducible review sample with explicitly provisional operational labels."""

import hashlib
import re
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://data.mendeley.com/public-api/datasets/z47pkh4x95/files?folder_id=root&version=1"
# Candidate annotation rules, independent of guest star ratings.
PATTERNS = [
    (
        "Critical",
        "Front Desk",
        r"electric shock|live wire|gas leak|caught fire|fire broke out|fire hazard|sparks flying|on fire|unsafe wiring|fingers crushed|slippery and dangerous|dangerous bathing|bathtub.{0,16}dangerous|dangerous.{0,35}bathtub",
    ),
    (
        "Urgent",
        "Maintenance",
        r"(?:air.?con(?:dition(?:er|ing))?|\bac\b|heater|toilet|shower|plumbing|water|elevator|lift|lock|electricity).{0,60}(?:broken|not work|wasn.t work|didn.t work|out of order|leak|flood|clog|malfunction|faulty|not cool|too hot)|(?:broken|faulty|leaking|clogged|no hot|without hot).{0,30}(?:water|shower|toilet|air.?con|heater|lock)|power outage",
    ),
    (
        "Moderate",
        "Housekeeping",
        r"\b(?:dirty|filthy|unclean|dusty|mould|mold|cockroach|bedbug|stained|uncleaned)\b|missing towels|not clean(?:ed)?\b",
    ),
    (
        "Moderate",
        "Maintenance",
        r"poor soundproof|thin walls|weak wi.?fi|slow wi.?fi|poor insulation|noisy air|poor drainage",
    ),
    (
        "Moderate",
        "Guest Relations",
        r"\b(?:rude|unhelpful|impolite|unfriendly|unprofessional|disrespectful|dismissive)\b",
    ),
    (
        "Moderate",
        "Front Desk",
        r"wait.{0,22}check.?in|long queue|check.?in.{0,18}(?:slow|delay)|reservation.{0,20}(?:wrong|error)",
    ),
    (
        "Low",
        "Marketing",
        r"recommend|value for money|good value|great location|excellent location",
    ),
    ("Low", "Guest Relations", r"enjoyed|wonderful stay|pleasant stay|friendly staff"),
]


def prepare():
    raw = ROOT / "data/raw"
    raw.mkdir(parents=True, exist_ok=True)
    if not all((raw / f).exists() for f in ["agoda.xlsx", "trip.com.xlsx"]):
        index = requests.get(API, timeout=30)
        index.raise_for_status()
        for item in index.json():
            details = item["content_details"]
            response = requests.get(details["download_url"], timeout=90)
            response.raise_for_status()
            assert (
                hashlib.sha256(response.content).hexdigest() == details["sha256_hash"]
            )
            (raw / Path(item["filename"]).name).write_bytes(response.content)
    df = pd.concat(
        [pd.read_excel(f).assign(source=f.stem) for f in sorted(raw.glob("*.xlsx"))]
    )
    df = df.dropna(subset=["text"]).copy()
    df = df[df.text.map(lambda x: isinstance(x, str))].copy()
    df["normalized"] = (
        df.text.str.lower().str.replace(r"\W+", " ", regex=True).str.strip()
    )
    df = df.drop_duplicates("normalized").sample(frac=1, random_state=4453)
    picks = []
    for urgency, department, pattern in PATTERNS:
        match = df.text.str.contains(pattern, flags=re.I, regex=True)
        picks.append(df[match].head(240).assign(urgency=urgency, department=department))
        df = df[~match]
    result = pd.concat(picks)[["review_id", "source", "text", "urgency", "department"]]
    result["reviewed"] = False
    out = ROOT / "data/reviews.csv"
    if out.exists():
        raise FileExistsError(
            "Keep the existing annotation work. Choose a new output before resampling."
        )
    result.to_csv(out, index=False)
    return result


if __name__ == "__main__":
    prepare()
