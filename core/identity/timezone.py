#!/usr/bin/env python3
"""Timezone normalization and ISO 8601 conversion.

Internally, all timestamps MUST be UTC and timezone-aware.
For UI and Taiwan betting display, converts to Taipei Time (UTC+8).
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

TAIPEI_TZ = timezone(timedelta(hours=8))
UTC_TZ = timezone.utc


def get_utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(UTC_TZ).isoformat()


def parse_playsport_time_to_utc(time_str: str, reference_date: Optional[date] = None) -> Optional[str]:
    """Parse Playsport time strings (e.g. 'AM 06:40', '09/18 AM 07:05', '19:30') into UTC ISO string."""
    if not time_str or time_str in ["即將開賽", "今日賽程"]:
        return None

    cleaned = time_str.strip()
    target_date = reference_date or datetime.now(TAIPEI_TZ).date()

    # Check if month/day is specified e.g. "09/18 AM 07:05"
    full_date = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", cleaned)
    md_match = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", cleaned)
    try:
        if full_date:
            target_date = date(*(int(part) for part in full_date.groups()))
        elif md_match:
            month, day = (int(part) for part in md_match.groups())
            candidates = []
            for year in (target_date.year - 1, target_date.year, target_date.year + 1):
                try:
                    candidates.append(date(year, month, day))
                except ValueError:
                    pass
            if not candidates:
                return None
            target_date = min(candidates, key=lambda candidate: abs((candidate - target_date).days))
    except ValueError:
        return None

    # Check for AM/PM
    ampm_match = re.search(r"(AM|PM)\s*(\d{1,2}):(\d{2})", cleaned, re.I)
    if ampm_match:
        period = ampm_match.group(1).upper()
        hour = int(ampm_match.group(2))
        minute = int(ampm_match.group(3))
        if period == "PM" and hour < 12:
            hour += 12
        elif period == "AM" and hour == 12:
            hour = 0
    else:
        # Check 24-hr format e.g. "19:30"
        h24_match = re.search(r"(\d{1,2}):(\d{2})", cleaned)
        if h24_match:
            hour = int(h24_match.group(1))
            minute = int(h24_match.group(2))
        else:
            return None

    try:
        local_dt = datetime.combine(target_date, time(hour, minute), tzinfo=TAIPEI_TZ)
    except ValueError:
        return None
    return local_dt.astimezone(UTC_TZ).isoformat()


def format_utc_to_taipei(utc_iso_str: str) -> str:
    """Format UTC ISO string into readable Taipei time (e.g. '09/18 06:40 (台北)')."""
    try:
        dt = datetime.fromisoformat(utc_iso_str.replace("Z", "+00:00"))
        taipei_dt = dt.astimezone(TAIPEI_TZ)
        return taipei_dt.strftime("%m/%d %H:%M")
    except Exception:
        return utc_iso_str
