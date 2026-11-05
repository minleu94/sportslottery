"""Qualification rules for formal and shadow forward observations.

New snapshots carry an explicit scope in ``signal_evidence``. Legacy snapshots
are classified from their prediction lead time without mutating their records.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

FORMAL = "FORMAL_QUALIFICATION_WINDOW"
SHADOW = "SHADOW_ONLY"
FORMAL_LEAD_MINUTES = 60
SHADOW_LEAD_MINUTES = 240


def observation_scope(row: Mapping[str, Any]) -> str:
    scope = row.get("observation_scope")
    evidence = row.get("signal_evidence")
    if not scope and isinstance(evidence, Mapping):
        scope = evidence.get("observation_scope")
    if scope in {FORMAL, SHADOW}:
        return _bounded_scope(row, str(scope))
    window_id = str(row.get("observation_window_id") or "").casefold()
    if ":shadow-" in window_id or "shadow_only" in window_id:
        return _bounded_scope(row, SHADOW)

    # Old records have no scope field. Admit them only when timestamps prove
    # that they fall within a known qualification horizon.
    lead_minutes = _lead_minutes(row)
    if lead_minutes is None:
        return "UNKNOWN"
    if 0 <= lead_minutes <= FORMAL_LEAD_MINUTES:
        return FORMAL
    if FORMAL_LEAD_MINUTES < lead_minutes <= SHADOW_LEAD_MINUTES:
        return SHADOW
    return "UNKNOWN"


def _bounded_scope(row: Mapping[str, Any], scope: str) -> str:
    lead_minutes = _lead_minutes(row)
    maximum = FORMAL_LEAD_MINUTES if scope == FORMAL else SHADOW_LEAD_MINUTES
    if lead_minutes is None or lead_minutes > maximum:
        return "UNKNOWN"
    if scope == SHADOW and lead_minutes <= FORMAL_LEAD_MINUTES:
        # New formal observations must not be mislabeled as shadow records.
        return "UNKNOWN"
    return scope


def _lead_minutes(row: Mapping[str, Any]) -> float | None:
    predicted = _parse_time(row.get("snapshot_timestamp") or row.get("prediction_timestamp")
                            or row.get("recorded_at") or row.get("timestamp"))
    starts = _parse_time(row.get("event_start") or row.get("start_time_utc"))
    if predicted is None or starts is None or predicted >= starts:
        return None
    return (starts - predicted).total_seconds() / 60.0


def qualifies_formal_strategy(row: Mapping[str, Any]) -> bool:
    return observation_scope(row) == FORMAL


def qualifies_shadow_calibration(row: Mapping[str, Any]) -> bool:
    return observation_scope(row) in {FORMAL, SHADOW}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None
