from __future__ import annotations

from datetime import datetime, timezone

from core.clv_reporting import build_clv_report
from core.experiment_identity import build_experiment_identity, get_current_experiment_identity
from core.recommendation_replay import compare_experiment_versions, replay_recommendation
from core.snapshot_logger import compute_prediction_payload_hash
from core.strategy_version import get_strategy_metadata
from core.odds_watcher import select_last_prestart_observation


def _snapshot(*, identity=None, event="evt-1", start="2026-10-13T20:00:00+00:00",
              prediction="2026-10-13T18:00:00+00:00", probability=0.7, odds=2.0,
              outcome=None, status="PENDING", side="主", line=None, market="不讓分",
              result_source="STATS_API"):
    identity = identity or get_current_experiment_identity()
    meta = get_strategy_metadata()
    meta["experiment_identity"] = identity
    row = {
        "prediction_hash_schema": 4,
        "snapshot_id": f"snap-{identity['experiment_id']}-{event}-{prediction}",
        "observation_window_id": "window-1",
        "snapshot_timestamp": prediction,
        "event_id": event,
        "canonical_event_id": event,
        "event_start": start,
        "sport": "baseball",
        "league": "MLB",
        "market": market,
        "selection": "Home",
        "side": side,
        "line": line,
        "taiwan_odds": odds,
        "recommendation_probability": probability,
        "expected_value": probability * odds - 1,
        "strategy_version": identity["strategy_version"],
        "strategy_metadata": meta,
        "strategy_config_hashes": identity["config_hashes"],
        "experiment_identity": identity,
        "forward_validation_eligible": True,
        "settlement_status": status,
        "is_settled": status in {"WON", "LOST"},
        "result_source": result_source,
        "actual_outcome": outcome,
        "settled_at": "2026-10-14T01:00:00+00:00" if status in {"WON", "LOST"} else None,
        "signal_evidence": {"independent_support_count": 2, "supporting_groups": ["market", "model"]},
    }
    row["prediction_payload_hash"] = compute_prediction_payload_hash(row)
    return row


def _variant_identity():
    metadata = get_strategy_metadata()
    base = get_current_experiment_identity()
    return build_experiment_identity(metadata, {**base["protocol_settings"], "comparison_variant": "v-next"})


def test_clv_uses_exact_last_prestart_observation_and_labels_observed_price():
    row = _snapshot()
    start = row["event_start"]
    observations = [
        {"event_id": "evt-1", "canonical_event_id": "evt-1", "sport": "baseball", "league": "MLB",
         "market": "不讓分", "selection": "Home", "side": "主", "line": None, "odds": 1.8,
         "observed_at": "2026-10-13T19:40:00+00:00", "event_start": start, "source": "BOOK_FEED", "status": "LIVE"},
        {"event_id": "evt-1", "canonical_event_id": "evt-1", "sport": "baseball", "league": "MLB",
         "market": "不讓分", "selection": "Home", "side": "客", "line": None, "odds": 9.0,
         "observed_at": "2026-10-13T19:55:00+00:00", "event_start": start, "source": "BOOK_FEED", "status": "LIVE"},
        {"event_id": "evt-1", "canonical_event_id": "evt-1", "sport": "baseball", "league": "MLB",
         "market": "不讓分", "selection": "Home", "side": "主", "line": None, "odds": 1.1,
         "observed_at": "2026-10-13T20:01:00+00:00", "event_start": start, "source": "BOOK_FEED", "status": "LIVE"},
        {"event_id": "evt-1", "canonical_event_id": "evt-1", "sport": "baseball", "league": "MLB",
         "market": "不讓分", "selection": "Home", "side": "主", "line": 1.5, "odds": 1.2,
         "observed_at": "2026-10-13T19:59:00+00:00", "event_start": start, "source": "BOOK_FEED", "status": "LIVE"},
        {"event_id": "evt-1", "canonical_event_id": "evt-1", "sport": "baseball", "league": "MLB",
         "market": "不讓分", "selection": "Home", "side": "主", "line": None, "odds": 1.85,
         "observed_at": "2026-10-13T19:50:00+00:00", "event_start": start, "source": "BOOK_FEED", "status": "LIVE"},
    ]
    report = build_clv_report([row], observations, as_of="2026-10-13T20:10:00+00:00")
    prediction = report["predictions"][0]
    assert prediction["status"] == "LAST_PRESTART_OBSERVED"
    assert prediction["last_prestart_observation"]["odds"] == 1.85
    assert prediction["minutes_before_start"] == 10
    assert prediction["within_15_minutes_of_start"] is True
    assert "not verified official" in prediction["price_label"]
    assert report["all_last_prestart_observations"]["sample_size"] == 1
    assert report["observations_within_15_minutes"]["sample_size"] == 1


def test_clv_pending_and_missing_are_explicit_and_bad_identity_is_excluded():
    pending = _snapshot(event="pending", start="2026-10-15T20:00:00+00:00",
                        prediction="2026-10-14T21:00:00+00:00")
    missing = _snapshot(event="missing")
    tampered = dict(missing, taiwan_odds=3.0)
    future_prediction = _snapshot(event="future-pred", start="2026-10-15T20:00:00+00:00",
                                  prediction="2026-10-14T22:30:00+00:00")
    ineligible = _snapshot(event="excluded")
    ineligible["forward_validation_eligible"] = False
    ineligible["prediction_payload_hash"] = compute_prediction_payload_hash(ineligible)
    report = build_clv_report([pending, missing, tampered, future_prediction, ineligible], [],
                              as_of="2026-10-14T22:00:00+00:00")
    assert {row["status"] for row in report["predictions"]} == {"PENDING_EVENT", "NO_PRESTART_QUOTE"}
    assert report["audit"]["invalid_identity_or_payload"] == 1
    assert report["audit"]["not_forward_eligible"] == 1
    assert report["audit"]["non_pre_event_or_after_asof_prediction"] == 1
    assert report["all_last_prestart_observations"]["sample_size"] == 0
    assert report["all_last_prestart_observations"]["mean_odds_clv_ratio"] is None


def test_quote_selector_requires_post_prediction_aware_observation_and_asof_cutoff():
    rows = [
        {"event_id": "e", "canonical_event_id": "e", "sport": "baseball", "league": "MLB",
         "market": "不讓分", "selection": "Home", "side": "主", "line": None,
         "event_start": "2026-10-15T20:00:00+00:00", "observed_at": "2026-10-15T17:00:00+00:00",
         "odds": 1.7, "source": "BOOK_FEED", "status": "LIVE"},
        {"event_id": "e", "canonical_event_id": "e", "sport": "baseball", "league": "MLB",
         "market": "不讓分", "selection": "Home", "side": "主", "line": None,
         "event_start": "2026-10-15T20:00:00+00:00", "observed_at": "2026-10-15T19:30:00+00:00",
         "odds": 1.9, "source": "BOOK_FEED", "status": "LIVE"},
        {"event_id": "e", "canonical_event_id": "e", "sport": "baseball", "league": "MLB",
         "market": "不讓分", "selection": "Home", "side": "主", "line": None,
         "event_start": "2026-10-15T20:00:00+00:00", "observed_at": "2026-10-15T19:50:00+00:00",
         "odds": 1.8, "source": "BOOK_FEED", "status": "LIVE"},
    ]
    args = {"event_id": "e", "canonical_event_id": "e", "sport": "baseball", "league": "MLB",
            "market": "不讓分", "selection": "Home", "side": "主", "line": None,
            "event_start": "2026-10-15T20:00:00+00:00",
            "not_before": "2026-10-15T18:00:00+00:00"}
    assert select_last_prestart_observation(rows, **args, as_of="2026-10-15T19:40:00+00:00")["odds"] == 1.9
    assert select_last_prestart_observation(rows, **args, as_of="2026-10-15T19:55:00+00:00")["odds"] == 1.8
    assert select_last_prestart_observation(rows, **{**args, "not_before": "2026-10-15T19:35:00+00:00"},
                                            as_of="2026-10-15T19:40:00+00:00") is None


def test_replay_recomputes_sealed_ev_and_matched_versions_without_model_calls():
    identity_a = get_current_experiment_identity()
    identity_b = _variant_identity()
    rows = []
    for identity, probs in ((identity_a, (0.8, 0.3)), (identity_b, (0.6, 0.4))):
        for index, (prob, outcome) in enumerate(zip(probs, (True, False)), start=1):
            rows.append(_snapshot(identity=identity, event=f"evt-{index}", probability=prob,
                                  odds=2.0, outcome=outcome, status="WON" if outcome else "LOST"))
    replay = replay_recommendation(rows[0])
    assert replay["integrity_valid"] is True
    assert replay["breakeven_probability"] == 0.5
    assert replay["replayed_expected_value"] == 0.6000000000000001
    assert replay["independent_support_count"] == 2
    assert replay["snapshot_refs"]["prediction_payload_hash"] == rows[0]["prediction_payload_hash"]

    comparison = compare_experiment_versions(
        rows, experiment_ids=[identity_a["experiment_id"], identity_b["experiment_id"]],
        as_of="2026-10-14T02:00:00+00:00",
    )
    assert comparison["status"] == "COMPLETED"
    assert comparison["matched_event_count"] == 2
    assert comparison["settled_matched_count"] == 2
    assert all(item["n"] == 2 for item in comparison["version_metrics"].values())
    assert comparison["version_metrics"][identity_a["experiment_id"]]["selection_hit_rate"] == 0.5


def test_version_comparison_requires_qualified_result_source_and_settled_provenance():
    a, b = get_current_experiment_identity(), _variant_identity()
    for source in (None, "", "MANUAL", "UNKNOWN", "TEST", "FIXTURE"):
        rows = [_snapshot(identity=a, event="source-check", outcome=True, status="WON", result_source=source),
                _snapshot(identity=b, event="source-check", outcome=True, status="WON", result_source=source)]
        result = compare_experiment_versions(
            rows, experiment_ids=[a["experiment_id"], b["experiment_id"]], as_of="2026-10-14T02:00:00+00:00")
        assert result["settled_matched_count"] == 0, source
        assert result["audit"]["invalid_result_source_excluded"] == 2, source

    # Fixture payloads explicitly declare the normalized known source used by the
    # production forward-cohort rule; no network result is implied by this test.
    valid_rows = [_snapshot(identity=a, event="source-check", outcome=True, status="WON",
                            result_source="STATS_API"),
                  _snapshot(identity=b, event="source-check", outcome=True, status="WON",
                            result_source="STATS_API")]
    accepted = compare_experiment_versions(
        valid_rows, experiment_ids=[a["experiment_id"], b["experiment_id"]], as_of="2026-10-14T02:00:00+00:00")
    assert accepted["settled_matched_count"] == 1


def test_comparison_keeps_zero_sample_empty_and_tampered_snapshots_out():
    a, b = get_current_experiment_identity(), _variant_identity()
    row = _snapshot(identity=a, status="PENDING")
    tampered = dict(_snapshot(identity=b), taiwan_odds=1.01)
    result = compare_experiment_versions([row, tampered], experiment_ids=[a["experiment_id"], b["experiment_id"]])
    assert result["status"] == "NO_SETTLED_MATCHED_COHORT"
    assert result["matched_event_count"] == 0
    assert result["settled_matched_count"] == 0
    assert result["version_metrics"][a["experiment_id"]]["n"] == 0
    assert result["version_metrics"][a["experiment_id"]]["brier"] is None


def test_comparison_excludes_conflicting_duplicate_settlements():
    a, b = get_current_experiment_identity(), _variant_identity()
    rows = [
        _snapshot(identity=a, event="conflict", outcome=True, status="WON"),
        _snapshot(identity=a, event="conflict", prediction="2026-10-13T18:30:00+00:00",
                  outcome=False, status="LOST"),
        _snapshot(identity=b, event="conflict", outcome=True, status="WON"),
    ]
    result = compare_experiment_versions(
        rows, experiment_ids=[a["experiment_id"], b["experiment_id"]], as_of="2026-10-14T02:00:00+00:00")
    assert result["matched_event_count"] == 0
    assert result["settled_matched_count"] == 0


def test_replay_never_prefers_fields_not_covered_by_older_hash_schema():
    row=_snapshot(probability=0.7,odds=2.0)
    row["prediction_hash_schema"]=3
    row["consensus_probability"]=0.6
    row["recommendation_probability"]=0.99
    row["independent_support_count"]=999
    row["supporting_groups"]=["injected"]
    row["prediction_payload_hash"]=compute_prediction_payload_hash(row)
    replay=replay_recommendation(row)
    assert replay["integrity_valid"]
    assert replay["probability"]==0.6
    assert replay["independent_support_count"]==2
    assert replay["supporting_groups"]==["market","model"]


def test_legacy_unsealed_eligibility_and_malformed_schema_cannot_certify_metrics():
    row=_snapshot(outcome=True,status="WON")
    row["prediction_hash_schema"]=2
    row["prediction_payload_hash"]=compute_prediction_payload_hash(row)
    variant=_snapshot(identity=_variant_identity(),outcome=True,status="WON")
    comparison=compare_experiment_versions([row,variant],as_of="2026-10-14T03:00:00Z")
    assert comparison["settled_matched_count"]==0
    row["prediction_hash_schema"]="broken"
    assert not replay_recommendation(row)["integrity_valid"]
    report=build_clv_report([row],[],as_of="2026-10-14T03:00:00Z")
    assert report["predictions"]==[]
