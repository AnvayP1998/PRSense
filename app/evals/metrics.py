"""Metric computation: precision/recall/F1/FPR and latency percentiles.

Pure functions, no framework dependencies, so they're trivially unit-testable
with hand-computed expected values (see tests/test_eval_metrics.py) — this is
the part of Phase 4 that must not be "vibes".
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ClassificationMetrics:
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def false_positive_rate(self) -> float:
        return self.fp / (self.fp + self.tn) if (self.fp + self.tn) else 0.0

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.n if self.n else 0.0

    def as_dict(self) -> dict:
        return {
            "n": self.n, "tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "accuracy": round(self.accuracy, 4),
        }


def classification_metrics(y_true: list[bool], y_pred: list[bool]) -> ClassificationMetrics:
    if len(y_true) != len(y_pred):
        raise ValueError(f"length mismatch: {len(y_true)} true vs {len(y_pred)} pred")
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    tn = sum(1 for t, p in zip(y_true, y_pred) if not t and not p)
    return ClassificationMetrics(tp=tp, fp=fp, fn=fn, tn=tn)


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile, p in [0, 100]. No numpy needed."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return s[int(k)]
    frac = k - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def latency_summary(latencies_ms: list[float]) -> dict:
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "max": 0.0}
    return {
        "p50": round(percentile(latencies_ms, 50), 1),
        "p95": round(percentile(latencies_ms, 95), 1),
        "p99": round(percentile(latencies_ms, 99), 1),
        "mean": round(sum(latencies_ms) / len(latencies_ms), 1),
        "max": round(max(latencies_ms), 1),
    }
