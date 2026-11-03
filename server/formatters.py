"""Presentation-safe labels shared by API responses."""

from __future__ import annotations

import re
from typing import Optional


def clean_league_name(league: Optional[str]) -> str:
    if not league:
        return "綜合賽事"
    value = re.sub(r"^unknown[_\-\s]*", "", str(league).strip(), flags=re.IGNORECASE).strip()
    upper = value.upper()
    league_map = {
        "COLOMBIA_PRIMERA_A": "哥倫比亞甲級聯賽",
        "SAUDI_PRO_LEAGUE": "沙烏地職業聯賽",
        "KBO": "韓國職棒 (KBO)",
        "NBA": "美國職籃 (NBA)",
        "WNBA": "美國女子職籃 (WNBA)",
        "MLB": "美國職棒 (MLB)",
        "NPB": "日本職棒 (NPB)",
        "CPBL": "中華職棒 (CPBL)",
        "NFL": "美式足球 (NFL)",
        "NHL": "國家冰球 (NHL)",
        "SOCCER": "綜合足球",
        "BASKETBALL": "綜合籃球",
        "BASEBALL": "綜合棒球",
        "FOOTBALL": "美式足球",
    }
    return league_map.get(upper, value) or "綜合賽事"


__all__ = ["clean_league_name"]
