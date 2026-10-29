#!/usr/bin/env python3
"""Unit tests for LINE Bot Notification Engine."""

import json
from unittest.mock import MagicMock
import pytest
from core.line_notifier import LineNotifier


def test_line_notifier_unconfigured_safely_handles_push(tmp_path):
    cfg_file = tmp_path / "line_notifier.yaml"
    notifier = LineNotifier(config_path=cfg_file)
    assert not notifier.is_configured()

    res = notifier.send_push_message("Test message")
    assert not res["success"]
    assert res["error"] == "LINE_NOT_CONFIGURED"


def test_line_notifier_persists_config(tmp_path):
    cfg_file = tmp_path / "line_notifier.yaml"
    notifier = LineNotifier(config_path=cfg_file)
    notifier.save_config({
        "enabled": True,
        "channel_access_token": "test-token-123",
        "user_id": "U1234567890abcdef",
    })

    assert notifier.is_configured()
    # Re-instantiate from disk
    notifier2 = LineNotifier(config_path=cfg_file)
    assert notifier2.is_configured()
    assert notifier2.config["channel_access_token"] == "test-token-123"
    assert notifier2.config["user_id"] == "U1234567890abcdef"


def test_line_notifier_successful_push_mocked(tmp_path):
    cfg_file = tmp_path / "line_notifier.yaml"
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_session.post.return_value = mock_resp

    notifier = LineNotifier(config_path=cfg_file, session=mock_session)
    notifier.save_config({
        "enabled": True,
        "channel_access_token": "token-xyz",
        "user_id": "U999",
    })

    res = notifier.send_push_message("Hello from test!")
    assert res["success"] is True
    assert res["status_code"] == 200

    # Verify post payload
    call_args = mock_session.post.call_args
    assert call_args[0][0] == "https://api.line.me/v2/bot/message/push"
    headers = call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer token-xyz"
    json_data = call_args[1]["json"]
    assert json_data["to"] == "U999"
    assert json_data["messages"][0]["text"] == "Hello from test!"


def test_line_notifier_steam_drop_alert_format(tmp_path):
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_session.post.return_value = mock_resp

    notifier = LineNotifier(config_path=tmp_path / "line.yaml", session=mock_session)
    notifier.save_config({
        "enabled": True,
        "channel_access_token": "tok",
        "user_id": "U123",
    })

    notifier.notify_steam_drop(
        league="MLB",
        match_title="紐約洋基 vs 波士頓紅襪",
        market="不讓分",
        selection="洋基勝",
        old_odds=1.85,
        new_odds=1.70,
        delta_odds=-0.15,
        delta_pct=-0.081,
    )

    sent_text = mock_session.post.call_args[1]["json"]["messages"][0]["text"]
    assert "跳水警報" in sent_text
    assert "洋基 vs 波士頓紅襪" in sent_text
    assert "1.85 ➔ 1.70" in sent_text


def test_line_notifier_ticket_won_celebration_format(tmp_path):
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_session.post.return_value = mock_resp

    notifier = LineNotifier(config_path=tmp_path / "line.yaml", session=mock_session)
    notifier.save_config({
        "enabled": True,
        "channel_access_token": "tok",
        "user_id": "U123",
    })

    ticket = {
        "sports_summary": "MLB + NBA 3 串 1",
        "stake": 20.0,
        "total_odds": 18.5,
    }
    notifier.notify_ticket_settlement(
        ticket=ticket,
        won=True,
        actual_payout=370.0,
        prize_pool=1250.0,
        weekly_balance=180.0,
    )

    sent_text = mock_session.post.call_args[1]["json"]["messages"][0]["text"]
    assert "中獎報喜" in sent_text
    assert "NT$ 370.00" in sent_text
    assert "保留儲備池" in sent_text


def test_line_notifier_hedging_alert_format(tmp_path):
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_session.post.return_value = mock_resp

    notifier = LineNotifier(config_path=tmp_path / "line.yaml", session=mock_session)
    notifier.save_config({
        "enabled": True,
        "channel_access_token": "tok",
        "user_id": "U123",
    })

    ticket = {
        "sports_summary": "4 串 1 瘋狗流",
        "stake": 50.0,
        "potential_payout": 2500.0,
    }
    pending_leg = {
        "league": "NBA",
        "away_team": "勇士",
        "home_team": "湖人",
        "selection": "湖人 -3.5",
    }
    hedge_analysis = {
        "opposing_selection": "勇士 +3.5",
        "hedge_odds": 1.75,
        "breakeven_stake": 67.0,
        "guaranteed_stake": 910.0,
        "guaranteed_profit": 1540.0,
    }

    notifier.notify_hedging_alert(ticket, pending_leg, hedge_analysis)

    sent_text = mock_session.post.call_args[1]["json"]["messages"][0]["text"]
    assert "恭喜聽牌" in sent_text
    assert "保本對衝" in sent_text
    assert "100% 絕對鎖利" in sent_text
    assert "勇士 +3.5" in sent_text


def test_line_notifier_handle_user_message_wallet():
    notifier = LineNotifier()
    mock_wallet = MagicMock()
    mock_wallet.get_status.return_value = {
        "weekly_wallet_balance": 180.0,
        "weekly_staked": 20.0,
        "prize_pool": 750.0,
        "lifetime_net_profit": 550.0,
    }
    reply = notifier.handle_user_message("查戰績", wallet_mgr=mock_wallet)
    assert "瘋狗流資金與戰績總覽" in reply
    assert "NT$ 180.00" in reply
    assert "NT$ 750.00" in reply


def test_line_notifier_handle_user_message_multiplier():
    notifier = LineNotifier()
    mock_engine = MagicMock()
    mock_engine.search_parlays.return_value = {
        "high_consensus": [{
            "parlay_name": "3 串 1",
            "total_odds": 20.5,
            "joint_probability": 0.08,
            "parlay_ev_pct": 15.0,
            "legs": [
                {"league": "MLB", "away_team": "洋基", "home_team": "紅襪", "selection": "洋基勝", "taiwan_odds": 2.0},
                {"league": "NBA", "away_team": "湖人", "home_team": "勇士", "selection": "湖人勝", "taiwan_odds": 2.5},
            ],
        }]
    }
    reply = notifier.handle_user_message("20倍", parlay_engine=mock_engine, available_legs=[{"dummy": 1}])
    assert "總賠率 20.5x" in reply
    assert "洋基 vs 紅襪" in reply
    assert "湖人 vs 勇士" in reply


def test_line_notifier_handle_user_message_help():
    notifier = LineNotifier()
    reply = notifier.handle_user_message("怎麼用")
    assert "瘋狗流 LINE 助手指令說明" in reply


def test_line_notifier_reply_message():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_session.post.return_value = mock_resp

    notifier = LineNotifier(session=mock_session)
    notifier.config["channel_access_token"] = "fake-token"
    quick_replies = notifier.default_quick_replies()

    res = notifier.reply_message("fake-reply-token", "測試回覆", quick_replies=quick_replies)
    assert res["success"] is True
    assert mock_session.post.called
    call_kwargs = mock_session.post.call_args[1]
    assert call_kwargs["json"]["replyToken"] == "fake-reply-token"
    assert "quickReply" in call_kwargs["json"]["messages"][0]
    assert len(call_kwargs["json"]["messages"][0]["quickReply"]["items"]) == 6


def test_format_parlay_leg_clean_league_and_sport():
    notifier = LineNotifier()

    # 1. Columbia Primera A test
    leg_columbia = {
        "sport": "soccer",
        "league": "columbia_primera_a",
        "away_team": "麥德林獨立",
        "home_team": "卡利體育會",
        "market": "不讓分",
        "selection": "客勝",
        "taiwan_odds": 2.2,
    }
    rendered1 = notifier.format_parlay_leg(leg_columbia, idx=1)
    assert "⚽ [哥倫比亞甲級足球聯賽]" in rendered1
    assert "麥德林獨立 vs 卡利體育會" in rendered1
    assert "不讓分 ➔ 【客勝】(2.20x)" in rendered1

    # 2. Unknown soccer test
    leg_unknown = {
        "sport": "soccer",
        "league": "unknown",
        "away_team": "波哥大公平",
        "home_team": "百萬富翁",
        "market": "大小",
        "line": "2.5",
        "selection": "小",
        "taiwan_odds": 1.68,
    }
    rendered2 = notifier.format_parlay_leg(leg_unknown, idx=2)
    assert "⚽ [國際足球錦標賽]" in rendered2
    assert "大小分 [2.5] ➔ 【小】(1.68x)" in rendered2
