"""Isolated tests for LINE Bot Flex, identity and notification behavior."""

from datetime import datetime, timedelta, timezone
from itertools import cycle
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

import core.line_notifier as line_notifier_module
from core.line_flex import (
    TAIWAN_LOTTERY_URL,
    build_menu_flex,
    build_parlay_flex,
    build_radar_flex,
    system_deep_link,
)
from core.line_notifier import LineNotifier


@pytest.fixture(autouse=True)
def isolate_runtime_url(monkeypatch):
    monkeypatch.setattr(line_notifier_module, "load_active_runtime", lambda _path: {})


class FakeProfiles:
    def __init__(self):
        self.profiles = [
            {"id": "p-a", "name": "玩家甲", "line_user_id": "U-A"},
            {"id": "p-b", "name": "玩家乙", "line_user_id": "U-B"},
        ]

    def list_profiles(self):
        return [dict(profile) for profile in self.profiles]

    def get_profile(self, profile_id):
        return next((dict(profile) for profile in self.profiles if profile["id"] == profile_id), None)

    def get_profile_by_name(self, name):
        return next((dict(profile) for profile in self.profiles if profile["name"].casefold() == name.casefold()), None)

    def get_profile_by_line_user_id(self, line_user_id):
        return next((dict(profile) for profile in self.profiles if profile.get("line_user_id") == line_user_id), None)

    def bind_line_user_from_authenticated_session(self, profile_id, line_user_id):
        owner = self.get_profile_by_line_user_id(line_user_id)
        if owner and owner["id"] != profile_id:
            raise ValueError("LINE identity already belongs to another Profile")
        profile = next(profile for profile in self.profiles if profile["id"] == profile_id)
        profile["line_user_id"] = line_user_id
        return dict(profile)


def _mock_session(status_codes=(200,)):
    session = MagicMock()
    responses = []
    for status_code in status_codes:
        response = MagicMock()
        response.status_code = status_code
        response.text = "mock"
        responses.append(response)
    session.post.side_effect = cycle(responses)
    return session


def _configured_notifier(tmp_path, session=None, profiles=None):
    notifier = LineNotifier(
        config_path=tmp_path / "line.yaml",
        session=session or _mock_session(),
        profile_manager=profiles,
    )
    notifier.save_config({
        "enabled": True,
        "channel_access_token": "mock-token",
        "user_id": "legacy-global-recipient",
    })
    return notifier


def test_preference_save_does_not_persist_environment_token(tmp_path, monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "mock-env-token")
    config_path = tmp_path / "line.yaml"
    notifier = LineNotifier(config_path=config_path, profile_manager=FakeProfiles())

    result = notifier.update_notification_preferences("U-A", {"steam_drop": False})

    assert result["steam_drop"] is False
    assert notifier.config["channel_access_token"] == "mock-env-token"
    persisted = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert "channel_access_token" not in persisted
    assert "mock-env-token" not in config_path.read_text(encoding="utf-8")


def test_push_requires_explicit_profile_bound_recipient(tmp_path):
    notifier = _configured_notifier(tmp_path)
    assert "user_id" not in notifier.config
    result = notifier.send_push_message("mock message")
    assert result["error"] == "LINE_TARGET_REQUIRED"


def test_push_and_flex_rejection_fall_back_to_complete_text(tmp_path):
    session = _mock_session((400, 200))
    notifier = _configured_notifier(tmp_path, session=session)
    flex = build_menu_flex("https://sportslottery.example/app")
    result = notifier.send_push_message(
        "完整文字備援：六個入口與操作說明",
        user_id="U-MOCK",
        flex_message=flex,
        quick_replies=notifier.default_quick_replies(),
    )
    assert result["success"] is True
    assert result["fallback"] == "text"
    first_payload = session.post.call_args_list[0].kwargs["json"]
    second_payload = session.post.call_args_list[1].kwargs["json"]
    assert first_payload["messages"][0]["type"] == "flex"
    assert second_payload["messages"][0]["text"] == "完整文字備援：六個入口與操作說明"
    assert len(second_payload["messages"][0]["quickReply"]["items"]) == 6


def test_flex_menu_actions_and_text_alt_are_complete():
    menu = build_menu_flex("https://sportslottery.example/app")
    assert menu["type"] == "flex"
    assert all(menu["altText"] and key in menu["altText"] for key in ("智慧串關", "Banker", "今日賽事", "資產戰績", "通知設定", "個人設定"))
    actions = menu["contents"]["footer"]["contents"]
    assert len(actions) == 6
    assert all(item["type"] == "button" and item["action"]["type"] in {"message", "uri"} for item in actions)
    assert actions[-1]["action"]["uri"] == "https://sportslottery.example/app?tab=profile"
    assert actions[-1]["style"] == "primary"
    assert actions[-1]["color"] == "#1E3A8A"


def test_radar_cta_uses_high_contrast_primary_button():
    radar = build_radar_flex(
        {"source_status": "fresh", "as_of": "2026-11-06T10:00:00Z", "radar": []},
        system_url="https://sportslottery.example/app",
    )
    button = radar["contents"]["footer"]["contents"][0]
    assert button["action"]["label"] == "開啟主系統賽事雷達"
    assert button["style"] == "primary"
    assert button["color"] == "#1E3A8A"
    assert button["action"]["type"] == "uri"


def test_line_search_uses_shared_react_search_request_and_tier_order(monkeypatch, tmp_path):
    from server.routers import parlay as parlay_routes

    calls = []
    high = {"candidate_id": "high", "total_odds_exact": 20, "joint_probability": 0.2, "joint_probability_sources": ["UNVALIDATED_MODEL"], "parlay_ev_pct": 5, "credible_value_status": "UNVERIFIED", "legs": []}
    aggressive = {"candidate_id": "aggressive", "total_odds_exact": 20, "joint_probability": 0.1, "legs": []}
    moonshot = {"candidate_id": "moonshot", "total_odds_exact": 20, "joint_probability": 0.05, "legs": []}

    def fake_search(req):
        calls.append(req)
        return {"tiers": {"high_consensus": [high], "aggressive": [aggressive], "moonshot": [moonshot]}, "diagnostics": {}, "search_complete": True}

    monkeypatch.setattr(parlay_routes, "_execute_parlay_search", fake_search)
    notifier = LineNotifier(config_path=tmp_path / "line.yaml")
    text = notifier._search_parlay_for_bot(20.0)
    assert notifier.last_recommended_parlay["candidate_id"] == "high"
    assert "未驗證" in text
    assert calls[0].target_odds == 20
    assert calls[0].tolerance == 0.20
    assert (calls[0].min_legs, calls[0].max_legs) == (2, 5)
    assert calls[0].signal_filter == "normal"
    assert calls[0].ranking_mode == "WIN_PROBABILITY"

    notifier._search_parlay_for_bot(3.75, sport_filter="banker")
    assert calls[1].min_odds == 1.5 and calls[1].max_odds == 6.0
    assert calls[1].target_odds == 3.75
    assert (calls[1].min_legs, calls[1].max_legs) == (1, 3)
    assert calls[1].signal_filter == "value_only"
    assert calls[1].ranking_mode == "WIN_PROBABILITY"


def test_line_search_explains_when_shared_search_has_no_qualified_candidate(monkeypatch, tmp_path):
    from server import service_registry
    from server.routers import parlay as parlay_routes

    adapter = SimpleNamespace(get_source_status=lambda: {
        "1": {"source_status": "LIVE"},
        "4": {"source_status": "STALE_CACHE"},
    })
    monkeypatch.setattr(service_registry, "get_services", lambda: (adapter, None, None, None, None, None, None, None))
    monkeypatch.setattr(parlay_routes, "_execute_parlay_search", lambda _req: {
        "tiers": {"high_consensus": [], "aggressive": [], "moonshot": []},
        "diagnostics": {"excluded_option_reasons": {"ODDS_STALE": 3}},
        "search_complete": False,
    })
    notifier = LineNotifier(config_path=tmp_path / "line.yaml")
    text = notifier._search_parlay_for_bot(20.0)
    assert "沒有符合主系統資格" in text
    assert "LIVE 1 個聯盟" in text and "STALE_CACHE 1 個聯盟" in text
    assert "ODDS_STALE: 3" in text
    assert "未放寬條件湊單" in text
    assert notifier.last_recommended_parlay is None


def test_parlay_flex_discloses_model_and_probability_sources():
    candidate = {
        "total_odds_exact": 12,
        "joint_probability": 0.12,
        "joint_probability_sources": ["UNVALIDATED_MODEL", "SHARP_MARKET"],
        "has_sharp_benchmark": True,
        "sharp_joint_probability": 0.1,
        "parlay_ev_pct": 40,
        "credible_value_basis": False,
        "credible_value_status": "UNVERIFIED",
        "correlation_risk_grade": "MEDIUM",
        "legs": [{
            "event_id": "101", "league": "NBA", "away_team": "勇士", "home_team": "湖人",
            "market": "不讓分", "selection": "湖人勝", "taiwan_odds": 1.9,
            "odds_status": "FRESH", "odds_age_minutes": 4,
            "odds_scraped_at": "2026-11-06T12:00:00+00:00",
            "signal_evidence": {
                "probability_status": "UNVALIDATED_MODEL_ESTIMATE",
                "market_source_qualification": "SHARP_QUALIFIED",
                "market_benchmark_status": "AVAILABLE",
                "sharp_fair_probability": 0.55,
                "sharp_expected_value_pct": 4.5,
                "market_fair_probability": 0.51,
                "market_fair_method": "TWO_WAY_PROPORTIONAL",
            },
        }],
    }
    flex = build_parlay_flex(candidate, system_url="https://sportslottery.example/app")
    assert "合格 Sharp 市場估計" in flex["altText"]
    body_text = " ".join(item.get("text", "") for item in flex["contents"]["body"]["contents"] if item["type"] == "text")
    serialized = repr(flex)
    assert "組合機率：10.0%" in serialized
    assert "Sharp 市場估計" in serialized
    assert "台彩市場估計" in serialized
    assert "資料時間" in serialized
    assert "相關性風險" in serialized
    assert "Sharp 市場估計 EV" in serialized
    assert "未驗收候選，不列為正式模型推薦依據" in serialized
    assert "SPORTSLOTTERY" in body_text or "智慧串關" in flex["altText"]


def test_line_search_state_and_private_wallet_are_profile_isolated(monkeypatch, tmp_path):
    from server import service_registry

    profiles = FakeProfiles()
    notifier = LineNotifier(config_path=tmp_path / "line.yaml", profile_manager=profiles)
    wallets = {"p-a": {"weekly_wallet_balance": 40}, "p-b": {"weekly_wallet_balance": 900}}
    tickets = {"p-a": [{"sports_summary": "A 注單", "status": "OPEN", "stake": 10}], "p-b": [{"sports_summary": "B 注單", "status": "WON", "stake": 30}]}
    monkeypatch.setattr(service_registry, "get_wallet", lambda profile_id: SimpleNamespace(get_status=lambda: dict(wallets[profile_id])))
    monkeypatch.setattr(service_registry, "get_betting_service", lambda profile_id: SimpleNamespace(list_tickets=lambda **_kwargs: list(tickets[profile_id])))

    snapshot_a = notifier._get_line_wallet_snapshot("U-A")
    snapshot_b = notifier._get_line_wallet_snapshot("U-B")
    snapshot_unbound = notifier._get_line_wallet_snapshot("U-UNKNOWN")
    assert snapshot_a["status"]["weekly_wallet_balance"] == 40
    assert snapshot_a["tickets"][0]["sports_summary"] == "A 注單"
    assert snapshot_b["status"]["weekly_wallet_balance"] == 900
    assert snapshot_b["tickets"][0]["sports_summary"] == "B 注單"
    assert snapshot_unbound["status"] is None and snapshot_unbound["tickets"] == []
    assert "尚未綁定" in snapshot_unbound["text"]

    with notifier.user_search_context("U-A") as state_a:
        state_a.last_recommended_parlay = {"candidate_id": "A"}
    with notifier.user_search_context("U-B") as state_b:
        assert state_b.last_recommended_parlay is None
        state_b.last_recommended_parlay = {"candidate_id": "B"}
    assert notifier._user_search_states["U-A"].last_recommended_parlay["candidate_id"] == "A"
    assert notifier._user_search_states["U-B"].last_recommended_parlay["candidate_id"] == "B"


def test_sensitive_profile_commands_route_to_authenticated_web(monkeypatch, tmp_path):
    import core.line_notifier as line_notifier_module

    monkeypatch.setattr(line_notifier_module, "load_active_runtime", lambda _path: {})
    notifier = LineNotifier(config_path=tmp_path / "line.yaml")
    reply = notifier.handle_user_message("改密碼 1234 9876")
    assert "主系統" in reply
    assert "1234" not in reply and "9876" not in reply
    assert "Sportslottery" in notifier.handle_user_message("個人設定")


def test_line_binding_requires_profile_approval_and_is_scoped(tmp_path):
    profiles = FakeProfiles()
    notifier = LineNotifier(config_path=tmp_path / "line.yaml", profile_manager=profiles)
    request = notifier.request_line_binding("玩家甲", "U-NEW")
    pending = notifier.list_line_binding_requests("p-a")
    request_id = pending[0]["request_id"]
    assert request["success"] and request["profile_name"] == "玩家甲"
    assert request["confirmation_code"] == pending[0]["confirmation_code"]
    assert len(request["confirmation_code"]) == 6
    repeated = notifier.request_line_binding("玩家甲", "U-NEW")
    assert repeated["already_pending"] is True
    assert repeated["confirmation_code"] == request["confirmation_code"]
    assert notifier.approve_line_binding_request("p-b", request_id) is False
    assert profiles.get_profile_by_line_user_id("U-NEW") is None
    assert notifier.approve_line_binding_request("p-a", request_id) is True
    assert profiles.get_profile_by_line_user_id("U-NEW")["id"] == "p-a"


def test_line_binding_requests_are_capped_per_profile(tmp_path):
    profiles = FakeProfiles()
    notifier = LineNotifier(config_path=tmp_path / "line.yaml", profile_manager=profiles)
    for index in range(5):
        assert notifier.request_line_binding("玩家甲", f"U-{index}")["success"] is True
    rejected = notifier.request_line_binding("玩家甲", "U-OVERFLOW")
    assert rejected == {"success": False, "reason": "TOO_MANY_PENDING_REQUESTS"}
    assert len(notifier.list_line_binding_requests("p-a")) == 5


def test_line_private_chat_classifier_covers_wallet_and_settings_only():
    assert LineNotifier.requires_private_line_chat("查戰績") is True
    assert LineNotifier.requires_private_line_chat("通知 全部 關閉") is True
    assert LineNotifier.requires_private_line_chat("智慧串關 20倍") is False


def test_preferences_are_bound_profile_specific_and_ignore_legacy_global(tmp_path):
    profiles = FakeProfiles()
    notifier = _configured_notifier(tmp_path, profiles=profiles)
    notifier.config["notify_events"] = {"steam_drop": False}
    assert notifier.get_notification_preferences("p-a")["steam_drop"] is True
    saved = notifier.update_notification_preferences("U-A", {"steam_drop": False})
    assert saved["steam_drop"] is False
    assert notifier.get_notification_preferences("p-b")["steam_drop"] is True
    assert notifier.handle_user_message("通知 全部 關閉", line_user_id="U-A").startswith("已更新")


def test_notifications_require_recent_sources_preferences_and_dedupe(tmp_path):
    profiles = FakeProfiles()
    session = _mock_session()
    notifier = _configured_notifier(tmp_path, session=session, profiles=profiles)
    now = datetime.now(timezone.utc).isoformat()
    result = notifier.notify_steam_drop(
        "NBA", "勇士 vs 湖人", "不讓分", "湖人勝", 1.95, 1.8, -0.15, -0.077,
        source="mock odds source", observed_at=now, trigger="mock price threshold",
    )
    assert result["success"] and result["sent"] == 2
    assert session.post.call_count == 2
    message = session.post.call_args_list[0].kwargs["json"]["messages"][0]
    assert message["type"] == "flex"
    assert "mock odds source" in message["altText"]
    assert "資金流向" in message["altText"]
    duplicate = notifier.notify_steam_drop(
        "NBA", "勇士 vs 湖人", "不讓分", "湖人勝", 1.95, 1.8, -0.15, -0.077,
        source="mock odds source", observed_at=now, trigger="mock price threshold",
    )
    assert duplicate["reason"] == "DUPLICATE"
    assert session.post.call_count == 2

    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    stale = notifier.notify_steam_drop("NBA", "A vs B", "ML", "A", 2, 1.8, -0.2, -0.1, observed_at=stale_time)
    assert stale["reason"] == "SOURCE_TIME_MISSING_OR_STALE"
    assert session.post.call_count == 2


def test_ticket_notifications_are_profile_scoped_and_disclose_local_record(tmp_path):
    profiles = FakeProfiles()
    session = _mock_session()
    notifier = _configured_notifier(tmp_path, session=session, profiles=profiles)
    missing_profile = notifier.notify_ticket_settlement(
        {"id": "t0", "stake": 10}, True, 20, 100, 50,
    )
    assert missing_profile["reason"] == "PROFILE_REQUIRED"
    assert session.post.call_count == 0

    sent = notifier.notify_ticket_settlement(
        {"id": "t1", "profile_id": "p-a", "sports_summary": "mock combo", "stake": 10, "settled_at": "mock-time"},
        True, 20, 100, 50,
    )
    assert sent["success"] and sent["sent"] == 1
    payload = session.post.call_args.kwargs["json"]
    assert payload["to"] == "U-A"
    assert "本站 Ticket 結算記錄" in payload["messages"][0]["altText"]
    assert "不代表台灣運彩官方" in payload["messages"][0]["altText"]


def test_hedging_notice_is_conditional_and_never_promises_profit(tmp_path):
    profiles = FakeProfiles()
    session = _mock_session()
    notifier = _configured_notifier(tmp_path, session=session, profiles=profiles)
    result = notifier.notify_hedging_alert(
        {"id": "t2", "profile_id": "p-b", "stake": 20, "potential_payout": 200},
        {"event_id": "e1", "league": "NBA", "away_team": "勇士", "home_team": "湖人", "selection": "湖人勝"},
        {"opposing_selection": "勇士勝", "hedge_odds": 1.75, "breakeven_stake": 80, "source": "manual assumption", "observed_at": "user-entered"},
    )
    assert result["success"]
    payload = session.post.call_args.kwargs["json"]
    assert payload["to"] == "U-B"
    text = payload["messages"][0]["altText"]
    assert "條件式試算" in text
    assert "不保證可成交" in text
    assert "絕對鎖利" not in text and "100%" not in text


def test_radar_notification_requires_fresh_timestamp(tmp_path):
    session = _mock_session()
    notifier = _configured_notifier(tmp_path, session=session, profiles=FakeProfiles())
    stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    result = notifier.notify_morning_radar([], as_of=stale, source_status="mock")
    assert result["reason"] == "SOURCE_TIME_MISSING_OR_STALE"
    assert session.post.call_count == 0


def test_manual_slip_has_official_link_but_no_issuance_qr(tmp_path):
    notifier = LineNotifier(config_path=tmp_path / "line.yaml")
    combo = {
        "parlay_name": "2 串 1", "total_odds": 3.5,
        "legs": [{"event_id": "101", "league": "NBA", "away_team": "勇士", "home_team": "湖人", "market": "不讓分", "selection": "湖人勝", "taiwan_odds": 1.75}],
    }
    result = notifier._generate_qr_for_combo(combo, stake=100)
    assert result["official_qr_verified"] is False
    assert result["image_url"] is None
    assert "#101" in result["text"]
    assert TAIWAN_LOTTERY_URL in result["text"]
    with notifier.user_search_context("U-A") as state:
        state.last_recommended_parlay = combo
    flex = notifier.handle_user_message_full("投注單明細", line_user_id="U-A")
    assert flex["flex_message"]["type"] == "flex"
    assert "未驗證" in flex["flex_message"]["altText"]


def test_manual_slip_push_uses_flex_with_full_text_fallback(tmp_path):
    session = _mock_session()
    notifier = _configured_notifier(tmp_path, session=session)
    combo = {
        "parlay_name": "單場",
        "legs": [{"event_id": "102", "league": "NBA", "away_team": "勇士", "home_team": "湖人", "market": "不讓分", "selection": "湖人勝", "taiwan_odds": 1.8}],
    }

    result = notifier.notify_ticket_qr(combo, stake=100, user_id="U-BOUND")

    assert result["success"]
    payload = session.post.call_args.kwargs["json"]
    assert payload["to"] == "U-BOUND"
    assert payload["messages"][0]["type"] == "flex"
    assert "未驗證" in payload["messages"][0]["altText"]
    assert TAIWAN_LOTTERY_URL in str(payload["messages"][0]["contents"])


def test_deep_links_require_https_and_drop_untrusted_query_values():
    assert system_deep_link("http://sportslottery.example/?token=secret", "profile") is None
    assert system_deep_link("https://user:pass@sportslottery.example", "profile") is None
    link = system_deep_link("https://sportslottery.example/base?token=secret", "wallet", profile_id="p-a", token="secret")
    assert link == "https://sportslottery.example/base?tab=wallet&profile_id=p-a"
    assert "secret" not in link


def test_parlay_leg_formatter_uses_qualified_sources_and_no_cash_flow_claims():
    leg = {
        "sport": "basketball", "league": "NBA", "away_team": "勇士", "home_team": "湖人",
        "market": "不讓分", "selection": "湖人勝", "taiwan_odds": 1.8,
        "signal_evidence": {
            "sharp_fair_probability": 0.62, "sharp_expected_value_pct": 8.5,
            "market_source_qualification": "SHARP_QUALIFIED", "market_benchmark_status": "AVAILABLE",
            "market_fair_probability": 0.57, "market_fair_method": "TWO_WAY_PROPORTIONAL",
            "money_percentage": 75, "bet_percentage": 50,
        },
    }
    rendered = LineNotifier.format_parlay_leg(leg, 1)
    assert "Sharp 市場估計: 62.0%" in rendered
    assert "TWO WAY PROPORTIONAL: 57.0%" in rendered
    assert "資金顯著分歧" not in rendered
    assert "國際籌碼傾向" not in rendered
