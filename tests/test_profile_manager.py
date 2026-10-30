#!/usr/bin/env python3
"""Tests for ProfileManager: creation, PIN protection, updating settings, and wallet isolation."""

import pytest
import sqlite3

from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID, PBKDF2_PREFIX, verify_pin_code
from core.wallet import WeeklyWalletManager
from core.ticket_recorder import TicketRecorder


def test_default_profile_initialization(tmp_path):
    db = tmp_path / "test_profiles.sqlite3"
    pm = ProfileManager(db_path=db)
    profiles = pm.list_profiles()
    assert len(profiles) == 1
    assert profiles[0]["id"] == DEFAULT_PROFILE_ID
    assert profiles[0]["name"] == "主帳號"
    assert profiles[0]["weekly_play_cap"] == 200.0
    assert pm.verify_pin(DEFAULT_PROFILE_ID, "0000") is True
    assert profiles[0]["pin_code"].startswith(PBKDF2_PREFIX)


def test_create_new_profile_and_pin_validation(tmp_path):
    db = tmp_path / "test_profiles.sqlite3"
    pm = ProfileManager(db_path=db)
    
    # Invalid PINs
    with pytest.raises(ValueError, match="PIN 碼必須為 4 位純數字"):
        pm.create_profile(name="小明", pin_code="123")
    with pytest.raises(ValueError, match="PIN 碼必須為 4 位純數字"):
        pm.create_profile(name="小明", pin_code="abcd")
    with pytest.raises(ValueError, match="PIN 碼必須為 4 位純數字"):
        pm.create_profile(name="小明", pin_code="12345")

    # Valid creation
    p2 = pm.create_profile(name="小明", weekly_play_cap=500.0, pin_code="8888")
    assert p2["name"] == "小明"
    assert p2["weekly_play_cap"] == 500.0
    assert pm.verify_pin(p2["id"], "8888") is True
    assert p2["pin_code"].startswith(PBKDF2_PREFIX)

    # Duplicate name rejection
    with pytest.raises(ValueError, match="已存在名為「小明」的玩家 Profile"):
        pm.create_profile(name="小明", pin_code="9999")

    profiles = pm.list_profiles()
    assert len(profiles) == 2


def test_update_profile_pin_protection(tmp_path):
    db = tmp_path / "test_profiles.sqlite3"
    pm = ProfileManager(db_path=db)
    p = pm.create_profile(name="阿倫", weekly_play_cap=300.0, pin_code="1234")
    pid = p["id"]

    # Wrong PIN
    with pytest.raises(ValueError, match="PIN 碼驗證失敗"):
        pm.update_profile(pid, current_pin="0000", new_name="倫哥")

    # Correct PIN updates name, weekly_play_cap, and pin
    updated = pm.update_profile(pid, current_pin="1234", new_name="倫哥", new_weekly_play_cap=600.0, new_pin_code="5678")
    assert updated["name"] == "倫哥"
    assert updated["weekly_play_cap"] == 600.0
    assert pm.verify_pin(pid, "5678") is True
    assert updated["pin_code"].startswith(PBKDF2_PREFIX)

    # Old PIN cannot be used anymore
    assert pm.verify_pin(pid, "1234") is False
    assert pm.verify_pin(pid, "5678") is True


def test_multi_user_wallet_and_prize_pool_isolation(tmp_path):
    db = tmp_path / "test_profiles.sqlite3"
    pm = ProfileManager(db_path=db)
    p_ming = pm.create_profile(name="小明", weekly_play_cap=300.0, pin_code="1111")
    
    wallet_default = WeeklyWalletManager(db_path=db, profile_id=DEFAULT_PROFILE_ID)
    wallet_ming = WeeklyWalletManager(db_path=db, profile_id=p_ming["id"])

    # Default profile gets 200 cap, Ming gets 300 cap
    assert wallet_default.get_status()["weekly_play_cap"] == 200.0
    assert wallet_ming.get_status()["weekly_play_cap"] == 300.0

    # User deposits are strictly isolated
    wallet_default.deposit_external(150.0)
    wallet_ming.deposit_external(250.0)

    assert wallet_default.get_status()["weekly_wallet_balance"] == 150.0
    assert wallet_ming.get_status()["weekly_wallet_balance"] == 250.0

    # Ming places a bet using his TicketRecorder
    rec_ming = TicketRecorder(wallet=wallet_ming)
    ticket_ming = rec_ming.place_ticket([{"league": "NBA"}], 50.0, 2.0)

    # Verify Ming's balance decreased, default was untouched
    assert wallet_ming.get_status()["weekly_wallet_balance"] == 200.0
    assert wallet_ming.get_status()["weekly_staked"] == 50.0
    assert wallet_default.get_status()["weekly_wallet_balance"] == 150.0
    assert wallet_default.get_status()["weekly_staked"] == 0.0

    # Ming settles ticket as WON: NT$ 100 goes into Ming's prize pool
    rec_ming.settle_ticket(ticket_ming["ticket_id"], won=True)
    assert wallet_ming.get_status()["prize_pool"] == 100.0
    assert wallet_default.get_status()["prize_pool"] == 0.0

    # Tickets list separation
    rec_default = TicketRecorder(wallet=wallet_default)
    assert len(rec_default.list_tickets()) == 0
    assert len(rec_ming.list_tickets()) == 1
    assert len(rec_default.list_tickets(profile_id="all")) == 1


def test_get_profile_by_name_and_verify_login(tmp_path):
    db = tmp_path / "test_profiles.sqlite3"
    pm = ProfileManager(db_path=db)
    pm.create_profile(name="志玲", weekly_play_cap=250.0, pin_code="5200")

    # Name lookup
    p = pm.get_profile_by_name("志玲")
    assert p is not None
    assert p["name"] == "志玲"
    assert p["weekly_play_cap"] == 250.0

    assert pm.get_profile_by_name("不存在") is None

    # Verify login by name
    ok, p_log, msg = pm.verify_login("志玲", "5200")
    assert ok is True
    assert p_log["name"] == "志玲"

    # Verify login with wrong PIN
    ok_fail, _, msg_fail = pm.verify_login("志玲", "9999")
    assert ok_fail is False
    assert "PIN 碼不正確" in msg_fail

    # Verify login with non-existent user
    ok_missing, _, msg_missing = pm.verify_login("老王", "1234")
    assert ok_missing is False
    assert "找不到玩家" in msg_missing

    # Verify login by ID
    ok_id, p_id, _ = pm.verify_login(p["id"], "5200")
    assert ok_id is True
    assert p_id["name"] == "志玲"


def test_line_user_binding_and_change_pin(tmp_path):
    db = tmp_path / "test_profiles.sqlite3"
    pm = ProfileManager(db_path=db)
    p = pm.create_profile(name="冠宇", weekly_play_cap=200.0, pin_code="8888")

    # Bind LINE user ID
    bound = pm.bind_line_user(p["id"], line_user_id="U1234567890abcdef", current_pin="8888")
    assert bound["line_user_id"] == "U1234567890abcdef"

    # Query by LINE user ID
    queried = pm.get_profile_by_line_user_id("U1234567890abcdef")
    assert queried is not None
    assert queried["id"] == p["id"]
    assert queried["name"] == "冠宇"

    # Change PIN
    updated = pm.change_pin(p["id"], current_pin="8888", new_pin="9999")
    assert pm.verify_pin(p["id"], "9999") is True
    assert updated["pin_code"].startswith(PBKDF2_PREFIX)

    # Unbind
    pm.unbind_line_user(p["id"], current_pin="9999")
    assert pm.get_profile_by_line_user_id("U1234567890abcdef") is None


def test_admin_player_management_and_deletion(tmp_path):
    db = tmp_path / "test_profiles.sqlite3"
    pm = ProfileManager(db_path=db)

    # Create test players
    p1 = pm.create_profile(name="測試員A", weekly_play_cap=200.0, pin_code="1234")
    p2 = pm.create_profile(name="測試員B", weekly_play_cap=300.0, pin_code="5678")

    # 1. Admin reset PIN for player A without needing player's old PIN
    reset_res = pm.admin_reset_pin(p1["id"], new_pin_code="0000")
    assert pm.verify_pin(p1["id"], "0000") is True
    assert pm.verify_pin(p1["id"], "1234") is False

    # 2. Admin update player settings directly
    upd_res = pm.admin_update_player(p2["id"], new_name="測試員B_改名", new_weekly_play_cap=500.0)
    assert upd_res["name"] == "測試員B_改名"
    assert upd_res["weekly_play_cap"] == 500.0

    # 3. Cannot delete default profile (Archie / 主帳號)
    with pytest.raises(ValueError, match="系統預設的「主帳號」不可被刪除"):
        pm.admin_delete_profile(DEFAULT_PROFILE_ID)

    # 4. Admin deletes player A
    del_ok = pm.admin_delete_profile(p1["id"])
    assert del_ok is True
    assert pm.get_profile(p1["id"]) is None

    # Verify only default and player B remain
    remaining = [p["name"] for p in pm.list_profiles()]
    assert "測試員A" not in remaining
    assert "測試員B_改名" in remaining
