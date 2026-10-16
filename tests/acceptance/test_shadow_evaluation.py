#!/usr/bin/env python3
"""Acceptance Test Suite for Shadow Evaluation & Forward Performance Phase.

Validates:
1. Strategy Versioning (v2.0-research, metadata, immutability)
2. Daily Prediction Snapshots (full 14+ field schema, append-only)
3. Multi-tier Parlay Snapshots (10-25x, 25-75x, 75-200x, 200-500x; 0-candidate preservation)
4. Shadow Portfolio Isolation (NT$10 virtual stake, 100% decoupling from real Weekly NT$200 Wallet)
5. Settlement Engine (Score resolution, Brier/LogLoss, CLV, immutable prediction preservation)
6. Multi-Bucket Performance Metrics (Agreement buckets, Delta buckets, Expert/Crowd buckets, Calibration)
7. Small Sample Safeguard (N < 30 labeled INSUFFICIENT_SAMPLE)
8. Weekly Report Generation (reports/YYYY-Www.md)
"""

from __future__ import annotations

import copy
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from core.performance_metrics import PerformanceMetricsEngine
from core.experiment_identity import get_current_experiment_identity
from core.settlement_engine import SettlementEngine
from core.shadow_parlay_logger import MULTIPLIER_TIERS, ShadowParlayLogger
from core.shadow_portfolio import ShadowPortfolioManager
from core.snapshot_logger import PredictionSnapshotLogger, compute_prediction_payload_hash
from core.strategy_version import GOVERNANCE_RULES, STRATEGY_VERSION, get_strategy_metadata
from core.wallet import WeeklyWalletManager
from integrations.common.models import PredictionSignal, TaiwanLeg
from scripts.generate_weekly_report import generate_weekly_report


def test_strategy_version_immutability():
    """Verify the research strategy has a new immutable version and full provenance."""
    assert STRATEGY_VERSION == "v2.0-research"
    meta = get_strategy_metadata()
    assert meta["strategy_version"] == STRATEGY_VERSION
    assert "code_version" in meta
    assert "penaltyblog_dixon_coles" in meta["model_versions"]
    assert "live_mlb_elo" in meta["model_versions"]
    assert "fivethirtyeight_mlb_elo" not in meta["model_versions"]
    assert meta["governance_rules"]["model_probabilities_calibrated"] is False
    assert GOVERNANCE_RULES["no_mid_test_weight_changes"] is True
    assert GOVERNANCE_RULES["insufficient_sample_threshold"] == 30
    assert GOVERNANCE_RULES["virtual_shadow_stake_ntd"] == 10.0


def test_daily_prediction_snapshot_schema_and_append_only(tmp_path):
    """Verify all 14+ required snapshot fields and strictly append-only persistence."""
    log_file = tmp_path / "test_snaps.jsonl"
    logger = PredictionSnapshotLogger(log_path=log_file)

    leg = TaiwanLeg(
        event_id="101",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="小熊 客勝",
        taiwan_odds=1.85,
        start_time="test future event",
        start_time_utc=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        odds_scraped_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        odds_age_minutes=1.0,
        away_team="小熊",
        home_team="紅人",
        side="客",
    )
    leg.odds_status = "LIVE"
    leg.odds_age_minutes = 0.5
    leg.signal_evidence = {
        "crowd_ratio": 0.68,
        "crowd_votes": 120,
        "crowd_age_minutes": 2.0,
        "verified_experts": [{"userid": "TaiwanPro99", "pick_timestamp": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()}],
        "expert_consensus": 1,
        "publication_time_precision": "DATETIME",
        "expert_publication_timestamp": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
        "probability_status": "UNVALIDATED_MODEL_ESTIMATE",
        "consensus_probability": 0.58,
        "model_fusion_groups": ["ELO"],
        "model_market_delta_pp": 3.9,
        "agreement_badge": "🟢 HIGH",
        "quality_score": 65.0,
        "independent_support_count": 2,
    }
    leg.signals = [
        PredictionSignal(
            source_id="dixon",
            source_name="FiveThirtyEight MLB Elo",
            source_type="MODEL",
            source_category="LOCAL_REIMPLEMENTATION",
            independence_group="ELO",
            event_id="101",
            market="不讓分",
            selection="小熊 客勝",
            probability=0.58,
            timestamp=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            data_as_of=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            freshness_status="FRESH",
            metadata={"provenance": "fixed unit-test fixture"},
        )
    ]

    snap1 = logger.log_snapshot(leg)

    # Check required fields
    required_fields = [
        "snapshot_id", "snapshot_timestamp", "event_id", "sport", "league",
        "market", "selection", "taiwan_odds", "odds_timestamp",
        "crowd_ratio", "crowd_votes", "verified_experts", "expert_consensus",
        "model_predictions", "model_probability", "model_market_delta",
        "evidence_quality", "freshness", "strategy_version"
    ]
    for rf in required_fields:
        assert rf in snap1, f"Missing required field: {rf}"

    assert snap1["strategy_version"] == STRATEGY_VERSION
    assert snap1["crowd_ratio"] == 0.68
    assert snap1["crowd_votes"] == 120
    assert snap1["verified_experts"][0]["userid"] == "TaiwanPro99"
    assert "FiveThirtyEight MLB Elo" in snap1["model_predictions"]
    assert snap1["is_settled"] is False

    # Append second record (distinct leg to test append-only persistence)
    leg2 = copy.deepcopy(leg)
    leg2.event_id = "102"
    snap2 = logger.log_snapshot(leg2)
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2, "Snapshot file must be append-only"


def test_shadow_parlay_logging_including_zero_candidates(tmp_path):
    """Verify parlay candidate logging preserves all multiplier tiers even if count is 0."""
    p_log = tmp_path / "parlays.jsonl"
    logger = ShadowParlayLogger(log_path=p_log)

    tier_results = {
        "10-25x": {
            "high_consensus": [{"total_odds": 15.2, "legs": [{"event_id": "1", "selection": "客勝", "taiwan_odds": 1.8}]}],
            "aggressive": [],
            "moonshot": [],
        },
        "25-75x": {"high_consensus": [], "aggressive": [], "moonshot": []},
        "75-200x": {"high_consensus": [], "aggressive": [], "moonshot": []},
        "200-500x": {"high_consensus": [], "aggressive": [], "moonshot": []},
    }

    records = logger.log_daily_parlays(tier_results, date_str="2026-09-18")
    assert len(records) == 4  # All 4 tiers saved

    t_10_25 = next(r for r in records if r["multiplier_tier"] == "10-25x")
    assert t_10_25["total_candidate_count"] == 1

    t_200_500 = next(r for r in records if r["multiplier_tier"] == "200-500x")
    assert t_200_500["total_candidate_count"] == 0, "Zero candidate tiers must be preserved"


def test_shadow_portfolio_isolation_from_real_wallet(tmp_path):
    """Verify Shadow Portfolio uses NT$10 virtual stake and is 100% decoupled from real wallet."""
    shadow_db = tmp_path / "shadow.sqlite"
    shadow_mgr = ShadowPortfolioManager(db_path=shadow_db)

    real_db = tmp_path / "real_wallet.sqlite"
    real_wallet = WeeklyWalletManager(db_path=real_db)
    real_wallet.deposit_external(200.0)

    initial_real_balance = real_wallet.get_status()["weekly_wallet_balance"]
    assert initial_real_balance == 200.0


    # Place virtual shadow bet
    dummy_legs = [{"event_id": "10", "selection": "主勝", "taiwan_odds": 1.75}]
    t = shadow_mgr.place_shadow_ticket(
        legs=dummy_legs,
        total_odds=12.5,
        selection_category="TOP_HIGH",
        multiplier_tier="10-25x",
        notes="Virtual Test",
    )
    assert t["virtual_stake"] == 10.0
    assert t["potential_payout"] == 125.0

    # Verify real wallet balance is UNTOUCHED
    after_real_status = real_wallet.get_status()
    assert after_real_status["weekly_wallet_balance"] == 200.0
    assert after_real_status["weekly_staked"] == 0.0

    # Verify shadow summary
    sh_sum = shadow_mgr.get_portfolio_summary()
    assert sh_sum["total_tickets_logged"] == 1
    assert sh_sum["open_tickets"] == 1


def test_settlement_engine_immutable_settlement():
    """Verify that settlement updates results without altering original prediction fields."""
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
        _test_settlement_engine_immutable_settlement(Path(folder) / "snaps.jsonl")


def _test_settlement_engine_immutable_settlement(snap_file):
    snap_logger = PredictionSnapshotLogger(log_path=snap_file)

    leg = TaiwanLeg(
        event_id="202",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="洋基 客勝",
        taiwan_odds=2.00,
        start_time="test future event",
        start_time_utc=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        odds_scraped_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        odds_age_minutes=1.0,
        away_team="洋基",
        home_team="紅襪",
        side="客",
    )
    leg.odds_status = "LIVE"
    leg.signal_evidence = {"consensus_probability": 0.60, "probability_status": "UNVALIDATED_MODEL_ESTIMATE", "publication_time_precision": "NOT_APPLICABLE", "model_market_delta_pp": 10.0, "model_fusion_groups": ["TEST_MODEL"]}
    leg.signals = [PredictionSignal(source_id="test-model", source_name="Fixed test model", source_type="MODEL",
                                    source_category="OPEN_SOURCE_ENGINE", independence_group="TEST_MODEL",
                                    event_id="202", market="不讓分", selection="洋基 客勝", probability=0.60,
                                    timestamp=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                                    data_as_of=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                                    freshness_status="FRESH", metadata={"provenance": "fixed unit-test fixture"})]
    snap = snap_logger.log_snapshot(leg)
    sid = snap["snapshot_id"]

    settler = SettlementEngine(snapshot_logger=snap_logger)

    # Outcome evaluation: Away 5, Home 3 -> Away wins
    eval_win = settler.evaluate_leg_outcome(
        market="不讓分",
        selection="洋基 客勝",
        line=None,
        away_score=5,
        home_score=3,
        side="客",
    )
    assert eval_win is True

    # Settle snapshot
    settled = settler.settle_single_prediction_direct(
        snapshot_id=sid,
        actual_outcome=True,
        closing_odds=1.90,
        final_score="5:3",
    )

    assert settled["is_settled"] is True
    assert settled["actual_outcome"] is True
    assert settled["brier_score"] == round((0.60 - 1.0) ** 2, 4)  # 0.16
    assert settled["closing_odds"] == 1.90
    assert settled["clv_beat"] is True  # 2.00 > 1.90
    # Original prediction fields remain intact
    assert settled["taiwan_odds"] == 2.00
    assert settled["selection"] == "洋基 客勝"
    assert settled["strategy_version"] == STRATEGY_VERSION


def test_metrics_engine_buckets_and_insufficient_sample():
    """Verify Agreement buckets, Delta buckets, Expert/Crowd buckets, and N < 30 flag."""
    metrics = PerformanceMetricsEngine()

    dummy_snapshots = [
        {
            "is_settled": True,
            "actual_outcome": True,
            "evidence_quality": "HIGH",
            "taiwan_odds": 2.0,
            "model_market_delta_pp": 6.5,
            "crowd_ratio": 0.75,
            "verified_experts": ["ExpertA"],
            "model_probability": 0.65,
        },
        {
            "is_settled": True,
            "actual_outcome": False,
            "evidence_quality": "HIGH",
            "taiwan_odds": 1.8,
            "model_market_delta_pp": 4.0,
            "crowd_ratio": 0.62,
            "verified_experts": ["ExpertA", "ExpertB"],
            "model_probability": 0.55,
        },
        {
            "is_settled": True,
            "actual_outcome": True,
            "evidence_quality": "MED",
            "taiwan_odds": 1.9,
            "model_market_delta_pp": -2.0,
            "crowd_ratio": 0.55,
            "verified_experts": [],
            "model_probability": 0.50,
        },
    ]
    for index, snapshot in enumerate(dummy_snapshots):
        snapshot.update({
            "forward_validation_eligible": True,
            "settlement_status": "WON" if snapshot["actual_outcome"] else "LOST",
            "strategy_version": STRATEGY_VERSION,
            "probability_status": "UNVALIDATED_MODEL_ESTIMATE",
            "snapshot_id": f"metric-{index}",
            "snapshot_timestamp": "2026-10-10T12:00:00+00:00",
            "event_id": f"metric-event-{index}",
            "canonical_event_id": f"metric-event-{index}",
            "event_start": f"2026-10-{11 + index:02d}T12:00:00+00:00",
            "settled_at": f"2026-10-{12 + index:02d}T12:00:00+00:00",
            "result_source": "STATS_API",
            "sport": "soccer", "league": "eng.1", "away_team": "Chelsea", "home_team": "Arsenal",
            "market": "不讓分", "selection": f"selection-{index}", "side": f"side-{index}", "line": None,
        })
        identity = get_current_experiment_identity()
        snapshot["experiment_identity"] = identity
        snapshot["strategy_config_hashes"] = identity["config_hashes"]
        snapshot["strategy_metadata"] = {"experiment_identity": identity}
        snapshot["prediction_hash_schema"] = 3
        snapshot["settlement_rule_id"] = "test-rule-v1"
        snapshot["prediction_payload_hash"] = compute_prediction_payload_hash(snapshot)

    agree = metrics.evaluate_agreement_buckets(dummy_snapshots)
    assert agree["HIGH"]["sample_size"] == 2
    assert agree["HIGH"]["wins"] == 1
    assert agree["HIGH"]["hit_rate"] == 0.5
    assert agree["HIGH"]["is_insufficient_sample"] is True  # N=2 < 30

    deltas = metrics.evaluate_model_market_delta_buckets(dummy_snapshots)
    assert deltas["+5 ~ +10pp"]["sample_size"] == 1
    assert deltas["+5 ~ +10pp"]["wins"] == 1

    crowd = metrics.evaluate_crowd_buckets(dummy_snapshots)
    assert crowd["70-80%"]["sample_size"] == 1
    assert crowd["70-80%"]["wins"] == 1

    calib = metrics.evaluate_calibration_bins(dummy_snapshots)
    assert "65-70%" in calib
    assert calib["65-70%"]["sample_size"] == 1



def test_shadow_ticket_win_loss_settlement(tmp_path):
    """Verify shadow ticket payout and P/L settlement logic."""
    shadow_db = tmp_path / "shadow_tickets.sqlite"
    shadow_mgr = ShadowPortfolioManager(db_path=shadow_db)

    # Place and settle winning ticket
    t_win = shadow_mgr.place_shadow_ticket(
        legs=[{"event_id": "1", "selection": "勝", "taiwan_odds": 10.0}],
        total_odds=10.0,
        selection_category="TOP_HIGH",
        multiplier_tier="10-25x",
    )
    res_win = shadow_mgr.settle_ticket(t_win["ticket_id"], won=True)
    assert res_win["status"] == "WON"
    assert res_win["actual_payout"] == 100.0
    assert res_win["net_profit"] == 90.0

    # Place and settle losing ticket
    t_lose = shadow_mgr.place_shadow_ticket(
        legs=[{"event_id": "2", "selection": "勝", "taiwan_odds": 20.0}],
        total_odds=20.0,
        selection_category="TOP_MED",
        multiplier_tier="10-25x",
    )
    res_lose = shadow_mgr.settle_ticket(t_lose["ticket_id"], won=False)
    assert res_lose["status"] == "LOST"
    assert res_lose["actual_payout"] == 0.0
    assert res_lose["net_profit"] == -10.0

    summary = shadow_mgr.get_portfolio_summary()
    assert summary["settled_tickets"] == 2
    assert summary["wins"] == 1
    assert summary["total_virtual_staked"] == 20.0
    assert summary["total_virtual_payout"] == 100.0
    assert summary["net_pl"] == 80.0
    assert summary["roi_pct"] == 400.0


def test_weekly_report_generation(tmp_path, monkeypatch):
    """Verify generate_weekly_report generates markdown file with milestone and wallet isolation."""
    import scripts.generate_weekly_report as report_module

    class Snapshots:
        def get_all_snapshots(self):
            return []

    class Portfolio:
        def get_portfolio_summary(self, **options):
            return {"total_tickets_logged": 0, "settled_tickets": 0, "open_tickets": 0,
                    "wins": 0, "win_rate": 0.0, "total_virtual_staked": 0.0,
                    "total_virtual_payout": 0.0, "net_pl": 0.0, "roi_pct": 0.0}

    class Wallet:
        def get_status(self):
            return {"weekly_wallet_balance": 0.0, "weekly_staked": 0.0,
                    "prize_pool": 0.0, "weekly_external_deposited": 0.0}

    monkeypatch.setattr(report_module, "REPORTS_DIR", tmp_path / "reports")
    report_module.REPORTS_DIR.mkdir(parents=True)
    monkeypatch.setattr(report_module, "PredictionSnapshotLogger", Snapshots)
    class Parlays:
        def get_all_parlay_snapshots(self):
            return []
    monkeypatch.setattr(report_module, "ShadowParlayLogger", Parlays)
    monkeypatch.setattr(report_module, "ShadowPortfolioManager", Portfolio)
    monkeypatch.setattr(report_module, "WeeklyWalletManager", Wallet)
    monkeypatch.setattr(report_module, "TicketRecorder", lambda wallet: object())
    rep_path = generate_weekly_report(target_week="2026-W38")
    assert rep_path.exists()
    content = rep_path.read_text(encoding="utf-8")
    assert "Weekly Shadow Evaluation" in content
    assert STRATEGY_VERSION in content
    assert "First Milestone Target" in content
    assert "Real User Betting Ledger" in content
    assert "INSUFFICIENT_SAMPLE" in content
