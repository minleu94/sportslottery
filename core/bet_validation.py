"""One readiness policy shared by recommendation search, UI and recording.

Manual historical records are a separate workflow. Unknown timestamps never
become a claim that a recommendation is currently available for placement.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

MAX_ODDS_AGE = timedelta(minutes=15)
MAX_CLOCK_SKEW = timedelta(minutes=2)
REASON_LABELS = {
    "ODDS_INVALID": "賠率無效",
    "ODDS_STALE": "盤口資料已過期",
    "ODDS_TIME_UNKNOWN": "盤口抓取時間未知",
    "ODDS_TIME_FUTURE": "盤口時間在未來，需重新核對",
    "START_TIME_UNKNOWN": "開賽時間未知",
    "EVENT_STARTED": "賽事已開賽",
    "LINE_UNKNOWN": "讓分或大小門檻不完整",
    "MARKET_UNSUPPORTED": "尚未支援此玩法",
    "EVENT_ID_UNKNOWN": "賽事識別不足",
    "EVENT_IDENTITY_INCOMPLETE": "主客隊識別不完整，不能推薦",
    "DUPLICATE_EVENT": "同場賽事不可重複串入",
}


def parse_aware_time(value: Any) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _get(leg: Any, key: str, default: Any = None) -> Any:
    return leg.get(key, default) if isinstance(leg, Mapping) else getattr(leg, key, default)


def event_key(leg: Any) -> str:
    """Prefer canonical identity; scope local ids by competition and start date."""
    canonical = _get(leg, "canonical_event_id")
    if canonical:
        return str(canonical)
    local_id = _get(leg, "event_id") or _get(leg, "match_id")
    start = parse_aware_time(_get(leg, "start_time_utc"))
    sport, league = _get(leg, "sport"), _get(leg, "league")
    return f"{sport}:{league}:{local_id}:{start.isoformat() if start else 'unknown'}" if local_id and sport and league else ""


def has_complete_team_identity(leg: Any) -> bool:
    """Check source team fields; registry canonicalization is a separate concern."""
    placeholders = {"", "客隊", "主隊", "未知", "unknown", "away", "home", "tbd", "待定"}
    def normalize(value: Any) -> str:
        return re.sub(r"[\s()（）\[\]【】,，.。_-]+", "", str(value or "")).casefold()
    away = normalize(_get(leg, "away_team"))
    home = normalize(_get(leg, "home_team"))
    return away not in placeholders and home not in placeholders and away != home


def assess_leg(leg: Any, now: Any = None) -> dict[str, Any]:
    current = parse_aware_time(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        raise ValueError("核對時間必須包含有效時區。")
    reasons = []
    raw_odds = _get(leg, "taiwan_odds", _get(leg, "odds"))
    try:
        odds = float(raw_odds)
        if not math.isfinite(odds) or odds <= 1:
            reasons.append("ODDS_INVALID")
    except (ValueError, TypeError):
        reasons.append("ODDS_INVALID")
    if not event_key(leg):
        reasons.append("EVENT_ID_UNKNOWN")
    evidence = _get(leg, "signal_evidence", {}) or {}
    if ((isinstance(evidence, Mapping) and evidence.get("identity_incomplete"))
            or not has_complete_team_identity(leg)):
        reasons.append("EVENT_IDENTITY_INCOMPLETE")
    start = parse_aware_time(_get(leg, "start_time_utc"))
    if start is None:
        reasons.append("START_TIME_UNKNOWN")
    elif start <= current:
        reasons.append("EVENT_STARTED")
    observed = parse_aware_time(_get(leg, "odds_scraped_at"))
    if observed is None:
        reasons.append("ODDS_TIME_UNKNOWN")
    elif observed - current > MAX_CLOCK_SKEW:
        reasons.append("ODDS_TIME_FUTURE")
    elif current - observed > MAX_ODDS_AGE:
        reasons.append("ODDS_STALE")
    if _get(leg, "odds_status", "UNKNOWN") not in {"LIVE", "FRESH"} and "ODDS_STALE" not in reasons:
        reasons.append("ODDS_STALE")
    market = _get(leg, "market", _get(leg, "market_type", ""))
    if market not in {"不讓分", "獨贏", "和局", "讓分", "大小"}:
        reasons.append("MARKET_UNSUPPORTED")
    if market in {"讓分", "大小"}:
        try:
            if not math.isfinite(float(_get(leg, "line"))):
                reasons.append("LINE_UNKNOWN")
        except (ValueError, TypeError):
            reasons.append("LINE_UNKNOWN")
    return {"is_ready": not reasons, "reasons": reasons, "messages": [REASON_LABELS[r] for r in reasons]}


def validate_recommendation_legs(legs: list[dict[str, Any]], now: Any = None) -> None:
    if not legs:
        raise ValueError("推薦注單必須包含關卡。")
    keys = []
    errors = []
    for index, leg in enumerate(legs, 1):
        assessment = assess_leg(leg, now)
        if not assessment["is_ready"]:
            errors.append(f"關卡 {index}：{'、'.join(assessment['messages'])}")
        keys.append(event_key(leg))
    if len(keys) != len(set(keys)):
        errors.append(REASON_LABELS["DUPLICATE_EVENT"])
    if errors:
        raise ValueError("推薦目前無法記錄：" + "；".join(errors))

def validate_manual_legs(legs: list[dict[str, Any]], default_odds: float | None = None) -> None:
    """Validate legs for manual accounting / bookkeeping.

    Permits historical / past matches and unobserved odds timestamps (for recording
    wagers already made at the kiosk), but strictly validates odds (> 1.0), leg count (1~8),
    and basic team/selection metadata.
    """
    if not legs:
        raise ValueError("手動記帳注單必須包含至少 1 個賽事關卡。")
    if len(legs) > 8:
        raise ValueError("串關關卡數量不可超過 8 關。")

    errors: list[str] = []
    for index, leg in enumerate(legs, 1):
        raw_odds = _get(leg, "taiwan_odds", _get(leg, "odds", default_odds))
        if raw_odds is None and default_odds is not None:
            raw_odds = default_odds

        if raw_odds is not None:
            try:
                odds = float(raw_odds)
                if not math.isfinite(odds) or odds <= 1.0:
                    errors.append(f"關卡 {index} 賠率無效 ({raw_odds})，必須大於 1.0。")
            except (ValueError, TypeError):
                errors.append(f"關卡 {index} 賠率格式錯誤 ({raw_odds})。")
        else:
            errors.append(f"關卡 {index} 缺少有效賠率。")

        market = str(_get(leg, "market", _get(leg, "market_type", _get(leg, "play_type", ""))) or "").strip()
        selection = str(_get(leg, "selection", _get(leg, "side", _get(leg, "recommend_side", ""))) or "").strip()
        home = str(_get(leg, "home_team", "") or "").strip()
        away = str(_get(leg, "away_team", "") or "").strip()
        team = str(_get(leg, "team", "") or "").strip()
        event = str(_get(leg, "event_id", _get(leg, "match_id", _get(leg, "game_id", ""))) or "").strip()
        league = str(_get(leg, "league", _get(leg, "alliance", _get(leg, "sport", ""))) or "").strip()

        has_bet_spec = bool(selection or market)
        has_event_spec = bool(home or away or team or event)

        if not has_bet_spec:
            # Allow pure league-level placeholder records (e.g. {"league": "NBA"}) for generic bookkeeping
            if not (league and not has_event_spec):
                errors.append(f"關卡 {index} 缺少投注選項或玩法資訊。")

        if not has_event_spec and not league:
            errors.append(f"關卡 {index} 缺少賽事識別或隊伍名稱。")

        if market in {"讓分", "大小", "spread", "totals"}:
            line_val = _get(leg, "line")
            if line_val is not None and str(line_val).strip() != "":
                try:
                    line_f = float(line_val)
                    if not math.isfinite(line_f):
                        errors.append(f"關卡 {index} 門檻數值 ({line_val}) 無效。")
                except (ValueError, TypeError):
                    errors.append(f"關卡 {index} 門檻數值 ({line_val}) 格式錯誤。")

    if errors:
        raise ValueError("手動注單驗證失敗：" + "；".join(errors))

