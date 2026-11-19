"""Fold-local supervised term weighting for an imbalanced linear text classifier."""

import numpy as np
from sklearn.feature_selection import chi2
from sklearn.linear_model import LogisticRegression


class WeightedTermLogistic(LogisticRegression):
    """Fit in a class-sensitive feature space; export coefficients in ordinary TF-IDF units."""

    def __init__(
        self, C=1.0, class_weight="balanced", max_iter=1200, critical_bias=0.0
    ):
        super().__init__(C=C, class_weight=class_weight, max_iter=max_iter)
        self.critical_bias = critical_bias

    def fit(self, X, y, sample_weight=None):
        presence = X.copy()
        presence.data.fill(1)
        association, _ = chi2(presence, y)
        # Compress extreme chi-square values. Damp single-document coincidences.
        support = np.asarray(presence.sum(axis=0)).ravel()
        scale = 1 + np.log1p(association) * support / (support + 2)
        super().fit(X.multiply(scale).tocsr(), y, sample_weight=sample_weight)
        self.coef_ *= scale
        self.intercept_[self.classes_ == "Critical"] += self.critical_bias
        return self
