"""Official CPBL Stats page adapter.

The CPBL schedule page exposes JSON-LD SportsEvent rows with explicit
homeTeam/awayTeam, startDate, and an official per-game URL. Game detail pages
carry the score in their title and a pitcher decision line when finished.
"""

from __future__ import annotations

import json
import re
from datetime import date as date_type, datetime
from typing import Any, Iterable, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from .models import ResultGame, iso_utc, parse_score

BASE = "https://stats.cpbl.com.tw"
SCHEDULE_URL = f"{BASE}/schedule"
GAME_ID_RE = re.compile(r"^\d{4}-[A-Z]-\d+$")


def _events_from_jsonld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    events = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            raw = json.loads(node.string or node.get_text())
        except (TypeError, ValueError):
            continue
        queue = raw if isinstance(raw, list) else [raw]
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            typ = item.get("@type")
            if typ == "ListItem" and isinstance(item.get("item"), dict):
                queue.append(item["item"])
            elif typ == "SportsEvent":
                events.append(item)
            elif isinstance(item.get("itemListElement"), list):
                queue.extend(item["itemListElement"])
    return events


def parse_cpbl_game_page(html: str, game_id: str, source_url: str, observed_at_utc: Optional[str] = None) -> ResultGame:
    soup = BeautifulSoup(html, "html.parser")
    event = next((item for item in _events_from_jsonld(soup)
                  if str(item.get("url") or "").rstrip("/").endswith("/" + game_id)), None)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    score_match = re.search(r"^(.+?)\s+(\d+)\s*:\s*(\d+)\s+(.+?)\s*\|", title)
    if event is None:
        return ResultGame("CPBL_STATS_OFFICIAL", game_id, "baseball", "CPBL", None, None,
                          None, None, None, None, None, None, "UNRESOLVED", None, None,
                          source_url=source_url, observed_at_utc=observed_at_utc,
                          unresolved_reason="official page missing SportsEvent home/away identity")
    away_name = str((event.get("awayTeam") or {}).get("name") or "").strip() or None
    home_name = str((event.get("homeTeam") or {}).get("name") or "").strip() or None
    start_raw = event.get("startDate")
    start_utc = None
    local_date = None
    if isinstance(start_raw, str):
        try:
            local_start = datetime.fromisoformat(start_raw)
            if local_start.tzinfo is None:
                local_start = local_start.replace(tzinfo=ZoneInfo("Asia/Taipei"))
            start_utc = iso_utc(local_start.isoformat())
            local_date = local_start.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
        except ValueError:
            pass
    away_score = home_score = None
    if score_match and away_name and home_name:
        left, right = score_match.group(1).strip(), score_match.group(4).strip()
        left_score, right_score = int(score_match.group(2)), int(score_match.group(3))
        # Title ordering is tied back to the structured home/away fields; do
        # not infer which title side is home from ordering alone.
        if left == away_name and right == home_name:
            away_score, home_score = left_score, right_score
        elif left == home_name and right == away_name:
            home_score, away_score = left_score, right_score
    description = str((soup.find("meta", attrs={"name": "description"}) or {}).get("content") or "")
    state = str(event.get("eventStatus") or "").rsplit("/", 1)[-1]
    if state == "EventCancelled":
        status, completion, provider_status = "VOID", "CANCELLED", state
    elif state == "EventPostponed":
        status, completion, provider_status = "PENDING", None, state
    elif away_score is not None and home_score is not None and "勝投:" in description and "敗投:" in description:
        status, completion, provider_status = "FINAL", "REGULATION_COMPLETED", "SCORE_AND_PITCHER_DECISIONS"
    elif away_score is not None and home_score is not None:
        status, completion, provider_status = "UNRESOLVED", None, "SCORE_WITHOUT_COMPLETION_EVIDENCE"
    else:
        status, completion, provider_status = "PENDING", None, state or "SCHEDULED"
    reason = None
    if not away_name or not home_name:
        status, completion, reason = "UNRESOLVED", None, "explicit CPBL away/home names missing"
    elif score_match and away_score is None:
        status, completion, reason = "UNRESOLVED", None, "title score sides do not match structured away/home names"
    return ResultGame(
        provider="CPBL_STATS_OFFICIAL", provider_event_id=game_id, sport="baseball", league="CPBL",
        event_date_local=local_date, start_time_utc=start_utc, away_team=away_name, home_team=home_name,
        away_provider_team_id=None, home_provider_team_id=None, away_score=away_score, home_score=home_score,
        status=status, provider_status=provider_status, official_completion_status=completion,
        source_url=source_url, observed_at_utc=observed_at_utc, unresolved_reason=reason,
    )


def parse_cpbl_schedule_page(html: str, target_date: str) -> list[str]:
    """Return official game IDs explicitly listed for a requested local date."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for event in _events_from_jsonld(soup):
        start = event.get("startDate")
        url = str(event.get("url") or "")
        game_id = url.rstrip("/").rsplit("/", 1)[-1]
        if isinstance(start, str) and start[:10] == target_date and GAME_ID_RE.fullmatch(game_id):
            found.append(game_id)
    return sorted(set(found))


class CPBLResultProvider:
    def __init__(self, session: Optional[requests.Session] = None, timeout: float = 12.0):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Referer": SCHEDULE_URL,
        })

    def fetch(self, target_date: str, source_ids: Iterable[str] = ()) -> list[ResultGame]:
        date_type.fromisoformat(target_date)
        ids = {str(item) for item in source_ids if GAME_ID_RE.fullmatch(str(item))}
        if not ids:
            schedule = self.session.get(SCHEDULE_URL, timeout=self.timeout)
            schedule.raise_for_status()
            ids = set(parse_cpbl_schedule_page(schedule.text, target_date))
        observed = datetime.now(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
        games = []
        for game_id in sorted(ids):
            url = f"{BASE}/schedule/{game_id}"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            games.append(parse_cpbl_game_page(response.text, game_id, url, observed))
        return games
