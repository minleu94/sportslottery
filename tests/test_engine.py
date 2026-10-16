#!/usr/bin/env python3
"""Comprehensive test suite for War Chest, Parlay Optimizer, and Ticket Manager."""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
import pytest

from core.war_chest import WarChestManager, WEEKLY_DEPOSIT_CAP
from core.ticket_manager import TicketManager
from core.optimizer import ParlayOptimizer


@pytest.fixture
def temp_war_chest():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tf:
        db_path = Path(tf.name)
    manager = WarChestManager(db_path=db_path)
    yield manager
    try:
        db_path.unlink(missing_ok=True)
    except Exception:
        pass


def test_war_chest_weekly_deposit_cap(temp_war_chest):
    """Verify that weekly deposits strictly enforce the NT$ 200 cap."""
    test_date = date(2026, 9, 17)

    # First deposit 120 -> OK
    res1 = temp_war_chest.deposit(120.0, target_date=test_date)
    assert res1["balance_after"] == 120.0
    assert res1["week_deposit_remaining"] == 80.0

    # Second deposit 100 -> Exceeds remaining 80 -> should raise ValueError
    with pytest.raises(ValueError, match="風控攔截"):
        temp_war_chest.deposit(100.0, target_date=test_date)

    # Deposit exactly remaining 80 -> OK
    res2 = temp_war_chest.deposit(80.0, target_date=test_date)
    assert res2["balance_after"] == 200.0
    assert res2["week_deposit_remaining"] == 0.0

    # Any further deposit in the same week must fail
    with pytest.raises(ValueError, match="風控攔截"):
        temp_war_chest.deposit(10.0, target_date=test_date)


def test_war_chest_surplus_reinvestment(temp_war_chest):
    """Verify '多餘的才可以再繼續' logic: winnings can be re-invested freely."""
    test_date = date(2026, 9, 17)

    # Deposit weekly max 200
    temp_war_chest.deposit(200.0, target_date=test_date)
    assert temp_war_chest.get_latest_balance() == 200.0

    # Place a 200 bet -> Balance becomes 0
    temp_war_chest.commit_bet(stake=200.0, ticket_id="TICKET_001")
    assert temp_war_chest.get_latest_balance() == 0.0

    # Balance is 0 and weekly quota is 0 -> Cannot bet now
    with pytest.raises(ValueError, match="資金不足"):
        temp_war_chest.commit_bet(stake=50.0, ticket_id="TICKET_FAIL")

    # Win the bet! 200 * 50x = 10,000 NTD payout
    settle_res = temp_war_chest.settle_bet(ticket_id="TICKET_001", won=True, payout=10000.0)
    assert settle_res["balance_after"] == 10000.0
    assert temp_war_chest.get_latest_balance() == 10000.0

    # Now the user has surplus (多餘的戰備金)! They can continue betting!
    res_surplus = temp_war_chest.commit_bet(stake=200.0, ticket_id="TICKET_SURPLUS")
    assert res_surplus["balance_after"] == 9800.0


def test_optimizer_rules_and_odds_bounds():
    """Verify parlay optimizer guarantees odds bounds and mutually exclusive matches."""
    matches = [
        {
            "match_id": "M_01",
            "league": "MLB",
            "away_team": "洋基",
            "home_team": "紅襪",
            "options": [
                {"odds": 1.80, "fair_prob": 0.60, "consensus_ratio": 0.70, "selection": "洋基 不讓分勝 (1.80)"},
                {"odds": 2.05, "fair_prob": 0.45, "consensus_ratio": 0.30, "selection": "紅襪 不讓分勝 (2.05)"},
            ],
        },
        {
            "match_id": "M_02",
            "league": "MLB",
            "away_team": "道奇",
            "home_team": "巨人",
            "options": [
                {"odds": 1.50, "fair_prob": 0.70, "consensus_ratio": 0.80, "selection": "道奇 不讓分勝 (1.50)"},
                {"odds": 1.75, "fair_prob": 0.58, "consensus_ratio": 0.65, "selection": "大 8.5 (1.75)"},
            ],
        },
        {
            "match_id": "M_03",
            "league": "足球",
            "away_team": "皇馬",
            "home_team": "巴薩",
            "options": [
                {"odds": 2.50, "fair_prob": 0.42, "consensus_ratio": 0.55, "selection": "皇馬 不讓分勝 (2.50)"},
                {"odds": 3.40, "fair_prob": 0.30, "consensus_ratio": 0.35, "selection": "和局 (3.40)"},
            ],
        },
        {
            "match_id": "M_04",
            "league": "足球",
            "away_team": "兵工廠",
            "home_team": "曼城",
            "options": [
                {"odds": 2.10, "fair_prob": 0.50, "consensus_ratio": 0.60, "selection": "曼城 不讓分勝 (2.10)"},
            ],
        },
    ]

    optimizer = ParlayOptimizer(min_odds=10.0, max_odds=500.0)
    results = optimizer.optimize(
        matches=matches,
        min_odds=10.0,
        max_odds=500.0,
        min_legs=3,
        max_legs=4,
        stake=200.0,
    )

    assert len(results) > 0

    for r in results:
        # Check odds constraint [10x, 500x]
        assert 10.0 <= r["total_odds"] <= 500.0
        # Check EV formula: EV = (total_odds * win_prob) - 1.0
        calculated_ev = round((r["total_odds"] * r["win_prob"]) - 1.0, 4)
        assert abs(r["ev"] - calculated_ev) < 0.001
        # Check mutually exclusive matches (台彩串關規定: 同場不重複)
        selected_match_ids = [leg.get("match_id", f"M_{idx}") for idx, leg in enumerate(r["legs"])]
        assert len(selected_match_ids) == len(set(selected_match_ids))


def test_ticket_manager_workflow(temp_war_chest):
    """Verify placing a ticket, listing, and settling."""
    ticket_mgr = TicketManager(war_chest=temp_war_chest)
    # First deposit 200
    temp_war_chest.deposit(200.0)

    legs = [
        {"match_id": "M1", "league": "MLB", "selection": "道奇勝", "odds": 2.0},
        {"match_id": "M2", "league": "MLB", "selection": "洋基勝", "odds": 5.5},
    ]

    # Place ticket: 200 * 11.0 = 2,200 payout
    ticket = ticket_mgr.place_ticket(legs=legs, stake=200.0, total_odds=11.0)
    assert ticket["status"] == "OPEN"
    assert ticket["stake"] == 200.0
    assert ticket["potential_payout"] == 2200.0
    assert temp_war_chest.get_latest_balance() == 0.0

    # Settle ticket as WON
    settle_res = ticket_mgr.settle_ticket(ticket["ticket_id"], won=True)
    assert settle_res["won"] is True
    assert settle_res["payout"] == 2200.0
    assert settle_res["new_balance"] == 2200.0
