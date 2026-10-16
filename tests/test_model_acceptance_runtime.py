from copy import deepcopy

import pytest

from core.edge_engine import EdgeEngine
from core.model_acceptance import acceptance_evidence_hash, protocol_hash
from probability.calibration import apply_binary_temperature
from core.signal_hub import SignalHub
from integrations.common.models import PredictionSignal, TaiwanLeg


def _leg():
    return TaiwanLeg(event_id="gate-event", sport="soccer", league="EPL", market="不讓分",
                     selection="Home", taiwan_odds=2.0, start_time="2026-10-14T20:00:00+00:00",
                     away_team="Away", home_team="Home", side="主")


def _signal(*, accepted=False, scope_overrides=None, freshness="FRESH"):
    model_id, model_version = "dixon", "2.0"
    artifact_hash, protocol_id = "a"*64, "taiwan-forward-binary-temperature-v1"
    protocol_hash_value = protocol_hash({"protocol_id": protocol_id})
    scope = {"model_id": model_id, "model_version": model_version, "league": "EPL", "market": "不讓分",
             "source_scope": "taiwan_forward", "artifact_hash": artifact_hash,
             "protocol_id": protocol_id, "protocol_hash": protocol_hash_value}
    scope.update(scope_overrides or {})
    temperature = 1.0
    acceptance = {"accepted": accepted, "status": "ACCEPTED" if accepted else "REJECTED",
                  "scope": scope, "calibration_temperature": temperature,
                  "calibration_n": 100, "calibration_event_count": 100,
                  "evaluation_n": 100, "evaluation_event_count": 100,
                  "evaluation_cluster_count": 50,
                  "calibration_max_prediction_timestamp": "2026-01-01T00:00:00+00:00",
                  "calibration_outcomes_known_by": "2026-01-02T00:00:00+00:00",
                  "evaluation_min_prediction_timestamp": "2026-01-03T00:00:00+00:00",
                  "criteria": {"brier_upper_below_zero": True,
                               "logloss_upper_below_zero": True,
                               "roi_lower_above_policy": True},
                  "metrics": {"paired_brier_delta_95_ci": [-0.2, -0.1]}}
    if accepted:
        acceptance["evidence_derived"] = True
        acceptance["evidence_hash"] = acceptance_evidence_hash(acceptance)
    metadata = {"model_id": model_id, "model_version": model_version, "model_artifact_hash": artifact_hash,
                "model_protocol_id": protocol_id, "model_protocol_hash": protocol_hash_value,
                "prediction_source_scope": "taiwan_forward", "configured_weight": 1.0,
                "model_candidate_probability": 0.8,
                "model_acceptance": acceptance}
    if accepted:
        metadata["model_calibrated_probability"] = apply_binary_temperature(0.8, temperature)
        metadata["calibration_provenance"] = {
            "temperature": temperature, "fit_cutoff": acceptance["calibration_max_prediction_timestamp"],
            "outcomes_known_by": acceptance["calibration_outcomes_known_by"],
            "training_sample_size": acceptance["calibration_n"], "protocol_id": protocol_id,
        }
    probability = apply_binary_temperature(0.8, temperature) if accepted else 0.8
    return PredictionSignal(source_id=model_id, source_name="Dixon model", source_type="MODEL",
                            source_category="EXTERNAL_OPEN_SOURCE_ENGINE", independence_group="DIXON_COLES_MATCHES",
                            event_id="gate-event", market="不讓分", selection="Home", probability=probability,
                            score=10.0, freshness_status=freshness, metadata=metadata)


def _hub():
    return SignalHub(model_registry=object(), edge_engine=EdgeEngine())


def test_unaccepted_model_stays_visible_as_research_but_cannot_change_recommendation_or_support():
    leg = _hub().synthesize_signals_for_leg(_leg(), [_signal(accepted=False)])
    assert leg.signal_evidence["model_candidate_probability_raw"] == pytest.approx(0.8)
    assert leg.signal_evidence["model_candidate_probability_fused"] > 0.5
    assert leg.signal_evidence["probability_status"] == "MARKET_BASELINE_ONLY"
    assert leg.signal_evidence["model_probability_raw"] is None
    assert leg.consensus_probability == pytest.approx(0.5)
    assert leg.signal_evidence["support_count"] == 0
    assert leg.signal_evidence["quality_score"] == 0


@pytest.mark.parametrize("scope_overrides", [
    {"model_id": "other-model"},
    {"model_version": "stale-version"},
    {"league": "La Liga"},
    {"market": "大小"},
    {"source_scope": "football_data_b365_historical"},
    {"artifact_hash": "c"*64},
    {"protocol_hash": "d"*64},
])
def test_wrong_exact_scope_cannot_use_an_accepted_flag(scope_overrides):
    leg = _hub().synthesize_signals_for_leg(_leg(), [_signal(accepted=True, scope_overrides=scope_overrides)])
    assert leg.signal_evidence["model_probability_raw"] is None
    assert leg.consensus_probability == pytest.approx(0.5)
    assert leg.signal_evidence["support_count"] == 0


@pytest.mark.parametrize("mutation", ["missing_marker", "tampered_hash", "wrong_calibrated_probability"])
def test_accepted_boolean_without_matching_evidence_certificate_fails_closed(mutation):
    signal = _signal(accepted=True)
    if mutation == "missing_marker":
        signal.metadata["model_acceptance"].pop("evidence_derived")
    elif mutation == "tampered_hash":
        signal.metadata["model_acceptance"]["metrics"]["paired_brier_delta_95_ci"] = [0.1, 0.2]
    else:
        signal.metadata["model_calibrated_probability"] = 0.7
    leg = _hub().synthesize_signals_for_leg(_leg(), [signal])
    assert leg.signal_evidence["model_probability_raw"] is None
    assert leg.consensus_probability == pytest.approx(0.5)
    assert leg.signal_evidence["support_count"] == 0


def test_accepted_exact_scope_can_contribute_to_fusion_and_support():
    signal = _signal(accepted=True)
    # Registry-calibrated probability differs from the raw research candidate.
    temperature = 1.2
    calibrated = apply_binary_temperature(0.8, temperature)
    acceptance = signal.metadata["model_acceptance"]
    acceptance["calibration_temperature"] = temperature
    acceptance["evidence_hash"] = acceptance_evidence_hash(acceptance)
    signal.probability = calibrated
    signal.metadata["model_calibrated_probability"] = calibrated
    signal.metadata["calibration_provenance"]["temperature"] = temperature
    leg = _hub().synthesize_signals_for_leg(_leg(), [signal])
    assert leg.signal_evidence["model_probability_raw"] == pytest.approx(calibrated)
    assert leg.signal_evidence["model_candidate_probability_raw"] == pytest.approx(0.8)
    assert leg.signal_evidence["model_candidate_probability_fused"] > 0.5
    # The exact calibrated probability evaluated by the gate reaches runtime;
    # there is no additional beta shrinkage or multi-model fusion.
    assert leg.consensus_probability == pytest.approx(calibrated)
    assert leg.signal_evidence["model_probability_calibrated"] == pytest.approx(calibrated)
    assert leg.signal_evidence["active_model_champion_id"] == "dixon"


def test_active_probability_preserves_certified_extreme_value_without_second_clip():
    signal = _signal(accepted=True)
    raw = 0.999999
    temperature = 0.25
    calibrated = apply_binary_temperature(raw, temperature)
    acceptance = signal.metadata["model_acceptance"]
    acceptance["calibration_temperature"] = temperature
    acceptance["evidence_hash"] = acceptance_evidence_hash(acceptance)
    signal.metadata["model_candidate_probability"] = raw
    signal.metadata["model_calibrated_probability"] = calibrated
    signal.metadata["calibration_provenance"]["temperature"] = temperature
    signal.probability = calibrated
    leg = _hub().synthesize_signals_for_leg(_leg(), [signal])
    assert calibrated > 0.999
    assert leg.consensus_probability == calibrated
    assert leg.signal_evidence["support_count"] == 1
    assert leg.signal_evidence["quality_score"] > 0


def test_stale_model_remains_provenance_only_and_never_changes_fusion():
    leg = _hub().synthesize_signals_for_leg(_leg(), [_signal(accepted=True, freshness="STALE")])
    assert leg.signal_evidence["model_probability_raw"] is None
    assert leg.consensus_probability == pytest.approx(0.5)
    assert leg.signal_evidence["support_count"] == 0
    assert leg.signal_evidence["model_candidate_provenances"][0]["model_id"] == "dixon"
