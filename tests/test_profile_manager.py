#!/usr/bin/env python3
"""Tests for ProfileManager: creation, PIN protection, updating settings, and wallet isolation."""

import pytest
import sqlite3

from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID
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
    assert profiles[0]["pin_code"] == "0000"


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
    assert p2["pin_code"] == "8888"

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
    assert updated["pin_code"] == "5678"

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
