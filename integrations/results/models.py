"""Normalized, provenance-preserving match result records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass(frozen=True)
class ResultGame:
    provider: str
    provider_event_id: Optional[str]
    sport: str
    league: str
    event_date_local: Optional[str]
    start_time_utc: Optional[str]
    away_team: Optional[str]
    home_team: Optional[str]
    away_provider_team_id: Optional[str]
    home_provider_team_id: Optional[str]
    away_score: Optional[int]
    home_score: Optional[int]
    status: str
    provider_status: Optional[str]
    official_completion_status: Optional[str]
    soccer_regulation_away: Optional[int] = None
    soccer_regulation_home: Optional[int] = None
    innings_completed: Optional[float] = None
    source_url: Optional[str] = None
    observed_at_utc: Optional[str] = None
    unresolved_reason: Optional[str] = None
    away_team_source_name: Optional[str] = None
    home_team_source_name: Optional[str] = None

    @property
    def final_score(self) -> Optional[str]:
        if self.away_score is None or self.home_score is None:
            return None
        return f"{self.away_score}:{self.home_score}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_score(value: Any) -> Optional[int]:
    """Accept only finite, nonnegative integer scores (bool is not an int here)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value.is_integer() else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def iso_utc(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError, OverflowError):
        return None
