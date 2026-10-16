from datetime import datetime, timedelta, timezone

from core.model_acceptance import evaluate_scope_evidence


def _evidence_rows(n=240):
    rows = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for index in range(n):
        outcome = index % 2
        rows.append({
            "model_id": "model-a", "model_version": "1.2", "league": "EPL", "market": "不讓分",
            "source_scope": "taiwan_forward", "artifact_hash": "a" * 64,
            "protocol_id": "taiwan-forward-binary-temperature-v1", "protocol_hash": "b" * 64,
            "raw_probability": 0.8 if outcome else 0.2, "outcome": outcome,
            "prediction_timestamp": (start + timedelta(days=index)).isoformat(),
            "settled_at": (start + timedelta(days=index, hours=1)).isoformat(),
            "settlement_status": "WON" if outcome else "LOST", "result_source": "STATS_API",
            "market_probability": 0.5, "decimal_odds": 2.05, "event_id": f"e{index}",
        })
    return rows


def _kwargs():
    return {"model_id": "model-a", "model_version": "1.2", "league": "EPL", "market": "不讓分",
            "source_scope": "taiwan_forward", "artifact_hash": "a" * 64,
            "protocol_id": "taiwan-forward-binary-temperature-v1", "protocol_hash_value": "b" * 64,
            "policy": {"min_calibration_samples": 100, "min_evaluation_samples": 100,
                       "bootstrap_rounds": 300, "bootstrap_seed": 17, "roi_lower_bound_min": 0.0}}


def test_exact_scope_chronological_evidence_can_qualify_and_reports_uncertainty():
    result = evaluate_scope_evidence(_evidence_rows(), **_kwargs())
    assert result["accepted"] is True
    assert result["status"] == "ACCEPTED"
    assert result["calibration_n"] == 100
    assert result["evaluation_n"] == 140
    assert result["calibration_max_prediction_timestamp"] < result["evaluation_min_prediction_timestamp"]
    assert result["criteria"] == {"brier_upper_below_zero": True,
                                   "logloss_upper_below_zero": True,
                                   "roi_lower_above_policy": True}
    assert result["metrics"]["paired_brier_delta_95_ci"][1] < 0
    assert result["metrics"]["paired_logloss_delta_95_ci"][1] < 0


def test_missing_wrong_scope_wrong_artifact_or_protocol_never_accepts():
    rows = _evidence_rows()
    args = _kwargs()
    assert evaluate_scope_evidence(rows[:199], **args)["accepted"] is False
    assert evaluate_scope_evidence(rows, **{**args, "model_id": "other"})["accepted"] is False
    assert evaluate_scope_evidence(rows, **{**args, "league": "La Liga"})["accepted"] is False
    assert evaluate_scope_evidence(rows, **{**args, "market": "大小"})["accepted"] is False
    assert evaluate_scope_evidence(rows, **{**args, "artifact_hash": "c" * 64})["accepted"] is False
    assert evaluate_scope_evidence(rows, **{**args, "protocol_hash_value": "d" * 64})["accepted"] is False


def test_external_historical_evidence_is_status_only_even_when_metrics_are_strong():
    rows = [{**row, "source_scope": "football_data_b365_historical"} for row in _evidence_rows()]
    result = evaluate_scope_evidence(rows, **{**_kwargs(), "source_scope": "football_data_b365_historical"})
    assert result["accepted"] is False
    assert result["status"] == "HISTORICAL_ONLY"


def test_overlapping_fit_and_evaluation_timestamps_are_rejected():
    rows = _evidence_rows()
    for row in rows[100:]:
        row["prediction_timestamp"] = rows[99]["prediction_timestamp"]
    result = evaluate_scope_evidence(rows, **_kwargs())
    assert result["accepted"] is False
    assert result["status"] == "INVALID_CHRONOLOGY"


def test_three_way_choices_are_kept_together_in_chronological_fit_and_eval_windows():
    source_rows = _evidence_rows(240)
    rows = []
    for row in source_rows:
        for side in ("HOME", "DRAW", "AWAY"):
            rows.append({**row, "side": side, "line": None})
    result = evaluate_scope_evidence(rows, **_kwargs())
    assert result["accepted"] is True
    assert result["calibration_event_count"] == 100
    assert result["calibration_n"] == 300
    assert result["evaluation_event_count"] == 140
    assert result["evaluation_n"] == 420


def test_invalid_timestamps_odds_and_as_of_fail_closed():
    rows = _evidence_rows()
    invalid = [{**row, "decimal_odds": True} for row in rows]
    result = evaluate_scope_evidence(invalid, **_kwargs())
    assert result["accepted"] is False
    assert result.get("matched_rows", 0) == 0

    future_settlement = [{**row, "settled_at": "2024-12-31T23:00:00+00:00"} for row in rows]
    result = evaluate_scope_evidence(future_settlement, **_kwargs())
    assert result["accepted"] is False
    assert result.get("matched_rows", 0) == 0

    result = evaluate_scope_evidence(rows, **{**_kwargs(), "as_of": "2025-01-01"})
    assert result["accepted"] is False
    assert result["status"] == "INVALID_AS_OF"


def test_event_start_must_precede_prediction_and_not_follow_settlement():
    rows = _evidence_rows()
    rows = [{**row, "event_start": row["prediction_timestamp"]} for row in rows]
    result = evaluate_scope_evidence(rows, **_kwargs())
    assert result["accepted"] is False
    assert result.get("matched_rows", 0) == 0
