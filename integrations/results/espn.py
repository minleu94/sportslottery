"""ESPN's public scoreboard feed adapter (third-party result source).

The adapter is deliberately separate from official league sources and is
fail-closed on incomplete identities, malformed scores, and soccer ET detail.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from core.identity.team_alias import GLOBAL_TEAM_REGISTRY
from .models import ResultGame, iso_utc, parse_score

logger = logging.getLogger(__name__)

ESPN_LEAGUES = {
    ("soccer", "PREMIER"): "soccer/eng.1",
    ("soccer", "LALIGA"): "soccer/esp.1",
    ("soccer", "MLS"): "soccer/usa.1",
    ("soccer", "UNKNOWN_美國足球大聯盟"): "soccer/usa.1",
    ("soccer", "COLOMBIA_PRIMERA_A"): "soccer/col.1",
    ("soccer", "COSTA_RICA_PRIMERA"): "soccer/crc.1",
    ("soccer", "AFC_CHAMPIONS_LEAGUE_TWO"): "soccer/afc.cup",
    ("soccer", "SAUDI_PRO_LEAGUE"): "soccer/ksa.1",
    ("soccer", "CONMEBOL_LIBERTADORES"): "soccer/conmebol.libertadores",
    ("soccer", "CHAMPIONS"): "soccer/uefa.champions",
    ("basketball", "NBA"): "basketball/nba",
    ("basketball", "WNBA"): "basketball/wnba",
    ("football", "NFL"): "football/nfl",
}
BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"


def _canonical_team(team: dict[str, Any], sport: str, league: str) -> Optional[str]:
    name = str(team.get("displayName") or team.get("name") or "").strip()
    provider_id = str(team.get("id") or "")
    resolved = GLOBAL_TEAM_REGISTRY.resolve(name, sport=sport, league=None if sport == "soccer" else league) if name else None
    # Keep the provider name when the registry does not yet cover that team,
    # but never use an approximate substring resolution as a canonical ID.
    def is_exact(team_record):
        if not team_record or team_record.sport != sport:
            return False
        if team_record.league != league and sport != "soccer":
            return False
        exact_keys = {
            team_record.canonical_id.lower(), team_record.abbreviation.lower(),
            team_record.display_name_en.lower(), team_record.display_name_zh.lower(),
            team_record.short_name_zh.lower(), *(str(a).lower() for a in team_record.aliases),
        }
        return name.lower() in exact_keys
    if is_exact(resolved):
        return resolved.canonical_id
    if provider_id:
        by_espn_id = GLOBAL_TEAM_REGISTRY.resolve(f"ESPN_TEAM_{provider_id}", sport=sport, league=league)
        if is_exact(by_espn_id):
            return by_espn_id.canonical_id
    if provider_id:
        by_id = GLOBAL_TEAM_REGISTRY.resolve("", sport=sport, league=league, playsport_team_id=provider_id)
        if is_exact(by_id):
            return by_id.canonical_id
    return None


def _event_status(event: dict[str, Any]) -> tuple[str, Optional[str], Optional[str]]:
    typ = event.get("status", {}).get("type", {})
    code = str(typ.get("name") or "")
    detail = str(typ.get("detail") or "")
    source_status = ":".join(value for value in (code, detail) if value) or None
    state = str(typ.get("state") or "").lower()
    completed = typ.get("completed") is True
    if code in {"STATUS_CANCELED", "STATUS_CANCELLED"} or "cancel" in detail.lower():
        return "VOID", source_status, "CANCELLED"
    if code == "STATUS_POSTPONED" or "postpon" in detail.lower():
        return "PENDING", source_status, None
    if completed and state == "post":
        return "FINAL", source_status, "REGULATION_COMPLETED"
    if code or detail:
        return "PENDING", source_status, "IN_PROGRESS" if state == "in" else None
    return "UNRESOLVED", source_status, None


def _soccer_regulation_scores(comp: dict[str, Any], competitors: dict[str, dict[str, Any]]) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """Derive regulation score from scoring events without counting ET/shootout.

    For AET/PEN, full-time competitor scores include extra time. All scoring
    events must be represented so the remaining non-shootout events can be
    split at 90 minutes. A missing/ambiguous event clock is not guessed.
    """
    details = comp.get("details")
    if not isinstance(details, list) or not details:
        return None, None, "soccer scoring details missing"
    full = {side: parse_score(team.get("score")) for side, team in competitors.items()}
    if any(v is None for v in full.values()):
        return None, None, "final soccer score invalid"
    counted = {"away": 0, "home": 0}
    regulation = {"away": 0, "home": 0}
    for detail in details:
        if detail.get("scoringPlay") is not True or detail.get("shootout") is True:
            continue
        team_id = str((detail.get("team") or {}).get("id") or "")
        side = next((s for s, t in competitors.items() if str((t.get("team") or {}).get("id") or "") == team_id), None)
        value = parse_score(detail.get("scoreValue"))
        clock_text = str((detail.get("clock") or {}).get("displayValue") or "")
        match = re.search(r"(\d+)", clock_text)
        if side is None or value is None or not match:
            return None, None, "soccer scoring event identity/time/score incomplete"
        minute = int(match.group(1))
        counted[side] += value
        if minute <= 90:
            regulation[side] += value
    if counted != full:
        return None, None, "soccer scoring detail does not reconcile to final score"
    return regulation["away"], regulation["home"], None


def parse_espn_event(
    event: dict[str, Any], sport: str, league: str, *, source_url: Optional[str] = None,
    observed_at_utc: Optional[str] = None,
) -> ResultGame:
    competitions = event.get("competitions")
    comp = competitions[0] if isinstance(competitions, list) and len(competitions) == 1 else None
    if comp is None:
        return ResultGame("ESPN_PUBLIC_SCOREBOARD", str(event.get("id") or "") or None, sport, league,
                          None, iso_utc(event.get("date")), None, None, None, None, None, None,
                          "UNRESOLVED", None, None, source_url=source_url,
                          observed_at_utc=observed_at_utc, unresolved_reason="expected exactly one competition")
    competitors_raw = comp.get("competitors")
    competitors: dict[str, dict[str, Any]] = {}
    if isinstance(competitors_raw, list):
        for team in competitors_raw:
            side = team.get("homeAway")
            if side in {"home", "away"} and side not in competitors:
                competitors[side] = team
    away, home = competitors.get("away"), competitors.get("home")
    start = iso_utc(comp.get("date") or comp.get("startDate") or event.get("date"))
    event_status, provider_status, completion = _event_status(event)
    unresolved = None
    away_source_name = str(((away or {}).get("team") or {}).get("displayName")
                           or ((away or {}).get("team") or {}).get("name") or "").strip() or None
    home_source_name = str(((home or {}).get("team") or {}).get("displayName")
                           or ((home or {}).get("team") or {}).get("name") or "").strip() or None
    away_name = _canonical_team((away or {}).get("team") or {}, sport, league)
    home_name = _canonical_team((home or {}).get("team") or {}, sport, league)
    away_score = parse_score((away or {}).get("score"))
    home_score = parse_score((home or {}).get("score"))
    regulation_away = regulation_home = None
    status_type = event.get("status", {}).get("type", {})
    status_code = str(status_type.get("name") or "")
    if sport == "soccer" and event_status == "FINAL":
        if status_code in {"STATUS_FINAL_AET", "STATUS_FINAL_PEN"}:
            regulation_away, regulation_home, unresolved = _soccer_regulation_scores(comp, competitors)
        elif status_code == "STATUS_FULL_TIME":
            regulation_away, regulation_home = away_score, home_score
        else:
            unresolved = "soccer completion period is not an explicitly supported full-time state"
    if not away or not home or not away_name or not home_name:
        unresolved = unresolved or "both canonical teams are required"
    if not start:
        unresolved = unresolved or "aware event start time missing"
    if event_status == "FINAL" and (away_score is None or home_score is None):
        unresolved = unresolved or "final score missing or invalid"
    if sport == "soccer" and event_status == "FINAL" and (regulation_away is None or regulation_home is None):
        unresolved = unresolved or "regulation-time score unavailable"
    if unresolved:
        event_status = "UNRESOLVED"
        completion = None
    return ResultGame(
        provider="ESPN_PUBLIC_SCOREBOARD", provider_event_id=str(event.get("id") or "") or None,
        sport=sport, league=league, event_date_local=(start[:10] if start else None),
        start_time_utc=start, away_team=away_name, home_team=home_name,
        away_provider_team_id=str(((away or {}).get("team") or {}).get("id") or "") or None,
        home_provider_team_id=str(((home or {}).get("team") or {}).get("id") or "") or None,
        away_score=away_score, home_score=home_score, status=event_status,
        provider_status=provider_status, official_completion_status=completion,
        soccer_regulation_away=regulation_away, soccer_regulation_home=regulation_home,
        source_url=source_url, observed_at_utc=observed_at_utc, unresolved_reason=unresolved,
        away_team_source_name=away_source_name, home_team_source_name=home_source_name,
    )


class ESPNResultProvider:
    """Small bounded GET client for ESPN's public scoreboards."""

    def __init__(self, session: Optional[requests.Session] = None, timeout: float = 10.0):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.setdefault("User-Agent", "sportslottery-result-reader/1.0")

    def fetch(self, sport: str, league: str, date_yyyymmdd: str) -> list[ResultGame]:
        path = ESPN_LEAGUES.get((sport, league))
        if not path:
            raise ValueError(f"ESPN result feed does not cover {sport}/{league}")
        if not re.fullmatch(r"\d{8}", str(date_yyyymmdd)):
            raise ValueError("date must be YYYYMMDD")
        url = f"{BASE_URL}/{path}/scoreboard?dates={date_yyyymmdd}"
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        observed = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        events = payload.get("events")
        if not isinstance(events, list):
            raise ValueError("ESPN scoreboard did not contain an events array")
        return [parse_espn_event(e, sport, league, source_url=url, observed_at_utc=observed)
                for e in events if isinstance(e, dict)]
