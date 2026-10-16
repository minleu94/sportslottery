from copy import deepcopy
import pytest

from core.model_calibration import fit_chronological_temperature
from probability.calibration import apply_multiclass_temperature


def _rows(split, dates, outcomes):
    return [{"date": date, "outcome_idx": outcome,
             "forecast": [0.75, 0.15, 0.10] if outcome == 0 else [0.15, 0.75, 0.10]}
            for date, outcome in zip(dates, outcomes)]


def test_temperature_fit_uses_earlier_rows_and_produces_finite_normalized_holdout():
    training = _rows("train", [f"2024-01-{i:02d}" for i in range(1, 11)], [0, 1] * 5)
    holdout = _rows("holdout", [f"2024-02-{i:02d}" for i in range(1, 5)], [0, 1, 0, 1])
    fit = fit_chronological_temperature(training, holdout, probability_key="forecast")
    assert fit["fit_method"] == "multiclass_temperature_scaling_nll-v1"
    assert fit["training_max_date"] < fit["evaluation_min_date"]
    assert len(fit["evaluation_probabilities"]) == len(holdout)
    for probs in fit["evaluation_probabilities"]:
        assert all(0 < p < 1 for p in probs)
        assert sum(probs) == pytest.approx(1.0)

    changed_holdout = deepcopy(holdout)
    for row in changed_holdout:
        row["outcome_idx"] = 2
    changed = fit_chronological_temperature(training, changed_holdout, probability_key="forecast")
    assert changed["temperature"] == fit["temperature"]


def test_chronological_calibration_rejects_overlapping_or_reversed_dates():
    training = _rows("train", ["2024-02-01", "2024-02-02"], [0, 1])
    holdout = _rows("holdout", ["2024-02-02", "2024-02-03"], [0, 1])
    with pytest.raises(ValueError, match="strictly precede"):
        fit_chronological_temperature(training, holdout, probability_key="forecast")


def test_temperature_application_rejects_invalid_values():
    with pytest.raises(ValueError):
        apply_multiclass_temperature([0.5, 0.5], 0)
