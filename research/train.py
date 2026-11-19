"""Called by the six-phase Colab notebook. Streamlit only loads exported artifacts."""

import hashlib
import json
import time

import joblib
import nltk
import numpy as np
import pandas as pd
from nltk.stem import WordNetLemmatizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    make_scorer,
    recall_score,
    precision_score,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from hotel import nlp
from research.urgency import WeightedTermLogistic


def frozen_split(df, verified=False):
    keys = ["source", "review_id"]
    manifest = pd.read_csv(nlp.ROOT / "research/partition.csv")
    rows = manifest.merge(df, on=keys, how="left", validate="one_to_one", sort=False)
    missing = rows.text.isna()
    if (
        (missing & (rows.partition == "test")).any()
        or (not verified and missing.any())
        or len(df) != (~missing).sum()
    ):
        raise ValueError(
            "Expected the original review cohort. Keep the locked split intact."
        )
    rows = rows[~missing].copy()
    digests = rows.text.map(lambda text: hashlib.sha256(text.encode()).hexdigest())
    if not digests.equals(rows.text_sha256):
        raise ValueError("A review differs from its locked text fingerprint.")
    return rows[rows.partition == "train"], rows[rows.partition == "test"]


def critical_rank(recall, precision, macro_f1):
    # Select by validation only. Avoid winning critical recall by flagging every guest.
    eligible = recall >= 2 / 3 and precision >= 0.50
    return (eligible, macro_f1 if eligible else min(recall, precision), macro_f1)


def training_search(a, target, extra=None):
    searches = []
    estimators = [
        LogisticRegression(max_iter=1200, class_weight="balanced"),
        LinearSVC(class_weight="balanced", random_state=4453),
    ]
    if target == "urgency":
        estimators.append(WeightedTermLogistic(max_iter=1200, class_weight="balanced"))
    experiments = [(estimator, None) for estimator in estimators]
    if target == "urgency" and extra is not None:
        experiments.append(
            (WeightedTermLogistic(max_iter=1200, class_weight="balanced"), extra)
        )
    for estimator, supplement in experiments:
        pipe = Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        preprocessor=nlp.normalize, lowercase=False, sublinear_tf=True
                    ),
                ),
                ("model", estimator),
            ]
        )
        params = {"tfidf__ngram_range": [(1, 1), (1, 2)], "model__C": [0.5, 2]}
        scoring = {"macro": "f1_macro"}
        refit = "macro"
        if target == "urgency":
            scoring.update(
                recall=make_scorer(
                    recall_score, labels=["Critical"], average="macro", zero_division=0
                ),
                precision=make_scorer(
                    precision_score,
                    labels=["Critical"],
                    average="macro",
                    zero_division=0,
                ),
            )
        if isinstance(estimator, WeightedTermLogistic):
            params.update(
                {
                    "tfidf__min_df": [2],
                    "model__C": [0.5, 2, 8],
                    "model__critical_bias": [0.0, 1.0, 2.0],
                }
            )

            def refit(results):
                return max(
                    range(len(results["params"])),
                    key=lambda i: critical_rank(
                        *[
                            results["mean_test_" + k][i]
                            for k in ("recall", "precision", "macro")
                        ]
                    ),
                )

        fit = (
            pd.concat([a, supplement], ignore_index=True)
            if supplement is not None
            else a
        )
        # Every candidate is scored on identical validation rows. Additional labeled
        # safety examples are training-only, including inside every validation fold.
        folds = [
            (np.r_[tr, np.arange(len(a), len(fit))], va)
            for tr, va in StratifiedKFold(3, shuffle=True, random_state=4453).split(
                a.text, a[target]
            )
        ]
        grid = GridSearchCV(pipe, params, cv=folds, scoring=scoring, refit=refit)
        grid.fit(fit.text, fit[target])
        grid.experiment = (
            "supplemental safety training"
            if supplement is not None
            else "original training cohort"
        )
        searches.append(grid)

    def rank(grid):
        i = grid.best_index_
        if target == "urgency":
            return critical_rank(
                *[
                    grid.cv_results_["mean_test_" + k][i]
                    for k in ("recall", "precision", "macro")
                ]
            )
        return grid.cv_results_["mean_test_macro"][i]

    return searches, max(searches, key=rank)


def train(data, verified=False):
    df = data.copy()
    if verified:
        df = df[df.reviewed.astype(str).str.lower().eq("true")]
        if len(df) < 1000:
            raise ValueError("The assessment requires 1,000 human-reviewed records.")
    df["signature"] = df.text.map(nlp.clean)
    df = (
        df[df.signature.str.len() > 0]
        .drop_duplicates("signature")
        .reset_index(drop=True)
    )
    if verified and len(df) < 1000:
        raise ValueError(
            "Fewer than 1,000 unique reviewed texts remain after cleaning."
        )
    a, b = frozen_split(df, verified)
    supplement = pd.read_csv(nlp.ROOT / "research/safety_reviews.csv")
    supplement_keys = supplement.set_index(["source", "review_id"]).index
    if not supplement_keys.is_unique or len(
        supplement_keys.intersection(df.set_index(["source", "review_id"]).index)
    ):
        raise ValueError("Safety review IDs overlap the original cohort.")
    signatures = supplement.text.map(nlp.clean)
    if signatures.duplicated().any() or signatures.isin(df.signature).any():
        raise ValueError("Safety review texts overlap another partition.")
    added = supplement[supplement.partition == "train"]
    if verified:
        added = added[added.reviewed.astype(str).str.lower().eq("true")]
    challenge = supplement[supplement.partition == "challenge"]
    path = nlp.ROOT / "artifacts"
    path.mkdir(exist_ok=True)
    nltk.data.path.insert(0, str(nlp.ROOT / ".runtime/nltk_data"))
    lemma = WordNetLemmatizer()
    words = sorted({token for text in a.text for token in nlp.clean(text).split()})
    # Cache a fixed WordNet lookup for offline inference. Unseen forms keep their spelling.
    forms = {w: lemma.lemmatize(lemma.lemmatize(w, "v"), "n") for w in words}
    (path / "lemmas.json").write_text(
        json.dumps({w: v for w, v in forms.items() if w != v}), encoding="utf8"
    )
    nlp.lexicon.cache_clear()
    models, results, errors = {}, {}, []
    selected = {
        target: training_search(a, target, added)
        for target in ["urgency", "department"]
    }
    # Both champions and every hyperparameter are frozen before scoring the test reviews.
    comparison = {}
    for target, (candidates, best) in selected.items():
        models[target] = best.best_estimator_
        labels = list(models[target].classes_)
        runs = []
        for grid in candidates:
            pred = grid.predict(b.text)
            report = classification_report(
                b[target], pred, labels=labels, output_dict=True, zero_division=0
            )
            runs.append(
                {
                    "model": type(grid.best_estimator_["model"]).__name__,
                    "experiment": grid.experiment,
                    "selected": grid is best,
                    "cv_macro_f1": grid.cv_results_["mean_test_macro"][
                        grid.best_index_
                    ],
                    "parameters": grid.best_params_,
                    "accuracy": accuracy_score(b[target], pred),
                    "report": report,
                    "tuning": [
                        {"parameters": p, "macro_f1": float(s)}
                        for p, s in zip(
                            grid.cv_results_["params"],
                            grid.cv_results_["mean_test_macro"],
                        )
                    ],
                }
            )
        pred = best.predict(b.text)
        if target == "urgency":
            before = max(
                candidates[:2],
                key=lambda g: g.cv_results_["mean_test_macro"][g.best_index_],
            )
            predictions = {"Before": before.predict(b.text), "After": pred}
            for name, labels_pred in predictions.items():
                report = classification_report(
                    b[target], labels_pred, output_dict=True, zero_division=0
                )
                is_critical = b[target].to_numpy() == "Critical"
                comparison[name] = {
                    "model": type(
                        (before if name == "Before" else best).best_estimator_["model"]
                    ).__name__,
                    "macro_f1": report["macro avg"]["f1-score"],
                    "critical_recall": report["Critical"]["recall"],
                    "critical_precision": report["Critical"]["precision"],
                    "critical_cases": int(is_critical.sum()),
                    "critical_detected": int(
                        (labels_pred[is_critical] == "Critical").sum()
                    ),
                    "false_critical_alerts": int(
                        (labels_pred[~is_critical] == "Critical").sum()
                    ),
                }
            pd.DataFrame(
                {
                    "source": b.source,
                    "review_id": b.review_id,
                    "expected": b.urgency,
                    **predictions,
                }
            ).to_csv(path / "urgency_comparison.csv", index=False)
            for name, g in [("Before", before), ("After", best)]:
                p = g.predict(challenge.text)
                cr = challenge.urgency == "Critical"
                comparison[name]["challenge"] = {
                    "size": len(challenge),
                    "critical_cases": int(cr.sum()),
                    "critical_detected": int((p[cr] == "Critical").sum()),
                    "false_critical_alerts": int((p[~cr] == "Critical").sum()),
                }
        for (_, row), label in zip(b.iterrows(), pred):
            if label != row[target]:
                errors.append(
                    {
                        "id": str(row.review_id),
                        "text": row.text,
                        "target": target,
                        "expected": row[target],
                        "predicted": label,
                    }
                )
        results[target] = {
            "champion": type(models[target]["model"]).__name__,
            "labels": labels,
            "champion_experiment": best.experiment,
            "runs": runs,
            "confusion": confusion_matrix(b[target], pred, labels=labels).tolist(),
        }
    mode = "human-reviewed" if verified else "provisional rule labels"
    digest = hashlib.sha256(
        (
            a[["text", "urgency", "department"]].to_csv(index=False)
            + added[["text", "urgency"]].to_csv(index=False)
            + json.dumps(
                {
                    k: [v["champion"], selected[k][1].best_params_]
                    for k, v in results.items()
                },
                sort_keys=True,
            )
        ).encode()
    ).hexdigest()[:10]
    version = f"tfidf-v2-{digest}"
    joblib.dump({"models": models, "version": version}, nlp.MODEL, compress=3)
    nlp.bundle.cache_clear()
    latencies = []
    for text in b.text.head(100):
        start = time.perf_counter()
        nlp.analyze(text)
        latencies.append(1000 * (time.perf_counter() - start))
    report = {
        "version": version,
        "labels_status": mode,
        "rows": len(df),
        "train": len(a),
        "test": len(b),
        "targets": results,
        "urgency_comparison": comparison,
        "evaluation_status": "Previously inspected locked holdout; not a new unseen evaluation",
        "urgency_extra_train": len(added),
        "urgency_extra_critical": int(added.urgency.eq("Critical").sum()),
        "errors": sorted(errors, key=lambda e: e["expected"] != "Critical")[:5],
        "p95_ms": float(np.percentile(latencies, 95)),
    }
    (path / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
    )
    b[["source", "review_id", "text", "urgency", "department"]].to_csv(
        path / "holdout.csv", index=False
    )
    return report


if __name__ == "__main__":
    train(pd.read_csv(nlp.ROOT / "data/reviews.csv"))
