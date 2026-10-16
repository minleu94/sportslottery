from copy import deepcopy
from datetime import datetime, timezone

from core.experiment_identity import get_current_experiment_identity
from core.parlay_validation import evaluate_parlay_forward, shared_event_exposure, evaluation_tier, prediction_hash
from core.recommendation_replay import replay_parlay_recommendation, replay_parlay_recommendations
from core.shadow_parlay_logger import ShadowParlayLogger
from core.snapshot_logger import PredictionSnapshotLogger
from integrations.common.models import TaiwanLeg


class Before(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 1, 1, 10, tzinfo=timezone.utc)


class After(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 1, 10, 10, tzinfo=timezone.utc)


def ticket(tmp_path, monkeypatch, *, event_day=2, prefix="", statuses=("WON", "WON")):
    import core.snapshot_logger as snapshot_module
    import core.shadow_parlay_logger as parlay_module
    monkeypatch.setattr(snapshot_module, "datetime", Before)
    monkeypatch.setattr(parlay_module, "datetime", Before)
    logger = PredictionSnapshotLogger(tmp_path / "legs.jsonl")
    legs = [TaiwanLeg(event_id=prefix + str(i), sport="baseball", league="MLB", market="不讓分",
                      selection="客勝", taiwan_odds=4.0, away_team="洋基", home_team="紅襪",
                      side="客", start_time_utc=f"2026-01-{event_day:02d}T10:00:00+00:00",
                      odds_scraped_at="2026-01-01T09:59:00+00:00", odds_status="FRESH",
                      signal_evidence={"probability_status": "MARKET_BASELINE_ONLY",
                                       "publication_time_precision": "NOT_APPLICABLE"}) for i in (1, 2)]
    snapshots = logger.log_batch(legs)
    for leg, row in zip(legs, snapshots):
        leg.signal_evidence["snapshot_id"] = row["snapshot_id"]
    parlay = ShadowParlayLogger(tmp_path / "tickets.jsonl")
    item = {"legs": [leg.to_dict() for leg in legs], "total_odds": 16.0,
            "joint_probability": .05, "naive_joint_probability": .0625, "correlation_penalty": .2}
    records = parlay.log_daily_parlays({"10-25x": {"high_consensus": [item]}},
                                       prediction_snapshots=snapshots)
    candidate = records[0]["candidates"][0]
    results = deepcopy(snapshots)
    for row, status in zip(results, statuses):
        row.update(is_settled=True, settlement_status=status, actual_outcome=status == "WON",
                   settled_at="2026-01-10T09:00:00+00:00", result_source="OFFICIAL_TEST_FEED")
    monkeypatch.setattr(parlay_module, "datetime", After)
    parlay.settle_parlay_candidate_with_taiwan_rules(candidate["candidate_id"], [(status, 4.0) for status in statuses],
                                                    leg_result_snapshots=results)
    return parlay.get_all_parlay_snapshots(), parlay, candidate


def test_real_logger_to_parlay_metrics_without_grafting_identity(tmp_path, monkeypatch):
    records, _, candidate = ticket(tmp_path, monkeypatch)
    assert candidate["forward_validation_eligible"], candidate["forward_exclusion_reason"]
    result = evaluate_parlay_forward(records, get_current_experiment_identity()["experiment_id"])
    tier = result["tiers"]["10-25x"]
    assert tier["n"] == 1
    assert tier["brier"] == (.05 - 1) ** 2
    assert tier["roi_pct"] == 1500
    assert tier["cluster_bootstrap_ci95"] is None


def test_whole_parlay_replay_reads_sealed_probabilities_and_leg_snapshot_refs(tmp_path, monkeypatch):
    records, _, candidate = ticket(tmp_path, monkeypatch)
    replay = replay_parlay_recommendation(candidate)
    assert replay["integrity_valid"] is True
    assert replay["forward_validation_eligible"] is True
    assert replay["math_consistent"] is True
    assert replay["original_total_odds"] == 16
    assert replay["breakeven_probability"] == 1 / 16
    assert replay["joint_probability"] == .05
    assert replay["naive_joint_probability"] == .0625
    assert replay["correlation_penalty"] == .2
    assert abs(replay["expected_value"] + .2) < 1e-12
    assert len(replay["legs"]) == 2
    assert all(row["snapshot_ref"]["snapshot_id"] for row in replay["legs"])
    report = replay_parlay_recommendations(records)
    assert report["candidate_count"] == 1
    assert report["recommendations"][0]["candidate_id"] == candidate["candidate_id"]


def test_whole_parlay_replay_fails_closed_on_hash_missing_refs_and_math_tamper(tmp_path, monkeypatch):
    _, _, candidate = ticket(tmp_path, monkeypatch)
    tampered = deepcopy(candidate)
    tampered["joint_probability"] = .9
    rejected_hash = replay_parlay_recommendation(tampered)
    assert rejected_hash["integrity_valid"] is False
    assert rejected_hash["forward_validation_eligible"] is False
    assert "TICKET_PAYLOAD_HASH_MISMATCH" in rejected_hash["exclusion_reasons"]

    missing = deepcopy(candidate)
    missing["validation_legs"] = missing["validation_legs"][:1]
    missing["prediction_payload_hash"] = prediction_hash(missing)
    rejected_refs = replay_parlay_recommendation(missing)
    assert rejected_refs["forward_validation_eligible"] is False
    assert "MISSING_PRE_EVENT_LEG_SNAPSHOTS" in rejected_refs["exclusion_reasons"]

    inconsistent = deepcopy(candidate)
    inconsistent["correlation_penalty"] = .1
    inconsistent["prediction_payload_hash"] = prediction_hash(inconsistent)
    rejected_math = replay_parlay_recommendation(inconsistent)
    assert rejected_math["integrity_valid"] is True
    assert rejected_math["forward_validation_eligible"] is False
    assert "INCONSISTENT_HEURISTIC_ESTIMATE" in rejected_math["exclusion_reasons"]


def test_tamper_and_missing_result_source_are_excluded(tmp_path, monkeypatch):
    records, _, _ = ticket(tmp_path, monkeypatch)
    changed = deepcopy(records)
    changed[0]["candidates"][0]["joint_probability"] = .9
    result = evaluate_parlay_forward(changed, get_current_experiment_identity()["experiment_id"])
    assert result["tiers"]["10-25x"]["n"] == 0
    changed = deepcopy(records)
    changed[0]["candidates"][0]["leg_result_snapshots"][0]["result_source"] = None
    result = evaluate_parlay_forward(changed, get_current_experiment_identity()["experiment_id"])
    assert result["excluded_counts"]["INVALID_RESULT_PROVENANCE"] == 1


def test_repeated_candidates_do_not_inflate_n(tmp_path, monkeypatch):
    records, _, _ = ticket(tmp_path, monkeypatch)
    result = evaluate_parlay_forward(records + deepcopy(records), get_current_experiment_identity()["experiment_id"])
    assert result["tiers"]["10-25x"]["n"] == 1


def test_evaluation_tier_endpoints_are_disjoint():
    assert [evaluation_tier(value) for value in (10, 24.99, 25, 75, 200, 500)] == [
        "10-25x", "10-25x", "25-75x", "75-200x", "200-500x", "200-500x"]
    assert evaluation_tier(500.01) is None


def test_manual_result_source_is_not_forward_evidence(tmp_path, monkeypatch):
    records, _, _ = ticket(tmp_path, monkeypatch)
    records[0]["candidates"][0]["leg_result_snapshots"][0]["result_source"] = "MANUAL"
    report = evaluate_parlay_forward(records, get_current_experiment_identity()["experiment_id"])
    assert report["excluded_counts"]["INVALID_RESULT_PROVENANCE"] == 1


def test_pending_leg_never_finishes_ticket(tmp_path):
    logger = ShadowParlayLogger(tmp_path / "pending.jsonl")
    records = logger.log_daily_parlays({"10-25x": {"high_consensus": [{"total_odds": 12,
                    "legs": [{"event_id": "a"}, {"event_id": "b"}]}]}})
    key = records[0]["candidates"][0]["candidate_id"]
    for statuses in ([("WON", 3), ("PENDING", 4)], [("VOID", 3), ("PENDING", 4)]):
        row = logger.settle_parlay_candidate_with_taiwan_rules(key, statuses)
        assert row["settled"] is False
        assert row["settlement_status"] == "PENDING"


def test_event_exposure_uses_event_not_selection_and_scopes_local_ids():
    def leg(league, selection):
        return {"sport": "baseball", "league": league, "event_id": "1",
                "start_time_utc": "2026-01-01T10:00:00+00:00", "selection": selection}
    rows = shared_event_exposure([{"legs": [leg("MLB", "客勝")]},
                                 {"legs": [leg("MLB", "主勝")]},
                                 {"legs": [leg("NPB", "客勝")]}])
    assert rows[0]["overlapping_ticket_numbers"] == [2]
    assert rows[0]["maximum_event_overlap_ratio"] == 1
    assert rows[2]["shared_event_count"] == 0


def test_cluster_intervals_resample_slates_and_are_reproducible(tmp_path, monkeypatch):
    records = []
    for i in range(6):
        result, _, _ = ticket(tmp_path / str(i), monkeypatch, event_day=2+i, prefix=str(i),
                              statuses=("WON", "WON") if i % 2 else ("LOST", "WON"))
        records.extend(result)
    identity = get_current_experiment_identity()["experiment_id"]
    first = evaluate_parlay_forward(records, identity, replicates=100)
    second = evaluate_parlay_forward(records, identity, replicates=100)
    tier = first["tiers"]["10-25x"]
    assert first == second
    assert tier["n"] == tier["event_slate_cluster_count"] == 6
    assert tier["cluster_bootstrap_ci95"]["hit_rate"][0] < tier["hit_rate"] < tier["cluster_bootstrap_ci95"]["hit_rate"][1]


def test_many_tickets_on_one_slate_are_not_independent_samples(tmp_path, monkeypatch):
    records = []
    for i in range(6):
        result, _, _ = ticket(tmp_path / str(i), monkeypatch, prefix=str(i))
        records.extend(result)
    report = evaluate_parlay_forward(records, get_current_experiment_identity()["experiment_id"], replicates=100)
    tier = report["tiers"]["10-25x"]
    assert tier["n"] == 6
    assert tier["event_slate_cluster_count"] == 1
    assert tier["cluster_bootstrap_ci95"] is None
