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
    ) -> List[Dict[str, Any]]:
        """Determine radar status prioritizing Taiwan Sports Lottery market availability."""
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
            })

        return summary
