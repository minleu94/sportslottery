#!/usr/bin/env python3
"""Comprehensive test suite for Taiwan Sports Lottery Quantitative Decision Upgrade.

Verifies:
1. Official Taiwan Baseball Settlement Engine v2 (Called Game rules, Regulation rules, VOID refund).
2. EdgeEngine (Shin de-vigging, logit shrinkage, 90% confidence bounds, EV/Edge calculation, negative EV trap detection).
3. Source-Family Independence Architecture (Market, Human, Statistical Model, Fundamental Data).
4. CorrelationGuard (cross-leg correlation, haircut factor, joint probability, parlay EV).
5. LiveMLBEloAdapter (Home Field Advantage +24, dynamic updates, persistence).
6. 4-State Odds Tracking & CLV Analytics (Signal, Recommendation, Placed, Closing).
7. Lifetime Wallet Accounting & Reserve Bankroll (Gross Payout vs Net Profit).
8. PerformanceMetricsEngine EV Buckets.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from core.settlement.taiwan_rules import (
    RULE_VERSION,
    OfficialCompletionStatus,
    SettlementResult,
    TaiwanSettlementRules,
)
from core.edge_engine import EdgeEngine
from core.signal_hub import (
    SignalHub,
    FAMILY_HUMAN,
    FAMILY_STATISTICAL_MODEL,
    FAMILY_MARKET,
    FAMILY_FUNDAMENTAL,
)
from core.correlation_guard import CorrelationGuard
from integrations.models.external.live_mlb_elo import LiveMLBEloAdapter
from core.ticket_recorder import TicketRecorder
from core.wallet import WalletManager
from core.performance_metrics import PerformanceMetricsEngine
from core.experiment_identity import get_current_experiment_identity
from core.snapshot_logger import compute_prediction_payload_hash
from core.strategy_version import STRATEGY_VERSION
from integrations.common.models import TaiwanLeg, PredictionSignal


# =====================================================================
# 1. Official Taiwan Settlement Engine v2
# =====================================================================

def test_taiwan_settlement_regulation_game():
    """9-inning completed game settles all markets normally."""
    home_score = 6
    away_score = 4
    innings = 9.0
    status = OfficialCompletionStatus.REGULATION_COMPLETED

    # Moneyline
    res_ml_home = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-ML",
        market="不讓分",
        selection="主隊",
        line=None,
        away_score=away_score,
        home_score=home_score,
        innings_completed=innings,
        official_completion_status=status,
    )
    assert res_ml_home.status == "WON"
    assert res_ml_home.effective_odds == 1.0

    res_ml_away = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-ML",
        market="不讓分",
        selection="客隊",
        line=None,
        away_score=away_score,
        home_score=home_score,
        innings_completed=innings,
        official_completion_status=status,
    )
    assert res_ml_away.status == "LOST"

    # Spread: Away +1.5 -> diff is 6 - 4 = 2 -> Home covers -1.5, Away loses +1.5
    res_sp_away = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-SPREAD",
        market="讓分",
        selection="客隊",
        line=1.5,
        away_score=away_score,
        home_score=home_score,
        innings_completed=innings,
        official_completion_status=status,
    )
    assert res_sp_away.status == "LOST"

    # Total: Line 8.5, total is 10 -> Over WIN, Under LOSS
    res_ov = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-TOTAL",
        market="大小",
        selection="大分",
        line=8.5,
        away_score=away_score,
        home_score=home_score,
        innings_completed=innings,
        official_completion_status=status,
    )
    assert res_ov.status == "WON"

    res_un = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-TOTAL",
        market="大小",
        selection="小分",
        line=8.5,
        away_score=away_score,
        home_score=home_score,
        innings_completed=innings,
        official_completion_status=status,
    )
    assert res_un.status == "LOST"


def test_taiwan_settlement_called_game_rules():
    """Called game (e.g. rain stoppage after 6 innings):
    - Moneyline (不讓分): Pre-game bets are VALID according to official interrupted score.
    - Total (大小):
        - If score already surpassed line (e.g. 5+3=8 > 7.5): VALID (Over WIN, Under LOSS).
        - If score has NOT surpassed line (e.g. 5+3=8 < 8.5): VOID (refund odds = 1.0).
    - Spread (讓分): Incomplete regulation innings -> VOID (refund odds = 1.0).
    """
    home_score = 5
    away_score = 3
    innings = 6.0
    status = OfficialCompletionStatus.CALLED_GAME_SHORTENED

    # Moneyline: Home 5, Away 3 -> VALID, Home WIN
    res_ml_home = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-ML",
        market="不讓分",
        selection="主隊",
        line=None,
        away_score=away_score,
        home_score=home_score,
        innings_completed=innings,
        official_completion_status=status,
    )
    assert res_ml_home.status == "WON"
    assert res_ml_home.is_called_game is True

    res_ml_away = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-ML",
        market="不讓分",
        selection="客隊",
        line=None,
        away_score=away_score,
        home_score=home_score,
        innings_completed=innings,
        official_completion_status=status,
    )
    assert res_ml_away.status == "LOST"
    assert res_ml_away.is_called_game is True

    # Spread (讓分): MUST BE VOID because 9 innings not completed
    res_sp = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-SPREAD",
        market="讓分",
        selection="主隊",
        line=-1.5,
        away_score=away_score,
        home_score=home_score,
        innings_completed=innings,
        official_completion_status=status,
    )
    assert res_sp.status == "VOID"
    assert res_sp.effective_odds == 1.0
    assert "未滿法定 9 局" in res_sp.reason

    # Total Line 7.5 (Total score 8 already EXCEEDED 7.5) -> Over is WIN, Under is LOSS
    res_tot_ov = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-TOTAL",
        market="大小",
        selection="大分",
        line=7.5,
        away_score=away_score,
        home_score=home_score,
        innings_completed=innings,
        official_completion_status=status,
    )
    assert res_tot_ov.status == "WON"

    res_tot_un = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-TOTAL",
        market="大小",
        selection="小分",
        line=7.5,
        away_score=away_score,
        home_score=home_score,
        innings_completed=innings,
        official_completion_status=status,
    )
    assert res_tot_un.status == "LOST"

    # Total Line 8.5 (Total score 8 has NOT exceeded 8.5) -> VOID refund
    res_tot_void = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-TOTAL",
        market="大小",
        selection="大分",
        line=8.5,
        away_score=away_score,
        home_score=home_score,
        innings_completed=innings,
        official_completion_status=status,
    )
    assert res_tot_void.status == "VOID"
    assert res_tot_void.effective_odds == 1.0


def test_taiwan_settlement_cancelled_or_abandoned():
    """Match abandoned early or cancelled -> VOID."""
    res = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="TW-BASEBALL-MLB-ML",
        market="不讓分",
        selection="主隊",
        line=None,
        away_score=1,
        home_score=0,
        innings_completed=2.0,
        official_completion_status=OfficialCompletionStatus.CANCELLED,
    )
    assert res.status == "VOID"
    assert res.effective_odds == 1.0


# =====================================================================
# 2. EdgeEngine & Probability Calibration
# =====================================================================

def test_edge_engine_devig_and_calibration():
    """Verify de-vigging, logit shrinkage, conservative confidence bound, and EV."""
    # Test De-vigging: standard balanced market (1.80 vs 1.80) -> sum of inv = 1.111 -> de-vigged is 0.50
    devig_probs = EdgeEngine.devig_proportional([1.80, 1.80])
    assert abs(devig_probs[0] - 0.50) < 1e-4
    assert abs(devig_probs[1] - 0.50) < 1e-4

    # Logit shrinkage calibration: extreme raw probability 0.85 shrinks towards 0.50
    cal_prob = EdgeEngine.calibrate_probability_logit(0.85, shrinkage_factor=0.80)
    assert cal_prob < 0.85
    assert cal_prob > 0.70

    # Confidence interval lower bound
    ci = EdgeEngine.calculate_confidence_interval(prob=0.60, sample_size=15, confidence_level=0.90)
    assert ci.lower_bound < 0.60
    assert ci.upper_bound > 0.60
    assert ci.uncertainty_level in ["MEDIUM", "HIGH"]


def test_edge_engine_negative_ev_trap_detection():
    """Demonstrate negative-EV trap on heavy public favorites (e.g. 1.25 @ 78% win rate)."""
    # 78% win rate on 1.25 odds: EV = 0.78 * 1.25 - 1 = -0.025 (-2.5%)
    eval_res = EdgeEngine.evaluate_edge(
        raw_prob=0.78,
        odds=1.25,
        sample_size=20,
        apply_calibration=True,
    )
    # Calibrated prob will be slightly lower than 0.78, EV will be negative
    assert eval_res.expected_value < 0.0
    assert eval_res.edge_pct < 0.0
    assert eval_res.is_negative_ev is True
    assert eval_res.is_value_bet is False
    assert "負期望值陷阱" in eval_res.trap_warning

    # Positive EV pick: 55% win rate on 2.10 odds: EV = 0.55 * 2.10 - 1 = +0.155 (+15.5%)
    eval_pos = EdgeEngine.evaluate_edge(
        raw_prob=0.55,
        odds=2.10,
        sample_size=30,
        apply_calibration=False,
    )
    assert eval_pos.expected_value > 0.10
    assert eval_pos.is_negative_ev is False
    assert eval_pos.is_value_bet is True


# =====================================================================
# 3. Source-Family Independence Architecture
# =====================================================================

def test_source_family_independence():
    """Verify that Playsport Expert + Crowd belong to FAMILY_HUMAN and cannot alone yield HIGH."""
    hub = SignalHub()

    # Case A: Expert + Crowd (Both in FAMILY_HUMAN)
    leg1 = TaiwanLeg(
        event_id="E1",
        sport="BASEBALL",
        league="MLB",
        market="不讓分",
        selection="主隊",
        taiwan_odds=1.85,
    )
    signals_human_only = [
        PredictionSignal(
            source_id="playsport_crowd",
            source_name="playsport_crowd",
            source_type="CROWD_CONSENSUS",
            event_id="E1",
            market="不讓分",
            selection="主隊",
            pick="主隊",
            score=65.0,
            confidence="MED",
            source_category="CROWD_CONSENSUS",
            independence_group="PLAYSPORT_CROWD",
            freshness_status="FRESH",
            timestamp="2026-09-18T11:00:00Z",
            data_as_of="2026-09-18T11:00:00Z",
            metadata={"vote_count": 100, "provenance": "fixed unit-test fixture"},
        ),
        PredictionSignal(
            source_id="playsport_expert",
            source_name="playsport_expert",
            source_type="VERIFIED_EXPERT",
            event_id="E1",
            market="不讓分",
            selection="主隊",
            pick="主隊",
            score=60.0,
            confidence="HIGH",
            source_category="VERIFIED_EXPERT",
            independence_group="PLAYSPORT_EXPERT",
            freshness_status="FRESH",
            timestamp="2026-09-18T11:00:00Z",
            data_as_of="2026-09-18T11:00:00Z",
            metadata={"sample_size": 20, "provenance": "fixed unit-test fixture"},
        ),
    ]

    leg1 = hub.synthesize_signals_for_leg(leg1, signals_human_only)
    assert FAMILY_HUMAN in leg1.source_families
    assert len(leg1.source_families) == 1
    # Must NOT be HIGH because it lacks cross-family corroboration
    assert leg1.evidence_quality in ["MED", "LOW"]

    # Case B: Human Expert (FAMILY_HUMAN) + Live MLB Elo (FAMILY_STATISTICAL_MODEL)
    leg2 = TaiwanLeg(
        event_id="E2",
        sport="BASEBALL",
        league="MLB",
        market="不讓分",
        selection="主隊",
        taiwan_odds=1.85,
        start_time_utc="2026-09-18T12:00:00Z",
    )
    signals_multi_family = [
        PredictionSignal(
            source_id="playsport_expert",
            source_name="playsport_expert",
            source_type="VERIFIED_EXPERT",
            event_id="E2",
            market="不讓分",
            selection="主隊",
            pick="主隊",
            score=60.0,
            confidence="HIGH",
            source_category="VERIFIED_EXPERT",
            independence_group="PLAYSPORT_EXPERT",
            freshness_status="FRESH",
            timestamp="2026-09-18T11:00:00Z",
            data_as_of="2026-09-18T11:00:00Z",
            metadata={"sample_size": 20, "provenance": "fixed unit-test fixture"},
        ),
        PredictionSignal(
            source_id="live_mlb_elo",
            source_name="live_mlb_elo",
            source_type="OPEN_SOURCE_ENGINE",
            event_id="E2",
            market="不讓分",
            selection="主隊",
            pick="主隊",
            probability=0.65,
            score=10.0,
            confidence="HIGH",
            source_category="OPEN_SOURCE_ENGINE",
            independence_group="LIVE_MLB_ELO",
            freshness_status="FRESH",
            timestamp="2026-09-18T11:00:00Z",
            data_as_of="2026-09-18T11:00:00Z",
            metadata={"initialized": True, "provenance": "fixed unit-test fixture"},
        ),
    ]

    leg2 = hub.synthesize_signals_for_leg(leg2, signals_multi_family)
    assert FAMILY_HUMAN in leg2.source_families
    assert FAMILY_STATISTICAL_MODEL not in leg2.source_families
    assert len(leg2.source_families) == 1
    assert len(leg2.signal_evidence["model_candidate_provenances"]) == 1
    assert leg2.evidence_quality != "HIGH"


# =====================================================================
# 4. CorrelationGuard
# =====================================================================

def test_correlation_guard_haircut():
    """Verify parlay correlation detection, haircut factor, and parlay EV."""
    guard = CorrelationGuard()

    # Independent legs: Different events, different teams, different markets
    leg1 = TaiwanLeg(
        event_id="E101",
        sport="BASEBALL",
        league="MLB",
        home_team="Dodgers",
        away_team="Giants",
        market="不讓分",
        selection="主隊",
        taiwan_odds=1.80,
        consensus_probability=0.58,
        expected_value=0.044,
    )
    leg2 = TaiwanLeg(
        event_id="E102",
        sport="BASEBALL",
        league="MLB",
        home_team="Yankees",
        away_team="Red Sox",
        market="大小",
        selection="大分",
        taiwan_odds=1.90,
        consensus_probability=0.55,
        expected_value=0.045,
    )

    clean_assessment = guard.assess_parlay([leg1, leg2])
    assert clean_assessment.risk_level == "INDEPENDENT_CLEAN"
    assert clean_assessment.haircut_factor == 0.0
    assert abs(clean_assessment.joint_probability - (0.58 * 0.55)) < 1e-4

    # Correlated legs: Multiple legs with the same team
    leg3_same_team = TaiwanLeg(
        event_id="E103",
        sport="BASEBALL",
        league="MLB",
        home_team="Dodgers",  # Same team as leg1
        away_team="Padres",
        market="不讓分",
        selection="主隊",
        taiwan_odds=1.85,
        start_time_utc="2026-09-18T12:00:00Z",
        consensus_probability=0.60,
        expected_value=0.11,
    )

    corr_assessment = guard.assess_parlay([leg1, leg3_same_team])
    assert corr_assessment.haircut_factor > 0.0
    raw_joint = 0.58 * 0.60
    assert corr_assessment.joint_probability < raw_joint
    assert corr_assessment.parlay_expected_value is not None


# =====================================================================
# 5. LiveMLBEloAdapter
# =====================================================================

def test_live_mlb_elo_adapter():
    """Neutral startup stays experimental; only official game records advance Elo."""
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
        _test_live_mlb_elo_adapter(Path(folder) / "live-elo.json")


def _test_live_mlb_elo_adapter(state_file):
    adapter = LiveMLBEloAdapter(state_file=state_file)
    r_lad = adapter.get_rating("MLB_LAD")
    assert r_lad == 1500.0

    p_home, p_away = adapter.predict_match("MLB_LAD", "MLB_LAD")
    assert p_home > 0.50
    assert p_away < 0.50

    leg = TaiwanLeg(event_id="E_MLB_1", sport="baseball", league="MLB", home_team="道奇",
                    away_team="洋基", market="不讓分", selection="道奇 主勝", taiwan_odds=1.75, side="主")
    signal = adapter.evaluate_leg(leg)
    assert signal is not None
    assert signal.quality_label == "MODEL_EXPERIMENTAL"
    assert signal.freshness_status == "UNKNOWN"
    assert signal.metadata["starting_pitcher_adjustment_used"] is False

    result = adapter.apply_official_games([{
        "gamePk": 191000001,
        "gameDate": "2026-07-01T20:00:00Z",
        "status": {"abstractGameState": "Final", "codedGameState": "F"},
        "teams": {"home": {"team": {"name": "Los Angeles Dodgers"}},
                  "away": {"team": {"name": "New York Yankees"}}},
        "linescore": {"teams": {"home": {"runs": 7}, "away": {"runs": 2}}},
    }])
    assert result["updated_games"] == 1
    assert adapter.get_rating("MLB_LAD") > r_lad
    assert adapter.get_rating("MLB_NYY") < 1500.0
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["processed_game_pks"] == ["191000001"]


# =====================================================================
# 6. 4-State Odds Tracking & CLV Analytics
# =====================================================================

def test_ticket_4_state_odds_and_clv():
    """Verify 4-state odds tracking, CLV calculation, and VOID settlement refund."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tf:
        db_path = Path(tf.name)

    try:
        wallet = WalletManager(db_path=db_path)
        wallet.deposit_external(200.0)
        recorder = TicketRecorder(wallet=wallet)

        res1 = recorder.place_ticket(
            stake=100.0,
            total_odds=50.0,
            legs=[
                {"event_id": "E1", "selection": "主隊", "odds": 5.0, "league": "MLB"},
                {"event_id": "E2", "selection": "大分", "odds": 10.0, "league": "MLB"},
            ],
            recommendation_odds=50.0,
            placed_odds=50.0,
        )
        ticket_id_1 = res1["ticket_id"]

        # Update closing odds before settlement: closing_odds dropped to 40.0
        # CLV = placed_odds / closing_odds - 1.0 = 50.0 / 40.0 - 1.0 = +25.0%
        recorder.update_closing_odds(ticket_id_1, closing_odds=40.0)

        # Settle ticket as WON
        recorder.settle_ticket(ticket_id_1, won=True)

        # Check CLV analytics
        analytics = recorder.get_clv_analytics()
        assert analytics["sample_size"] == 1
        assert analytics["avg_clv_pct"] == 25.0
        assert analytics["beating_closing_line_rate"] == 100.0
        assert analytics["positive_clv_count"] == 1

        # Place second ticket and settle as VOID (rainout / called game refund)
        res2 = recorder.place_ticket(
            stake=50.0,
            total_odds=15.0,
            legs=[{"event_id": "E3", "odds": 15.0, "league": "MLB"}],
            recommendation_odds=15.0,
            placed_odds=15.0,
        )
        ticket_id_2 = res2["ticket_id"]
        void_res = recorder.settle_ticket(ticket_id_2, won=False, is_void=True)

        assert void_res["status"] == "VOID"
        assert void_res["payout"] == 50.0  # Exact stake refund at 1.0 odds
        assert void_res["net_profit"] == 0.0

    finally:
        try:
            db_path.unlink(missing_ok=True)
        except Exception:
            pass


# =====================================================================
# 7. Lifetime Wallet Accounting & Reserve Bankroll
# =====================================================================

def test_wallet_lifetime_accounting():
    """Verify lifetime statistics, Gross Payout vs Net Profit, and Reserve Bankroll operations."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tf:
        db_path = Path(tf.name)

    try:
        wallet = WalletManager(db_path=db_path)

        # External deposit of NT$ 200
        wallet.deposit_external(200.0)

        # Place a bet of NT$ 100 on 3.00 odds
        wallet.stake_bet(100.0, ticket_id="TKT_W_001")

        # Win payout: Gross Payout = NT$ 300, Net Profit = NT$ 200
        wallet.credit_winnings(payout=300.0, ticket_id="TKT_W_001")

        status = wallet.get_status()
        assert status["lifetime_external_deposited"] == 200.0
        assert status["lifetime_staked"] == 100.0
        assert status["lifetime_gross_payout"] == 300.0
        assert status["lifetime_net_profit"] == 200.0
        assert status["reserve_balance"] == 300.0

        # Withdraw from reserve bankroll
        withdrawn = wallet.withdraw_from_prize_pool(50.0)
        assert withdrawn["amount"] == 50.0
        assert withdrawn["new_prize_pool"] == 250.0

        new_status = wallet.get_status()
        assert new_status["lifetime_withdrawn"] == 50.0
        assert new_status["reserve_balance"] == 250.0

    finally:
        try:
            db_path.unlink(missing_ok=True)
        except Exception:
            pass


# =====================================================================
# 8. PerformanceMetricsEngine EV Buckets
# =====================================================================

def test_metrics_engine_ev_buckets():
    """Verify evaluate_ev_buckets correctly categorizes positive and negative EV predictions."""
    test_snapshots = [
        # High Positive EV: prob = 0.60, odds = 2.00 -> EV = +0.20 (20%) -> WIN
        {
            "is_settled": True,
            "actual_outcome": True,
            "taiwan_odds": 2.00,
            "expected_value": 0.20,
            "model_probability": 0.60,
        },
        # Moderate Positive EV: prob = 0.52, odds = 2.00 -> EV = +0.04 (4%) -> WIN
        {
            "is_settled": True,
            "actual_outcome": True,
            "taiwan_odds": 2.00,
            "expected_value": 0.04,
            "model_probability": 0.52,
        },
        # Negative EV Trap: prob = 0.75, odds = 1.25 -> EV = -0.0625 (-6.25%) -> LOSS
        {
            "is_settled": True,
            "actual_outcome": False,
            "taiwan_odds": 1.25,
            "expected_value": -0.0625,
            "model_probability": 0.75,
        },
    ]
    for index, snapshot in enumerate(test_snapshots):
        snapshot.update({
            "forward_validation_eligible": True,
            "settlement_status": "WON" if snapshot["actual_outcome"] else "LOST",
            "strategy_version": STRATEGY_VERSION,
            "probability_status": "UNVALIDATED_MODEL_ESTIMATE",
            "snapshot_id": f"ev-metric-{index}",
            "snapshot_timestamp": "2026-10-01T12:00:00+00:00",
            "event_id": f"ev-event-{index}", "canonical_event_id": f"ev-event-{index}",
            "event_start": f"2026-10-{2 + index:02d}T12:00:00+00:00",
            "settled_at": f"2026-10-{5 + index:02d}T12:00:00+00:00",
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

    ev_buckets = PerformanceMetricsEngine.evaluate_ev_buckets(test_snapshots)

    high_ev = ev_buckets["優質價值 (EV ≥ +5%)"]
    assert high_ev["sample_size"] == 1
    assert high_ev["wins"] == 1
    assert high_ev["hit_rate"] == 1.0

    mod_ev = ev_buckets["溫和價值 (0% ≤ EV < +5%)"]
    assert mod_ev["sample_size"] == 1
    assert mod_ev["wins"] == 1

    neg_ev = ev_buckets["負期望值陷阱 (EV < 0%)"]
    assert neg_ev["sample_size"] == 1
    assert neg_ev["wins"] == 0
    assert neg_ev["hit_rate"] == 0.0
