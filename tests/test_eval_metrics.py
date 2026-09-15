"""Hand-computed sanity checks for the metrics the eval framework reports —
this is the part of Phase 4 that must not be vibes."""
from __future__ import annotations

from app.evals.metrics import classification_metrics, latency_summary, percentile


def test_classification_metrics_hand_computed():
    # 4 actually-buggy PRs, 4 actually-clean PRs.
    # Model flags PRs 1,2,3 (of which 1,2 are real bugs, 3 is a false alarm)
    # and misses PR 4 (a real bug it didn't catch).
    y_true = [True, True, True, True, False, False, False, False]
    y_pred = [True, True, False, False, True, False, False, False]
    m = classification_metrics(y_true, y_pred)

    assert m.tp == 2  # PRs 1, 2
    assert m.fn == 2  # PRs 3, 4 (real bugs, missed)
    assert m.fp == 1  # PR 5 (clean, wrongly flagged)
    assert m.tn == 3  # PRs 6, 7, 8

    assert m.precision == 2 / 3
    assert m.recall == 2 / 4
    assert m.f1 == 2 * (2 / 3 * 1 / 2) / (2 / 3 + 1 / 2)
    assert m.false_positive_rate == 1 / 4
    assert m.accuracy == 5 / 8


def test_classification_metrics_all_correct():
    y_true = [True, False, True, False]
    y_pred = [True, False, True, False]
    m = classification_metrics(y_true, y_pred)
    assert (m.precision, m.recall, m.f1, m.false_positive_rate) == (1.0, 1.0, 1.0, 0.0)


def test_classification_metrics_no_positives_predicted():
    y_true = [True, True, False]
    y_pred = [False, False, False]
    m = classification_metrics(y_true, y_pred)
    assert m.precision == 0.0  # 0/0 defined as 0, not NaN/error
    assert m.recall == 0.0
    assert m.f1 == 0.0


def test_percentile_matches_known_values():
    values = [10, 20, 30, 40, 50]
    assert percentile(values, 50) == 30
    assert percentile(values, 0) == 10
    assert percentile(values, 100) == 50


def test_latency_summary_empty():
    s = latency_summary([])
    assert s["p50"] == 0.0


def test_latency_summary_basic():
    s = latency_summary([100, 200, 300, 400, 500])
    assert s["p50"] == 300
    assert s["max"] == 500
    assert s["mean"] == 300
