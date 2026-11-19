"""Export an offline annotation worksheet without changing labels or the frozen split."""

import argparse
import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def export(destination):
    if destination.exists():
        raise FileExistsError(
            "Choose a new filename; never overwrite an annotation worksheet."
        )
    with (ROOT / "research/partition.csv").open(encoding="utf8", newline="") as file:
        partitions = {(r["source"], r["review_id"]): r for r in csv.DictReader(file)}
    with (ROOT / "data/reviews.csv").open(encoding="utf8", newline="") as file:
        rows = list(csv.DictReader(file))
    fields = [
        "source",
        "review_id",
        "partition",
        "text_sha256",
        "text",
        "original_urgency",
        "original_department",
        "reviewer",
        "reviewed_at_utc",
        "reviewed_urgency",
        "reviewed_department",
        "rationale",
        "review_status",
    ]
    with destination.open("x", encoding="utf8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            split = partitions[(row["source"], row["review_id"])]
            digest = hashlib.sha256(row["text"].encode()).hexdigest()
            if digest != split["text_sha256"]:
                raise ValueError("Review text no longer matches the frozen partition.")
            writer.writerow(
                {
                    "source": row["source"],
                    "review_id": row["review_id"],
                    "partition": split["partition"],
                    "text_sha256": digest,
                    "text": row["text"],
                    "original_urgency": row["urgency"],
                    "original_department": row["department"],
                    "review_status": "provisional_unreviewed",
                }
            )
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(
        f"Exported {export(args.output)} provisional records. No labels or partition files changed."
    )
