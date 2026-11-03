#!/usr/bin/env python3
"""Precision Event & Market Alignment Engine.

Milestone 2 of Phase 4: Global Market Intelligence & Prediction Quality Upgrade.

Strictly enforces:
1. Team aliases & multi-lingual name resolution (Traditional Chinese, English, Abbreviations)
2. Home / Away direction consistency (US format Away@Home vs Soccer/Taiwan format Home vs Away)
3. UTC / Taiwan Time & DST matching within bounded temporal windows
4. Market equivalence verification (Moneyline, Spread, Total)
5. Exact handicap & threshold comparison (Line -1.5 cannot compare with Line -2.5)
6. Pre-match validity & staleness rejection
7. Explicit audit statuses: MATCHED, AMBIGUOUS, UNMATCHED, STALE, MARKET_NOT_EQUIVALENT
"""

from __future__ import annotations

import difflib
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from core.contracts.common import TaiwanLeg
from core.identity.league_mapping import normalize_league_and_sport
from core.identity.team_alias import GLOBAL_TEAM_REGISTRY
from core.contracts.market import (
    MarketAlignmentRecord,
    MarketAlignmentStatus,
    MarketOddsSnapshot,
    MarketSelectionIdentity,
)

logger = logging.getLogger(__name__)


def _normalize_market_league(value: Optional[str], from_odds_api: bool = False) -> Optional[str]:
    """Return a verified competition key, or None when the league is too vague."""
    raw = str(value or "").strip()
    if not raw or raw.upper().startswith("UNKNOWN_"):
        return None

    key = re.sub(r"[\s()（）_\-]+", "", raw).casefold()
    aliases = {
        "epl": "PREMIER",
        "premier": "PREMIER",
        "premierleague": "PREMIER",
        "英超": "PREMIER",
        "laliga": "LALIGA",
        "laligaspain": "LALIGA",
        "西甲": "LALIGA",
        "champions": "CHAMPIONS",
        "championsleague": "CHAMPIONS",
        "champsleague": "CHAMPIONS",
        "uefachampionsleague": "CHAMPIONS",
        "歐冠": "CHAMPIONS",
    }
    if key in aliases:
        return aliases[key]

    if from_odds_api:
        # These are provider query aliases. The Odds API client maps generic
        # sport names to one specific competition (e.g. SOCCER -> soccer_epl).
        api_aliases = {
            "baseball": "MLB",
            "basketball": "NBA",
            "football": "NFL",
            "soccer": "PREMIER",
        }
        if key in api_aliases:
            return api_aliases[key]

    canonical_codes = {
        "MLB", "NBA", "WNBA", "NFL", "NHL", "CPBL", "NPB", "KBO",
        "PREMIER", "LALIGA", "MLS", "CHAMPIONS", "CHAMPIONS_QUALIFYING",
        "COLOMBIA_PRIMERA_A", "COSTA_RICA_PRIMERA", "AFC_CHAMPIONS_LEAGUE_TWO",
        "SAUDI_PRO_LEAGUE", "CONMEBOL_LIBERTADORES",
    }
    if raw.upper() in canonical_codes:
        return raw.upper()

    canonical, _sport = normalize_league_and_sport(raw)
    if canonical == "OTHER" or canonical.startswith("UNKNOWN_"):
        return None
    return canonical


def _parse_utc_datetime(value: Optional[Any]) -> Optional[datetime]:
    """Parse an ISO timestamp only when it carries an explicit timezone."""
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None

# Canonical team dictionary across leagues
# Maps canonical_id -> list of aliases (Chinese Traditional, Simplified, English, Short code)
TEAM_CANONICAL_ALIASES: Dict[str, Dict[str, str]] = {
    "MLB": {
        "lad": "los angeles dodgers",
        "道奇": "los angeles dodgers",
        "洛杉磯道奇": "los angeles dodgers",
        "dodgers": "los angeles dodgers",
        "sd": "san diego padres",
        "教士": "san diego padres",
        "聖地牙哥教士": "san diego padres",
        "padres": "san diego padres",
        "nyy": "new york yankees",
        "洋基": "new york yankees",
        "紐約洋基": "new york yankees",
        "yankees": "new york yankees",
        "bos": "boston red sox",
        "紅襪": "boston red sox",
        "波士頓紅襪": "boston red sox",
        "red sox": "boston red sox",
        "mil": "milwaukee brewers",
        "釀酒人": "milwaukee brewers",
        "密爾瓦基釀酒人": "milwaukee brewers",
        "brewers": "milwaukee brewers",
        "pit": "pittsburgh pirates",
        "海盜": "pittsburgh pirates",
        "匹茲堡海盜": "pittsburgh pirates",
        "pirates": "pittsburgh pirates",
        "bal": "baltimore orioles",
        "金鶯": "baltimore orioles",
        "巴爾的摩金鶯": "baltimore orioles",
        "orioles": "baltimore orioles",
        "tor": "toronto blue jays",
        "藍鳥": "toronto blue jays",
        "多倫多藍鳥": "toronto blue jays",
        "blue jays": "toronto blue jays",
        "hou": "houston astros",
        "太空人": "houston astros",
        "休士頓太空人": "houston astros",
        "astros": "houston astros",
        "phi": "philadelphia phillies",
        "費城人": "philadelphia phillies",
        "費城費城人": "philadelphia phillies",
        "phillies": "philadelphia phillies",
    },
    "NBA": {
        "bos": "boston celtics",
        "塞爾提克": "boston celtics",
        "波士頓塞爾提克": "boston celtics",
        "celtics": "boston celtics",
        "mil": "milwaukee bucks",
        "公鹿": "milwaukee bucks",
        "密爾瓦基公鹿": "milwaukee bucks",
        "bucks": "milwaukee bucks",
        "den": "denver nuggets",
        "金塊": "denver nuggets",
        "丹佛金塊": "denver nuggets",
        "nuggets": "denver nuggets",
        "lal": "los angeles lakers",
        "湖人": "los angeles lakers",
        "洛杉磯湖人": "los angeles lakers",
        "lakers": "los angeles lakers",
        "gsw": "golden state warriors",
        "勇士": "golden state warriors",
        "金州勇士": "golden state warriors",
        "warriors": "golden state warriors",
    },
    "NFL": {
        "kc": "kansas city chiefs",
        "酋長": "kansas city chiefs",
        "堪薩斯酋長": "kansas city chiefs",
        "chiefs": "kansas city chiefs",
        "buf": "buffalo bills",
        "比爾": "buffalo bills",
        "水牛城比爾": "buffalo bills",
        "bills": "buffalo bills",
    },
    "SOCCER": {
        "arsenal": "arsenal",
        "兵工廠": "arsenal",
        "阿森納": "arsenal",
        "chelsea": "chelsea",
        "切爾西": "chelsea",
        "車路士": "chelsea",
        "real madrid": "real madrid",
        "皇馬": "real madrid",
        "皇家馬德里": "real madrid",
        "barcelona": "barcelona",
        "巴塞隆納": "barcelona",
        "巴薩": "barcelona",
        "liverpool": "liverpool",
        "利物浦": "liverpool",
        "manchester city": "manchester city",
        "曼城": "manchester city",
    },
}

# Add alias fallbacks for league synonyms
TEAM_CANONICAL_ALIASES["EPL"] = TEAM_CANONICAL_ALIASES["SOCCER"]
TEAM_CANONICAL_ALIASES["英超"] = TEAM_CANONICAL_ALIASES["SOCCER"]
TEAM_CANONICAL_ALIASES["LALIGA"] = TEAM_CANONICAL_ALIASES["SOCCER"]
TEAM_CANONICAL_ALIASES["西甲"] = TEAM_CANONICAL_ALIASES["SOCCER"]


def normalize_string(val: Optional[str]) -> str:
    if not val:
        return ""
    return re.sub(r"[^\w\s]", "", str(val).lower()).strip()


def resolve_canonical_team(team_str: str, league: str) -> Optional[str]:
    """Resolve a team string (Chinese, English, or Abbr) to a canonical lowercase name."""
    if not team_str:
        return None
    league_key = league.upper().strip()

    alias_dict = TEAM_CANONICAL_ALIASES.get(league_key) or TEAM_CANONICAL_ALIASES.get("SOCCER", {})

    cleaned = normalize_string(team_str)
    # Direct match
    if cleaned in alias_dict:
        return alias_dict[cleaned]

    # Partial/substring match in alias keys
    for k, canonical in alias_dict.items():
        if k in cleaned or cleaned in k:
            return canonical

    # If already an English full name in canonical values
    canonical_values = set(alias_dict.values())
    for c in canonical_values:
        if c in cleaned or cleaned in c:
            return c

    # Fuzzy match with high cutoff
    matches = difflib.get_close_matches(cleaned, list(alias_dict.keys()), n=1, cutoff=0.75)
    if matches:
        return alias_dict[matches[0]]

    # Fall back to the project-wide, sport-scoped alias registry. The legacy
    # market table only covered a handful of NBA/NFL teams, so valid fixtures
    # were rejected before kickoff or market comparison could run.
    canonical_league, sport = normalize_league_and_sport(league_key)
    if sport == "other" and canonical_league == "OTHER" and league_key in {
        "PREMIER", "CHAMPIONS", "CHAMPIONS_QUALIFYING", "MLS", "LALIGA",
        "COLOMBIA_PRIMERA_A", "COSTA_RICA_PRIMERA", "AFC_CHAMPIONS_LEAGUE_TWO",
        "SAUDI_PRO_LEAGUE", "CONMEBOL_LIBERTADORES",
    }:
        sport = "soccer"
        canonical_league = league_key
    if sport != "other" and not canonical_league.startswith("UNKNOWN_"):
        registered = GLOBAL_TEAM_REGISTRY.resolve(
            team_str,
            sport=sport,
            league=canonical_league,
        )
        if registered:
            return registered.canonical_id.casefold()

    return None


def parse_numeric_line(line_str: Optional[Any]) -> Optional[float]:
    """Parse spread or total line into float, handling +, -, or strings like '8.5'."""
    if line_str is None or str(line_str).strip() == "":
        return None
    try:
        val = float(str(line_str).replace("+", "").strip())
        return val if math.isfinite(val) else None
    except (ValueError, TypeError):
        return None


class MarketAligner:
    """Precision alignment engine between TaiwanLeg and International Market Odds."""

    def __init__(self, max_time_delta_seconds: float = 7200.0, max_staleness_seconds: float = 10800.0):
        # 7200 seconds = 2 hours; wider gaps risk matching a different fixture.
        self.max_time_delta = max_time_delta_seconds
        # 10800 seconds = 3 hours staleness
        self.max_staleness = max_staleness_seconds

    def align_leg_with_candidates(
        self,
        leg: TaiwanLeg,
        candidates: List[MarketOddsSnapshot],
        now_utc: Optional[datetime] = None,
    ) -> Tuple[Optional[MarketOddsSnapshot], MarketAlignmentRecord]:
        """Attempt to match a TaiwanLeg to a single, high-fidelity international quote.

        Strictly returns (matched_snapshot, record). If matched_snapshot is None,
        record explains why it was rejected.
        """
        now = now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            now = now.replace(tzinfo=timezone.utc)
        else:
            now = now.astimezone(timezone.utc)
        now_iso = now.isoformat()

        def reject_event_identity(
            rejection_code: str,
            reason: str,
            candidate: Optional[MarketOddsSnapshot] = None,
            time_delta_seconds: Optional[float] = None,
            status: MarketAlignmentStatus = MarketAlignmentStatus.AMBIGUOUS,
        ) -> Tuple[None, MarketAlignmentRecord]:
            record = MarketAlignmentRecord(
                status=status,
                taiwan_event_id=leg.event_id,
                taiwan_league=leg.league,
                taiwan_market=leg.market,
                taiwan_selection=leg.selection,
                taiwan_side=leg.side,
                taiwan_line=leg.line,
                international_event_id=candidate.event_id if candidate else None,
                international_source_id=candidate.source_id if candidate else None,
                international_market_type=candidate.market_type if candidate else None,
                international_selection=candidate.selection if candidate else None,
                international_line=candidate.line if candidate else None,
                aligned_at_utc=now_iso,
                time_delta_seconds=time_delta_seconds,
                reason=reason,
                rejection_code=rejection_code,
            )
            return None, record

        # Step 1: Validate TaiwanLeg basics
        if not leg.league or not leg.market or not leg.taiwan_odds or leg.taiwan_odds <= 1.0:
            rec = MarketAlignmentRecord(
                status=MarketAlignmentStatus.UNMATCHED,
                taiwan_event_id=leg.event_id,
                taiwan_league=leg.league,
                taiwan_market=leg.market,
                taiwan_selection=leg.selection,
                taiwan_side=leg.side,
                taiwan_line=leg.line,
                international_event_id=None,
                international_source_id=None,
                international_market_type=None,
                international_selection=None,
                international_line=None,
                aligned_at_utc=now_iso,
                reason="Taiwan leg missing required fields or has invalid odds <= 1.0",
                rejection_code="ERR_INVALID_TAIWAN_LEG",
            )
            return None, rec

        tw_league = _normalize_market_league(leg.league)
        if not tw_league:
            return reject_event_identity(
                "ERR_LEAGUE_UNKNOWN",
                f"Taiwan competition '{leg.league}' is unresolved; refusing cross-league alignment.",
            )

        tw_start = _parse_utc_datetime(leg.start_time_utc)
        if tw_start is None:
            return reject_event_identity(
                "ERR_EVENT_TIME_UNKNOWN",
                "Taiwan event kickoff is missing, invalid, or has no timezone; refusing to align by team names alone.",
            )

        if not candidates:
            return reject_event_identity(
                "ERR_NO_INTERNATIONAL_QUOTES",
                f"No international quotes were supplied for Taiwan competition '{tw_league}'.",
                status=MarketAlignmentStatus.UNMATCHED,
            )

        # Resolve Taiwan canonical teams within the verified competition family.
        tw_home_canon = resolve_canonical_team(leg.home_team, tw_league)
        tw_away_canon = resolve_canonical_team(leg.away_team, tw_league)

        if not tw_home_canon or not tw_away_canon:
            rec = MarketAlignmentRecord(
                status=MarketAlignmentStatus.UNMATCHED,
                taiwan_event_id=leg.event_id,
                taiwan_league=leg.league,
                taiwan_market=leg.market,
                taiwan_selection=leg.selection,
                taiwan_side=leg.side,
                taiwan_line=leg.line,
                international_event_id=None,
                international_source_id=None,
                international_market_type=None,
                international_selection=None,
                international_line=None,
                aligned_at_utc=now_iso,
                reason=f"Unable to resolve canonical team names for Taiwan teams: '{leg.home_team}' vs '{leg.away_team}' in league '{leg.league}'",
                rejection_code="ERR_TEAM_NOT_FOUND",
            )
            return None, rec

        # Map Taiwan market to standard market_type
        # 讓分 -> SPREAD, 不讓分/獨贏 -> MONEYLINE, 大小 -> TOTAL
        tw_market_type: Optional[str] = None
        if leg.market in {"讓分", "讓球"}:
            tw_market_type = "SPREAD"
        elif leg.market in {"不讓分", "和局", "獨贏", "勝負"}:
            tw_market_type = "MONEYLINE"
        elif leg.market in {"大小", "大小分", "總分"}:
            tw_market_type = "TOTAL"
        else:
            rec = MarketAlignmentRecord(
                status=MarketAlignmentStatus.MARKET_NOT_EQUIVALENT,
                taiwan_event_id=leg.event_id,
                taiwan_league=leg.league,
                taiwan_market=leg.market,
                taiwan_selection=leg.selection,
                taiwan_side=leg.side,
                taiwan_line=leg.line,
                international_event_id=None,
                international_source_id=None,
                international_market_type=None,
                international_selection=None,
                international_line=None,
                aligned_at_utc=now_iso,
                reason=f"Unsupported Taiwan market type: {leg.market}",
                rejection_code="ERR_MARKET_TYPE_MISMATCH",
            )
            return None, rec

        # Filter candidates by competition and team match before comparing kickoff.
        league_candidates = [
            cand for cand in candidates
            if _normalize_market_league(cand.league, from_odds_api=True) == tw_league
        ]
        team_candidates: List[Tuple[MarketOddsSnapshot, bool]] = []
        for cand in candidates:
            if _normalize_market_league(cand.league, from_odds_api=True) != tw_league:
                continue

            cand_home_canon = resolve_canonical_team(cand.home_team, tw_league) or normalize_string(cand.home_team)
            cand_away_canon = resolve_canonical_team(cand.away_team, tw_league) or normalize_string(cand.away_team)

            if tw_home_canon == cand_home_canon and tw_away_canon == cand_away_canon:
                team_candidates.append((cand, True))
            elif tw_home_canon == cand_away_canon and tw_away_canon == cand_home_canon:
                team_candidates.append((cand, False))

        if not team_candidates:
            if not league_candidates:
                rejection_code = "ERR_LEAGUE_MISMATCH"
                reason = f"No international quotes belong to Taiwan competition '{tw_league}'."
            else:
                rejection_code = "ERR_TEAM_NOT_MATCHED"
                reason = f"Same-league quotes exist, but no home/away team pair matched {tw_away_canon} @ {tw_home_canon}."
            rec = MarketAlignmentRecord(
                status=MarketAlignmentStatus.UNMATCHED,
                taiwan_event_id=leg.event_id,
                taiwan_league=leg.league,
                taiwan_market=leg.market,
                taiwan_selection=leg.selection,
                taiwan_side=leg.side,
                taiwan_line=leg.line,
                international_event_id=None,
                international_source_id=None,
                international_market_type=None,
                international_selection=None,
                international_line=None,
                aligned_at_utc=now_iso,
                reason=reason,
                rejection_code=rejection_code,
            )
            return None, rec

        # Group quotes by external event so multiple markets/books do not count
        # as separate events. Every candidate event must have a trustworthy UTC
        # kickoff before it can be considered for identity matching.
        event_groups: Dict[str, List[Tuple[MarketOddsSnapshot, bool]]] = {}
        for item in team_candidates:
            event_groups.setdefault(item[0].event_id, []).append(item)

        timed_events: Dict[str, Tuple[List[Tuple[MarketOddsSnapshot, bool]], float]] = {}
        unknown_time_events: List[List[Tuple[MarketOddsSnapshot, bool]]] = []
        out_of_window: List[Tuple[MarketOddsSnapshot, float]] = []
        for event_quotes in event_groups.values():
            event_times = [_parse_utc_datetime(item[0].start_time_utc) for item in event_quotes]
            if any(event_time is None for event_time in event_times):
                unknown_time_events.append(event_quotes)
                continue
            parsed_times = [event_time for event_time in event_times if event_time is not None]
            kickoff = parsed_times[0]
            if any(abs((candidate_time - kickoff).total_seconds()) > 1.0 for candidate_time in parsed_times[1:]):
                unknown_time_events.append(event_quotes)
                continue
            delta = abs((kickoff - tw_start).total_seconds())
            if delta <= self.max_time_delta:
                timed_events[event_quotes[0][0].event_id] = (event_quotes, delta)
            else:
                out_of_window.append((event_quotes[0][0], delta))

        if unknown_time_events:
            candidate = unknown_time_events[0][0][0]
            return reject_event_identity(
                "ERR_EVENT_TIME_UNKNOWN",
                "A same-league, same-team international candidate has an invalid or inconsistent UTC kickoff.",
                candidate=candidate,
            )

        if not timed_events:
            nearest = min(out_of_window, key=lambda item: item[1]) if out_of_window else None
            return reject_event_identity(
                "ERR_EVENT_TIME_MISMATCH",
                f"Matching teams were found, but no kickoff was within {self.max_time_delta:.0f} seconds of the Taiwan event.",
                candidate=nearest[0] if nearest else None,
                time_delta_seconds=nearest[1] if nearest else None,
            )

        if len(timed_events) > 1:
            nearest_event = min(timed_events.values(), key=lambda item: item[1])
            return reject_event_identity(
                "ERR_EVENT_TIME_AMBIGUOUS",
                "Multiple international event IDs match the same teams, league, and kickoff window; refusing to choose the first.",
                candidate=nearest_event[0][0][0],
                time_delta_seconds=nearest_event[1],
            )

        matched_event_id, (matched_candidates, event_time_delta) = next(iter(timed_events.items()))

        # Check for market type match
        market_cands = [(c, aligned) for (c, aligned) in matched_candidates if c.market_type == tw_market_type]
        if not market_cands:
            rec = MarketAlignmentRecord(
                status=MarketAlignmentStatus.MARKET_NOT_EQUIVALENT,
                taiwan_event_id=leg.event_id,
                taiwan_league=leg.league,
                taiwan_market=leg.market,
                taiwan_selection=leg.selection,
                taiwan_side=leg.side,
                taiwan_line=leg.line,
                international_event_id=matched_candidates[0][0].event_id,
                international_source_id=matched_candidates[0][0].source_id,
                international_market_type=None,
                international_selection=None,
                international_line=None,
                aligned_at_utc=now_iso,
                reason=f"Event found, but requested market '{tw_market_type}' is unavailable in international quotes",
                rejection_code="ERR_MARKET_NOT_FOUND",
            )
            return None, rec

        # Match selection and line
        tw_parsed_line = parse_numeric_line(leg.line)
        selected_cand: Optional[MarketOddsSnapshot] = None
        alignment_note: str = ""

        for cand, is_aligned in market_cands:
            cand_line = cand.line

            # 1. Moneyline
            if tw_market_type == "MONEYLINE":
                target_sel = self._map_side_to_selection(leg.side, is_aligned)
                if MarketSelectionIdentity("MONEYLINE", target_sel, cand.line).same_outcome(
                    MarketSelectionIdentity(cand.market_type, cand.selection, cand.line)
                ):
                    selected_cand = cand
                    alignment_note = f"Moneyline matched ({target_sel})"
                    if not is_aligned:
                        alignment_note += "; international home/away order reversed"
                    break

            # 2. Spread (Line matching required!)
            elif tw_market_type == "SPREAD":
                target_sel = self._map_side_to_selection(leg.side, is_aligned)
                if cand.selection != target_sel:
                    continue

                # Spread line check:
                # If Taiwan gives line +1.5 or -1.5, candidate must match equivalent handicap
                # Note: If is_aligned is False (teams reversed), candidate's spread direction flips
                expected_cand_line = tw_parsed_line if is_aligned else (-tw_parsed_line if tw_parsed_line is not None else None)

                if MarketSelectionIdentity("SPREAD", target_sel, expected_cand_line).same_outcome(
                    MarketSelectionIdentity(cand.market_type, cand.selection, cand_line)
                ):
                    selected_cand = cand
                    alignment_note = (
                        f"Spread line matched ({cand_line:+.1f})"
                        if cand_line is not None else "Spread without line matched"
                    )
                    break

            # 3. Total (Line threshold matching required!)
            elif tw_market_type == "TOTAL":
                target_sel = "over" if leg.side in {"大", "大分"} else ("under" if leg.side in {"小", "小分"} else None)
                if cand.selection != target_sel:
                    continue

                if MarketSelectionIdentity("TOTAL", target_sel, tw_parsed_line).same_outcome(
                    MarketSelectionIdentity(cand.market_type, cand.selection, cand_line)
                ):
                    selected_cand = cand
                    alignment_note = f"Total threshold matched ({cand_line:.1f})" if cand_line is not None else "Total matched"
                    break

        # If no quote matched the exact line
        if not selected_cand:
            rec = MarketAlignmentRecord(
                status=MarketAlignmentStatus.MARKET_NOT_EQUIVALENT,
                taiwan_event_id=leg.event_id,
                taiwan_league=leg.league,
                taiwan_market=leg.market,
                taiwan_selection=leg.selection,
                taiwan_side=leg.side,
                taiwan_line=leg.line,
                international_event_id=market_cands[0][0].event_id,
                international_source_id=market_cands[0][0].source_id,
                international_market_type=tw_market_type,
                international_selection=leg.side,
                international_line=market_cands[0][0].line,
                aligned_at_utc=now_iso,
                reason=f"Market line threshold mismatch. Taiwan line was '{leg.line}', international quotes had different lines",
                rejection_code="ERR_LINE_MISMATCH",
            )
            return None, rec

        # Check Staleness of selected quote
        obs_dt = _parse_utc_datetime(selected_cand.observed_at_utc)
        if obs_dt is None:
            return reject_event_identity(
                "ERR_ODDS_TIME_UNKNOWN",
                "Matched international quote has an invalid or timezone-free observation timestamp.",
                candidate=selected_cand,
            )
        age_sec = (now - obs_dt).total_seconds()
        if age_sec < -300.0:
            return reject_event_identity(
                "ERR_ODDS_TIME_FUTURE",
                "Matched international quote observation timestamp is more than five minutes in the future.",
                candidate=selected_cand,
                time_delta_seconds=age_sec,
            )
        if age_sec > self.max_staleness:
            rec = MarketAlignmentRecord(
                status=MarketAlignmentStatus.STALE,
                taiwan_event_id=leg.event_id,
                taiwan_league=leg.league,
                taiwan_market=leg.market,
                taiwan_selection=leg.selection,
                taiwan_side=leg.side,
                taiwan_line=leg.line,
                international_event_id=selected_cand.event_id,
                international_source_id=selected_cand.source_id,
                international_market_type=selected_cand.market_type,
                international_selection=selected_cand.selection,
                international_line=selected_cand.line,
                aligned_at_utc=now_iso,
                time_delta_seconds=age_sec,
                reason=f"International quote is stale (age {age_sec/60:.1f} min > limit {self.max_staleness/60:.0f} min)",
                rejection_code="ERR_STALE_ODDS",
            )
            return None, rec

        # High-Fidelity Match confirmed!
        rec = MarketAlignmentRecord(
            status=MarketAlignmentStatus.MATCHED,
            taiwan_event_id=leg.event_id,
            taiwan_league=leg.league,
            taiwan_market=leg.market,
            taiwan_selection=leg.selection,
            taiwan_side=leg.side,
            taiwan_line=leg.line,
            international_event_id=selected_cand.event_id,
            international_source_id=selected_cand.source_id,
            international_market_type=selected_cand.market_type,
            international_selection=selected_cand.selection,
            international_line=selected_cand.line,
            aligned_at_utc=now_iso,
            time_delta_seconds=event_time_delta,
            reason=alignment_note,
        )
        return selected_cand, rec

    def _map_side_to_selection(self, side: str, is_aligned: bool) -> str:
        """Map Taiwan side ('主', '客', '和') to ('home', 'away', 'draw'), taking inversion into account."""
        if side in {"主", "主隊"}:
            return "home" if is_aligned else "away"
        elif side in {"客", "客隊"}:
            return "away" if is_aligned else "home"
        elif side in {"和", "和局"}:
            return "draw"
        return side.lower()
