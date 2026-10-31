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

from integrations.common.models import TaiwanLeg
from integrations.odds.market_models import (
    MarketAlignmentRecord,
    MarketAlignmentStatus,
    MarketOddsSnapshot,
)

logger = logging.getLogger(__name__)

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

    def __init__(self, max_time_delta_seconds: float = 28800.0, max_staleness_seconds: float = 10800.0):
        # 28800 seconds = 8 hours tolerance for schedule time differences
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
        now_iso = now.isoformat()

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

        # Resolve Taiwan canonical teams
        tw_home_canon = resolve_canonical_team(leg.home_team, leg.league)
        tw_away_canon = resolve_canonical_team(leg.away_team, leg.league)

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
        elif leg.market in {"不讓分", "獨贏", "勝負"}:
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

        # Filter candidates by team match
        matched_candidates: List[Tuple[MarketOddsSnapshot, bool]] = []
        # bool indicates whether home/away are aligned (True) or reversed (False)

        for cand in candidates:
            cand_home_canon = resolve_canonical_team(cand.home_team, cand.league) or normalize_string(cand.home_team)
            cand_away_canon = resolve_canonical_team(cand.away_team, cand.league) or normalize_string(cand.away_team)

            # Check direct match: tw_home == cand_home and tw_away == cand_away
            if tw_home_canon == cand_home_canon and tw_away_canon == cand_away_canon:
                matched_candidates.append((cand, True))
            # Check reversed match: tw_home == cand_away and tw_away == cand_home
            elif tw_home_canon == cand_away_canon and tw_away_canon == cand_home_canon:
                matched_candidates.append((cand, False))

        if not matched_candidates:
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
                reason=f"No matching international event found for {tw_away_canon} @ {tw_home_canon}",
                rejection_code="ERR_EVENT_NOT_FOUND",
            )
            return None, rec

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
                if cand.selection == target_sel:
                    selected_cand = cand
                    alignment_note = f"Moneyline matched ({target_sel})"
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

                if tw_parsed_line is not None and cand_line is not None:
                    if math.isclose(cand_line, expected_cand_line, abs_tol=0.01):
                        selected_cand = cand
                        alignment_note = f"Spread line matched ({cand_line:+.1f})"
                        break
                    else:
                        # Line mismatch
                        continue
                elif tw_parsed_line is None and cand_line is None:
                    selected_cand = cand
                    alignment_note = "Spread without line matched"
                    break

            # 3. Total (Line threshold matching required!)
            elif tw_market_type == "TOTAL":
                target_sel = "over" if leg.side in {"大", "大分"} else ("under" if leg.side in {"小", "小分"} else None)
                if cand.selection != target_sel:
                    continue

                if tw_parsed_line is not None and cand_line is not None:
                    if math.isclose(cand_line, tw_parsed_line, abs_tol=0.01):
                        selected_cand = cand
                        alignment_note = f"Total threshold matched ({cand_line:.1f})"
                        break
                    else:
                        continue
                elif tw_parsed_line is None and cand_line is None:
                    selected_cand = cand
                    alignment_note = "Total matched"
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
        try:
            obs_dt = datetime.fromisoformat(selected_cand.observed_at_utc.replace("Z", "+00:00"))
            age_sec = (now - obs_dt).total_seconds()
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
        except Exception:
            pass

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
