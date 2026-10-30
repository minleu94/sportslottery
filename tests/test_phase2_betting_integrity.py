"""Phase 2 comprehensive verification: Betting and data integrity tests.

Validates:
1. Idempotency Key retry semantics vs. intentional re-betting.
2. Unified validation policies: recommendation vs manual bookkeeping.
3. Service / Repository layer (no raw SQL in API route handlers).
4. Cross-user isolation and RBAC in ticket placement and settlement.
5. Transaction atomicity (no orphaned tickets on failure) and settlement protection.
"""

from __future__ import annotations

import ast
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from core.bet_validation import validate_manual_legs, validate_recommendation_legs
from core.betting_service import BettingService
from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID
from core.ticket_recorder import TicketRecorder
from core.wallet import WeeklyWalletManager
from integrations.common.models import TaiwanLeg
import server.api as api_module
from server.api import app, get_recorder, get_wallet


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch):
    """Set up isolated sqlite databases and monkeypatch get_wallet / get_recorder."""
    db_path = tmp_path / "sportslottery_phase2.db"
    prof_mgr = ProfileManager(db_path=db_path)

    monkeypatch.setattr("server.api.get_wallet", lambda profile_id="default": WeeklyWalletManager(db_path=db_path, profile_id=profile_id))
    monkeypatch.setattr("server.api.get_recorder", lambda profile_id="default": TicketRecorder(db_path=db_path, profile_id=profile_id))
    monkeypatch.setattr("server.api.get_betting_service", lambda profile_id="default": BettingService(db_path=db_path, profile_id=profile_id))
    monkeypatch.setattr("server.api._profile_mgr", prof_mgr)
    monkeypatch.setattr("core.profile_manager.DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr("core.wallet.DEFAULT_DB_PATH", db_path)

    return db_path, prof_mgr


def test_idempotency_retry_vs_deliberate_rebet(isolated_env):
    """Verify that same idempotency_key returns cached ticket without debiting again,

    while distinct or omitted keys allow deliberate identical re-bets.
    """
    db_path, prof_mgr = isolated_env
    client = TestClient(app)

    # Deposit initial funds to default
    wallet = WeeklyWalletManager(db_path=db_path, profile_id=DEFAULT_PROFILE_ID)
    wallet.deposit_external(200.0)

    # Login as default admin
    login_resp = client.post("/api/profiles/login", json={"identifier": "default", "pin_code": "0000"})
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    leg = {
        "event_id": "game-101",
        "sport": "baseball",
        "league": "CPBL",
        "home_team": "中信兄弟",
        "away_team": "統一獅",
        "market": "不讓分",
        "selection": "中信兄弟",
        "taiwan_odds": 1.75,
    }

    # 1. Place first bet with client-generated idempotency_key
    custom_key = "idemp-client-key-1"
    req_payload = {
        "profile_id": "default",
        "legs": [leg],
        "stake": 50.0,
        "placed_odds": 1.75,
        "idempotency_key": custom_key,
    }
    resp1 = client.post("/api/tickets/place", json=req_payload, headers=headers)
    assert resp1.status_code == 200
    ticket1 = resp1.json()["ticket"]
    assert wallet.get_status()["weekly_staked"] == 50.0

    # 2. Resend exact same request with same idempotency_key (simulating network retry)
    resp2 = client.post("/api/tickets/place", json=req_payload, headers=headers)
    assert resp2.status_code == 200
    ticket2 = resp2.json()["ticket"]
    assert ticket2["ticket_id"] == ticket1["ticket_id"]
    # Crucial: balance/staked must NOT have changed!
    assert wallet.get_status()["weekly_staked"] == 50.0

    # 3. Deliberately place identical bet again using a NEW idempotency key
    req_payload_new_key = dict(req_payload)
    req_payload_new_key["idempotency_key"] = "idemp-client-key-2"
    resp3 = client.post("/api/tickets/place", json=req_payload_new_key, headers=headers)
    assert resp3.status_code == 200
    ticket3 = resp3.json()["ticket"]
    assert ticket3["ticket_id"] != ticket1["ticket_id"]
    assert wallet.get_status()["weekly_staked"] == 100.0

    # 4. Attempt to reuse custom_key with different payload -> must fail with 400
    conflict_payload = dict(req_payload)
    conflict_payload["stake"] = 30.0  # different stake
    resp_conflict = client.post("/api/tickets/place", json=conflict_payload, headers=headers)
    assert resp_conflict.status_code == 400
    assert "idempotency_key 已用於不同下注內容" in resp_conflict.json()["detail"]


def test_unified_validation_policies(isolated_env):
    """Verify recommendation policy requires live unstarted games, while manual

    bookkeeping accepts historical matches but enforces odds, leg count, and selections.
    """
    db_path, prof_mgr = isolated_env
    prof_mgr.admin_update_player("default", new_weekly_play_cap=1000.0)
    recorder = TicketRecorder(db_path=db_path, profile_id="default")
    wallet = WeeklyWalletManager(db_path=db_path, profile_id="default")
    wallet.deposit_external(500.0)

    now = datetime.now(timezone.utc)

    # --- Policy A: Recommendation ---
    # 1. Stale / Expired odds rejected
    stale_leg = {
        "event_id": "rec-1",
        "sport": "baseball",
        "league": "MLB",
        "home_team": "洋基",
        "away_team": "紅襪",
        "market": "不讓分",
        "selection": "洋基",
        "taiwan_odds": 1.90,
        "start_time_utc": (now + timedelta(hours=2)).isoformat(),
        "odds_scraped_at": (now - timedelta(minutes=30)).isoformat(),  # > 15 min
        "odds_status": "LIVE",
    }
    with pytest.raises(ValueError, match="盤口資料已過期"):
        recorder.place_ticket(
            legs=[stale_leg],
            stake=50.0,
            total_odds=1.90,
            entry_mode="recommendation",
        )

    # 2. Already started game rejected
    started_leg = {
        "event_id": "rec-2",
        "sport": "baseball",
        "league": "MLB",
        "home_team": "洋基",
        "away_team": "紅襪",
        "market": "不讓分",
        "selection": "洋基",
        "taiwan_odds": 1.90,
        "start_time_utc": (now - timedelta(minutes=10)).isoformat(),  # Started
        "odds_scraped_at": now.isoformat(),
        "odds_status": "LIVE",
    }
    with pytest.raises(ValueError, match="賽事已開賽"):
        recorder.place_ticket(
            legs=[started_leg],
            stake=50.0,
            total_odds=1.90,
            entry_mode="recommendation",
        )

    # 3. Valid recommendation accepted and tagged
    valid_rec_leg = {
        "event_id": "rec-3",
        "sport": "baseball",
        "league": "MLB",
        "home_team": "洋基",
        "away_team": "紅襪",
        "market": "不讓分",
        "selection": "洋基",
        "taiwan_odds": 1.90,
        "start_time_utc": (now + timedelta(hours=2)).isoformat(),
        "odds_scraped_at": now.isoformat(),
        "odds_status": "LIVE",
    }
    rec_ticket = recorder.place_ticket(
        legs=[valid_rec_leg],
        stake=50.0,
        total_odds=1.90,
        entry_mode="recommendation",
    )
    assert rec_ticket["status"] == "OPEN"
    saved_legs = rec_ticket["legs"]
    assert saved_legs[0]["data_source"] == "verified_recommendation"

    # --- Policy B: Manual Bookkeeping ---
    # 1. Historical start time accepted for kiosk bookkeeping
    historical_leg = {
        "event_id": "manual-hist-1",
        "sport": "basketball",
        "league": "NBA",
        "home_team": "湖人",
        "away_team": "勇士",
        "market": "不讓分",
        "selection": "湖人",
        "taiwan_odds": 1.80,
        "start_time_utc": (now - timedelta(hours=5)).isoformat(),  # past match
    }
    manual_ticket = recorder.place_ticket(
        legs=[historical_leg],
        stake=50.0,
        total_odds=1.80,
        entry_mode="manual",
    )
    assert manual_ticket["status"] == "OPEN"
    assert manual_ticket["legs"][0]["data_source"] == "manual_entry"

    # Client forging data_source: "verified_recommendation" on a manual ticket is overridden
    forged_leg = dict(historical_leg)
    forged_leg["data_source"] = "verified_recommendation"
    forged_ticket = recorder.place_ticket(
        legs=[forged_leg],
        stake=50.0,
        total_odds=1.80,
        entry_mode="manual",
    )
    assert forged_ticket["legs"][0]["data_source"] == "manual_entry"

    # 2. Invalid odds rejected in manual bookkeeping
    invalid_odds_leg = dict(historical_leg)
    invalid_odds_leg["taiwan_odds"] = 0.95
    with pytest.raises(ValueError, match="必須大於 1.0"):
        recorder.place_ticket(
            legs=[invalid_odds_leg],
            stake=50.0,
            total_odds=1.80,
            entry_mode="manual",
        )

    # 3. Empty selection/market rejected
    empty_sel_leg = {
        "event_id": "manual-bad",
        "sport": "baseball",
        "taiwan_odds": 1.80,
    }
    with pytest.raises(ValueError, match="缺少投注選項或玩法資訊"):
        recorder.place_ticket(
            legs=[empty_sel_leg],
            stake=50.0,
            total_odds=1.80,
            entry_mode="manual",
        )

    # 4. More than 8 legs rejected
    too_many_legs = [dict(historical_leg, event_id=f"g-{i}") for i in range(9)]
    with pytest.raises(ValueError, match="不可超過 8 關"):
        recorder.place_ticket(
            legs=too_many_legs,
            stake=50.0,
            total_odds=100.0,
            entry_mode="manual",
        )


def test_repository_and_service_layer_no_raw_sql_in_api(isolated_env):
    """Verify TicketRecorder get_ticket/get_ticket_owner methods, BettingService

    delegation, and that server/api.py contains zero direct raw SQL queries.
    """
    db_path, prof_mgr = isolated_env
    prof = prof_mgr.create_profile("Player 1", weekly_play_cap=500.0, pin_code="1234")
    player_id = prof["id"]

    recorder = TicketRecorder(db_path=db_path, profile_id=player_id)
    wallet = WeeklyWalletManager(db_path=db_path, profile_id=player_id)
    wallet.deposit_external(300.0)

    service = BettingService(db_path=db_path, profile_id=player_id)
    leg = {
        "sport": "baseball",
        "league": "CPBL",
        "home_team": "中信兄弟",
        "away_team": "富邦悍將",
        "market": "不讓分",
        "selection": "中信兄弟",
        "taiwan_odds": 1.65,
    }

    # Place through service
    ticket = service.place_ticket(
        legs=[leg],
        stake=100.0,
        total_odds=1.65,
        entry_mode="manual",
    )
    ticket_id = ticket["ticket_id"]

    # Verify repository methods
    fetched = recorder.get_ticket(ticket_id)
    assert fetched is not None
    assert fetched["ticket_id"] == ticket_id
    assert fetched["stake"] == 100.0
    assert recorder.get_ticket_owner(ticket_id) == player_id

    # Non-existent ticket returns None
    assert recorder.get_ticket("non-existent-uuid") is None
    assert recorder.get_ticket_owner("non-existent-uuid") is None

    # AST / Source scan on server/api.py: Ensure NO raw SQL statements exist
    api_path = Path("server/api.py").resolve()
    with open(api_path, "r", encoding="utf-8") as f:
        api_source = f.read()

    # Parse AST to inspect route functions
    tree = ast.parse(api_source, filename=str(api_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Check body for execute() calls with raw SQL strings
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                    if sub.func.attr == "execute":
                        # If first arg is a string literal containing SQL
                        if sub.args and isinstance(sub.args[0], ast.Constant) and isinstance(sub.args[0].value, str):
                            sql = sub.args[0].value.upper()
                            assert not any(kw in sql for kw in ["SELECT ", "INSERT ", "UPDATE ", "DELETE "]), (
                                f"Found raw SQL in route handler {node.name}: {sql}"
                            )


def test_cross_user_isolation_and_rbac(isolated_env):
    """Verify that User A cannot place tickets for User B or settle User B's

    tickets (403 Forbidden), but Admin can settle any user's ticket.
    """
    db_path, prof_mgr = isolated_env
    client = TestClient(app)

    # 1. Create two users: user_a, user_b
    prof_a = prof_mgr.create_profile("User Alice", weekly_play_cap=500.0, pin_code="1111")
    prof_b = prof_mgr.create_profile("User Bob", weekly_play_cap=500.0, pin_code="2222")
    user_a_id = prof_a["id"]
    user_b_id = prof_b["id"]

    # Deposit funds for both
    WeeklyWalletManager(db_path=db_path, profile_id=user_a_id).deposit_external(200.0)
    WeeklyWalletManager(db_path=db_path, profile_id=user_b_id).deposit_external(200.0)

    # Login user_a
    token_a = client.post("/api/profiles/login", json={"identifier": user_a_id, "pin_code": "1111"}).json()["token"]
    # Login user_b
    token_b = client.post("/api/profiles/login", json={"identifier": user_b_id, "pin_code": "2222"}).json()["token"]
    # Login admin (default)
    token_admin = client.post("/api/profiles/login", json={"identifier": "default", "pin_code": "0000"}).json()["token"]

    leg = {
        "sport": "baseball",
        "league": "CPBL",
        "home_team": "中信兄弟",
        "away_team": "味全龍",
        "market": "不讓分",
        "selection": "中信兄弟",
        "taiwan_odds": 2.0,
    }

    # 2. User A tries to place a ticket under User B's profile_id -> 403 Forbidden
    resp_cross_place = client.post(
        "/api/tickets/place",
        json={"profile_id": user_b_id, "legs": [leg], "stake": 50.0, "placed_odds": 2.0},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_cross_place.status_code == 403

    # 3. User A places a ticket for User A
    resp_a_place = client.post(
        "/api/tickets/place",
        json={"profile_id": user_a_id, "legs": [leg], "stake": 50.0, "placed_odds": 2.0},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_a_place.status_code == 200
    ticket_a_id = resp_a_place.json()["ticket"]["ticket_id"]

    # 4. User B tries to settle User A's ticket -> 403 Forbidden
    resp_cross_settle = client.post(
        "/api/tickets/settle",
        json={"ticket_id": ticket_a_id, "result": "WON"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_cross_settle.status_code == 403

    # 5. Admin settles User A's ticket -> 200 OK
    resp_admin_settle = client.post(
        "/api/tickets/settle",
        json={"ticket_id": ticket_a_id, "result": "WON"},
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert resp_admin_settle.status_code == 200
    assert resp_admin_settle.json()["result"]["status"] == "WON"

    # Check that Alice's wallet received the winning payout (50 * 2 = 100), NOT Admin's wallet
    wallet_a = WeeklyWalletManager(db_path=db_path, profile_id=user_a_id)
    wallet_admin = WeeklyWalletManager(db_path=db_path, profile_id="default")
    assert wallet_a.get_status()["prize_pool"] == 100.0
    assert wallet_admin.get_status()["prize_pool"] == 0.0


def test_transaction_atomicity_and_double_settlement(isolated_env):
    """Verify transaction atomicity on insufficient balance (no orphan ticket)

    and rejection of double settlement.
    """
    db_path, prof_mgr = isolated_env
    prof = prof_mgr.create_profile("User Charlie", weekly_play_cap=500.0, pin_code="3333")
    user_c_id = prof["id"]

    recorder = TicketRecorder(db_path=db_path, profile_id=user_c_id)
    wallet = WeeklyWalletManager(db_path=db_path, profile_id=user_c_id)
    # Deposit only 30
    wallet.deposit_external(30.0)

    leg = {
        "sport": "baseball",
        "league": "CPBL",
        "home_team": "中信兄弟",
        "away_team": "味全龍",
        "market": "不讓分",
        "selection": "中信兄弟",
        "taiwan_odds": 2.0,
    }

    # 1. Place bet of 100 (exceeds 30 balance)
    with pytest.raises(ValueError, match="預算不足"):
        recorder.place_ticket(
            legs=[leg],
            stake=100.0,
            total_odds=2.0,
            entry_mode="manual",
        )

    # Ensure NO orphaned ticket exists in the database
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT count(*) FROM tickets WHERE profile_id=?", (user_c_id,)).fetchone()[0]
    conn.close()
    assert count == 0, "Failed transaction must not leave an orphaned ticket row!"

    # 2. Deposit enough, place ticket, and verify double settlement protection
    wallet.deposit_external(100.0)
    ticket = recorder.place_ticket(
        legs=[leg],
        stake=50.0,
        total_odds=2.0,
        entry_mode="manual",
    )
    tid = ticket["ticket_id"]

    # First settlement succeeds
    res1 = recorder.settle_ticket(tid, won=True)
    assert res1["status"] == "WON"
    assert res1["payout"] == 100.0

    # Second settlement fails
    with pytest.raises(ValueError, match="注單已結算.*不可重複結算"):
        recorder.settle_ticket(tid, won=True)
