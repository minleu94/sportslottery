"""Read-only parsers for NPB and KBO public official result pages."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from .models import ResultGame, iso_utc, parse_score

NPB_BASE = "https://npb.jp/bis/eng/{year}/games/gm{date}.html"
KBO_BASE = "https://eng.koreabaseball.com/Schedule/Scoreboard.aspx"


def _status(raw: str, has_scores: bool) -> tuple[str, Optional[str], Optional[str]]:
    value = raw.strip().upper()
    if any(word in value for word in ("CANCEL", "ABANDONED")):
        return "VOID", value, "CANCELLED" if "CANCEL" in value else None
    if any(word in value for word in ("POSTPON", "SUSPEND", "DELAY")):
        return "PENDING", value, "IN_PROGRESS" if "SUSPEND" in value else None
    if has_scores and any(word in value for word in ("FINAL", "END", "完了")):
        return "FINAL", value, "REGULATION_COMPLETED"
    return "PENDING", value or None, "IN_PROGRESS" if value and "LIVE" in value else None


def parse_npb_scoreboard(html: str, date_yyyymmdd: str, source_url: str) -> list[ResultGame]:
    """Parse NPB official daily `gmYYYYMMDD` page; left=home, right=away."""
    date = f"{date_yyyymmdd[:4]}-{date_yyyymmdd[4:6]}-{date_yyyymmdd[6:8]}"
    soup = BeautifulSoup(html, "html.parser")
    score_page = bool(soup.title and "(scores)" in soup.title.get_text(" ", strip=True).lower())
    results = []
    for anchor in soup.select('a.link_box[href*="/games/s"]'):
        unit = anchor.select_one(".unit")
        if not unit:
            continue
        left, right = unit.select_one(".team_left"), unit.select_one(".team_right")
        if not left or not right:
            continue
        home_name = left.select_one(".team_name")
        away_name = right.select_one(".team_name")
        home_score = parse_score((left.select_one(".score_text") or {}).get_text(" ", strip=True) if left.select_one(".score_text") else None)
        away_score = parse_score((right.select_one(".score_text") or {}).get_text(" ", strip=True) if right.select_one(".score_text") else None)
        if not home_name or not away_name:
            continue
        text = unit.get_text(" ", strip=True)
        has_scores = home_score is not None and away_score is not None
        status, raw_status, completion = _status(text, has_scores)
        if home_score is None or away_score is None:
            status = "PENDING"
            completion = None
        elif score_page:
            status, raw_status, completion = "FINAL", "SCORES", "REGULATION_COMPLETED"
        href = anchor.get("href", "")
        game_id_match = re.search(r"/(s\d+)\.html", href)
        results.append(ResultGame(
            provider="NPB_OFFICIAL", provider_event_id=game_id_match.group(1) if game_id_match else None,
            sport="baseball", league="NPB", event_date_local=date, start_time_utc=None,
            away_team=away_name.get_text(" ", strip=True), home_team=home_name.get_text(" ", strip=True),
            away_provider_team_id=None, home_provider_team_id=None, away_score=away_score, home_score=home_score,
            status=status, provider_status=raw_status, official_completion_status=completion,
            source_url=source_url,
        ))
    return results


def _kbo_local_time(text: str, date: str) -> Optional[str]:
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if not match:
        return None
    try:
        dt = datetime.strptime(f"{date} {int(match.group(1)):02d}:{match.group(2)}", "%Y-%m-%d %H:%M")
        return iso_utc(dt.replace(tzinfo=ZoneInfo("Asia/Seoul")).isoformat())
    except ValueError:
        return None


def parse_kbo_scoreboard(html: str, date: str, source_url: str) -> list[ResultGame]:
    """Parse official KBO day scoreboard, preserving its displayed state."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for block in soup.select(".scoreboard_time"):
        names = [e.get_text(" ", strip=True) for e in block.select(".team_name")]
        scores = [parse_score(e.get_text(" ", strip=True)) for e in block.select(".team_score")]
        state = block.select_one(".timer")
        raw_status = state.get_text(" ", strip=True) if state else ""
        # Team order on the KBO public board is away, score, state, score, home.
        if len(names) != 2:
            continue
        away_score = scores[0] if len(scores) > 0 else None
        home_score = scores[1] if len(scores) > 1 else None
        status, raw_status, completion = _status(raw_status, away_score is not None and home_score is not None)
        if away_score is None or home_score is None:
            status, completion = "PENDING", None
        local = block.find_next_sibling(class_="scoreboard_local")
        local_text = local.get_text(" ", strip=True) if local else ""
        results.append(ResultGame(
            provider="KBO_OFFICIAL", provider_event_id=None, sport="baseball", league="KBO",
            event_date_local=date, start_time_utc=_kbo_local_time(local_text, date),
            away_team=names[0], home_team=names[1], away_provider_team_id=None, home_provider_team_id=None,
            away_score=away_score, home_score=home_score, status=status, provider_status=raw_status or None,
            official_completion_status=completion, source_url=source_url,
        ))
    return results


class OfficialAsianBaseballProvider:
    """Bounded unauthenticated GET client for NPB and KBO daily score pages."""

    def __init__(self, session: Optional[requests.Session] = None, timeout: float = 12.0):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.setdefault("User-Agent", "sportslottery-result-reader/1.0")

    def fetch(self, league: str, date: str) -> list[ResultGame]:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("date must be YYYY-MM-DD")
        if league.upper() == "NPB":
            compact = date.replace("-", "")
            url = NPB_BASE.format(year=compact[:4], date=compact)
            parse = lambda html: parse_npb_scoreboard(html, compact, url)
        elif league.upper() == "KBO":
            url = f"{KBO_BASE}?{urlencode({'searchDate': date})}"
            parse = lambda html: parse_kbo_scoreboard(html, date, url)
        else:
            raise ValueError(f"No official Asian baseball provider for {league}")
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return parse(response.text)
