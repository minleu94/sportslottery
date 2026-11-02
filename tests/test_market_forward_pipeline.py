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
from core.market_forward_pipeline import MarketForwardPipeline, _alignment_summary_from_scheduler_status
from core.snapshot_logger import AuditFailureError, PredictionSnapshotLogger
from integrations.common.models import PredictionSignal, TaiwanLeg
from integrations.odds.market_models import MarketAlignmentRecord, MarketAlignmentStatus, MarketOddsSnapshot
from integrations.odds.the_odds_api import TheOddsApiClient


def _qualified_forward_test_leg(event_id: str, now: datetime, start_time: datetime) -> TaiwanLeg:
    """Build an explicitly auditable, pre-match research fixture."""
    group = "TEST_MODEL"
    probability = 0.55
    return TaiwanLeg(
        sport="baseball",
        league="MLB",
        event_id=event_id,
        home_team="Team A",
        away_team="Team B",
        market="不讓分",
        selection="home",
        taiwan_odds=1.95,
        odds_status="LIVE",
        odds_scraped_at=now.isoformat(),
        start_time_utc=start_time.isoformat(),
        signal_evidence={
            "market_source": "the_odds_api:draftkings",
            "market_fair_probability": 0.52,
            "market_fair_method": "COMPLETE_MARKET_PROPORTIONAL",
            "market_observed_at": now.isoformat(),
            "market_complete": True,
            "is_market_synthetic": False,
            "model_probability_raw": probability,
            "model_probability_calibrated": probability,
            "consensus_probability": probability,
            "probability_status": "UNVALIDATED_MODEL_ESTIMATE",
            "model_fusion_groups": [group],
        },
        signals=[PredictionSignal(
            source_id="test_model",
            source_name="Test Model",
            source_type="MODEL",
            source_category="LOCAL_FALLBACK_MODEL",
            independence_group=group,
            event_id=event_id,
            market="不讓分",
            selection="home",
            probability=probability,
            data_as_of=now.isoformat(),
            freshness_status="FRESH",
            metadata={"initialized": True},
        )],
    )


def _market_quote(selection: str, observed_at: str | None) -> MarketOddsSnapshot:
    now = datetime.now(timezone.utc)
    return MarketOddsSnapshot(
        source_id="the_odds_api:pinnacle",
        source_type="BOOKMAKER",
        event_id="intl-event-1",
        league="MLB",
        home_team="Los Angeles Dodgers",
        away_team="San Diego Padres",
        start_time_utc=(now + timedelta(hours=2)).isoformat(),
        market_type="MONEYLINE",
        selection=selection,
        decimal_odds=1.9,
        observed_at_utc=observed_at,
        retrieved_at_utc=now.isoformat(),
        freshness_status="UNKNOWN" if observed_at is None else "LIVE",
    )


def test_fair_quote_requires_fresh_same_book_quotes_with_consistent_market_times():
    now = datetime.now(timezone.utc)
    primary = _market_quote("home", now.isoformat())
    counterpart = _market_quote("away", (now - timedelta(seconds=90)).isoformat())
    valid = MarketForwardPipeline._build_fair_odds_quote(primary, [primary, counterpart], False)
    assert valid is not None

    too_far_apart = _market_quote("away", (now - timedelta(seconds=180)).isoformat())
    assert MarketForwardPipeline._build_fair_odds_quote(primary, [primary, too_far_apart], False) is None

    unknown_time = _market_quote("away", None)
    assert MarketForwardPipeline._build_fair_odds_quote(primary, [primary, unknown_time], False) is None

    stale = _market_quote("away", (now - timedelta(minutes=20)).isoformat())
    assert MarketForwardPipeline._build_fair_odds_quote(primary, [primary, stale], False) is None


def test_market_forward_pipeline_snapshot_and_evaluation(tmp_path: Path):
    snap_path = tmp_path / "prediction_snapshots.jsonl"
    summary_path = tmp_path / "forward_evaluation_summary.json"
    cache_path = tmp_path / "cache.json"

    snap_logger = PredictionSnapshotLogger(log_path=snap_path)
    eval_engine = ForwardEvaluationEngine()
    odds_fixture_client = TheOddsApiClient(cache_path=cache_path)
    odds_client = MagicMock()
    odds_client.get_source_status.return_value = {
        "requests_used_this_month": 0,
        "requests_remaining_est": 500,
        "operating_mode": "SYNTHETIC_FIXTURE",
    }
    odds_client.scheduled_markets = "h2h"
    odds_client.regions = "us,eu"
    odds_client.fetch_market_odds.return_value = odds_fixture_client._generate_synthetic_fixtures("MLB")

    now = datetime.now(timezone.utc)
    mock_legs = [
        TaiwanLeg(
            sport="baseball",
            league="MLB",
            event_id="test_leg_1",
            home_team="Los Angeles Dodgers",
            away_team="San Diego Padres",
            market="不讓分",
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
            market="不讓分",
            selection="away",
            taiwan_odds=1.95,
            odds_status="LIVE",
            odds_scraped_at=now.isoformat(),
            start_time_utc=(now + timedelta(hours=4)).isoformat(),
        ),
    ]

    mock_odds_adapter = MagicMock()
    mock_odds_adapter.get_taiwan_legs.return_value = mock_legs
    # Keep this synthetic pipeline test hermetic: the production SignalHub's
    # model acceptance registry reads the user's research ledger at startup.
    signal_hub = MagicMock()
    signal_hub.evaluate_taiwan_leg.side_effect = lambda leg: leg

    pipeline = MarketForwardPipeline(
        odds_adapter=mock_odds_adapter,
        odds_client=odds_client,
        signal_hub=signal_hub,
        snapshot_logger=snap_logger,
        settlement_engine=MagicMock(),
        evaluation_engine=eval_engine,
        summary_path=summary_path,
    )

    # 1. Run full cycle with synthetic fallback (no API key configured)
    res = pipeline.run_full_cycle(leagues=["MLB"])
    assert res["operation_status"] == "SUCCESS"
    assert res["cycle_status"] == "NO_QUALIFIED_REAL_MARKET_DATA"
    assert res["snapshot_cycle"]["snapshots_logged"] > 0
    assert res["snapshot_cycle"]["synthetic_market_quote_count"] > 0
    assert res["snapshot_cycle"]["qualified_pending_candidate_count"] == 0
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


def test_snapshot_cycle_returns_alignment_rejection_diagnostics(tmp_path: Path):
    now = datetime.now(timezone.utc)
    leg = TaiwanLeg(
        event_id="reject_me",
        sport="basketball",
        league="NBA",
        home_team="Home",
        away_team="Away",
        market="不讓分",
        selection="Home",
        side="主",
        taiwan_odds=1.9,
        odds_status="LIVE",
        odds_scraped_at=now.isoformat(),
        start_time_utc=(now + timedelta(hours=1)).isoformat(),
    )
    rejection = MarketAlignmentRecord(
        status=MarketAlignmentStatus.UNMATCHED,
        taiwan_event_id="reject_me",
        taiwan_league="NBA",
        taiwan_market="不讓分",
        taiwan_selection="Home",
        taiwan_side="主",
        taiwan_line=None,
        international_event_id=None,
        international_source_id=None,
        international_market_type=None,
        international_selection=None,
        international_line=None,
        aligned_at_utc=now.isoformat(),
        reason="Team alias was not found.",
        rejection_code="ERR_TEAM_NOT_FOUND",
    )
    odds_adapter = MagicMock()
    odds_adapter.get_taiwan_legs.return_value = [leg]
    odds_client = MagicMock()
    odds_client.get_source_status.return_value = {"requests_used_this_month": 0}
    odds_client.scheduled_markets = "h2h"
    odds_client.regions = "us"
    odds_client.fetch_market_odds.return_value = []
    signal_hub = MagicMock()
    signal_hub.evaluate_taiwan_leg.side_effect = lambda item: item
    aligner = MagicMock()
    aligner.align_leg_with_candidates.return_value = (None, rejection)
    snapshot_logger = MagicMock()
    snapshot_logger.log_snapshot.return_value = {"forward_validation_eligible": False}

    pipeline = MarketForwardPipeline(
        odds_adapter=odds_adapter,
        odds_client=odds_client,
        signal_hub=signal_hub,
        aligner=aligner,
        snapshot_logger=snapshot_logger,
        settlement_engine=MagicMock(),
        summary_path=tmp_path / "summary.json",
    )
    result = pipeline.run_market_snapshot_cycle(leagues=["NBA"])

    assert result["total_unmatched"] == 1
    assert result["alignment_rejection_counts"] == {"ERR_TEAM_NOT_FOUND": 1}
    assert result["alignment_rejection_examples"]["ERR_TEAM_NOT_FOUND"][0]["taiwan_event_id"] == "reject_me"


def test_alignment_summary_does_not_conflate_live_source_with_zero_matches():
    summary = _alignment_summary_from_scheduler_status({
        "quota_operating_mode": "LIVE_VERIFIED",
        "last_cycle_summary": {
            "real_matched_count": 0,
            "taiwan_snapshots_logged": 580,
            "real_market_quote_count": 2622,
            "candidate_rejection_counts": {"TAIWAN_ODDS_NOT_FRESH": 3},
            "alignment_rejection_counts": {"ERR_TEAM_NOT_FOUND": 205},
            "timestamp_utc": "2026-11-02T08:16:00Z",
        },
    })

    assert summary["status"] == "NO_REAL_QUOTES_MATCHED"
    assert summary["real_matched_count"] == 0
    assert summary["real_market_quote_count"] == 2622
    assert summary["candidate_rejection_counts"] == {"TAIWAN_ODDS_NOT_FRESH": 3}
    assert summary["rejection_counts"] == {"ERR_TEAM_NOT_FOUND": 205}


def _candidate_gate_pipeline(tmp_path: Path, legs_by_league: dict[str, list[TaiwanLeg]]):
    adapter = MagicMock()
    adapter.get_taiwan_legs.side_effect = lambda leagues, **kwargs: legs_by_league.get(leagues[0], [])
    odds_client = MagicMock()
    odds_client.get_source_status.return_value = {"requests_used_this_month": 0}
    odds_client.scheduled_markets = "h2h"
    odds_client.regions = "us,eu"
    odds_client.fetch_market_odds.return_value = []
    pipeline = MarketForwardPipeline(
        odds_adapter=adapter,
        odds_client=odds_client,
        signal_hub=MagicMock(),
        aligner=MarketAligner(),
        snapshot_logger=MagicMock(),
        settlement_engine=MagicMock(),
        summary_path=tmp_path / "candidate_gate_summary.json",
    )
    pipeline.signal_hub.evaluate_taiwan_leg.side_effect = lambda leg: leg
    pipeline.snapshot_logger.log_snapshot.return_value = {"forward_validation_eligible": False}
    return pipeline, odds_client


def _valid_candidate(league: str = "NBA", sport: str = "basketball", event_id: str = "tw-1") -> TaiwanLeg:
    now = datetime.now(timezone.utc)
    return TaiwanLeg(
        event_id=event_id,
        sport=sport,
        league=league,
        home_team="Boston Celtics",
        away_team="New York Knicks",
        market="不讓分",
        selection="Boston Celtics 不讓分勝",
        side="主",
        taiwan_odds=1.9,
        odds_status="LIVE",
        start_time_utc=(now + timedelta(hours=2)).isoformat(),
    )


def test_empty_taiwan_candidates_skip_odds_api_query(tmp_path: Path):
    pipeline, odds_client = _candidate_gate_pipeline(tmp_path, {"NBA": []})

    result = pipeline.run_market_snapshot_cycle(leagues=["NBA"], automated=True)

    odds_client.fetch_market_odds.assert_not_called()
    assert result["league_query_diagnostics"]["NBA"] == {
        "raw_leg_count": 0,
        "valid_candidate_count": 0,
        "valid_event_count": 0,
        "rejected_leg_count": 0,
        "skip_reason_counts": {"NO_TAIWAN_CANDIDATES": 1},
        "query_called": False,
        "client_call_count": 0,
        "network_request_count": 0,
        "cache_hit_count": 0,
        "estimated_credits": 0,
        "actual_credits": 0,
    }


@pytest.mark.parametrize(
    ("status", "synthetic", "reason"),
    [
        ("STALE_CACHE", False, "TAIWAN_ODDS_NOT_FRESH"),
        ("UNKNOWN", False, "TAIWAN_ODDS_NOT_FRESH"),
        ("LIVE", True, "SYNTHETIC_TAIWAN_ODDS"),
    ],
)
def test_stale_or_synthetic_taiwan_prices_do_not_trigger_odds_queries(tmp_path: Path, status, synthetic, reason):
    leg = _valid_candidate()
    leg.odds_status = status
    leg.is_synthetic = synthetic
    pipeline, odds_client = _candidate_gate_pipeline(tmp_path, {"NBA": [leg]})

    result = pipeline.run_market_snapshot_cycle(leagues=["NBA"], automated=True)

    odds_client.fetch_market_odds.assert_not_called()
    assert result["league_query_diagnostics"]["NBA"]["skip_reason_counts"] == {reason: 1}
    assert result["estimated_credits"] == 0


def test_valid_taiwan_candidate_still_queries_odds_api(tmp_path: Path):
    pipeline, odds_client = _candidate_gate_pipeline(tmp_path, {"NBA": [_valid_candidate()]})

    result = pipeline.run_market_snapshot_cycle(leagues=["NBA"], automated=True)

    odds_client.fetch_market_odds.assert_called_once_with(
        "NBA", markets="h2h", force_refresh=False, automated=True
    )
    diag = result["league_query_diagnostics"]["NBA"]
    assert diag["valid_candidate_count"] == 1
    assert diag["query_called"] is True
    assert diag["client_call_count"] == 1
    assert diag["network_request_count"] == 0
    assert diag["estimated_credits"] == 2
    assert diag["actual_credits"] == 0


def test_mixed_leagues_query_only_leagues_with_valid_candidates(tmp_path: Path):
    invalid_mlb = _valid_candidate("MLB", "basketball", "wrong-sport")
    pipeline, odds_client = _candidate_gate_pipeline(
        tmp_path,
        {
            "NBA": [_valid_candidate()],
            "MLB": [invalid_mlb],
            "NFL": [_valid_candidate("NFL", "football", "nfl-1")],
        },
    )

    result = pipeline.run_market_snapshot_cycle(leagues=["NBA", "MLB", "NFL"], automated=True)

    assert [call.args[0] for call in odds_client.fetch_market_odds.call_args_list] == ["NBA", "NFL"]
    assert result["league_query_diagnostics"]["MLB"]["skip_reason_counts"] == {
        "SPORT_LEAGUE_MISMATCH": 1
    }
    assert result["league_query_diagnostics"]["MLB"]["estimated_credits"] == 0
    assert result["league_query_diagnostics"]["MLB"]["actual_credits"] == 0


def test_mixed_valid_and_stale_candidates_only_analyze_valid_leg(tmp_path: Path):
    valid = _valid_candidate(event_id="valid-tw")
    stale = _valid_candidate(event_id="stale-tw")
    stale.odds_status = "STALE_CACHE"
    pipeline, odds_client = _candidate_gate_pipeline(tmp_path, {"NBA": [valid, stale]})
    pipeline.aligner = MagicMock(wraps=MarketAligner())

    result = pipeline.run_market_snapshot_cycle(leagues=["NBA"], automated=True)

    odds_client.fetch_market_odds.assert_called_once_with(
        "NBA", markets="h2h", force_refresh=False, automated=True
    )
    assert [call.args[0].event_id for call in pipeline.aligner.align_leg_with_candidates.call_args_list] == ["valid-tw"]
    assert [call.args[0].event_id for call in pipeline.signal_hub.evaluate_taiwan_leg.call_args_list] == ["valid-tw"]
    assert [call.args[0].event_id for call in pipeline.snapshot_logger.log_snapshot.call_args_list] == ["valid-tw"]
    assert result["valid_candidate_count"] == 1
    assert result["total_legs_processed"] == 2
    assert result["total_unmatched"] == 2
    assert result["candidate_rejection_counts"] == {"TAIWAN_ODDS_NOT_FRESH": 1}


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

    # Snapshot eligibility is the subject here; avoid constructing the real
    # SignalHub, whose adapters may read or fetch unrelated user data.
    enriched_valid = leg_valid
    enriched_leak = leg_leak

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
        leg = _qualified_forward_test_leg(
            f"test_n10_{i}", now, datetime.fromisoformat(start_time)
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
        leg = _qualified_forward_test_leg(
            f"test_n35_{i}", now, datetime.fromisoformat(start_time)
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
    assert report_35.status == "MODEL_EVIDENCE_UNVERIFIED"
    assert report_35.acceptance_gate_qualified is False
    assert report_35.evaluation_protocol_status == "MISSING_OR_MIXED_MODEL_LINEAGE"
    assert report_35.taiwan_market_baseline.brier_score is not None
    assert report_35.champion_source == "NO_QUALIFIED_BENCHMARK"
