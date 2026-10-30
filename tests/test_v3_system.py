#!/usr/bin/env python3
"""Comprehensive unit test suite for V3 Sports Lottery Decision System."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import tempfile
from datetime import date
from pathlib import Path
import pytest

from core.season_radar import SeasonRadar
from core.signal_hub import SignalHub
from core.parlay_engine import ParlayEngine
from core.wallet import WeeklyWalletManager, WEEKLY_PLAY_CAP
from core.ticket_recorder import TicketRecorder


@pytest.fixture
def temp_wallet():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tf:
        db_path = Path(tf.name)
    manager = WeeklyWalletManager(db_path=db_path)
    yield manager
    try:
        db_path.unlink(missing_ok=True)
    except Exception:
        pass


def test_season_radar_lights():
    """Verify season radar assigns Green, Yellow, and Red correctly."""
    radar = SeasonRadar()
    mock_live = [
        {"alliance_id": "1", "league": "MLB", "match_id": "101"},
        {"alliance_id": "1", "league": "MLB", "match_id": "102"},
    ]
    summary = radar.get_radar_summary(live_matches=mock_live)
    by_code = {item["code"]: item for item in summary}

    # MLB has live matches -> must be GREEN
    assert by_code["MLB"]["status"] == "GREEN"
    assert by_code["MLB"]["game_count"] == 2

    # NHL in off-season month or no matches -> must be RED or YELLOW
    assert by_code["NHL"]["status"] in ["RED", "YELLOW"]


def test_signal_hub_consistency():
    """Verify Signal Hub enriches options and calculates consistency levels."""
    hub = SignalHub()

    # Option with only crowd support (non-market count = 1) -> LOW
    crowd_opt = {
        "odds": 1.45,
        "consensus_ratio": 0.78,
        "vote_count": 250,
        "side": "客",
        "market_type": "不讓分",
    }
    res_crowd = hub.evaluate_option(crowd_opt)
    assert res_crowd["signals"]["consistency_level"] == "LOW"
    assert res_crowd["signals"]["support_count"] == 1

    # Longshot option with no non-market support -> INSUFFICIENT_SIGNAL
    insufficient_opt = {
        "odds": 8.50,
        "consensus_ratio": 0.15,
        "vote_count": 12,
        "side": "客",
        "market_type": "不讓分",
    }
    res_insufficient = hub.evaluate_option(insufficient_opt)
    assert res_insufficient["signals"]["consistency_level"] == "INSUFFICIENT_SIGNAL"
    assert res_insufficient["signals"]["support_count"] == 0

    # Multi-source high quality test with mocked expert
    from integrations.common.models import PredictionSignal, TaiwanLeg
    leg_multi = TaiwanLeg(
        event_id="test_high",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="道奇 客勝",
        taiwan_odds=1.70,
        start_time="10:00",
        start_time_utc=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        odds_scraped_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        odds_age_minutes=1.0,
        away_team="道奇",
        home_team="巨人",
        side="客",
        signal_evidence={"consensus_ratio": 0.65, "vote_count": 300, "crowd_snapshot_timestamp": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), "crowd_age_minutes": 1.0},
    )
    # Manually attach verified expert signal and evaluate
    class MockExpertAdapter:
        def get_expert_signal(self, leg):
            return PredictionSignal(
                source_id="test_expert",
                source_name="榜首大神",
                source_type="EXPERT",
                event_id=leg.event_id,
                market=leg.market,
                selection=leg.selection,
                probability=0.75,
                score=75.0,
                confidence="HIGH",
                freshness_status="FRESH",
                timestamp=(datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
                data_as_of=(datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
                metadata={"sample_size": 20, "provenance": "fixed unit-test fixture"},
            )
    hub_with_expert = SignalHub(expert_adapter=MockExpertAdapter())
    from integrations.common.models import PredictionSignal
    hub_with_expert.model_registry.evaluate_leg_across_models = lambda leg: [
        PredictionSignal(
            source_id="fresh-model-fixture",
            source_name="Fresh model test fixture",
            source_type="MODEL",
            source_category="OPEN_SOURCE_ENGINE",
            independence_group="LIVE_MLB_ELO",
            event_id=leg.event_id,
            market=leg.market,
            selection=leg.selection,
            probability=0.64,
            score=4.0,
            confidence="MED",
            freshness_status="FRESH",
            timestamp=(datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
            data_as_of=(datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
            metadata={"initialized": True, "provenance": "fixed unit-test fixture"},
        )
    ]
    evaluated_leg = hub_with_expert.evaluate_taiwan_leg(leg_multi)
    assert evaluated_leg.evidence_quality == "MED"
    assert evaluated_leg.signal_evidence["support_count"] >= 2
    assert "LIVE_MLB_ELO" not in evaluated_leg.signal_evidence["supporting_groups"]
    assert len(evaluated_leg.signal_evidence["model_candidate_provenances"]) == 1


def test_parlay_engine_bounds_and_mutual_exclusion():
    """Verify parlay search enforces target odds and mutual exclusivity."""
    hub = SignalHub()
    hub.expert_adapter.get_expert_signal = lambda leg: None
    engine = ParlayEngine(signal_hub=hub)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    fixture_clock = {
        "start_time_utc": (now + timedelta(hours=3)).isoformat(),
        "odds_scraped_at": (now - timedelta(minutes=1)).isoformat(),
        "odds_status": "FRESH",
        "odds_age_minutes": 1.0,
    }

    mock_matches = [
        {
            "match_id": "M1",
            "sport": "baseball",
            "league": "MLB",
            "market": "不讓分",
            "alliance_id": "1",
            "away_team": "洋基",
            "home_team": "紅襪",
            **fixture_clock,
            "options": [
                {"odds": 1.70, "consensus_ratio": 0.72, "vote_count": 100, "crowd_snapshot_timestamp": (now - timedelta(minutes=1)).isoformat(), "crowd_age_minutes": 1.0, "side": "客", "selection": "洋基客勝 (1.70)"},
                {"odds": 2.15, "consensus_ratio": 0.28, "vote_count": 100, "crowd_snapshot_timestamp": (now - timedelta(minutes=1)).isoformat(), "crowd_age_minutes": 1.0, "side": "主", "selection": "紅襪主勝 (2.15)"},
            ],
        },
        {
            "match_id": "M2",
            "sport": "football",
            "league": "NFL",
            "market": "不讓分",
            "alliance_id": "93",
            "away_team": "酋長",
            "home_team": "突擊者",
            **fixture_clock,
            "options": [
                {"odds": 1.55, "consensus_ratio": 0.80, "vote_count": 100, "crowd_snapshot_timestamp": (now - timedelta(minutes=1)).isoformat(), "crowd_age_minutes": 1.0, "side": "客", "selection": "酋長客勝 (1.55)"},
                {"odds": 2.45, "consensus_ratio": 0.20, "vote_count": 100, "crowd_snapshot_timestamp": (now - timedelta(minutes=1)).isoformat(), "crowd_age_minutes": 1.0, "side": "主", "selection": "突擊者主勝 (2.45)"},
            ],
        },
        {
            "match_id": "M3",
            "sport": "soccer",
            "league": "足球",
            "market": "不讓分",
            "alliance_id": "4",
            "away_team": "兵工廠",
            "home_team": "車路士",
            **fixture_clock,
            "options": [
                {"odds": 2.05, "consensus_ratio": 0.65, "vote_count": 100, "crowd_snapshot_timestamp": (now - timedelta(minutes=1)).isoformat(), "crowd_age_minutes": 1.0, "side": "客", "selection": "兵工廠客勝 (2.05)"},
                {"odds": 3.20, "consensus_ratio": 0.25, "vote_count": 100, "crowd_snapshot_timestamp": (now - timedelta(minutes=1)).isoformat(), "crowd_age_minutes": 1.0, "side": "和", "selection": "和局 (3.20)"},
            ],
        },
        {
            "match_id": "M4",
            "sport": "baseball",
            "league": "MLB",
            "market": "不讓分",
            "alliance_id": "1",
            "away_team": "道奇",
            "home_team": "巨人",
            **fixture_clock,
            "options": [
                {"odds": 1.48, "consensus_ratio": 0.85, "vote_count": 100, "crowd_snapshot_timestamp": (now - timedelta(minutes=1)).isoformat(), "crowd_age_minutes": 1.0, "side": "客", "selection": "道奇客勝 (1.48)"},
            ],
        },
    ]

    results = engine.search_parlays(mock_matches, min_odds=5.0, max_odds=30.0, min_legs=2, max_legs=4)
    all_parlays = results["high_consensus"] + results["aggressive"] + results["moonshot"]

    assert len(all_parlays) > 0

    for p in all_parlays:
        assert 5.0 <= p["total_odds"] <= 30.0
        # Check mutual exclusion: no match_id repeated
        mids = [leg["match_id"] for leg in p["legs"]]
        assert len(mids) == len(set(mids))


def test_weekly_wallet_flow_and_prize_pool(temp_wallet):
    """Verify Weekly Wallet deposit limits, winnings lock to Prize Pool, and rollover."""
    # 1. Initially wallet = 0, external deposit quota = 200
    st0 = temp_wallet.get_status()
    assert st0["weekly_wallet_balance"] == 0.0
    assert st0["external_deposit_remaining"] == 200.0

    # 2. Deposit 150 from external cash
    dep_res = temp_wallet.deposit_external(150.0)
    assert dep_res["new_wallet_balance"] == 150.0

    st1 = temp_wallet.get_status()
    assert st1["weekly_wallet_balance"] == 150.0
    assert st1["external_deposit_remaining"] == 50.0

    # 3. Trying to deposit 60 fails (exceeds 50 shortfall limit)
    with pytest.raises(ValueError, match="入金上限攔截"):
        temp_wallet.deposit_external(60.0)

    # Deposit remaining 50 -> Wallet is full at 200
    temp_wallet.deposit_external(50.0)
    st2 = temp_wallet.get_status()
    assert st2["weekly_wallet_balance"] == 200.0
    assert st2["external_deposit_remaining"] == 0.0

    # 4. Stake a bet of 50
    temp_wallet.stake_bet(stake=50.0, ticket_id="T001")
    st3 = temp_wallet.get_status()
    assert st3["weekly_wallet_balance"] == 150.0
    assert st3["weekly_staked"] == 50.0

    # 5. Winning 1,000 credits DIRECTLY into Prize Pool (locked profit)!
    win_res = temp_wallet.credit_winnings(payout=1000.0, ticket_id="T001")
    assert win_res["new_prize_pool"] == 1000.0

    st4 = temp_wallet.get_status()
    # Wallet remains 150, winnings are locked in prize pool
    assert st4["weekly_wallet_balance"] == 150.0
    assert st4["prize_pool"] == 1000.0


def test_weekly_rollover_draws_from_prize_pool(temp_wallet):
    """Verify that when a new week arrives, budget is drawn from Prize Pool, NOT external cash."""
    # Set up wallet with 0 balance, but 500 in prize pool
    with temp_wallet._get_connection() as conn:
        conn.execute(
            """
            UPDATE wallet_state
            SET current_week = '2026-W01', wallet_balance = 0.0, weekly_staked = 200.0,
                prize_pool = 500.0, weekly_external_deposited = 200.0
            WHERE profile_id = 'default'
            """
        )
        conn.commit()

    # Call get_status with a future date (simulating next week)
    next_week_date = date(2026, 9, 18)
    temp_wallet._ensure_week_initialized(target_date=next_week_date)

    st = temp_wallet.get_status()
    # 200 must be transferred from Prize Pool to Weekly Wallet!
    assert st["weekly_wallet_balance"] == 200.0
    assert st["prize_pool"] == 300.0   # 500 - 200 = 300
    assert st["weekly_staked"] == 0.0
    # No external deposit allowed because Prize Pool covered it completely!
    assert st["external_deposit_remaining"] == 0.0
    assert st["can_deposit"] is False


def test_ticket_recorder_lifecycle(temp_wallet):
    """Verify placing and settling a ticket through TicketRecorder."""
    recorder = TicketRecorder(wallet=temp_wallet)
    temp_wallet.deposit_external(200.0)

    legs = [
        {"match_id": "M101", "league": "MLB", "away_team": "洋基", "home_team": "紅襪", "selection": "洋基勝", "odds": 2.0},
        {"match_id": "M102", "league": "NFL", "away_team": "酋長", "home_team": "突擊者", "selection": "酋長勝", "odds": 1.5},
    ]

    ticket = recorder.place_ticket(legs=legs, stake=30.0, total_odds=3.0)
    assert ticket["status"] == "OPEN"
    assert ticket["stake"] == 30.0
    assert ticket["potential_payout"] == 90.0
    assert "MLB + NFL" in ticket["sports_summary"]

    # Wallet deducted: 200 - 30 = 170
    assert temp_wallet.get_status()["weekly_wallet_balance"] == 170.0

    # Settle ticket as WON: 90.0 goes to prize pool
    settle = recorder.settle_ticket(ticket["ticket_id"], won=True)
    assert settle["won"] is True
    assert temp_wallet.get_status()["prize_pool"] == 90.0
