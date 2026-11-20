"""Compact Streamlit surfaces for explainable NLP and service recovery."""

import json
import pandas as pd
import streamlit as st
from hotel.ui_copy import words
from hotel.ui_client import request


def context(a):
    st.caption(
        "Evidence · "
        + a.get("provenance", {}).get(
            "evidence_source", a.get("retention", "English working text")
        )
    )
    intent = a.get("intent", {})
    sentiment = a.get("sentiment", {})
    with st.container(horizontal=True):
        st.metric("Intent", words(intent.get("label", "Not recorded")).title())
        st.metric("Sentiment", sentiment.get("label", "Not recorded").title())
    if intent.get("ambiguous"):
        st.info(intent["question"])
    with st.expander("Context and sentiment evidence"):
        if intent.get("evidence"):
            st.caption("Intent rule matched")
            st.text(intent["evidence"])
        if a.get("issues"):
            st.dataframe(a["issues"], hide_index=True)
        if sentiment.get("sentences"):
            st.dataframe(sentiment["sentences"], hide_index=True)
        if sentiment.get("frustration"):
            st.write("Frustration cues · " + ", ".join(sentiment["frustration"]))
        st.caption(
            sentiment.get(
                "limitation", "Sentiment is a heuristic and does not determine urgency."
            )
        )


def evaluation():
    r = request("GET", "/evaluation")
    st.caption(
        f"{r['rows']:,} reviews · {r['labels_status']} · frozen test set {r['test']} reviews"
    )
    challenge = r.get("safety_challenge", {})
    st.info(
        f"Historical scores against provisional labels. Safety challenge: {challenge.get('critical_detected', 'unavailable')} of {challenge.get('critical_cases', 'unavailable')} critical cases detected. Independent human review is still needed."
    )
    target = st.selectbox(
        "Model target", ["urgency", "department"], format_func=str.title
    )
    t = r["targets"][target]
    selected = next(
        (row for row in t["runs"] if row.get("selected")),
        next(row for row in t["runs"] if row["model"] == t["champion"]),
    )
    report = selected["report"]
    with st.container(horizontal=True):
        st.metric("Accuracy", f"{selected['accuracy']:.3f}")
        st.metric("Macro F1", f"{report['macro avg']['f1-score']:.3f}")
        st.metric("Weighted F1", f"{report['weighted avg']['f1-score']:.3f}")
    st.caption("Deployed classifier · " + t["champion"] + " · " + r["version"])
    st.dataframe(
        pd.DataFrame(
            {
                label: metrics
                for label, metrics in report.items()
                if isinstance(metrics, dict)
            }
        ).T.rename(
            columns={
                "precision": "Precision", "recall": "Recall",
                "f1-score": "F1 score", "support": "Sample size",
            },
        ),
        width="stretch",
    )
    with st.expander("Champion confusion matrix"):
        st.dataframe(
            pd.DataFrame(t["confusion"], index=t["labels"], columns=t["labels"])
        )
        st.caption("Rows are expected labels. Columns are predictions.")
    st.caption(
        f"Historical warm p95 · {r['p95_ms']:.1f} ms. The expanded engine is measured separately in Colab. Model comparisons, tuning and research charts are in the notebook."
    )


def insights(jump):
    from hotel.insights_ui import render

    render(jump)


def note_review(key, record):
    note = record.get("note", {})
    if not note:
        return
    if not record.get("consent_recorded", True):
        st.caption("Legacy record · transcript consent was not recorded at the time.")
    st.subheader("Service note")
    st.write(note["issue"])
    if note["constraints"]:
        st.write(" · ".join(note["constraints"]))
    st.caption(note["actions"])
    st.write(note["next_step"])
    for question in note["questions"]:
        st.caption("Still to confirm · " + question)
    st.caption(
        "Transcript storage "
        + (
            "accepted"
            if record.get("transcript_consent")
            else "off · service record only"
        )
    )
    with st.expander("Review or correct note"):
        st.caption(
            "Corrections are attributed to your account. Original predictions remain unchanged."
        )
        with st.form("review_" + key):
            issue = st.text_area("Service issue", note["issue"], max_chars=1000)
            constraints = st.text_area(
                "Guest constraints, one per line", "\n".join(note["constraints"])
            )
            next_step = st.text_area(
                "Recommended next step", note["next_step"], max_chars=1000
            )
            if st.form_submit_button("Save reviewed note"):
                request(
                    "POST",
                    f"/calls/{key}/note-review",
                    json={
                        "version": note["version"],
                        "issue": issue,
                        "constraints": [
                            v.strip() for v in constraints.splitlines() if v.strip()
                        ],
                        "next_step": next_step,
                    },
                )
                st.rerun()
        if record.get("revisions"):
            st.dataframe(
                [
                    {k: r[k] for k in ("version", "author", "created")}
                    for r in record["revisions"]
                ],
                hide_index=True,
            )
    if record.get("analyses"):
        with st.expander("Conversation NLP timeline"):
            st.dataframe(
                [
                    {
                        "Turn": i + 1,
                        "Intent": words(a.get("intent", {}).get("label")),
                        "Sentiment": a.get("sentiment", {}).get("label"),
                        "Urgency": a.get("urgency"),
                        "Department": a.get("department"),
                    }
                    for i, a in enumerate(record["analyses"])
                ],
                hide_index=True,
            )


def procedures(manager):
    from hotel.procedures import CATEGORIES, DEPARTMENTS
    from hotel.extraction import CONSTRAINTS

    data = request("GET", "/procedures")
    st.caption(
        "Reception follows approved categories and hotel rules. Unmapped legacy notes remain reference material."
    )
    records = {r["id"]: r for r in data["procedures"]}
    selected = st.selectbox(
        "Procedure",
        [""] + list(records),
        format_func=lambda k: records[k]["title"] if k else "New procedure",
    )
    row = records.get(selected, {})
    if not manager:
        for r in records.values():
            with st.expander(r["title"]):
                st.write(r["body"])
        return
    legacy = {r["id"]: r for r in data["legacy"]}
    imported = st.selectbox(
        "Start from a legacy note",
        [""] + list(legacy),
        format_func=lambda k: legacy[k]["title"] if k else "None",
        key="legacy_" + selected,
    )
    source = legacy.get(imported, row)
    with st.form("procedure_" + selected + imported):
        title = st.text_input("Title", source.get("title", ""), max_chars=100)
        category = st.selectbox(
            "Issue category",
            CATEGORIES,
            index=CATEGORIES.index(row.get("category", CATEGORIES[0])),
        )
        department = st.selectbox(
            "Responsible team",
            DEPARTMENTS,
            index=DEPARTMENTS.index(row.get("department", DEPARTMENTS[0])),
        )
        body = st.text_area("Approved actions", source.get("body", ""), max_chars=6000)
        conditions = st.multiselect(
            "Apply when these constraints are present",
            [c[0] for c in CONSTRAINTS],
            default=json.loads(row.get("constraints", "[]")),
        )
        questions = st.text_area(
            "Clarifications · field | question, one per line",
            "\n".join(
                q["field"] + " | " + q["question"]
                for q in json.loads(row.get("questions", "[]"))
            ),
        )
        approval = st.text_input(
            "Approval requirement", row.get("approval", ""), max_chars=600
        )
        enabled = st.checkbox("Approved for reception", bool(row.get("enabled", True)))
        completion_minutes = st.number_input(
            "Expected completion (minutes from assignment)",
            min_value=1,
            max_value=1440,
            value=row.get("completion_minutes"),
            placeholder="Leave blank if unknown",
        )
        st.caption(
            "Includes waiting and service time. This estimate is shown to guests. Arrival and internal deadlines are tracked separately."
        )
        if st.form_submit_button("Save procedure", type="primary"):
            pairs = [
                line.split("|", 1) for line in questions.splitlines() if line.strip()
            ]
            if any(len(pair) != 2 for pair in pairs):
                st.error("Use field | question on each line.")
            else:
                request(
                    "POST",
                    "/procedures",
                    json={
                        "id": selected,
                        "version": row.get("version", 0),
                        "title": title,
                        "category": category,
                        "department": department,
                        "body": body,
                        "constraints": conditions,
                        "questions": [
                            {"field": p[0].strip(), "question": p[1].strip()}
                            for p in pairs
                        ],
                        "approval": approval,
                        "enabled": enabled,
                        "completion_minutes": completion_minutes,
                    },
                )
                st.rerun()
