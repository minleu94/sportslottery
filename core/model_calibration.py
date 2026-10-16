"""Chronological fit/evaluation helpers for frozen probability forecasts."""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Sequence

from probability.calibration import apply_multiclass_temperature, fit_multiclass_temperature


def fit_chronological_temperature(
    training_rows: Sequence[Mapping[str, Any]],
    evaluation_rows: Sequence[Mapping[str, Any]],
    *,
    probability_key: str,
    date_key: str = "date",
    outcome_key: str = "outcome_idx",
) -> dict[str, Any]:
    """Fit on an earlier split, then score a later split without refitting."""
    if not training_rows or not evaluation_rows:
        raise ValueError("independent training and evaluation rows are required")
    train_dates = [date.fromisoformat(str(row[date_key])) for row in training_rows]
    eval_dates = [date.fromisoformat(str(row[date_key])) for row in evaluation_rows]
    train_cutoff = max(train_dates)
    evaluation_start = min(eval_dates)
    if train_cutoff >= evaluation_start:
        raise ValueError("calibration training dates must strictly precede evaluation dates")
    vectors = []
    outcomes = []
    for row in (*training_rows, *evaluation_rows):
        vector = row.get(probability_key)
        outcome = row.get(outcome_key)
        if (not isinstance(vector, (list, tuple)) or len(vector) < 2
                or type(outcome) not in {int, bool} or not 0 <= int(outcome) < len(vector)):
            raise ValueError("calibration rows need a valid multiclass vector and integer outcome")
        if (any(isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value)) or float(value) < 0 or float(value) > 1
                for value in vector) or abs(sum(float(value) for value in vector)-1.0) > 1e-6):
            raise ValueError("calibration vectors must be finite normalized probabilities")
    for row in training_rows:
        vectors.append(row[probability_key])
        outcomes.append(row[outcome_key])
    temperature = fit_multiclass_temperature(vectors, outcomes)
    if temperature is None:
        raise ValueError("training split cannot fit a finite temperature")
    evaluation_probs = [apply_multiclass_temperature(row[probability_key], temperature)
                        for row in evaluation_rows]
    return {"temperature": temperature, "training_sample_size": len(training_rows),
            "evaluation_sample_size": len(evaluation_rows), "training_max_date": train_cutoff.isoformat(),
            "evaluation_min_date": evaluation_start.isoformat(),
            "evaluation_probabilities": evaluation_probs,
            "fit_method": "multiclass_temperature_scaling_nll-v1"}


def multiclass_metrics(rows: Sequence[Mapping[str, Any]], vectors: Sequence[Sequence[float]]) -> dict[str, float | int]:
    if len(rows) != len(vectors) or not rows:
        raise ValueError("rows and probability vectors must be nonempty and aligned")
    briers, log_losses = [], []
    for row, vector in zip(rows, vectors):
        raw_outcome = row["outcome_idx"]
        if type(raw_outcome) not in {int, bool}:
            raise ValueError("outcome_idx must be an integer class label")
        outcome = int(raw_outcome)
        probs = [float(p) for p in vector]
        if not all(math.isfinite(p) and 0 <= p <= 1 for p in probs) or abs(sum(probs)-1.0) > 1e-6:
            raise ValueError("probability vector must be finite and sum to one")
        briers.append(sum((p - (1.0 if i == outcome else 0.0)) ** 2 for i, p in enumerate(probs)))
        log_losses.append(-math.log(max(1e-12, probs[outcome])))
    return {"n": len(rows), "multiclass_brier": sum(briers)/len(briers),
            "log_loss": sum(log_losses)/len(log_losses)}
