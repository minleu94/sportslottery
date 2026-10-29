#!/usr/bin/env python3
"""Unit tests for Round Robin combination ticket recording and settlement."""

import json
from unittest.mock import MagicMock
import pytest
from core.round_robin import RoundRobinEngine
from core.ticket_recorder import TicketRecorder
from core.ticket_settlement import TicketSettlementEngine
from core.wallet import WeeklyWalletManager


def test_round_robin_settlement_one_miss_survival():
    legs = [
        {"selection": "隊伍A", "odds": 2.0},
        {"selection": "隊伍B", "odds": 2.0},
        {"selection": "隊伍C", "odds": 2.0},
        {"selection": "隊伍D", "odds": 2.0},
    ]
    # 4 串 11: contains 6 of 2-legs + 4 of 3-legs + 1 of 4-legs = 11 bets
    # Unit stake: 10 NTD -> Total stake = 110 NTD
    # Case: Leg 0, 1, 2 WIN, Leg 3 LOSE (3 of 4 win, 1 miss)
    legs_eval = [
        {"status": "WON", "effective_odds": 2.0, "reason": "FINAL"},
        {"status": "WON", "effective_odds": 2.0, "reason": "FINAL"},
        {"status": "WON", "effective_odds": 2.0, "reason": "FINAL"},
        {"status": "LOST", "effective_odds": 2.0, "reason": "FINAL"},
    ]

    res = RoundRobinEngine.evaluate_round_robin_settlement(
        legs=legs,
        combo_key="4_11",
        legs_eval=legs_eval,
        unit_stake=10.0,
        total_stake=110.0,
    )

    assert res["can_settle"] is True
    assert res["final_status"] == "WON"
    # Surviving bets:
    # 2-legs among (0,1,2): C(3,2) = 3 bets, each paying 10 * 2 * 2 = 40 NTD -> 120 NTD
    # 3-legs among (0,1,2): C(3,3) = 1 bet, paying 10 * 2 * 2 * 2 = 80 NTD -> 80 NTD
    # Total payout = 120 + 80 = 200 NTD!
    # Even though 1 leg was LOST, total payout is 200 NTD, which is greater than total stake 110 NTD (Net profit +90 NTD)!
    assert res["winning_sub_count"] == 4
    assert res["payout"] == 200.0
    assert res["net_profit"] == 90.0
    assert "🎉" in res["summary"]


def test_round_robin_ticket_settlement_integration(tmp_path):
    db_path = tmp_path / "wallet.db"
    wallet = WeeklyWalletManager(db_path)
    wallet.deposit_external(200.0)
    recorder = TicketRecorder(wallet)

    legs = [
        {"league": "MLB", "away_team": "洋基", "home_team": "紅襪", "market": "不讓分", "selection": "洋基勝", "odds": 2.0, "event_id": "1"},
        {"league": "NBA", "away_team": "湖人", "home_team": "勇士", "market": "不讓分", "selection": "湖人勝", "odds": 2.0, "event_id": "2"},
        {"league": "CPBL", "away_team": "兄弟", "home_team": "統一", "market": "不讓分", "selection": "兄弟勝", "odds": 2.0, "event_id": "3"},
    ]
    # 3 串 4: 3 bets of 2-legs + 1 bet of 3-legs = 4 bets
    # Unit stake 10 -> Total stake 40 NTD
    rr_notes = json.dumps({
        "type": "ROUND_ROBIN",
        "round_robin_spec": "3_4",
        "unit_stake": 10.0,
    })

    ticket = recorder.place_ticket(
        legs=legs,
        stake=40.0,
        total_odds=8.0,
        notes=rr_notes,
    )
    assert ticket["ticket_id"] is not None

    stored_ticket = recorder.list_tickets()[0]

    settler = TicketSettlementEngine(ticket_recorder=recorder)
    # Mock evaluate_leg: leg 0, 1 WON, leg 2 LOST
    settler.evaluate_leg = MagicMock(side_effect=[
        {"status": "WON", "effective_odds": 2.0, "reason": "W"},
        {"status": "WON", "effective_odds": 2.0, "reason": "W"},
        {"status": "LOST", "effective_odds": 2.0, "reason": "L"},
    ])

    eval_ticket = settler.evaluate_ticket(stored_ticket)
    assert eval_ticket["is_round_robin"] is True
    assert eval_ticket["can_settle"] is True
    assert eval_ticket["final_status"] == "WON"
    # Surviving: only 1 pair of (0,1) won -> 10 * 2 * 2 = 40 NTD!
    assert eval_ticket["payout"] == 40.0
