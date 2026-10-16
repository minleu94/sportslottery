"""Identity, Canonical Teams, and Event Matching Package."""

from .team_alias import CanonicalTeam, TeamRegistry, GLOBAL_TEAM_REGISTRY
from .league_mapping import normalize_league_and_sport
from .timezone import parse_playsport_time_to_utc, format_utc_to_taipei, get_utc_now_iso
from .event_matcher import CanonicalEvent, EventMatcher, GLOBAL_EVENT_MATCHER

__all__ = [
    "CanonicalTeam",
    "TeamRegistry",
    "GLOBAL_TEAM_REGISTRY",
    "normalize_league_and_sport",
    "parse_playsport_time_to_utc",
    "format_utc_to_taipei",
    "get_utc_now_iso",
    "CanonicalEvent",
    "EventMatcher",
    "GLOBAL_EVENT_MATCHER",
]
