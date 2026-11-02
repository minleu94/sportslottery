#!/usr/bin/env python3
"""Tests for Market Intelligence & Continuous Forward Pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.forward_evaluation_engine import ForwardEvaluationEngine
from core.market_aligner import MarketAligner
from core.market_fair_odds import MarketFairOddsEngine
from core.market_forward_pipeline import MarketForwardPipeline
from core.snapshot_logger import AuditFailureError, PredictionSnapshotLogger
from integrations.common.models import TaiwanLeg
from integrations.odds.the_odds_api import TheOddsApiClient


def test_market_forward_pipeline_snapshot_and_evaluation(tmp_path: Path):
    snap_path = tmp_path / "prediction_snapshots.jsonl"
    summary_path = tmp_path / "forward_evaluation_summary.json"
    cache_path = tmp_path / "cache.json"

    snap_logger = PredictionSnapshotLogger(log_path=snap_path)
    eval_engine = ForwardEvaluationEngine()
    odds_client = TheOddsApiClient(cache_path=cache_path)

    now = datetime.now(timezone.utc)
    mock_legs = [
        TaiwanLeg(
            sport="baseball",
            league="MLB",
            event_id="test_leg_1",
            home_team="Los Angeles Dodgers",
            away_team="San Diego Padres",
            market="moneyline",
            selection="home",
            taiwan_odds=1.85,
            odds_status="LIVE",
            odds_scraped_at=now.isoformat(),
            start_time_utc=(now + timedelta(hours=3)).isoformat(),
        ),
        TaiwanLeg(
            sport="baseball",
            league="MLB",
            event_id="test_leg_2",
            home_team="Boston Red Sox",
            away_team="New York Yankees",
            market="moneyline",
            selection="away",
            taiwan_odds=1.95,
            odds_status="LIVE",
            odds_scraped_at=now.isoformat(),
            start_time_utc=(now + timedelta(hours=4)).isoformat(),
        ),
    ]

    mock_odds_adapter = MagicMock()
    mock_odds_adapter.get_taiwan_legs.return_value = mock_legs

    pipeline = MarketForwardPipeline(
        odds_adapter=mock_odds_adapter,
        odds_client=odds_client,
        snapshot_logger=snap_logger,
        evaluation_engine=eval_engine,
        summary_path=summary_path,
    )

    # 1. Run full cycle with synthetic fallback (no API key configured)
    res = pipeline.run_full_cycle(leagues=["MLB"])
    assert res["cycle_status"] == "SUCCESS"
    assert res["snapshot_cycle"]["snapshots_logged"] > 0
    assert summary_path.exists()

    # 2. Check snapshot ledger
    all_snaps = snap_logger.get_all_snapshots()
    assert len(all_snaps) > 0
    first = all_snaps[0]
    assert first["prediction_payload_hash"] is not None
    assert first["is_settled"] is False
    assert first["forward_validation_eligible"] is True

    # 3. Test Research status summary
    summary = pipeline.get_research_status_summary()
    assert summary["snapshots"]["total_count"] == len(all_snaps)
    assert summary["forward_evaluation"]["sample_size"] == 0  # None settled yet
    assert summary["forward_evaluation"]["status"] == "SHADOW_MODE_ACCUMULATING"
    assert "MAINTAIN_SHADOW_LOGGING" in summary["forward_evaluation"]["shadow_mode_recommendation"]


def test_pre_game_cutoff_and_payload_immutability(tmp_path: Path):
    snap_path = tmp_path / "prediction_snapshots.jsonl"
    snap_logger = PredictionSnapshotLogger(log_path=snap_path)

    now = datetime.now(timezone.utc)
    future_match = (now + timedelta(hours=2)).isoformat()
    past_match = (now - timedelta(hours=2)).isoformat()

    # Valid pre-match leg
    leg_valid = TaiwanLeg(
        sport="baseball",
        league="MLB",
        event_id="test_ev_valid_1",
        home_team="Los Angeles Dodgers",
        away_team="San Diego Padres",
        market="moneyline",
        selection="home",
        taiwan_odds=1.85,
        odds_status="LIVE",
        odds_scraped_at=now.isoformat(),
        start_time_utc=future_match,
    )

    # Past match leg (leak attempt)
    leg_leak = TaiwanLeg(
        sport="baseball",
        league="MLB",
        event_id="test_ev_leak_2",
        home_team="Boston Red Sox",
        away_team="New York Yankees",
        market="moneyline",
        selection="home",
        taiwan_odds=1.90,
        odds_status="LIVE",
        odds_scraped_at=now.isoformat(),
        start_time_utc=past_match,
    )

    from core.signal_hub import SignalHub
    hub = SignalHub()
    enriched_valid = hub.evaluate_taiwan_leg(leg_valid)
    enriched_leak = hub.evaluate_taiwan_leg(leg_leak)

    s1 = snap_logger.log_snapshot(enriched_valid)
    assert s1["forward_validation_eligible"] is True
    assert s1["exclusion_reason"] is None

    s2 = snap_logger.log_snapshot(enriched_leak)
    assert s2["forward_validation_eligible"] is False
    assert s2["exclusion_reason"] in {"POST_START_DATA", "PRE_GAME_CUTOFF_VIOLATION"}

    # Verify settlement verifies SHA-256 payload hash
    settled = snap_logger.settle_prediction(
        snapshot_id=s1["snapshot_id"],
        actual_outcome=True,
        settlement_status="WON",
        final_score="5-3",
        result_source="VERIFIED_STATS",
        closing_odds=1.75,
    )
    assert settled is not None
    assert settled["is_settled"] is True
    assert settled["settlement_status"] == "WON"
    assert settled["odds_clv_ratio"] > 0  # Beat closing line (1.85 > 1.75)

    # Test AuditFailureError if original payload is tampered with
    # Tamper with the raw log file line
    lines = snap_path.read_text(encoding="utf-8").splitlines()
    tampered_lines = []
    import json
    for line in lines:
        d = json.loads(line)
        if d.get("snapshot_id") == s1["snapshot_id"]:
            d["taiwan_odds"] = 99.9  # Tamper with pre-game odds
            tampered_lines.append(json.dumps(d))
        else:
            tampered_lines.append(line)
    snap_path.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")

    with pytest.raises(AuditFailureError):
        snap_logger.settle_prediction(
            snapshot_id=s1["snapshot_id"],
            actual_outcome=True,
            settlement_status="WON",
        )


def test_forward_evaluation_gate_sample_threshold(tmp_path: Path):
    snap_path = tmp_path / "prediction_snapshots.jsonl"
    snap_logger = PredictionSnapshotLogger(log_path=snap_path)
    eval_engine = ForwardEvaluationEngine()

    now = datetime.now(timezone.utc)

    # Log and settle 10 predictions (N=10 < 30)
    for i in range(10):
        start_time = (now + timedelta(hours=1, minutes=i)).isoformat()
        leg = TaiwanLeg(
            sport="baseball",
            league="MLB",
            event_id=f"test_n10_{i}",
            home_team="Team A",
            away_team="Team B",
            market="moneyline",
            selection="home",
            taiwan_odds=1.95,
            odds_status="LIVE",
            odds_scraped_at=now.isoformat(),
            start_time_utc=start_time,
            signal_evidence={
                "market_source": "THE_ODDS_API",
                "sharp_fair_prob": 0.52,
                "model_probability": 0.55,
                "probability_status": "MODEL_ESTIMATE",
            },
        )
        snap = snap_logger.log_snapshot(leg)
        snap_logger.settle_prediction(
            snapshot_id=snap["snapshot_id"],
            actual_outcome=(i % 2 == 0),
            settlement_status="WON" if i % 2 == 0 else "LOST",
            final_score="4-2",
        )

    snaps_10 = snap_logger.get_all_snapshots()
    report_10 = eval_engine.evaluate_cohort(snaps_10)
    assert report_10.sample_size == 10
    assert report_10.status == "SHADOW_MODE_ACCUMULATING"
    assert report_10.acceptance_gate_qualified is False
    assert "MAINTAIN_SHADOW_LOGGING_UNTIL_N_GTE_30" in report_10.shadow_mode_recommendation

    # Add 25 more predictions (Total N=35 >= 30)
    for i in range(10, 35):
        start_time = (now + timedelta(hours=1, minutes=i)).isoformat()
        leg = TaiwanLeg(
            sport="baseball",
            league="MLB",
            event_id=f"test_n35_{i}",
            home_team="Team A",
            away_team="Team B",
            market="moneyline",
            selection="home",
            taiwan_odds=1.95,
            odds_status="LIVE",
            odds_scraped_at=now.isoformat(),
            start_time_utc=start_time,
            signal_evidence={
                "market_source": "THE_ODDS_API",
                "sharp_fair_prob": 0.52,
                "model_probability": 0.55,
                "probability_status": "MODEL_ESTIMATE",
            },
        )
        snap = snap_logger.log_snapshot(leg)
        snap_logger.settle_prediction(
            snapshot_id=snap["snapshot_id"],
            actual_outcome=(i % 2 == 0),
            settlement_status="WON" if i % 2 == 0 else "LOST",
            final_score="4-2",
        )

    snaps_35 = snap_logger.get_all_snapshots()
    report_35 = eval_engine.evaluate_cohort(snaps_35)
    assert report_35.sample_size == 35
    assert report_35.status == "VALIDATED"
    assert report_35.taiwan_market_baseline.brier_score is not None
    assert report_35.champion_source in {"ACTIVE_MODEL", "INTERNATIONAL_SHARP_BENCHMARK"}
