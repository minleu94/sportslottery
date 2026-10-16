from copy import deepcopy

from core.experiment_identity import (
    build_experiment_identity,
    get_current_experiment_identity,
    validate_experiment_identity,
)
from core.performance_metrics import PerformanceMetricsEngine
from core.snapshot_logger import compute_prediction_payload_hash
from core.strategy_version import STRATEGY_VERSION, get_strategy_metadata, hash_prediction_manifest


def _identity_variant(*, code=None, config=None, strategy_version=None):
    metadata = get_strategy_metadata()
    if code is not None:
        manifest = dict(metadata["prediction_manifest"])
        manifest["core/edge_engine.py"] = code * 64
        metadata["prediction_manifest"] = manifest
        metadata["prediction_manifest_hash"] = hash_prediction_manifest(manifest)
    if config is not None:
        metadata["config_hashes"] = {"config/models.yaml": config * 64}
    if strategy_version is not None:
        metadata["strategy_version"] = strategy_version
    return build_experiment_identity(metadata)


def _snapshot(identity=None, *, key="game-1", side="home", outcome=True, probability=0.6,
              snapshot_id="s1", eligible=True):
    identity = deepcopy(identity or get_current_experiment_identity())
    row = {
        "snapshot_id": snapshot_id,
        "snapshot_timestamp": "2026-10-10T12:00:00+00:00",
        "timestamp": "2026-10-10T12:00:00+00:00",
        "event_id": key,
        "canonical_event_id": key,
        "event_start": "2026-10-11T12:00:00+00:00",
        "sport": "soccer",
        "league": "eng.1",
        "away_team": "Chelsea",
        "home_team": "Arsenal",
        "market": "不讓分",
        "selection": "Arsenal home win",
        "side": side,
        "line": None,
        "taiwan_odds": 2.0,
        "evidence_quality": "HIGH",
        "model_probability": probability,
        "model_market_delta_pp": 10.0,
        "probability_status": "UNVALIDATED_MODEL_ESTIMATE",
        "expected_value": 0.2,
        "forward_validation_eligible": eligible,
        "is_settled": True,
        "settlement_status": "WON" if outcome else "LOST",
        "actual_outcome": outcome,
        "settled_at": "2026-10-12T12:00:00+00:00",
        "result_source": "OFFICIAL_UNIT_TEST_FEED",
        "strategy_version": identity["strategy_version"],
        "experiment_identity": identity,
        "strategy_config_hashes": identity["config_hashes"],
        "strategy_metadata": {"experiment_identity": identity},
        "prediction_hash_schema": 3,
        "settlement_rule_id": "test-rule-v1",
    }
    row["prediction_payload_hash"] = compute_prediction_payload_hash(row)
    return row


def test_identity_stable_and_sensitive_only_to_strategy_content_config_models_and_protocol():
    metadata = get_strategy_metadata()
    first = build_experiment_identity(metadata, protocol_settings={"freshness_policy": "freshness-a"})
    same = build_experiment_identity({**metadata, "generated_at": "another-time", "git_dirty": True},
                                     protocol_settings={"freshness_policy": "freshness-a"})
    changed_code = _identity_variant(code="a")
    changed_config = _identity_variant(config="b")
    changed_protocol = build_experiment_identity(metadata, protocol_settings={"freshness_policy": "freshness-b"})
    assert first["experiment_id"] == same["experiment_id"]
    assert first["experiment_id"] != changed_code["experiment_id"]
    assert first["experiment_id"] != changed_config["experiment_id"]
    assert first["experiment_id"] != changed_protocol["experiment_id"]
    assert validate_experiment_identity(first)
    changed = deepcopy(first)
    changed["protocol_settings"]["freshness_policy"] = "tampered"
    assert not validate_experiment_identity(changed)


def test_historical_v1_identity_remains_verifiable_without_rewriting():
    metadata = get_strategy_metadata()
    legacy = build_experiment_identity({key: value for key, value in metadata.items()
                                        if key not in {"prediction_manifest", "prediction_manifest_hash"}})
    assert legacy["schema"] == "experiment-identity-v1"
    assert validate_experiment_identity(legacy)
    saved = deepcopy(legacy)
    current = get_current_experiment_identity()
    assert current["schema"] == "experiment-identity-v2"
    assert legacy == saved
    assert legacy["experiment_id"] != current["experiment_id"]


def test_default_metrics_select_only_current_experiment_and_require_hashes():
    current = _snapshot()
    other = _snapshot(_identity_variant(code="a"), key="other", snapshot_id="s2")
    legacy = _snapshot()
    legacy.pop("experiment_identity")
    legacy["prediction_payload_hash"] = compute_prediction_payload_hash(legacy)
    metrics = PerformanceMetricsEngine.evaluate_model_overall_metrics([current, other, legacy])
    assert metrics["target_experiment_id"] == get_current_experiment_identity()["experiment_id"]
    assert metrics["sample_size"] == 1
    assert metrics["hit_rate"] == 1.0
    assert metrics["classification_accuracy"] == 1.0
    assert metrics["audit"]["legacy_or_invalid_identity_excluded"] == 1
    assert metrics["audit"]["different_target_identity_excluded"] == 1
    assert "accuracy" not in metrics


def test_retry_dedupes_and_unique_event_count_distinguishes_multiple_selections():
    first = _snapshot(snapshot_id="a", side="home")
    retry = _snapshot(snapshot_id="b", side="home")
    another_selection = _snapshot(snapshot_id="c", side="away", outcome=False, probability=0.4)
    metrics = PerformanceMetricsEngine.evaluate_model_overall_metrics([first, retry, another_selection])
    assert metrics["sample_size"] == 2
    assert metrics["observation_count"] == 2
    assert metrics["unique_event_count"] == 1
    assert metrics["audit"]["duplicate_retries_removed"] == 1
    assert metrics["hit_rate"] == 0.5


def test_conflicting_duplicate_observation_is_excluded():
    first = _snapshot(snapshot_id="a", side="home", outcome=True)
    conflict = _snapshot(snapshot_id="b", side="home", outcome=False)
    metrics = PerformanceMetricsEngine.evaluate_model_overall_metrics([first, conflict])
    assert metrics["sample_size"] == 0
    assert metrics["audit"]["conflicting_observations_excluded"] == 1


def test_compare_experiments_groups_valid_history_and_uses_paired_observations():
    current = _snapshot(key="same-game", side="home", snapshot_id="cur")
    older_identity = _identity_variant(code="c", strategy_version="v2.0-prior")
    other = _snapshot(older_identity, key="same-game", side="home", snapshot_id="other")
    legacy = _snapshot(snapshot_id="legacy")
    legacy.pop("experiment_identity")
    result = PerformanceMetricsEngine.compare_experiments([current, other, legacy])
    assert len(result["experiments"]) == 2
    assert result["paired_observation_count"] == 1
    assert result["legacy_reference"]["excluded_count"] == 1
    assert all(group["model_metrics"]["sample_size"] == 1 for group in result["experiments"].values())
