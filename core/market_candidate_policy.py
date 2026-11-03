"""Pure eligibility rules for Taiwan market candidates.

Provider access and cycle accounting stay in ``MarketForwardPipeline``. This
module decides whether one already-fetched Taiwan leg is sufficiently complete
to request and compare an international quote.
"""

from __future__ import annotations

import math
from typing import Callable, Mapping, Optional

from core.bet_validation import parse_aware_time
from core.identity.league_mapping import normalize_league_and_sport
from integrations.common.models import TaiwanLeg


def candidate_rejection_reason(
    leg: TaiwanLeg,
    query_league: str,
    target_markets: str,
    *,
    market_to_api: Mapping[str, str],
    query_key_resolver: Callable[[str], Optional[str]],
) -> Optional[str]:
    """Return an explicit reason when a Taiwan leg cannot enter market analysis."""
    if not str(leg.event_id or "").strip():
        return "MISSING_EVENT_ID"
    if str(getattr(leg, "odds_status", "UNKNOWN") or "UNKNOWN").upper() not in {"LIVE", "FRESH"}:
        return "TAIWAN_ODDS_NOT_FRESH"
    if bool(getattr(leg, "is_synthetic", False)) or bool(
        (getattr(leg, "signal_evidence", None) or {}).get("is_synthetic")
    ):
        return "SYNTHETIC_TAIWAN_ODDS"
    if parse_aware_time(leg.start_time_utc) is None:
        return "INVALID_OR_MISSING_START_TIME"

    leg_key = query_key_resolver(leg.league)
    target_label = str(query_league or "").strip().upper()
    target_key = query_key_resolver(query_league)
    if not target_key or not leg_key:
        return "UNSUPPORTED_OR_MISMATCHED_LEAGUE"
    if target_label == "SOCCER":
        if not leg_key.startswith("soccer_") or str(leg.league or "").strip().upper() == "SOCCER":
            return "UNSUPPORTED_OR_MISMATCHED_LEAGUE"
    elif target_key != leg_key:
        return "UNSUPPORTED_OR_MISMATCHED_LEAGUE"

    key_to_sport = {
        "baseball": "baseball",
        "basketball": "basketball",
        "americanfootball": "football",
        "soccer": "soccer",
    }
    expected_sport = key_to_sport.get(leg_key.split("_")[0])
    supplied_sport = str(leg.sport or "").strip().casefold().replace(" ", "")
    if supplied_sport in {"americanfootball", "football"}:
        supplied_sport = "football"
    if not expected_sport or supplied_sport != expected_sport:
        return "SPORT_LEAGUE_MISMATCH"

    if not str(leg.home_team or "").strip() or not str(leg.away_team or "").strip():
        return "MISSING_TEAMS"
    if str(leg.home_team).strip() in {"主隊", "主队"} or str(leg.away_team).strip() in {"客隊", "客队"}:
        return "MISSING_TEAMS"
    if not str(leg.selection or "").strip():
        return "MISSING_SELECTION"

    api_market = market_to_api.get(str(leg.market or "").strip().casefold())
    if not api_market:
        return "UNSUPPORTED_MARKET"
    requested = {
        part.strip().casefold()
        for part in str(target_markets or "").split(",")
        if part.strip()
    }
    if api_market not in requested:
        return "MARKET_NOT_ALLOWED"

    side = str(leg.side or "").strip().casefold()
    valid_sides = {
        "h2h": {"主", "客", "和", "home", "away", "draw"},
        "spreads": {"主", "客", "home", "away"},
        "totals": {"大", "小", "大分", "小分", "over", "under"},
    }
    if side not in valid_sides[api_market]:
        return "INVALID_SELECTION_SIDE"
    if api_market in {"spreads", "totals"}:
        try:
            if leg.line is None or not math.isfinite(float(leg.line)):
                return "MISSING_OR_INVALID_LINE"
        except (TypeError, ValueError, OverflowError):
            return "MISSING_OR_INVALID_LINE"
    try:
        odds = float(leg.taiwan_odds)
    except (TypeError, ValueError, OverflowError):
        return "INVALID_TAIWAN_ODDS"
    if not math.isfinite(odds) or odds <= 1.0:
        return "INVALID_TAIWAN_ODDS"
    return None


def canonical_league_query_key(league: str, sport_key_map: Mapping[str, str]) -> Optional[str]:
    """Resolve a provider-supported competition key without creating a client."""
    raw = str(league or "").strip()
    key = sport_key_map.get(raw.upper()) or sport_key_map.get(raw.lower())
    if key:
        return key
    canonical_aliases = {
        "PREMIER": "EPL",
        "LALIGA": "LALIGA",
        "CHAMPIONS": "CHAMPIONS_LEAGUE",
    }
    if raw.upper() in canonical_aliases:
        return sport_key_map.get(canonical_aliases[raw.upper()])
    canonical, _ = normalize_league_and_sport(raw)
    alias = canonical_aliases.get(canonical)
    return sport_key_map.get(alias) if alias else None
