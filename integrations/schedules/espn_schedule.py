#!/usr/bin/env python3
"""ESPN Public Scoreboard Schedule Adapter (Layer C - Schedule Awareness).

Fetches live game schedules from ESPN's public scoreboard API.
Strictly used for Season Radar and schedule awareness; CANNOT generate betting candidates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

ESPN_SPORT_MAP = {
    "MLB": "baseball/mlb",
    "NFL": "football/nfl",
    "NBA": "basketball/nba",
    "WNBA": "basketball/wnba",
    "PREMIER": "soccer/eng.1",
    "LALIGA": "soccer/esp.1",
    "MLS": "soccer/usa.1",
    "COLOMBIA_PRIMERA_A": "soccer/col.1",
    "COSTA_RICA_PRIMERA": "soccer/crc.1",
    "AFC_CHAMPIONS_LEAGUE_TWO": "soccer/afc.cup",
    "SAUDI_PRO_LEAGUE": "soccer/ksa.1",
    "CONMEBOL_LIBERTADORES": "soccer/conmebol.libertadores",
    "CHAMPIONS": "soccer/uefa.champions",
    "NHL": "hockey/nhl",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


class ESPNScheduleAdapter:
    """Provides schedule awareness from ESPN public endpoints."""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)

    def fetch_live_events_with_status(self, league_code: str) -> Dict[str, Any]:
        """Keep verified empty schedules distinct from failed or unsupported sources."""
        slug = ESPN_SPORT_MAP.get(league_code)
        observed = datetime.now(timezone.utc).isoformat()
        if not slug:
            return {"events":[],"source_status":"UNSUPPORTED","observed_at_utc":observed,"error":None}
        url = f"https://site.api.espn.com/apis/site/v2/sports/{slug}/scoreboard"
        try:
            response = self.session.get(url, timeout=6)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            payload = response.json()
            events = payload.get("events")
            if not isinstance(events, list):
                raise ValueError("Missing or invalid events list")
            parsed = []
            for event in events:
                if not isinstance(event,dict):
                    raise ValueError("Invalid schedule event")
                name = event.get("name", "")
                parsed.append({"id":event.get("id"),"name":name,"short_name":event.get("shortName",name),
                    "date":event.get("date",""),"status":event.get("status",{}).get("type",{}).get("description","Unknown")})
            return {"events":parsed,"source_status":"LIVE" if parsed else "LIVE_NO_EVENTS",
                    "observed_at_utc":observed,"source_url":url,"error":None}
        except Exception as exc:
            logger.warning("Schedule source failed for %s: %s", league_code,exc)
            return {"events":[],"source_status":"FETCH_ERROR","observed_at_utc":observed,
                    "source_url":url,"error":str(exc)}

    def fetch_live_events(self, league_code: str) -> List[Dict[str, Any]]:
        return self.fetch_live_events_with_status(league_code)["events"]
