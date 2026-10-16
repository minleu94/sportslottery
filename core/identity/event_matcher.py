#!/usr/bin/env python3
"""Canonical Event Identity and Multi-Source Event Matching.

Aligns Taiwan Sports Lottery / Playsport events, ESPN Scoreboard events,
and external prediction models into unified CanonicalEvent objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .league_mapping import normalize_league_and_sport
from .team_alias import CanonicalTeam, GLOBAL_TEAM_REGISTRY, TeamRegistry
from .timezone import get_utc_now_iso, parse_playsport_time_to_utc
from core.bet_validation import parse_aware_time


@dataclass
class CanonicalEvent:
    canonical_event_id: str             # e.g. 'MLB_20260918_CHC_CIN'
    sport: str                          # 'baseball', 'soccer', etc.
    league: str                         # 'MLB', 'PREMIER', etc.
    away_team: CanonicalTeam
    home_team: CanonicalTeam
    start_time_utc: str                 # UTC ISO 8601
    taiwan_event_id: Optional[str] = None # e.g. '125'
    espn_event_id: Optional[str] = None   # e.g. '401695123'
    away_pitcher: Optional[str] = None
    home_pitcher: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_event_id": self.canonical_event_id,
            "sport": self.sport,
            "league": self.league,
            "away_team": {
                "id": self.away_team.canonical_id,
                "name": self.away_team.display_name_zh,
                "name_en": self.away_team.display_name_en,
                "abbr": self.away_team.abbreviation,
            },
            "home_team": {
                "id": self.home_team.canonical_id,
                "name": self.home_team.display_name_zh,
                "name_en": self.home_team.display_name_en,
                "abbr": self.home_team.abbreviation,
            },
            "start_time_utc": self.start_time_utc,
            "taiwan_event_id": self.taiwan_event_id,
            "espn_event_id": self.espn_event_id,
            "away_pitcher": self.away_pitcher,
            "home_pitcher": self.home_pitcher,
            "metadata": self.metadata,
        }


class EventMatcher:
    """Matches raw events from different providers to unified CanonicalEvent."""

    def __init__(self, team_registry: Optional[TeamRegistry] = None):
        self.team_registry = team_registry or GLOBAL_TEAM_REGISTRY
        self._events: Dict[str, CanonicalEvent] = {}
        self._by_taiwan_id: Dict[str, str] = {}
        self._by_espn_id: Dict[str, str] = {}

    def get_event_by_taiwan_id(self, event_id: str) -> Optional[CanonicalEvent]:
        cid = self._by_taiwan_id.get(str(event_id))
        return self._events.get(cid) if cid else None

    def match_or_create(
        self,
        sport: str,
        league: str,
        away_name: str,
        home_name: str,
        start_time_utc: Optional[str] = None,
        taiwan_event_id: Optional[str] = None,
        espn_event_id: Optional[str] = None,
        away_pitcher: Optional[str] = None,
        home_pitcher: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[CanonicalEvent]:
        """Match with existing canonical event, or create a new one if teams resolve."""
        target_dt = parse_aware_time(start_time_utc)
        if target_dt is None:
            return None
        def same_observation(existing: CanonicalEvent) -> bool:
            existing_dt = parse_aware_time(existing.start_time_utc)
            away = self.team_registry.resolve(away_name, sport=sport, league=league)
            home = self.team_registry.resolve(home_name, sport=sport, league=league)
            return bool(existing_dt and away and home and existing.sport == sport and existing.league == league
                        and existing.away_team.canonical_id == away.canonical_id
                        and existing.home_team.canonical_id == home.canonical_id
                        and abs((target_dt - existing_dt).total_seconds()) <= 3600)
        # Check if already mapped by ID
        if taiwan_event_id and str(taiwan_event_id) in self._by_taiwan_id and same_observation(self._events[self._by_taiwan_id[str(taiwan_event_id)]]):
            cid = self._by_taiwan_id[str(taiwan_event_id)]
            ev = self._events[cid]
            if espn_event_id:
                ev.espn_event_id = str(espn_event_id)
                self._by_espn_id[str(espn_event_id)] = cid
            if away_pitcher and not ev.away_pitcher:
                ev.away_pitcher = away_pitcher
            if home_pitcher and not ev.home_pitcher:
                ev.home_pitcher = home_pitcher
            return ev

        if espn_event_id and str(espn_event_id) in self._by_espn_id and same_observation(self._events[self._by_espn_id[str(espn_event_id)]]):
            cid = self._by_espn_id[str(espn_event_id)]
            ev = self._events[cid]
            if taiwan_event_id:
                ev.taiwan_event_id = str(taiwan_event_id)
                self._by_taiwan_id[str(taiwan_event_id)] = cid
            return ev

        # Resolve teams
        away_canonical = self.team_registry.resolve(away_name, sport=sport, league=league)
        home_canonical = self.team_registry.resolve(home_name, sport=sport, league=league)

        if not away_canonical or not home_canonical:
            # Cannot form canonical event without resolved teams
            return None

        time_utc = target_dt.isoformat()
        date_tag = time_utc[:10].replace("-", "")

        # A second game between the same teams must retain its own identity.
        for existing_cid, existing_ev in self._events.items():
            if existing_ev.sport == sport and existing_ev.league == league:
                if (
                    existing_ev.away_team.canonical_id == away_canonical.canonical_id
                    and existing_ev.home_team.canonical_id == home_canonical.canonical_id
                ):
                    try:
                        ex_dt = datetime.fromisoformat(existing_ev.start_time_utc.replace("Z", "+00:00"))
                        conflicting_taiwan_ids = bool(taiwan_event_id and existing_ev.taiwan_event_id and str(taiwan_event_id) != existing_ev.taiwan_event_id)
                        conflicting_espn_ids = bool(espn_event_id and existing_ev.espn_event_id and str(espn_event_id) != existing_ev.espn_event_id)
                        if not conflicting_taiwan_ids and not conflicting_espn_ids and abs((target_dt - ex_dt).total_seconds()) <= 3600:
                            # Match found!
                            if taiwan_event_id:
                                existing_ev.taiwan_event_id = str(taiwan_event_id)
                                self._by_taiwan_id[str(taiwan_event_id)] = existing_cid
                            if espn_event_id:
                                existing_ev.espn_event_id = str(espn_event_id)
                                self._by_espn_id[str(espn_event_id)] = existing_cid
                            if away_pitcher and not existing_ev.away_pitcher:
                                existing_ev.away_pitcher = away_pitcher
                            if home_pitcher and not existing_ev.home_pitcher:
                                existing_ev.home_pitcher = home_pitcher
                            return existing_ev
                    except Exception:
                        pass

        # Create new CanonicalEvent
        cid = f"{league}_{date_tag}_{away_canonical.abbreviation}_{home_canonical.abbreviation}_{target_dt.strftime('%H%M%S')}"
        canonical_ev = CanonicalEvent(
            canonical_event_id=cid,
            sport=sport,
            league=league,
            away_team=away_canonical,
            home_team=home_canonical,
            start_time_utc=time_utc,
            taiwan_event_id=str(taiwan_event_id) if taiwan_event_id else None,
            espn_event_id=str(espn_event_id) if espn_event_id else None,
            away_pitcher=away_pitcher,
            home_pitcher=home_pitcher,
            metadata=metadata or {},
        )

        self._events[cid] = canonical_ev
        if taiwan_event_id:
            self._by_taiwan_id[str(taiwan_event_id)] = cid
        if espn_event_id:
            self._by_espn_id[str(espn_event_id)] = cid

        return canonical_ev


GLOBAL_EVENT_MATCHER = EventMatcher()
