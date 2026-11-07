"""Small, validated LINE Flex Message builders for Sportslottery cards.

The returned ``altText`` is a complete text-only rendering for LINE clients
that cannot display Flex.  Actions use LINE message/URI actions only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlencode, urlsplit, urlunsplit


TAIWAN_LOTTERY_URL = "https://www.sportslottery.com.tw/sportsbook/daily-coupons"

_GREEN = "#087F5B"
_INK = "#152238"
_MUTED = "#64748B"
_SURFACE = "#F4F7FA"


def system_deep_link(base_url: str | None, tab: str, **params: Any) -> str | None:
    """Build a deep link only from the current HTTPS runtime origin."""
    raw = str(base_url or "").strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    if parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password:
        return None
    if parts.hostname.lower() in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return None
    if tab not in {"radar", "parlay", "wallet", "profile", "research"}:
        return None
    query: dict[str, str] = {"tab": tab}
    allowed_params = {"mode", "target_odds", "profile_id", "run_search"}
    for key, value in params.items():
        if key in allowed_params and value is not None and str(value) != "":
            query[key] = str(value)
    return urlunsplit(("https", parts.netloc, parts.path or "/", urlencode(query), ""))


def flex_message(alt_text: str, contents: dict[str, Any]) -> dict[str, Any]:
    return {"type": "flex", "altText": str(alt_text or "Sportslottery LINE 助手")[:1500], "contents": contents}


def _text(text: Any, *, size: str = "sm", color: str = _INK, weight: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"type": "text", "text": str(text or "—")[:2000], "size": size, "color": color, "wrap": True}
    if weight:
        item["weight"] = weight
    return item


def _message_button(label: str, message: str, *, color: str = _GREEN) -> dict[str, Any]:
    return {
        "type": "button", "style": "primary", "color": color, "height": "md",
        "action": {"type": "message", "label": label[:20], "text": message[:300]},
    }


def _uri_button(label: str, uri: str, *, color: str = _INK) -> dict[str, Any]:
    return {
        "type": "button", "style": "secondary", "color": color, "height": "md",
        "action": {"type": "uri", "label": label[:20], "uri": uri},
    }


def _bubble(title: str, subtitle: str, rows: Iterable[str] = (), footer: Iterable[dict[str, Any]] = (), *, accent: str = _GREEN) -> dict[str, Any]:
    body: list[dict[str, Any]] = [
        {"type": "box", "layout": "vertical", "spacing": "xs", "contents": [
            _text(title, size="lg", weight="bold"),
            _text(subtitle, size="xs", color=_MUTED),
        ]},
    ]
    values = list(rows)
    if values:
        body.append({"type": "separator", "margin": "md", "color": "#DCE4EC"})
        body.extend(_text(value, size="sm") for value in values)
    bubble: dict[str, Any] = {
        "type": "bubble", "size": "giga",
        "styles": {"body": {"backgroundColor": _SURFACE}, "footer": {"backgroundColor": _SURFACE}},
        "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "18px", "contents": body},
    }
    footer_values = list(footer)
    if footer_values:
        bubble["footer"] = {
            "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "16px",
            "contents": footer_values,
        }
    bubble["header"] = {
        "type": "box", "layout": "vertical", "paddingAll": "14px", "backgroundColor": accent,
        "contents": [_text("SPORTSLOTTERY", size="xs", color="#FFFFFF", weight="bold")],
    }
    return bubble


def build_menu_flex(system_url: str | None) -> dict[str, Any]:
    actions: list[dict[str, Any]] = [
        _message_button("🎯 智慧串關", "智慧串關"),
        _message_button("🛡️ Banker 穩健精選", "Banker 穩健精選"),
        _message_button("☀️ 今日賽事", "今日開盤"),
        _message_button("💰 資產戰績", "查戰績"),
        _message_button("🔔 通知設定", "通知設定"),
    ]
    profile_url = system_deep_link(system_url, "profile")
    if profile_url:
        actions.append(_uri_button("👤 個人設定／主系統", profile_url))
    else:
        actions.append(_message_button("👤 個人設定／主系統", "個人設定"))
    alt = "Sportslottery 快捷選單：智慧串關、Banker 穩健精選、今日賽事、資產戰績、通知設定、個人設定／主系統。"
    bubble = _bubble("手機快捷助手", "查詢、接收提醒；帳號管理與完整操作請前往主系統。", footer=actions)
    return flex_message(alt, bubble)


def _probability_label(sources: Any) -> str:
    values = {str(value).upper() for value in (sources or []) if value}
    labels = {
        "ACCEPTED_MODEL": "已驗收模型估計",
        "UNVALIDATED_MODEL": "未驗收模型估計（不作正式模型資格）",
        "UNVERIFIED_ESTIMATE": "未驗證估計",
        "SHARP_MARKET": "Sharp 市場估計",
        "INTERNATIONAL_MARKET": "國際市場估計",
        "TAIWAN_DEVIG": "台彩去水市場估計",
        "TAIWAN_BREAKEVEN": "台彩賠率損益平衡估計",
    }
    selected = [labels[value] for value in sorted(values) if value in labels]
    return "、".join(selected) if selected else "來源不足；不列為已驗證勝率"


def _parlay_probability_source(parlay: dict[str, Any]) -> str:
    """Mirror ParlayResultCard's joint-probability provenance selection."""
    if parlay.get("has_sharp_benchmark"):
        try:
            sharp = float(parlay.get("sharp_joint_probability"))
            if 0 < sharp < 1:
                return "合格 Sharp 市場估計；串關機率未經驗證"
        except (TypeError, ValueError, OverflowError):
            pass
    if str(parlay.get("joint_probability_validation_status") or "").upper() == "VALIDATED":
        return "已驗證聯合機率"
    sources = [str(value).upper() for value in (parlay.get("joint_probability_sources") or []) if value]
    if any(value in {"UNVALIDATED_MODEL", "UNVERIFIED_ESTIMATE"} for value in sources):
        return "未經模型驗證的估計；不是已驗證命中率"
    if sources and all(value == "TAIWAN_BREAKEVEN" for value in sources):
        return "台彩損益平衡基準組合估計；不是已驗證命中率"
    if sources and all(value in {"TAIWAN_DEVIG", "TAIWAN_BREAKEVEN"} for value in sources):
        return "台彩市場基準組合估計；串關機率未驗證"
    if sources and all(value in {"INTERNATIONAL_MARKET", "SHARP_MARKET"} for value in sources):
        return "外部市場基準組合估計；串關機率未驗證"
    if sources and all(value == "ACCEPTED_MODEL" for value in sources):
        return "已驗收模型輸入的組合估計；串關機率未驗證"
    if "UNAVAILABLE" in sources:
        return "未驗證估計；部分關卡缺少有效來源"
    return "混合來源組合估計；串關機率未驗證" if sources else "來源不足；不列為已驗證勝率"


def _leg_rows(legs: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for index, leg in enumerate(legs, 1):
        event = str(leg.get("event_id") or leg.get("canonical_event_id") or "賽事編號未知")
        league = str(leg.get("display_league") or leg.get("league") or "聯賽未知")
        away = str(leg.get("away_team") or "客隊未知")
        home = str(leg.get("home_team") or "主隊未知")
        market = str(leg.get("market") or leg.get("market_type") or "玩法未知")
        line = leg.get("line")
        selection = str(leg.get("selection") or "選項未知")
        odds = leg.get("taiwan_odds", leg.get("odds"))
        try:
            odds_text = f"{float(odds):.2f}"
        except (TypeError, ValueError, OverflowError):
            odds_text = "—"
        line_text = f" {line}" if line not in (None, "") else ""
        age = leg.get("odds_age_minutes")
        freshness = str(leg.get("odds_status") or (leg.get("signal_evidence") or {}).get("source_status") or "狀態未知")
        try:
            freshness = f"{freshness} · {max(0, float(age)):.0f} 分鐘前" if age is not None else freshness
        except (TypeError, ValueError, OverflowError):
            pass
        rows.append(f"{index}. [{league}] {away} vs {home} · #{event}\n{market}{line_text}｜{selection} @ {odds_text}\n資料：{freshness}")
        evidence = leg.get("signal_evidence") if isinstance(leg.get("signal_evidence"), dict) else {}
        try:
            market_probability = float(evidence.get("market_fair_probability")) * 100
        except (TypeError, ValueError, OverflowError):
            market_probability = None
        if market_probability is not None:
            method = str(evidence.get("market_fair_method") or "台彩市場估計").replace("_", " ")
            rows.append(f"台彩市場估計：{market_probability:.1f}% · {method}")
        try:
            sharp_probability = float(evidence.get("sharp_fair_probability")) * 100
            sharp_ev = evidence.get("sharp_expected_value_pct")
            qualified = (
                str(evidence.get("market_source_qualification") or "").upper() == "SHARP_QUALIFIED"
                and str(evidence.get("market_benchmark_status") or "").upper() == "AVAILABLE"
                and not evidence.get("is_market_synthetic")
            )
        except (TypeError, ValueError, OverflowError):
            sharp_probability, sharp_ev, qualified = None, None, False
        if qualified and sharp_probability is not None:
            ev_text = f" · Sharp EV {float(sharp_ev):+.1f}%" if isinstance(sharp_ev, (int, float)) else ""
            rows.append(f"Sharp 市場估計：{sharp_probability:.1f}%{ev_text}")
        model_status = str(evidence.get("probability_status") or "").upper()
        if model_status in {"CALIBRATED_MODEL_ESTIMATE", "UNVALIDATED_MODEL_ESTIMATE", "UNVALIDATED_MODEL_FUSION_ESTIMATE"}:
            accepted = model_status == "CALIBRATED_MODEL_ESTIMATE" and bool(evidence.get("model_accepted_ids"))
            rows.append("模型來源：已驗收模型輸入；串關機率仍未驗證" if accepted else "模型來源：未驗收候選，不列為正式模型推薦依據")
    return rows


def build_parlay_flex(parlay: dict[str, Any], *, system_url: str | None, banker: bool = False) -> dict[str, Any]:
    legs = [leg if isinstance(leg, dict) else {} for leg in (parlay.get("legs") or [])]
    try:
        odds = float(parlay.get("total_odds_exact", parlay.get("total_odds", 0)) or 0)
        odds_label = f"{odds:.2f}x" if odds > 0 else "倍率未提供"
    except (TypeError, ValueError, OverflowError):
        odds_label = "倍率未提供"
    probability_source = _parlay_probability_source(parlay)
    probability_raw = parlay.get("joint_probability")
    if parlay.get("has_sharp_benchmark"):
        try:
            sharp_probability = float(parlay.get("sharp_joint_probability"))
            if 0 < sharp_probability < 1:
                probability_raw = sharp_probability
        except (TypeError, ValueError, OverflowError):
            pass
    try:
        probability = float(probability_raw) * 100
        probability_label = f"{probability:.1f}%"
    except (TypeError, ValueError, OverflowError):
        probability_label = "未提供"
    ev = parlay.get("parlay_ev_pct")
    try:
        if parlay.get("has_sharp_benchmark") and parlay.get("sharp_joint_probability") is not None:
            sharp_probability = float(parlay.get("sharp_joint_probability"))
            ev_value = (sharp_probability * odds - 1) * 100 if odds > 1 else None
            ev_source = "Sharp 市場估計 EV"
        else:
            ev_value = float(ev) if ev is not None else None
            ev_source = "合格來源估計 EV" if parlay.get("credible_value_basis") else "未驗證估計 EV"
        ev_label = f"{ev_value:+.1f}% · {ev_source}" if ev_value is not None else "未提供"
    except (TypeError, ValueError, OverflowError):
        ev_label = "未提供"
    ev_status = str(parlay.get("credible_value_status") or "UNVERIFIED").replace("_", " ")
    as_of_values = [str(leg.get("odds_scraped_at") or "") for leg in legs if leg.get("odds_scraped_at")]
    as_of = max(as_of_values) if as_of_values else "時間未提供"
    title = "Banker 穩健候選" if banker else "智慧串關候選"
    rows = [
        f"關數：{len(legs)} 關    倍率：{odds_label}",
        f"組合機率：{probability_label}（{probability_source}）",
        f"EV：{ev_label} · 狀態 {ev_status}",
        f"資料時間：{as_of}",
        f"相關性風險：{parlay.get('correlation_risk_grade') or '未提供'}；組合估計不等於已驗證聯合機率",
        *_leg_rows(legs),
        "風險：機率與 EV 為估計值，會受盤口更新及關卡相關性影響；不代表已驗證命中率或獲利。",
    ]
    target = parlay.get("target_odds") or parlay.get("total_odds")
    details_url = system_deep_link(system_url, "parlay", mode="banker" if banker else "target", target_odds=target, run_search="1")
    footer = [_message_button("🎲 換一組", "換一組"), _message_button("🎯 調整倍率", "智慧串關")]
    if details_url:
        footer.append(_uri_button("📊 查看完整分析", details_url))
    else:
        footer.append(_message_button("📊 查看完整分析", "查看完整分析"))
    alt = f"{title}：{len(legs)} 關、{odds_label}；組合機率 {probability_label}，來源為{probability_source}；EV {ev_label}，狀態 {ev_status}。完整明細請開啟主系統。"
    return flex_message(alt, _bubble(title, f"依主系統資格、排序與估值來源 · {len(legs)} 關", rows, footer, accent="#176B55"))


def build_radar_flex(radar: dict[str, Any], *, system_url: str | None) -> dict[str, Any]:
    leagues = radar.get("radar") or []
    opened = [item for item in leagues if int(item.get("taiwan_market_count") or item.get("game_count") or 0) > 0]
    rows = [
        f"來源狀態：{radar.get('source_status') or '未知'} · 更新時間：{radar.get('as_of') or '未提供'}",
    ]
    for league in opened[:8]:
        rows.append(f"{league.get('icon') or '•'} {league.get('name') or '聯賽'}｜開盤 {league.get('taiwan_market_count') or league.get('game_count') or 0} 場｜{league.get('status_text') or '狀態未知'}")
    if not opened:
        rows.append("目前沒有可確認已開盤的場次；請稍後在主系統重新整理。")
    footer = []
    link = system_deep_link(system_url, "radar")
    if link:
        footer.append(_uri_button("開啟主系統賽事雷達", link))
    alt = "今日台彩開盤賽事：" + ("；".join(f"{r.get('name')} {r.get('taiwan_market_count') or r.get('game_count') or 0} 場" for r in opened[:5]) or "目前沒有已確認開盤場次") + f"。資料狀態：{radar.get('source_status') or '未知'}。"
    return flex_message(alt, _bubble("今日賽事", "只列出台彩已開盤場次", rows, footer, accent="#D28A12"))


def build_wallet_flex(status: dict[str, Any], recent_tickets: list[dict[str, Any]], *, system_url: str | None, profile_id: str) -> dict[str, Any]:
    def money(key: str) -> str:
        try:
            return f"NT$ {float(status.get(key) or 0):,.0f}"
        except (TypeError, ValueError, OverflowError):
            return "資料未提供"

    rows = [
        f"本週可用：{money('weekly_wallet_balance')}    本週已記錄注金：{money('weekly_staked')}",
        f"獲利保留池：{money('prize_pool')}    歷史淨利：{money('lifetime_net_profit')}",
        "本站錢包摘要；不代表台灣運彩官方投注或派彩紀錄。",
    ]
    status_labels = {"OPEN": "待結算", "WON": "本站記錄已結算：中獎", "LOST": "本站記錄已結算：未全數命中", "VOID": "本站記錄已退盤"}
    for ticket in recent_tickets[:3]:
        try:
            stake = f"NT$ {float(ticket.get('stake') or 0):,.0f}"
        except (TypeError, ValueError, OverflowError):
            stake = "金額未提供"
        raw_status = str(ticket.get("status") or "UNKNOWN").upper()
        detail = f"本站記錄 · {ticket.get('sports_summary') or ticket.get('parlay_name') or '注單'} · {status_labels.get(raw_status, raw_status)} · 注金 {stake}"
        payout = ticket.get("actual_payout", ticket.get("gross_payout"))
        if payout is not None and raw_status in {"WON", "SETTLED"}:
            try:
                detail += f" · 本站派彩 NT$ {float(payout):,.0f}"
            except (TypeError, ValueError, OverflowError):
                pass
        settled_at = ticket.get("settled_at") or ticket.get("updated_at")
        if settled_at:
            detail += f" · 時間 {settled_at}"
        rows.append(detail)
    if not recent_tickets:
        rows.append("近期沒有已結算的本站注單記錄。")
    link = system_deep_link(system_url, "wallet", profile_id=profile_id)
    footer = [_uri_button("開啟主系統 Wallet", link)] if link else []
    alt = f"本站 Wallet 摘要：可用 {money('weekly_wallet_balance')}，獲利保留池 {money('prize_pool')}，歷史淨利 {money('lifetime_net_profit')}。本站記錄不代表官方投注。"
    return flex_message(alt, _bubble("資產戰績", "僅顯示已綁定 Profile 的本站帳務摘要", rows, footer, accent="#176B55"))


def build_notification_flex(preferences: dict[str, bool]) -> dict[str, Any]:
    labels = {
        "steam_drop": "重要賠率變動",
        "ticket_settlement": "本站注單結算",
        "hedging_alert": "聽牌／對沖提醒",
        "morning_radar": "每日 Radar 摘要",
    }
    rows = [f"{name}：{'開啟' if preferences.get(key, True) else '關閉'}" for key, name in labels.items()]
    actions = [
        _message_button("開啟全部通知", "通知 全部 開啟"),
        _message_button("關閉全部通知", "通知 全部 關閉", color="#64748B"),
    ]
    alt = "Sportslottery LINE 通知設定。" + "；".join(rows)
    return flex_message(alt, _bubble("通知設定", "設定只套用於目前已綁定的 Profile", rows, actions, accent="#176B55"))


def build_manual_slip_flex(text: str, *, official_url: str = TAIWAN_LOTTERY_URL) -> dict[str, Any]:
    rows = str(text or "").splitlines()[:24]
    footer = [_uri_button("開啟台灣運彩官方投注頁", official_url)]
    alt = "本站投注單明細供人工核對；本站自製 QR 未驗證為官方出票格式。請到官方投注頁重新核對資料。"
    return flex_message(alt, _bubble("投注單明細", "本站整理資料；非官方投注 QR 或出票憑證", rows, footer, accent="#64748B"))


def build_status_flex(title: str, subtitle: str, rows: list[str], *, system_url: str | None = None, tab: str = "radar") -> dict[str, Any]:
    footer = []
    link = system_deep_link(system_url, tab)
    if link:
        footer.append(_uri_button("開啟主系統", link))
    alt = f"{title}。" + "；".join(rows[:8])
    return flex_message(alt, _bubble(title, subtitle, rows, footer))
