from copy import deepcopy

from core.edge_engine import EdgeEngine
from core.performance_metrics import PerformanceMetricsEngine
from core.experiment_identity import get_current_experiment_identity
from core.snapshot_logger import compute_prediction_payload_hash
from core.strategy_version import STRATEGY_VERSION


def valid_snapshot():
    identity = get_current_experiment_identity()
    record = {"forward_validation_eligible": True, "is_settled": True, "settlement_status": "WON",
            "actual_outcome": True, "strategy_version": STRATEGY_VERSION, "taiwan_odds": 2,
            "evidence_quality": "HIGH", "model_probability": 0.6, "expected_value": 0.2,
            "probability_status": "UNVALIDATED_MODEL_ESTIMATE", "model_market_delta_pp": 10,
            "crowd_ratio": 0.7, "verified_experts": [], "snapshot_timestamp": "2026-10-10T12:00:00Z",
            "event_id": "forward-event", "canonical_event_id": "forward-event",
            "event_start": "2026-10-11T12:00:00Z", "sport": "soccer", "league": "eng.1",
            "settled_at": "2026-10-12T12:00:00Z", "result_source": "STATS_API",
            "away_team": "Chelsea", "home_team": "Arsenal", "market": "不讓分",
            "selection": "Arsenal", "side": "home", "line": None,
            "experiment_identity": identity, "strategy_config_hashes": identity["config_hashes"],
            "strategy_metadata": {"experiment_identity": identity}, "prediction_hash_schema": 3,
            "settlement_rule_id": "test-rule-v1"}
    record["prediction_payload_hash"] = compute_prediction_payload_hash(record)
    return record


def test_unknown_cutoff_old_versions_and_nonbinary_results_never_enter_forward_metrics():
    record = valid_snapshot()
    excluded = []
    for changes in [{"forward_validation_eligible": False}, {"forward_validation_eligible": None},
                    {"settlement_status": "VOID", "actual_outcome": None},
                    {"settlement_status": "WON", "actual_outcome": False},
                    {"strategy_version": "v1.0-live"}, {"taiwan_odds": float("nan")}]:
        item = deepcopy(record)
        item.update(changes)
        item["prediction_payload_hash"] = compute_prediction_payload_hash(item)
        excluded.append(item)
    metrics = PerformanceMetricsEngine()
    observations = excluded + [record]
    assert metrics.evaluate_agreement_buckets(observations)["HIGH"]["sample_size"] == 1
    assert metrics.evaluate_model_overall_metrics(observations)["sample_size"] == 1
    assert sum(row["sample_size"] for row in metrics.evaluate_ev_buckets(observations).values()) == 1


def test_market_baseline_is_not_model_calibration_data():
    baseline = valid_snapshot()
    baseline["probability_status"] = "MARKET_BASELINE_ONLY"
    metrics = PerformanceMetricsEngine()
    assert metrics.evaluate_model_overall_metrics([baseline])["sample_size"] == 0
    assert sum(row["sample_size"] for row in metrics.evaluate_calibration_bins([baseline]).values()) == 0
    assert sum(row["sample_size"] for row in metrics.evaluate_ev_buckets([baseline]).values()) == 0


def test_wider_confidence_level_widens_actual_sample_interval():
    ninety = EdgeEngine.calculate_confidence_interval(0.6, 100, 0.90)
    ninety_five = EdgeEngine.calculate_confidence_interval(0.6, 100, 0.95)
    assert ninety_five.lower_bound < ninety.lower_bound
    assert ninety_five.upper_bound > ninety.upper_bound
