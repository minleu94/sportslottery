#!/usr/bin/env python3
"""Offline verification for strict prospective evaluation and benchmark separation."""

from pathlib import Path

from core.experiment_identity import get_current_experiment_identity
from core.forward_evaluation_engine import (
    ForwardEvaluationEngine,
    compute_brier_score,
    compute_log_loss,
    compute_max_drawdown,
)
from core.snapshot_logger import compute_prediction_payload_hash


def _sealed(record):
    record["prediction_hash_schema"] = 4
    record["prediction_payload_hash"] = compute_prediction_payload_hash(record)
    return record


def _market_evidence(event_id, *, sharp=True, fair=0.50):
    source = "the_odds_api:pinnacle" if sharp else "the_odds_api:draftkings"
    benchmark = {
        "taiwan_event_id": str(event_id),
        "taiwan_selection": "home",
        "canonical_event_id": f"baseball:mlb:provider-{event_id}:2026-10-30T14:00:00+00:00",
        "sport": "baseball",
        "league": "MLB",
        "market_type": "MONEYLINE",
        "selection": "home",
        "line": None,
        "source_id": "the_odds_api:consensus",
        "bookmaker_ids": [source],
        "raw_outcome_odds": {source: {"home": 1.95, "away": 1.95}},
        "market_observation_times": {source: {
            "home": "2026-10-30T09:59:00Z",
            "away": "2026-10-30T09:59:00Z",
        }},
        "retrieved_at_utc": "2026-10-30T10:00:00Z",
        "is_synthetic": False,
        "devig_method": "PROPORTIONAL",
        "fair_probability": fair,
        "sharp_fair_probability": fair if sharp else None,
        "source_qualification": "SHARP_QUALIFIED" if sharp else "INTERNATIONAL_MARKET",
        "complete": True,
        "freshness_status": "LIVE",
        "eligible": True,
        "sharp_qualified_source_ids": [source] if sharp else [],
    }
    return {"market_benchmark": benchmark}


def _accepted_model_provenance(identity):
    return {
        "model_candidate_provenances": [{
            "model_id": "test_model",
            "model_version": "1.0.0",
            "artifact_hash": "a" * 64,
            "protocol_hash": "b" * 64,
            "protocol_id": "test-protocol-v1",
            "acceptance_status_at_prediction": "ACCEPTED",
        }],
        "experiment_identity": identity,
        "strategy_metadata": {"experiment_identity": identity},
        "strategy_config_hashes": identity["config_hashes"],
    }


def _row(event_id, outcome, model_prob, *, sharp=True, fair=None, **extra):
    if fair is None:
        fair = 0.51 if outcome else 0.49
    return _sealed({
        "event_id": event_id,
        "prediction_timestamp": "2026-10-30T10:00:00Z",
        "event_start": "2026-10-30T14:00:00Z",
        "sport": "baseball",
        "league": "MLB",
        "market": "不讓分",
        "selection": "home",
        "side": "home",
        "taiwan_odds": 1.90,
        "market_evidence": _market_evidence(event_id, sharp=sharp, fair=fair),
        "model_prob": model_prob,
        "outcome": outcome,
        "forward_validation_eligible": True,
        **extra,
    })


def test_brier_and_log_loss():
    probs = [0.9, 0.1]
    outcomes = [1, 0]
    brier = compute_brier_score(probs, outcomes)
    assert brier is not None and brier < 0.05
    ll = compute_log_loss(probs, outcomes)
    assert ll is not None and ll < 0.2


def test_max_drawdown():
    assert compute_max_drawdown([1.0, -1.0, -2.0, 1.0, -1.0]) == 3.0


def test_data_leakage_omitted():
    row = _row("game_leak", 1, 0.85)
    row["prediction_timestamp"] = "2026-10-31T03:30:00Z"
    row["event_start"] = "2026-10-31T02:00:00Z"
    _sealed(row)
    report = ForwardEvaluationEngine().evaluate_cohort([row], scope_name="MLB")
    assert report.sample_size == 0
    assert report.status == "SHADOW_MODE_ACCUMULATING"


def test_insufficient_evidence_when_n_under_30():
    cohort = [_sealed({
        "event_id": f"game_{i}",
        "prediction_timestamp": "2026-10-31T01:00:00Z",
        "event_start": "2026-10-31T02:00:00Z",
        "taiwan_odds": 1.75,
        "outcome": 1 if i % 2 == 0 else 0,
        "model_prob": 0.55,
        "forward_validation_eligible": True,
    }) for i in range(15)]
    report = ForwardEvaluationEngine().evaluate_cohort(cohort, scope_name="MLB")
    assert report.sample_size == 15
    assert report.status == "SHADOW_MODE_ACCUMULATING"
    assert report.acceptance_gate_qualified is False
    assert "MAINTAIN_SHADOW_LOGGING" in report.shadow_mode_recommendation


def test_three_way_comparison_does_not_claim_weak_model_validated(tmp_path: Path):
    log_file = tmp_path / "shadow_log.jsonl"
    engine = ForwardEvaluationEngine(shadow_log_path=log_file)
    identity = get_current_experiment_identity()
    cohort = [
        _row(
            f"ev_{i}", 1 if i % 2 == 0 else 0,
            0.45 if i % 2 == 0 else 0.55,
            **_accepted_model_provenance(identity),
        )
        for i in range(40)
    ]
    report = engine.evaluate_cohort(cohort, scope_name="MLB_MONEYLINE")
    assert report.sample_size == 40
    assert report.status == "STATISTICAL_ADVANTAGE_NOT_ESTABLISHED"
    assert report.champion_source == "INTERNATIONAL_SHARP_BENCHMARK"
    assert report.acceptance_gate_qualified is False
    assert report.international_market_benchmark.sample_size == 40
    assert report.international_sharp_benchmark.sample_size == 40
    assert report.active_model_strategy.settled_roi_pct is None
    assert "KEEP_MODEL_IN_SHADOW_MODE" in report.shadow_mode_recommendation
    engine.log_shadow_record({"event_id": "test_1", "model_prob": 0.60})
    assert log_file.exists()


def test_model_advantage_requires_hash_and_stable_accepted_lineage():
    identity = get_current_experiment_identity()
    cohort = [
        _row(
            f"good_{i}", i % 2,
            0.90 if i % 2 else 0.10,
            **_accepted_model_provenance(identity),
        )
        for i in range(40)
    ]
    corrupt = dict(cohort[0], outcome=0)
    unsealed = dict(cohort[1])
    unsealed.pop("prediction_payload_hash")
    report = ForwardEvaluationEngine().evaluate_cohort(cohort + [corrupt, unsealed])
    assert report.sample_size == 40
    assert report.acceptance_gate_qualified is True
    assert report.status == "STATISTICAL_ADVANTAGE_SUPPORTED"
    assert report.delta_brier_ci_95[1] < 0


def test_international_market_is_not_promoted_to_sharp():
    cohort = [_row(f"intl_{i}", i % 2, 0.60 if i % 2 else 0.40, sharp=False) for i in range(30)]
    report = ForwardEvaluationEngine().evaluate_cohort(cohort)
    assert report.international_market_benchmark.sample_size == 30
    assert report.international_sharp_benchmark.sample_size == 0
    assert report.paired_sample_size == 0
    assert report.acceptance_gate_qualified is False
    assert report.champion_source == "INTERNATIONAL_MARKET_BENCHMARK"
    assert report.status == "MODEL_EVIDENCE_UNVERIFIED"


def test_repeated_snapshots_count_once_and_roi_is_not_called_settled_without_bets():
    identity = get_current_experiment_identity()
    cohort = []
    for i in range(30):
        base = _row(
            f"dedup_{i}", i % 2,
            0.90 if i % 2 else 0.10,
            **_accepted_model_provenance(identity),
        )
        cohort.extend([base, dict(base, snapshot_id=f"later-{i}")])
    report = ForwardEvaluationEngine().evaluate_cohort(cohort)
    assert report.sample_size == 30
    assert report.active_model_strategy.settled_roi_pct is None
    assert report.active_model_strategy.simulated_bet_count > 0
    assert report.active_model_strategy.simulated_roi_pct is not None
