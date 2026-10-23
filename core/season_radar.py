#!/usr/bin/env python3
"""Season Radar (賽季雷達 - v3 Revision).

Determines league activity using live ESPN schedules AND Taiwan Sports Lottery availability:
- 🟢 Green: In season AND Taiwan Sports Lottery has open betting markets today!
- 🟡 Yellow: In season (confirmed by ESPN schedule/calendar), BUT Taiwan Sports Lottery currently has no open markets.
- 🔴 Red: Off-season or no upcoming games.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from integrations.common.models import TaiwanLeg
from integrations.schedules.espn_schedule import ESPNScheduleAdapter
from core.identity.league_mapping import normalize_league_and_sport

logger = logging.getLogger(__name__)


class SeasonRadar:
    """Monitors live sport seasons and Taiwan Sports Lottery market availability."""

    LEAGUES = {
        "MLB": {
            "name": "MLB (美國職棒)",
            "sport": "baseball",
            "icon": "⚾",
            "playsport_aid": "1",
            "espn_code": "MLB",
            "default_season": (3, 11),
        },
        "NFL": {
            "name": "NFL (美式足球)",
            "sport": "football",
            "icon": "🏈",
            "playsport_aid": "93",
            "espn_code": "NFL",
            "default_season": (9, 2),
        },
        "PREMIER": {
            "name": "英超 (Premier League)",
            "sport": "soccer",
            "icon": "⚽",
            "playsport_aid": "4",
            "espn_code": "PREMIER",
            "default_season": (8, 5),
        },
        "LALIGA": {
            "name": "西甲 (LaLiga)",
            "sport": "soccer",
            "icon": "⚽",
            "playsport_aid": "4",
            "espn_code": "LALIGA",
            "default_season": (8, 5),
        },
        "CHAMPIONS": {
            "name": "歐冠 (Champions League)",
            "sport": "soccer",
            "icon": "⚽",
            "playsport_aid": "4",
            "espn_code": "CHAMPIONS",
            "default_season": (9, 6),
        },
        "CPBL": {
            "name": "中華職棒",
            "sport": "baseball",
            "icon": "⚾",
            "playsport_aid": "6",
            "espn_code": None,
            "default_season": (3, 10),
        },
        "NPB": {
            "name": "日本職棒",
            "sport": "baseball",
            "icon": "⚾",
            "playsport_aid": "2",
            "espn_code": None,
            "default_season": (3, 11),
        },
        "NBA": {
            "name": "NBA (美國職籃)",
            "sport": "basketball",
            "icon": "🏀",
            "playsport_aid": "3",
            "espn_code": "NBA",
            "default_season": (10, 6),
        },
        "WNBA": {
            "name": "WNBA (美國女子職籃)", "sport": "basketball", "icon": "🏀",
            "playsport_aid": "7", "espn_code": "WNBA", "default_season": (5, 10),
        },
        "KBO": {
            "name": "韓國職棒", "sport": "baseball", "icon": "⚾",
            "playsport_aid": "9", "espn_code": None, "default_season": (3, 11),
        },
        "NHL": {
            "name": "NHL (國家冰球)",
            "sport": "hockey",
            "icon": "🏒",
            "playsport_aid": "87",
            "espn_code": "NHL",
            "default_season": (10, 6),
        },
        "TPBL": {
            "name": "台灣職籃 (TPBL/PLG)",
            "sport": "basketball",
            "icon": "🏀",
            "playsport_aid": None,
            "espn_code": None,
            "default_season": (10, 5),
        },
    }

    def __init__(self, espn_adapter: Optional[ESPNScheduleAdapter] = None):
        self.espn = espn_adapter or ESPNScheduleAdapter()

    def get_radar_summary(
        self,
        taiwan_legs: Optional[List[TaiwanLeg]] = None,
        live_matches: Optional[List[Dict[str, Any]]] = None,
        check_live_espn: bool = False,
        evaluated_legs: Optional[List[Any]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Determine radar status prioritizing Taiwan Sports Lottery market availability."""
        evaluated_legs = evaluated_legs or kwargs.get("evaluated_legs")
        current_month = date.today().month

        # Group Taiwan legs by sport/league
        taiwan_games_by_aid: Dict[str, set] = {}
        games_by_league: Dict[str, List[Dict[str, Any]]] = {}

        if taiwan_legs:
            for l in taiwan_legs:
                raw = str(l.league).strip()
                code = raw.upper() if raw.upper() in self.LEAGUES else normalize_league_and_sport(raw)[0]
                if code in self.LEAGUES:
                    taiwan_games_by_aid.setdefault(code, set()).add(l.canonical_event_id or l.event_id)

        if live_matches:
            for m in live_matches:
                aid = str(m.get("alliance_id", ""))
                league_str = str(m.get("canonical_league") or m.get("league") or "")
                mid = str(m.get("match_id", id(m)))
                code = (league_str.upper() if league_str.upper() in self.LEAGUES
                        else normalize_league_and_sport(league_str, aid)[0])
                if code in self.LEAGUES:
                    taiwan_games_by_aid.setdefault(code, set()).add(mid)
                    games_by_league.setdefault(code, []).append(m)

        # Count opportunity metrics by league
        opportunities_by_league: Dict[str, Dict[str, int]] = {}
        all_eval_legs = evaluated_legs or [l for l in (taiwan_legs or []) if getattr(l, "signal_evidence", None)]
        if all_eval_legs:
            for leg in all_eval_legs:
                raw_league = str(getattr(leg, "league", "")).strip()
                code = raw_league.upper() if raw_league.upper() in self.LEAGUES else normalize_league_and_sport(raw_league)[0]
                if code not in self.LEAGUES:
                    continue
                ev_data = getattr(leg, "signal_evidence", {}) or {}
                if isinstance(leg, dict):
                    ev_data = leg.get("signal_evidence", leg)

                stats = opportunities_by_league.setdefault(code, {"positive_ev": 0, "banker": 0, "high_agreement": 0})
                is_pos_ev = bool(ev_data.get("is_positive_ev") or ev_data.get("is_sharp_value_bet") or (ev_data.get("expected_value", 0) > 0))
                prob = float(ev_data.get("consensus_probability") or ev_data.get("market_fair_probability") or 0.0)
                odds = float(getattr(leg, "taiwan_odds", 0.0) or (ev_data.get("taiwan_odds", 0.0) if isinstance(ev_data, dict) else 0.0))
                agreement = getattr(leg, "signal_agreement", "") or ev_data.get("signal_agreement", "")

                if is_pos_ev:
                    stats["positive_ev"] += 1
                if 1.25 <= odds <= 2.05 and prob >= 0.52 and (is_pos_ev or ev_data.get("expected_value", 0) >= -0.02):
                    stats["banker"] += 1
                if agreement == "HIGH":
                    stats["high_agreement"] += 1

        summary: List[Dict[str, Any]] = []

        for code, info in self.LEAGUES.items():
            start_m, end_m = info["default_season"]
            if start_m <= end_m:
                in_season_calendar = (start_m <= current_month <= end_m)
            else:
                in_season_calendar = (current_month >= start_m or current_month <= end_m)

            # 1. Check Taiwan Sports Lottery actual games
            active_taiwan_event_ids = taiwan_games_by_aid.get(code, set())
            taiwan_market_count = len(active_taiwan_event_ids)

            # 2. Check ESPN schedule if enabled
            espn_event_count = 0
            schedule_observation = {"source_status":"NOT_CHECKED","error":None}
            if check_live_espn and info["espn_code"]:
                try:
                    reader = getattr(self.espn, "fetch_live_events_with_status", None)
                    if callable(reader):
                        schedule_observation = reader(info["espn_code"])
                        events = schedule_observation["events"]
                    else:
                        events = self.espn.fetch_live_events(info["espn_code"])
                        schedule_observation = {"source_status":"UNKNOWN","error":None}
                    espn_event_count = len(events)
                except Exception as exc:
                    schedule_observation = {"source_status":"FETCH_ERROR","error":str(exc)}

            # Highest Rule: GREEN ONLY IF Taiwan Sports Lottery has open markets today!
            if taiwan_market_count > 0:
                status = "GREEN"
                status_text = f"進行中 · 台彩今日開盤 ({taiwan_market_count}場)"
                light_emoji = "🟢"
            elif in_season_calendar or espn_event_count > 0:
                status = "YELLOW"
                status_text = "賽季中 · 今日台彩無開盤"
                light_emoji = "🟡"
            else:
                status = "RED"
                status_text = "休賽季"
                light_emoji = "🔴"
            if taiwan_market_count == 0 and schedule_observation["source_status"] == "FETCH_ERROR":
                status, status_text, light_emoji = "UNKNOWN", "賽程來源取得失敗，賽事狀態未知", "⚪"

            opps = opportunities_by_league.get(code, {"positive_ev": 0, "banker": 0, "high_agreement": 0})
            pos_ev_cnt = opps["positive_ev"]
            banker_cnt = opps["banker"]
            high_agr_cnt = opps["high_agreement"]

            opp_badge = ""
            if pos_ev_cnt > 0 and banker_cnt > 0:
                opp_badge = f"🔥 {pos_ev_cnt} 場 +EV | 🛡️ {banker_cnt} 場穩健"
            elif pos_ev_cnt > 0:
                opp_badge = f"🔥 {pos_ev_cnt} 場 +EV 價值機會"
            elif banker_cnt > 0:
                opp_badge = f"🛡️ {banker_cnt} 場高勝率穩健候選"
            elif high_agr_cnt > 0:
                opp_badge = f"✨ {high_agr_cnt} 場 HIGH 跨源共識"
            elif taiwan_market_count > 0:
                opp_badge = "⚡ 盤口已開出"

            summary.append({
                "code": code,
                "name": info["name"],
                "icon": info["icon"],
                "status": status,
                "status_text": status_text,
                "light_emoji": light_emoji,
                "game_count": taiwan_market_count,
                "taiwan_market_count": taiwan_market_count,
                "espn_event_count": espn_event_count,
                "schedule_source_status":schedule_observation["source_status"],
                "schedule_source_error":schedule_observation.get("error"),
                "in_season_calendar": in_season_calendar,
                "games": games_by_league.get(code, []),
                "positive_ev_count": pos_ev_cnt,
                "banker_count": banker_cnt,
                "high_agreement_count": high_agr_cnt,
                "opportunity_badge": opp_badge,
            })

        return summary
