"""Shared, fail-closed freshness and point-in-time checks for model inputs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def model_input_evidence(
    data_as_of: Any,
    event_start: Any,
    *,
    now: datetime | None = None,
    fresh_hours: float = 48.0,
    aging_days: float = 7.0,
) -> dict[str, Any]:
    """Qualify a real, timezone-aware input watermark against a future event."""
    as_of = _aware(data_as_of)
    start = _aware(event_start)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if as_of is None or start is None:
        return {"freshness_status": "UNKNOWN", "point_in_time_status": "UNKNOWN",
                "point_in_time_verified": False, "pre_event_source_order_valid": False,
                "data_age_hours": None}
    age_hours = (current - as_of).total_seconds() / 3600.0
    freshness = ("UNKNOWN" if age_hours < 0 else "FRESH" if age_hours <= fresh_hours
                 else "AGING" if age_hours <= aging_days * 24 else "STALE")
    verified = as_of <= current and as_of < start
    return {"freshness_status": freshness,
            "point_in_time_status": "VALID" if verified else "INVALID",
            "point_in_time_verified": verified,
            "pre_event_source_order_valid": verified,
            "data_age_hours": round(age_hours, 2) if age_hours >= 0 else None}
