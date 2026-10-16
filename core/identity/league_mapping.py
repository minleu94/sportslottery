#!/usr/bin/env python3
"""League Mapping and Identifier Normalization."""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

LEAGUE_NORMALIZATION_MAP: Dict[str, Tuple[str, str]] = {
    # Playsport alliance ID -> (Canonical League, Sport)
    "1": ("MLB", "baseball"),
    "4": ("UNKNOWN_SOCCER", "soccer"),
    "93": ("NFL", "football"),
    "3": ("NBA", "basketball"),
    "7": ("WNBA", "basketball"),
    "6": ("CPBL", "baseball"),
    "2": ("NPB", "baseball"),
    "9": ("KBO", "baseball"),
    "87": ("NHL", "hockey"),
}

NAME_TO_LEAGUE_MAP: Dict[str, Tuple[str, str]] = {
    "MLB": ("MLB", "baseball"),
    "美棒": ("MLB", "baseball"),
    "美國職棒": ("MLB", "baseball"),
    "NFL": ("NFL", "football"),
    "美足": ("NFL", "football"),
    "美式足球": ("NFL", "football"),
    "英格蘭超級聯賽": ("PREMIER", "soccer"),
    "英格蘭足球超級聯賽": ("PREMIER", "soccer"),
    "英超": ("PREMIER", "soccer"),
    "PREMIER LEAGUE": ("PREMIER", "soccer"),
    "LALIGA": ("LALIGA", "soccer"),
    "ESP.1": ("LALIGA", "soccer"),
    "LA LIGA": ("LALIGA", "soccer"),
    "西甲": ("LALIGA", "soccer"),
    "西班牙甲級聯賽": ("LALIGA", "soccer"),
    "COLOMBIA_PRIMERA_A": ("COLOMBIA_PRIMERA_A", "soccer"),
    "COLOMBIA PRIMERA A": ("COLOMBIA_PRIMERA_A", "soccer"),
    "COL.1": ("COLOMBIA_PRIMERA_A", "soccer"),
    "哥倫比亞甲級聯賽": ("COLOMBIA_PRIMERA_A", "soccer"),
    "UNKNOWN_哥倫比亞甲級聯賽": ("COLOMBIA_PRIMERA_A", "soccer"),
    "COSTA_RICA_PRIMERA": ("COSTA_RICA_PRIMERA", "soccer"),
    "MLS": ("MLS", "soccer"),
    "USA.1": ("MLS", "soccer"),
    "MAJOR LEAGUE SOCCER": ("MLS", "soccer"),
    "美國足球大聯盟": ("MLS", "soccer"),
    # Exact legacy canonical value emitted before MLS was explicitly mapped.
    "UNKNOWN_美國足球大聯盟": ("MLS", "soccer"),
    "美國職業足球大聯盟": ("MLS", "soccer"),
    "CRC.1": ("COSTA_RICA_PRIMERA", "soccer"),
    "LIGA FPD": ("COSTA_RICA_PRIMERA", "soccer"),
    "哥斯大黎加甲級聯賽": ("COSTA_RICA_PRIMERA", "soccer"),
    "UNKNOWN_哥斯大黎加甲級聯賽": ("COSTA_RICA_PRIMERA", "soccer"),
    "AFC_CHAMPIONS_LEAGUE_TWO": ("AFC_CHAMPIONS_LEAGUE_TWO", "soccer"),
    "AFC CUP": ("AFC_CHAMPIONS_LEAGUE_TWO", "soccer"),
    "AFC.CHAMPIONS.LEAGUE.TWO": ("AFC_CHAMPIONS_LEAGUE_TWO", "soccer"),
    "亞洲冠軍二級聯賽": ("AFC_CHAMPIONS_LEAGUE_TWO", "soccer"),
    "UNKNOWN_亞洲冠軍二級聯賽": ("AFC_CHAMPIONS_LEAGUE_TWO", "soccer"),
    "AFC CHAMPIONS LEAGUE TWO": ("AFC_CHAMPIONS_LEAGUE_TWO", "soccer"),
    "SAUDI_PRO_LEAGUE": ("SAUDI_PRO_LEAGUE", "soccer"),
    "KSA.1": ("SAUDI_PRO_LEAGUE", "soccer"),
    "SAUDI PRO LEAGUE": ("SAUDI_PRO_LEAGUE", "soccer"),
    "沙烏地阿拉伯職業聯賽": ("SAUDI_PRO_LEAGUE", "soccer"),
    "UNKNOWN_沙烏地阿拉伯職業聯賽": ("SAUDI_PRO_LEAGUE", "soccer"),
    "CONMEBOL_LIBERTADORES": ("CONMEBOL_LIBERTADORES", "soccer"),
    "CONMEBOL.LIBERTADORES": ("CONMEBOL_LIBERTADORES", "soccer"),
    "CONMEBOL LIBERTADORES": ("CONMEBOL_LIBERTADORES", "soccer"),
    "南美自由者盃": ("CONMEBOL_LIBERTADORES", "soccer"),
    "UNKNOWN_南美自由者盃": ("CONMEBOL_LIBERTADORES", "soccer"),
    "歐洲冠軍聯賽": ("CHAMPIONS", "soccer"),
    "歐洲冠軍聯賽資格賽": ("CHAMPIONS_QUALIFYING", "soccer"),
    "歐冠": ("CHAMPIONS", "soccer"),
    "UEFA CHAMPIONS LEAGUE": ("CHAMPIONS", "soccer"),
    # The AFC's second-tier competition is separate from UEFA Champions League.
    "亞洲冠軍聯賽": ("UNKNOWN_ASIAN_CHAMPIONS_LEAGUE", "soccer"),
    "NBA": ("NBA", "basketball"),
    "WNBA": ("WNBA", "basketball"),
    "CPBL": ("CPBL", "baseball"),
    "中職": ("CPBL", "baseball"),
    "中華職棒": ("CPBL", "baseball"),
    "NPB": ("NPB", "baseball"),
    "日棒": ("NPB", "baseball"),
    "日本職棒": ("NPB", "baseball"),
    "NHL": ("NHL", "hockey"),
}


def normalize_league_and_sport(league_input: str, alliance_id: Optional[str] = None) -> Tuple[str, str]:
    """Normalize only explicit competition names; generic sport labels stay unknown.

    A source alliance is a sport/family hint. For multi-competition pages it is
    not evidence that a soccer event is the Premier League or that a basketball
    event is the NBA.
    """
    raw = str(league_input or "").strip()
    cleaned = re.sub(r"[\s()（）_\-]+", "", raw).casefold()
    aliases = NAME_TO_LEAGUE_MAP.items()
    for key, value in aliases:
        key_clean = re.sub(r"[\s()（）_\-]+", "", key).casefold()
        if cleaned == key_clean:
            return value

    # Sport family hints are intentionally applied after exact aliases.
    if alliance_id and alliance_id in LEAGUE_NORMALIZATION_MAP:
        league, sport = LEAGUE_NORMALIZATION_MAP[alliance_id]
        if str(alliance_id) == "4":
            # Retain the exact source competition in the unresolved league key.
            slug = re.sub(r"[^\w]+", "_", raw, flags=re.UNICODE).strip("_") or "UNSPECIFIED"
            return f"UNKNOWN_{slug}", "soccer"
        if not raw:
            return league, sport
        # For a generic source title, retain the sport but fail closed on league.
        if sport == "soccer":
            slug = re.sub(r"[^\w]+", "_", raw, flags=re.UNICODE).strip("_") or "UNSPECIFIED"
            return f"UNKNOWN_{slug}", sport
        if sport == "basketball" and ("/" in raw or cleaned in {"wnbanba", "籃球wnbanba"}):
            slug = re.sub(r"[^\w]+", "_", raw, flags=re.UNICODE).strip("_") or "UNSPECIFIED"
            return f"UNKNOWN_{slug}", sport
        return league, sport

    if not raw:
        return "OTHER", "other"
    if cleaned in {"足球", "足球各大聯賽"}:
        return "UNKNOWN_SOCCER", "soccer"
    if cleaned in {"wnbanba", "籃球wnbanba"}:
        return "UNKNOWN_BASKETBALL", "basketball"
    return "OTHER", "other"
