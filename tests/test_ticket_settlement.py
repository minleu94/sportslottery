"""Unit and integration tests for Automated User Ticket Settlement Engine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.settlement_engine import SettlementEngine
from core.ticket_recorder import TicketRecorder
from core.ticket_settlement import TicketSettlementEngine
from core.wallet import WeeklyWalletManager


@pytest.fixture
def mock_settlement_engine():
    engine = MagicMock(spec=SettlementEngine)
    engine.fetch_results = MagicMock(return_value=[])
    engine.match_result_game = MagicMock(return_value=None)
    return engine


def test_evaluate_leg_not_started(mock_settlement_engine):
    ts_engine = TicketSettlementEngine(settlement_engine=mock_settlement_engine)
    leg = {
        "sport": "baseball",
        "league": "MLB",
        "away_team": "波士頓紅襪",
        "home_team": "紐約洋基",
        "market": "讓分",
        "selection": "洋基 -1.5",
        "odds": 1.85,
        "start_time_utc": "2099-10-23T19:00:00Z",
    }
    mock_settlement_engine.match_result_game.return_value = None

    res = ts_engine.evaluate_leg(leg)
    assert res["status"] == "NOT_STARTED"
    assert "尚未開賽" in res["reason"]
    assert res["effective_odds"] == 1.85


def test_evaluate_leg_won_and_lost(mock_settlement_engine):
    ts_engine = TicketSettlementEngine(settlement_engine=mock_settlement_engine)
    leg = {
        "sport": "baseball",
        "league": "MLB",
        "away_team": "波士頓紅襪",
        "home_team": "紐約洋基",
        "market": "讓分",
        "selection": "洋基 -1.5",
        "line": -1.5,
        "side": "主",
        "odds": 1.90,
    }

    # Case A: Won
    mock_game_won = {
        "status": "FINAL",
        "away_score": 2,
        "home_score": 6,
        "final_score": "2:6",
        "game_status": "Final",
        "provider": "MLB_STATS_API",
    }
    mock_settlement_engine.match_result_game.return_value = mock_game_won
    mock_settlement_engine.evaluate_leg_settlement.return_value = MagicMock(
        status="WON", reason="洋基淨勝 4 分，覆蓋讓分 -1.5 門檻", effective_odds=1.90
    )

    res_won = ts_engine.evaluate_leg(leg, [mock_game_won])
    assert res_won["status"] == "WON"
    assert res_won["effective_odds"] == 1.90
    assert res_won["score"] == "2:6"

    # Case B: Lost
    mock_game_lost = {
        "status": "FINAL",
        "away_score": 5,
        "home_score": 4,
        "final_score": "5:4",
        "game_status": "Final",
    }
    mock_settlement_engine.match_result_game.return_value = mock_game_lost
    mock_settlement_engine.evaluate_leg_settlement.return_value = MagicMock(
        status="LOST", reason="洋基落後 1 分，未過讓分", effective_odds=0.0
    )

    res_lost = ts_engine.evaluate_leg(leg, [mock_game_lost])
    assert res_lost["status"] == "LOST"
    assert res_lost["effective_odds"] == 0.0


def test_evaluate_leg_void_called_game_or_cancelled(mock_settlement_engine):
    ts_engine = TicketSettlementEngine(settlement_engine=mock_settlement_engine)
    leg = {
        "sport": "baseball",
        "league": "MLB",
        "away_team": "波士頓紅襪",
        "home_team": "紐約洋基",
        "market": "讓分",
        "selection": "洋基 -1.5",
        "odds": 1.85,
    }

    mock_game_cancel = {
        "status": "VOID",
        "provider_status": "Postponed / Rain Out",
        "away_score": None,
        "home_score": None,
    }
    mock_settlement_engine.match_result_game.return_value = mock_game_cancel

    res = ts_engine.evaluate_leg(leg, [mock_game_cancel])
    assert res["status"] == "VOID"
    assert res["effective_odds"] == 1.0


def test_evaluate_ticket_full_win():
    ts_engine = TicketSettlementEngine()
    ts_engine.evaluate_leg = MagicMock(side_effect=[
        {"status": "WON", "effective_odds": 2.0, "score": "5:2", "reason": "過關"},
        {"status": "WON", "effective_odds": 1.8, "score": "3:1", "reason": "過關"},
    ])

    ticket = {
        "id": "t1",
        "stake": 100.0,
        "total_odds": 3.6,
        "potential_payout": 360.0,
        "legs": [{"selection": "A"}, {"selection": "B"}],
    }

    eval_res = ts_engine.evaluate_ticket(ticket)
    assert eval_res["can_settle"] is True
    assert eval_res["final_status"] == "WON"
    assert eval_res["recalculated_odds"] == 3.6
    assert eval_res["payout"] == 360.0
    assert eval_res["won_count"] == 2


def test_evaluate_ticket_one_lost_fails_parlay():
    ts_engine = TicketSettlementEngine()
    ts_engine.evaluate_leg = MagicMock(side_effect=[
        {"status": "WON", "effective_odds": 2.0, "score": "5:2", "reason": "過關"},
        {"status": "LOST", "effective_odds": 0.0, "score": "1:3", "reason": "未過關"},
        {"status": "PENDING", "effective_odds": 1.5, "score": None, "reason": "未完成"},
    ])

    ticket = {
        "id": "t2",
        "stake": 50.0,
        "total_odds": 6.0,
        "legs": [{"selection": "A"}, {"selection": "B"}, {"selection": "C"}],
    }

    eval_res = ts_engine.evaluate_ticket(ticket)
    assert eval_res["can_settle"] is True
    assert eval_res["final_status"] == "LOST"
    assert eval_res["payout"] == 0.0
    assert "未過關" in eval_res["summary"]


def test_evaluate_ticket_taiwan_void_rule_recalculation():
    """Taiwan rule: void leg multiplier becomes 1.0."""
    ts_engine = TicketSettlementEngine()
    ts_engine.evaluate_leg = MagicMock(side_effect=[
        {"status": "WON", "effective_odds": 2.0, "score": "5:2", "reason": "過關"},
        {"status": "VOID", "effective_odds": 1.0, "score": None, "reason": "因雨延賽退盤"},
    ])

    ticket = {
        "id": "t3",
        "stake": 100.0,
        "total_odds": 3.6,  # Originally 2.0 * 1.8 = 3.6
        "legs": [{"selection": "A"}, {"selection": "B"}],
    }

    eval_res = ts_engine.evaluate_ticket(ticket)
    assert eval_res["can_settle"] is True
    assert eval_res["final_status"] == "WON"
    assert eval_res["recalculated_odds"] == 2.0  # 2.0 * 1.0
    assert eval_res["payout"] == 200.0  # 100 * 2.0


def test_auto_settle_open_tickets_end_to_end(tmp_path: Path):
    """Integration test with temporary SQLite database and TicketRecorder."""
    db_file = tmp_path / "wallet_settle_test.db"
    wallet = WeeklyWalletManager(db_path=db_file)
    wallet.deposit_external(200.0)
    recorder = TicketRecorder(wallet=wallet, db_path=db_file)

    # Place an open ticket
    legs = [
        {
            "sport": "baseball",
            "league": "MLB",
            "away_team": "波士頓紅襪",
            "home_team": "紐約洋基",
            "market": "讓分",
            "selection": "洋基 -1.5",
            "odds": 2.0,
            "taiwan_odds": 2.0,
        },
        {
            "sport": "basketball",
            "league": "NBA",
            "away_team": "湖人",
            "home_team": "勇士",
            "market": "不讓分",
            "selection": "勇士 不讓分勝",
            "odds": 1.8,
            "taiwan_odds": 1.8,
        },
    ]

    placed = recorder.place_ticket(
        legs=legs,
        stake=20.0,
        total_odds=3.6,
        notes="測試自動結算注單",
    )
    tid = placed["ticket_id"]

    # Initial checks
    open_tickets = recorder.list_tickets(status_filter="OPEN")
    assert len(open_tickets) == 1
    assert open_tickets[0]["id"] == tid
    assert wallet.get_status()["prize_pool"] == 0.0

    # Setup TicketSettlementEngine with mocked leg evaluations
    ts_engine = TicketSettlementEngine(ticket_recorder=recorder)
    ts_engine.evaluate_leg = MagicMock(side_effect=[
        {"status": "WON", "effective_odds": 2.0, "score": "2:6", "reason": "洋基過關"},
        {"status": "WON", "effective_odds": 1.8, "score": "110:115", "reason": "勇士勝出"},
    ])

    # Run auto settlement
    report = ts_engine.auto_settle_open_tickets(dry_run=False)

    assert report["total_open_checked"] == 1
    assert report["settled_won"] == 1
    assert report["settled_lost"] == 0
    assert report["total_payout_credited"] == 72.0  # 20 * 3.6

    # Verify wallet prize pool has received winnings
    wallet_stat = wallet.get_status()
    assert wallet_stat["prize_pool"] == 72.0

    # Verify ticket status is now WON
    settled_ticket = recorder.list_tickets()[0]
    assert settled_ticket["id"] == tid
    assert settled_ticket["status"] == "WON"
    assert settled_ticket["actual_payout"] == 72.0
    assert settled_ticket["net_profit"] == 52.0

    # Second run should have nothing to settle
    report2 = ts_engine.auto_settle_open_tickets(dry_run=False)
    assert report2["total_open_checked"] == 0
    assert report2["settled_won"] == 0
