from concurrent.futures import ThreadPoolExecutor
from datetime import date
import sqlite3

import pytest

from core.ticket_recorder import TicketRecorder
from core.wallet import WeeklyWalletManager
import core.wallet as wallet_module


def setup_wallet(tmp_path, amount=200):
    db = tmp_path / "wallet.sqlite3"
    wallet = WeeklyWalletManager(db)
    wallet.deposit_external(amount)
    return db, wallet, TicketRecorder(wallet=wallet)


def test_ticket_insert_failure_rolls_back_stake_and_ledger(tmp_path):
    db, wallet, recorder = setup_wallet(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TRIGGER fail_ticket_insert BEFORE INSERT ON tickets BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        recorder.place_ticket([{"league": "MLB"}], 25, 2)
    status = wallet.get_status()
    assert status["weekly_wallet_balance"] == 200
    assert status["weekly_staked"] == 0
    assert [x for x in wallet.get_ledger_history() if x["event_type"] == "BET_STAKE"] == []
    assert recorder.list_tickets() == []


def test_settlement_update_failure_rolls_back_payout(tmp_path):
    db, wallet, recorder = setup_wallet(tmp_path)
    ticket = recorder.place_ticket([{"league": "MLB"}], 25, 2)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TRIGGER fail_ticket_settlement BEFORE UPDATE OF status ON tickets BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        recorder.settle_ticket(ticket["ticket_id"], won=True)
    assert recorder.list_tickets()[0]["status"] == "OPEN"
    assert wallet.get_status()["prize_pool"] == 0
    assert [x for x in wallet.get_ledger_history() if x["event_type"] == "BET_PAYOUT"] == []


def test_retry_and_idempotency_do_not_duplicate_accounting(tmp_path):
    _, wallet, recorder = setup_wallet(tmp_path)
    first = recorder.place_ticket([{"league": "MLB"}], 30, 2, idempotency_key="submit-1")
    repeated = recorder.place_ticket([{"league": "MLB"}], 30, 2, idempotency_key="submit-1")
    assert repeated["ticket_id"] == first["ticket_id"]
    assert wallet.get_status()["weekly_wallet_balance"] == 170
    settled = recorder.settle_ticket(first["ticket_id"], won=True)
    assert settled["payout"] == 60
    with pytest.raises(ValueError, match="已結算"):
        recorder.settle_ticket(first["ticket_id"], won=True)
    assert wallet.get_status()["prize_pool"] == 60
    assert len([x for x in wallet.get_ledger_history() if x["event_type"] == "BET_PAYOUT"]) == 1


def test_idempotency_key_rejects_different_bet_payload(tmp_path):
    _, wallet, recorder = setup_wallet(tmp_path)
    first = recorder.place_ticket([{"event_id": "e1", "selection": "home", "market": "不讓分"}], 30, 2, idempotency_key="same-key")
    # Refreshed timestamp and price metadata is allowed for the same business bet.
    again = recorder.place_ticket([{"event_id": "e1", "selection": "home", "market": "不讓分", "odds_scraped_at": "refreshed"}], 30, 2, idempotency_key="same-key")
    assert again["ticket_id"] == first["ticket_id"]
    for stake, odds, legs in (
        (31, 2, [{"event_id": "e1", "selection": "home", "market": "不讓分"}]),
        (30, 3, [{"event_id": "e1", "selection": "home", "market": "不讓分"}]),
        (30, 2, [{"event_id": "e2", "selection": "home", "market": "不讓分"}]),
    ):
        with pytest.raises(ValueError, match="不同下注內容"):
            recorder.place_ticket(legs, stake, odds, idempotency_key="same-key")
    assert wallet.get_status()["weekly_wallet_balance"] == 170


def test_concurrent_stakes_cannot_exceed_weekly_budget(tmp_path):
    _, wallet, recorder = setup_wallet(tmp_path)

    def place(i):
        try:
            recorder.place_ticket([{"league": "NBA"}], 150, 2, idempotency_key=f"concurrent-{i}")
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(place, (1, 2)))
    assert sum(outcomes) == 1
    status = wallet.get_status()
    assert status["weekly_staked"] == 150
    assert status["weekly_wallet_balance"] == 50
    assert len([x for x in wallet.get_ledger_history() if x["event_type"] == "BET_STAKE"]) == 1


def test_void_refund_and_finite_positive_amount_validation(tmp_path):
    _, wallet, recorder = setup_wallet(tmp_path)
    ticket = recorder.place_ticket([{"league": "MLB"}], 20, 3)
    result = recorder.settle_ticket(ticket["ticket_id"], won=False, is_void=True)
    assert result["status"] == "VOID"
    assert result["payout"] == 20
    assert wallet.get_status()["prize_pool"] == 20
    lost = recorder.place_ticket([{"league": "MLB"}], 10, 2)
    with pytest.raises(ValueError, match="輸單不能"):
        recorder.settle_ticket(lost["ticket_id"], won=False, custom_payout=1)
    with pytest.raises(ValueError, match="VOID 只能"):
        recorder.settle_ticket(lost["ticket_id"], won=False, is_void=True, custom_payout=11)
    assert recorder.settle_ticket(lost["ticket_id"], won=True, custom_payout=15)["payout"] == 15
    for amount in (float("nan"), float("inf"), 0.001, -1):
        with pytest.raises(ValueError):
            wallet.deposit_external(amount)
    for odds in (1, float("inf"), 1e308):
        with pytest.raises(ValueError):
            recorder.place_ticket([{"league": "MLB"}], 200, odds)


def test_week_rollover_happens_under_lock_and_respects_reserve(tmp_path, monkeypatch):
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 4)

    monkeypatch.setattr(wallet_module, "date", FrozenDate)
    db = tmp_path / "wallet.sqlite3"
    wallet = WeeklyWalletManager(db)
    wallet.deposit_external(200)
    wallet.stake_bet(200, "old-week-ticket")
    wallet.credit_winnings(75, "old-week-ticket")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE wallet_state SET current_week='2026-W52'")
    wallet._ensure_week_initialized()
    status = wallet.get_status()
    assert status["current_week"] == "2027-W01"
    assert status["weekly_wallet_balance"] == 75
    assert status["weekly_staked"] == 0
    assert status["prize_pool"] == 0
    assert wallet.deposit_external(125)["weekly_external_deposited"] == 125
    with pytest.raises(ValueError):
        wallet.deposit_external(1)


def test_wallet_and_ticket_database_must_match(tmp_path):
    wallet = WeeklyWalletManager(tmp_path / "wallet.sqlite3")
    with pytest.raises(ValueError, match="同一個 SQLite"):
        TicketRecorder(wallet=wallet, db_path=tmp_path / "other.sqlite3")


def test_old_database_migrates_without_losing_ledger_or_tickets(tmp_path):
    from core.wallet import get_current_iso_week
    cur_week = get_current_iso_week()
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE wallet_state (id INTEGER PRIMARY KEY, current_week TEXT NOT NULL, wallet_balance REAL NOT NULL, weekly_staked REAL NOT NULL, prize_pool REAL NOT NULL, weekly_external_deposited REAL NOT NULL, updated_at TEXT NOT NULL)")
        conn.execute(f"INSERT INTO wallet_state VALUES (1, '{cur_week}', 40, 10, 7, 50, 'legacy')")
        conn.execute("CREATE TABLE ledger (id TEXT PRIMARY KEY,timestamp TEXT NOT NULL,week_str TEXT NOT NULL,event_type TEXT NOT NULL,amount REAL NOT NULL,wallet_balance_after REAL NOT NULL,prize_pool_after REAL NOT NULL,notes TEXT NOT NULL DEFAULT '')")
        conn.execute(f"INSERT INTO ledger VALUES ('old-ledger','legacy','{cur_week}','EXTERNAL_DEPOSIT',50,40,7,'keep')")
        conn.execute("CREATE TABLE tickets (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,week_str TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('OPEN','WON','LOST','VOID')),stake REAL NOT NULL,total_odds REAL NOT NULL,potential_payout REAL NOT NULL,actual_payout REAL NOT NULL DEFAULT 0, sports_summary TEXT NOT NULL DEFAULT '',legs_json TEXT NOT NULL DEFAULT '[]',notes TEXT NOT NULL DEFAULT '')")
        conn.execute(f"INSERT INTO tickets (id,created_at,week_str,status,stake,total_odds,potential_payout,actual_payout) VALUES ('old-ticket','legacy','{cur_week}','OPEN',10,2,20,0)")
    wallet = WeeklyWalletManager(db)
    recorder = TicketRecorder(wallet=wallet)
    status = wallet.get_status()
    assert status["weekly_wallet_balance"] == 40
    assert status["prize_pool"] == 7
    assert wallet.get_ledger_history()[0]["id"] == "old-ledger"
    old = recorder.list_tickets()[0]
    assert old["id"] == "old-ticket"
    assert old["entry_mode"] == "manual"
    settled = recorder.settle_ticket("old-ticket", won=True)
    assert settled["status"] == "WON"


def test_recommendation_validation_is_strict_but_manual_history_is_allowed(tmp_path):
    _, wallet, recorder = setup_wallet(tmp_path)
    stale_leg = {"event_id": "e1", "league": "MLB", "odds": 2.0, "selection": "主隊"}
    with pytest.raises(ValueError, match="無法記錄"):
        recorder.place_ticket([stale_leg], 10, 2, entry_mode="recommendation")
    assert wallet.get_status()["weekly_wallet_balance"] == 200
    manual = recorder.place_ticket([stale_leg], 10, 2, entry_mode="manual")
    assert manual["entry_mode"] == "manual"
