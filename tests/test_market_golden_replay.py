"""Offline golden replay for the market candidate-to-snapshot boundary."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.market_aligner import MarketAligner
from core.market_forward_pipeline import MarketForwardPipeline
from core.signal_hub import SignalHub
from core.snapshot_logger import PredictionSnapshotLogger, compute_prediction_payload_hash
from core.contracts.common import TaiwanLeg
from integrations.odds.market_models import MarketOddsSnapshot


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "market" / "mlb_moneyline_replay.json"


def _fixed_datetime(monkeypatch, module_name: str, frozen: datetime) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)

    module = __import__(module_name, fromlist=["datetime"])
    monkeypatch.setattr(module, "datetime", FrozenDateTime)


def test_offline_market_golden_replay_preserves_evidence_through_snapshot(tmp_path, monkeypatch):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    as_of = datetime.fromisoformat(fixture["as_of_utc"])
    kickoff = datetime.fromisoformat(fixture["kickoff_utc"])
    for module_name in (
        "core.market_forward_pipeline",
        "core.market_aligner",
        "core.market_fair_odds",
        "core.snapshot_logger",
        "core.contracts.common",
    ):
        _fixed_datetime(monkeypatch, module_name, as_of)

    raw_leg = fixture["taiwan_leg"]
    leg = TaiwanLeg(
        **raw_leg,
        start_time_utc=kickoff.isoformat(),
        start_time=kickoff.isoformat(),
        odds_scraped_at=as_of.isoformat(),
    )
    quotes = [
        MarketOddsSnapshot(
            **row,
            start_time_utc=kickoff.isoformat(),
            observed_at_utc=as_of.isoformat(),
            retrieved_at_utc=as_of.isoformat(),
            freshness_status="LIVE",
        )
        for row in fixture["international_quotes"]
    ]
    adapter = MagicMock()
    adapter.get_taiwan_legs.return_value = [leg]
    odds_client = MagicMock(
        markets="h2h",
        scheduled_markets="auto",
        regions="us",
        sharp_qualified_books=["pinnacle"],
    )
    odds_client.get_source_status.return_value = {
        "requests_used_this_month": 0,
        "request_metrics": {"api_requests": 0, "cache_hits": 0, "coalesced_requests": 0},
    }
    odds_client.fetch_market_odds.return_value = quotes
    signal_hub = SignalHub(
        expert_adapter=MagicMock(get_expert_signal=lambda item: None),
        crowd_adapter=MagicMock(get_crowd_signal=lambda item: None),
        model_registry=MagicMock(evaluate_leg_across_models=lambda item: []),
        sharp_adapter=MagicMock(),
        line_movement_tracker=MagicMock(analyze_leg_movement=lambda item, current_odds: None),
        splits_client=MagicMock(get_betting_splits=lambda league: []),
        config_path=tmp_path / "missing-evidence-weights.yaml",
    )
    snapshots = PredictionSnapshotLogger(log_path=tmp_path / "snapshots.jsonl")
    pipeline = MarketForwardPipeline(
        odds_adapter=adapter,
        odds_client=odds_client,
        signal_hub=signal_hub,
        aligner=MarketAligner(),
        snapshot_logger=snapshots,
        settlement_engine=MagicMock(),
        evaluation_engine=MagicMock(),
        summary_path=tmp_path / "summary.json",
    )

    result = pipeline.run_market_snapshot_cycle(leagues=[fixture["league"]])
    records = snapshots.get_all_snapshots()
    assert len(records) == 1
    snapshot = records[0]
    expected = fixture["expected"]

    assert result["valid_candidate_count"] == expected["valid_candidate_count"]
    assert result["unique_candidate_event_count"] == expected["unique_candidate_event_count"]
    assert result["real_matched_count"] == expected["real_matched_count"]
    assert result["complete_market_benchmark_count"] == expected["complete_market_benchmark_count"]
    assert result["sharp_qualified_count"] == expected["sharp_qualified_count"]
    assert snapshot["forward_validation_eligible"] is expected["snapshot_forward_validation_eligible"]
    assert snapshot["settlement_status"] == expected["snapshot_settlement_status"]
    assert snapshot["market_implied_prob"] == pytest.approx(expected["taiwan_implied_probability"])
    assert snapshot["market_fair_probability"] == pytest.approx(expected["fair_probability"])
    assert snapshot["expected_value"] == pytest.approx(expected["expected_value"])
    assert snapshot["market_evidence"]["market_source_qualification"] == expected["market_source_qualification"]
    assert snapshot["market_evidence"]["market_source"] == "the_odds_api:consensus"
    assert snapshot["event_id"] == raw_leg["event_id"]
    assert snapshot["event_start"] == kickoff.isoformat()
    assert snapshot["prediction_payload_hash"] == compute_prediction_payload_hash(snapshot)

    # The international market is consumed as a baseline once; it does not
    # appear as a second independent signal vote.
    assert [signal["source_category"] for signal in snapshot["signals"]] == ["BETTING_MARKET"]
    assert snapshot["signal_evidence"]["market_benchmark"]["canonical_event_id"].startswith(
        "baseball:mlb:odds-api-golden-001:"
    )


def test_injected_market_providers_do_not_construct_default_clients(tmp_path, monkeypatch):
    import core.market_forward_pipeline as market_pipeline

    def unexpected_default_construction(*args, **kwargs):
        raise AssertionError("injected providers must bypass the default provider factory")

    monkeypatch.setattr(market_pipeline, "build_default_market_providers", unexpected_default_construction)
    adapter, client = object(), object()
    pipeline = MarketForwardPipeline(
        odds_adapter=adapter,
        odds_client=client,
        settlement_engine=MagicMock(),
        evaluation_engine=MagicMock(),
        summary_path=tmp_path / "summary.json",
    )

    assert pipeline.odds_adapter is adapter
    assert pipeline.odds_client is client
