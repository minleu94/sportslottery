from datetime import datetime, timedelta, timezone
import json
import tempfile
from pathlib import Path

from core.experiment_identity import get_current_experiment_identity
from core.performance_metrics import PerformanceMetricsEngine
from core.snapshot_logger import PredictionSnapshotLogger
from core.snapshot_logger import compute_prediction_payload_hash
from core.model_acceptance import ModelAcceptanceGate
from integrations.common.models import PredictionSignal, TaiwanLeg


def test_real_snapshot_settlement_and_metrics_preserve_current_experiment_identity(monkeypatch):
    from core import snapshot_logger as snapshot_logger_module
    real_now = datetime.now(timezone.utc)
    snapshot_time = real_now - timedelta(days=2)
    event_start = real_now - timedelta(days=1)
    settlement_time = real_now - timedelta(hours=12)
    clock_values = iter([snapshot_time, settlement_time])

    class ControlledDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = next(clock_values)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(snapshot_logger_module, "datetime", ControlledDateTime)
    now = snapshot_time
    leg = TaiwanLeg(
        event_id="identity-e2e-1", canonical_event_id="identity-e2e-1", sport="soccer", league="EPL",
        market="不讓分", selection="Home", taiwan_odds=2.1, start_time=event_start.isoformat(),
        start_time_utc=event_start.isoformat(), away_team="Away", home_team="Home", side="主",
        odds_scraped_at=(now - timedelta(minutes=1)).isoformat(), odds_status="FRESH",
    )
    signal = PredictionSignal(
        source_id="fixture-model", source_name="Fixture model", source_type="MODEL",
        source_category="OPEN_SOURCE_ENGINE", independence_group="fixture-model", event_id=leg.event_id,
        market=leg.market, selection=leg.selection, probability=0.7, freshness_status="FRESH",
        data_as_of=(now - timedelta(hours=2)).isoformat(), metadata={"model_id": "fixture-model", "model_version": "1",
            "model_acceptance": {"accepted": True, "status": "ACCEPTED", "scope": {"league": "EPL", "market": "不讓分"}},
            "configured_weight": 1.0},
    )
    leg.signals = [signal]
    leg.consensus_probability = 0.7
    leg.model_probability_raw = 0.7
    leg.model_probability_calibrated = 0.7
    leg.expected_value = 0.47
    leg.signal_evidence = {
        "probability_status": "CALIBRATED_MODEL_ESTIMATE", "consensus_probability": 0.7,
        "model_probability_raw": 0.7, "model_probability_calibrated": 0.7,
        "model_fusion_groups": ["fixture-model"], "model_fusion_groups": ["fixture-model"],
        "model_acceptance_statuses": [{"model_id": "fixture-model", "status": "ACCEPTED"}],
        "model_candidate_provenances": [{"source_id": "fixture-model", "model_id": "fixture-model",
            "model_version": "1", "artifact_hash": "a" * 64, "protocol_id": "test-v1",
            "protocol_hash": "b" * 64, "source_scope": "taiwan_forward", "raw_probability": 0.7,
            "data_as_of": signal.data_as_of, "freshness_status": "FRESH", "acceptance_status": "ACCEPTED"}],
        "publication_time_precision": "NOT_APPLICABLE", "model_market_delta_pp": 22.4,
    }
    # Atomic replacement is exercised under the writable workspace on Windows.
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
        logger = PredictionSnapshotLogger(Path(folder) / "prediction_snapshots.jsonl")
        snapshot = logger.log_snapshot(leg)
        identity = get_current_experiment_identity()
        assert snapshot["experiment_identity"] == identity
        assert snapshot["strategy_metadata"]["experiment_identity"] == identity
        assert snapshot["forward_validation_eligible"] is True
        assert snapshot["model_candidate_predictions"][0]["model_id"] == "fixture-model"
        sealed_hash = snapshot["prediction_payload_hash"]
        leg.signal_evidence["snapshot_id"] = snapshot["snapshot_id"]
        assert snapshot["prediction_payload_hash"] == sealed_hash
        assert compute_prediction_payload_hash(snapshot) == sealed_hash

        settled = logger.settle_prediction(snapshot["snapshot_id"], True, settlement_status="WON")
        assert settled["experiment_identity"] == identity
        from core.performance_metrics import _is_forward_binary
        assert _is_forward_binary(settled, identity["experiment_id"])
        metrics = PerformanceMetricsEngine.evaluate_model_overall_metrics([settled])
        assert metrics["target_experiment_id"] == identity["experiment_id"]
        assert metrics["sample_size"] == 1
        assert metrics["hit_rate"] == 1.0
        assert metrics["audit"]["legacy_or_invalid_identity_excluded"] == 0


def test_observation_window_id_seals_distinct_same_day_snapshots():
    now = datetime.now(timezone.utc)
    leg = TaiwanLeg(event_id="window-e2e", sport="soccer", league="EPL", market="不讓分",
                    selection="Home", taiwan_odds=2.1, start_time="2026-10-14T20:00:00+00:00",
                    start_time_utc=(now + timedelta(days=1)).isoformat(), away_team="Away", home_team="Home",
                    side="主", odds_scraped_at=(now-timedelta(minutes=1)).isoformat(), odds_status="FRESH")
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
        logger = PredictionSnapshotLogger(Path(folder) / "prediction_snapshots.jsonl")
        first = logger.log_snapshot(leg, observation_window_id="run-001")
        second = logger.log_snapshot(leg, observation_window_id="run-002")
        assert first["snapshot_id"] != second["snapshot_id"]
        assert first["observation_window_id"] == "run-001"
        assert second["observation_window_id"] == "run-002"
        tampered = dict(first, observation_window_id="run-003")
        assert compute_prediction_payload_hash(tampered) != first["prediction_payload_hash"]


def test_acceptance_ledger_rejects_tampered_snapshot_prediction_hash():
    now = datetime.now(timezone.utc)
    leg = TaiwanLeg(
        event_id="gate-hash-e2e", sport="baseball", league="MLB", market="不讓分",
        selection="Home", taiwan_odds=2.1, start_time_utc=(now + timedelta(days=1)).isoformat(),
        away_team="Away", home_team="Home", side="主",
        odds_scraped_at=(now - timedelta(minutes=1)).isoformat(), odds_status="FRESH",
    )
    signal = PredictionSignal(
        source_id="gate-hash-model", source_name="Gate hash model", source_type="MODEL",
        source_category="OPEN_SOURCE_ENGINE", independence_group="gate-hash-model",
        event_id=leg.event_id, market=leg.market, selection=leg.selection, probability=0.7,
        freshness_status="FRESH", data_as_of=(now - timedelta(hours=1)).isoformat(),
        metadata={"model_id": "gate-hash-model", "model_version": "1"},
    )
    leg.signals = [signal]
    leg.consensus_probability = 0.7
    leg.signal_evidence = {
        "probability_status": "UNVALIDATED_MODEL_ESTIMATE",
        "consensus_probability": 0.7,
        "model_fusion_groups": ["gate-hash-model"],
        "publication_time_precision": "NOT_APPLICABLE",
        "market_complete": True,
        "market_outcome_odds": {"主": 2.1, "客": 2.1},
        "market_fair_probability": 0.5,
        "market_fair_method": "COMPLETE_MARKET_PROPORTIONAL",
        "model_candidate_provenances": [{"model_id": "gate-hash-model", "model_version": "1",
            "artifact_hash": "a" * 64, "protocol_id": "test-protocol", "protocol_hash": "b" * 64,
            "source_scope": "taiwan_forward", "raw_probability": 0.7,
            "data_as_of": signal.data_as_of, "freshness_status": "FRESH"}],
    }
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
        path = Path(folder) / "prediction_snapshots.jsonl"
        logger = PredictionSnapshotLogger(path)
        row = logger.log_snapshot(leg)
        assert row["forward_validation_eligible"] is True, row.get("exclusion_reason")
        logger.settle_prediction(row["snapshot_id"], True, settlement_status="WON", result_source="STATS_API")
        persisted = json.loads(path.read_text(encoding="utf-8"))
        persisted["settled_at"] = (now + timedelta(days=1, hours=1)).isoformat()
        path.write_text(json.dumps(persisted, ensure_ascii=False) + "\n", encoding="utf-8")
        gate = ModelAcceptanceGate(snapshot_path=path)
        args = {"model_id": "gate-hash-model", "model_version": "1", "league": "MLB",
                "market": "不讓分", "source_scope": "taiwan_forward", "artifact_hash": "a" * 64,
                "protocol_id": "test-protocol", "protocol_hash_value": "b" * 64,
                "as_of": (now + timedelta(days=2)).isoformat()}
        intact = gate.status(**args)
        assert intact.get("matched_rows") == 1, intact

        persisted = json.loads(path.read_text(encoding="utf-8"))
        persisted["model_candidate_predictions"][0]["raw_probability"] = 0.71
        path.write_text(json.dumps(persisted, ensure_ascii=False) + "\n", encoding="utf-8")
        tampered = gate.status(**args)
        assert tampered.get("matched_rows", 0) == 0

        persisted["model_candidate_predictions"][0]["raw_probability"] = 0.7
        persisted["market_fair_method"] = "BREAKEVEN_BASELINE_NOT_DEVIGGED"
        persisted["market_evidence"]["market_fair_method"] = "BREAKEVEN_BASELINE_NOT_DEVIGGED"
        persisted["signal_evidence"]["market_fair_method"] = "BREAKEVEN_BASELINE_NOT_DEVIGGED"
        persisted["prediction_payload_hash"] = compute_prediction_payload_hash(persisted)
        path.write_text(json.dumps(persisted, ensure_ascii=False) + "\n", encoding="utf-8")
        incomplete_market = gate.status(**args)
        assert incomplete_market["incomplete_or_invalid_market_benchmark_excluded"] == 1
        assert incomplete_market.get("matched_rows", 0) == 0
