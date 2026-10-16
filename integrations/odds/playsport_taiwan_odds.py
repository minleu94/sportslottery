#!/usr/bin/env python3
"""Playsport Taiwan Sports Lottery Odds Adapter (Layer A - Core Market).

Fetches genuine Taiwan Sports Lottery odds from playsport.cc mirrors,
normalizes markets into standard TaiwanLeg objects.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
import time
from typing import Any, Dict, List, Optional

from core.scraper import PlaysportScraper
from core.identity.timezone import TAIPEI_TZ
from integrations.common.models import TaiwanLeg

logger = logging.getLogger(__name__)

SPORT_LEAGUE_MAP = {
    "1": ("baseball", "MLB"),
    "4": ("soccer", "足球"),
    "3": ("basketball", "NBA"),
    "7": ("basketball", "WNBA"),
    "2": ("baseball", "NPB (日棒)"),
    "6": ("baseball", "CPBL (中職)"),
    "9": ("baseball", "KBO (韓棒)"),
    "87": ("hockey", "NHL"),
    "93": ("football", "NFL"),
}


class PlaysportOddsAdapter:
    """Extracts genuine Taiwan Sports Lottery markets and odds."""

    def __init__(self, scraper: Optional[PlaysportScraper] = None):
        self.scraper = scraper or PlaysportScraper()

    def get_source_status(self) -> Dict[str, Dict[str, Any]]:
        getter = getattr(self.scraper, "get_scale_source_status", None)
        return getter() if callable(getter) else {}

    def get_taiwan_legs(
        self,
        alliance_ids: Optional[List[str]] = None,
        force_refresh: bool = False,
    ) -> List[TaiwanLeg]:
        """Fetch active matches and transform into validated TaiwanLeg betting selections."""
        aids = alliance_ids or ["1", "2", "3", "4", "6", "7", "9", "93"]
        legs: List[TaiwanLeg] = []

        for aid in aids:
            sport, default_league = SPORT_LEAGUE_MAP.get(aid, ("unknown", f"聯盟_{aid}"))
            matches = self.scraper.fetch_scale_matches(alliance_id=aid, force_refresh=force_refresh)

            def normalized_team(value: Any) -> str:
                return re.sub(r"[\s()（）\[\]【】,，.。_-]+", "", str(value or "")).casefold()

            def taipei_day(match: Dict[str, Any]) -> Optional[str]:
                value = match.get("start_time_utc")
                if value:
                    try:
                        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                        if stamp.tzinfo is None:
                            return None
                        return stamp.astimezone(TAIPEI_TZ).date().isoformat()
                    except (ValueError, TypeError):
                        return None
                game_time_value = str(match.get("game_time", ""))
                date_match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", game_time_value)
                return date_match.group(1).replace("/", "-") if date_match else None

            team_day_counts: Dict[tuple, int] = {}
            for candidate in matches:
                key = (normalized_team(candidate.get("away_team")), normalized_team(candidate.get("home_team")),
                       taipei_day(candidate))
                team_day_counts[key] = team_day_counts.get(key, 0) + 1

            for m in matches:
                event_id = str(m.get("match_id", ""))
                event_sport = str(m.get("sport") or sport)
                league = str(m.get("league", default_league))
                game_time = str(m.get("game_time", "今日賽程"))
                away = str(m.get("away_team", "客隊"))
                home = str(m.get("home_team", "主隊"))
                team_day_key = (normalized_team(away), normalized_team(home), taipei_day(m))
                same_team_day_event_count = team_day_counts.get(team_day_key, 1)
                identity_ambiguous = same_team_day_event_count > 1

                now_t = time.time()
                cached_at = m.get("_cached_at")
                cached_iso = m.get("_cached_iso")
                age_minutes = max(0.0, round((now_t - float(cached_at)) / 60.0, 1)) if cached_at is not None else None

                cache_status = m.get("_cache_status")
                identity_incomplete = bool(m.get("_identity_incomplete"))
                if m.get("_is_stale_cache") or cache_status == "STALE_CACHE" or (age_minutes is not None and age_minutes > 15.0):
                    odds_status = "STALE_CACHE"
                elif cache_status == "LIVE":
                    odds_status = "LIVE" if age_minutes is not None and age_minutes <= 1.0 else "FRESH"
                elif cache_status == "CACHED" and age_minutes is not None:
                    odds_status = "FRESH" if age_minutes <= 15.0 else "STALE_CACHE"
                elif cache_status == "UNKNOWN":
                    odds_status = "UNKNOWN"
                elif age_minutes is not None and age_minutes <= 15.0:
                    odds_status = "LIVE" if age_minutes <= 1.0 else "FRESH"
                else:
                    odds_status = "UNKNOWN"

                options = [opt for opt in m.get("options", []) if float(opt.get("odds", 0) or 0) > 1.0]
                outcome_groups: Dict[tuple, Dict[str, float]] = {}
                for outcome in options:
                    market_name = str(outcome.get("market_type", "不讓分"))
                    side_name = str(outcome.get("side", ""))
                    raw_line = outcome.get("line")
                    # Two team handicaps are opposite signed descriptions of the same spread.
                    try:
                        group_line = abs(float(raw_line)) if market_name == "讓分" and raw_line is not None else (
                            float(raw_line) if raw_line is not None else None)
                    except (TypeError, ValueError):
                        group_line = str(raw_line).strip() if raw_line is not None else None
                    # The soccer draw is a third outcome of the same 1X2
                    # market, even though Playsport labels its row 和局.
                    group_market = ("足球三向" if event_sport == "soccer" and
                                    market_name in {"不讓分", "和局", "獨贏"} else market_name)
                    group_key = (group_market, group_line)
                    if side_name:
                        outcome_groups.setdefault(group_key, {})[side_name] = float(outcome["odds"])

                for opt in options:
                    taiwan_odds = float(opt.get("odds", 0.0))
                    if taiwan_odds <= 1.0:
                        continue

                    market = str(opt.get("market_type", "不讓分"))
                    selection = str(opt.get("selection", ""))
                    side = str(opt.get("side", "客"))
                    line = opt.get("line")
                    try:
                        outcome_line = abs(float(line)) if market == "讓分" and line is not None else (
                            float(line) if line is not None else None)
                    except (TypeError, ValueError):
                        outcome_line = str(line).strip() if line is not None else None
                    group_market = ("足球三向" if event_sport == "soccer" and
                                    market in {"不讓分", "和局", "獨贏"} else market)
                    market_outcome_odds = outcome_groups.get((group_market, outcome_line), {})
                    market_outcome_sources = {
                        outcome_side: {
                            "odds": outcome_price,
                            "source_url": f"https://www.playsport.cc/predict/scale?allianceid={aid}",
                            "observed_at": cached_iso,
                            "source_status": odds_status,
                        }
                        for outcome_side, outcome_price in market_outcome_odds.items()
                    }
                    expected_sides = ({"客", "和", "主"} if event_sport == "soccer" and
                                      market in {"不讓分", "和局", "獨贏"} else
                                      {"客", "主"} if market in ("讓分", "不讓分") else
                                      {"大", "小"} if market == "大小" else set())
                    market_complete = bool(expected_sides) and expected_sides.issubset(market_outcome_odds)

                    leg = TaiwanLeg(
                        event_id=event_id,
                        canonical_event_id=m.get("canonical_event_id"),
                        sport=event_sport,
                        league=league,
                        market=market,
                        selection=selection,
                        taiwan_odds=taiwan_odds,
                        start_time=game_time,
                        start_time_utc=m.get("start_time_utc"),
                        away_team=away,
                        home_team=home,
                        away_pitcher=m.get("away_pitcher"),
                        home_pitcher=m.get("home_pitcher"),
                        odds_scraped_at=cached_iso,
                        odds_age_minutes=age_minutes,
                        odds_status=odds_status,
                        side=side,
                        line=line,
                        signal_evidence={
                            "source": "playsport_taiwan_odds",
                            "source_url": f"https://www.playsport.cc/predict/scale?allianceid={aid}",
                            "market_type": market,
                            "consensus_ratio": opt.get("consensus_ratio"),
                            "vote_count": opt.get("vote_count"),
                            "odds": taiwan_odds,
                            "market_outcome_odds": market_outcome_odds,
                            "market_outcome_sources": market_outcome_sources,
                            "market_outcome_line": outcome_line,
                            "market_complete": market_complete,
                            "same_team_day_event_count": same_team_day_event_count,
                            "identity_ambiguous": identity_ambiguous,
                            "identity_incomplete": identity_incomplete,
                            "identity_source": m.get("_identity_source"),
                            "identity_diagnostic": m.get("_identity_diagnostic"),
                            "source_cache_status": cache_status,
                            "source_failure_status": m.get("_failure_status"),
                            "source_error": m.get("_source_error"),
                            "source_status": m.get("_cache_status"),
                            "odds_scraped_at": cached_iso,
                            "odds_age_minutes": age_minutes,
                            "odds_status": odds_status,
                            "crowd_snapshot_timestamp": cached_iso,
                            "crowd_age_minutes": age_minutes,
                        },
                    )
                    if identity_incomplete:
                        leg.eligible_for_parlay = False
                    legs.append(leg)

        return legs
