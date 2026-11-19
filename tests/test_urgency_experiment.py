import json

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import f1_score

from hotel import nlp
from research.train import frozen_split


def test_evaluation_partitions_and_saved_estimator_agree():
    cohort = pd.read_csv(nlp.ROOT / "data/reviews.csv")
    cohort = cohort.loc[~cohort.text.map(nlp.clean).duplicated()]
    train, test = frozen_split(cohort)
    extra = pd.read_csv(nlp.ROOT / "research/safety_reviews.csv")
    assert set(train.text_sha256).isdisjoint(test.text_sha256)
    assert set(extra.text.map(nlp.clean)).isdisjoint(cohort.text.map(nlp.clean))
    assert len(train) == 835 and len(test) == 210
    predictions = pd.read_csv(nlp.ROOT / "artifacts/urgency_comparison.csv")
    assert predictions.review_id.tolist() == test.review_id.tolist()
    assert np.array_equal(
        predictions.After, nlp.bundle()["models"]["urgency"].predict(test.text)
    )
    report = json.loads(
        (nlp.ROOT / "artifacts/evaluation.json").read_text(encoding="utf8")
    )
    for name in ("Before", "After"):
        values = report["urgency_comparison"][name]
        assert values["macro_f1"] == pytest.approx(
            f1_score(test.urgency, predictions[name], average="macro")
        )
        assert (
            values["critical_detected"]
            == (
                (predictions.expected == "Critical") & (predictions[name] == "Critical")
            ).sum()
        )


def test_changed_evaluation_text_is_rejected():
    data = pd.read_csv(nlp.ROOT / "data/reviews.csv")
    data = data.loc[~data.text.map(nlp.clean).duplicated()].copy()
    manifest = pd.read_csv(nlp.ROOT / "research/partition.csv")
    changed = manifest[manifest.partition == "test"].iloc[0]
    data.loc[
        (data.source == changed.source) & (data.review_id == changed.review_id), "text"
    ] = "Different review"
    with pytest.raises(ValueError, match="fingerprint"):
        frozen_split(data)
