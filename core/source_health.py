"""Privacy-safe completeness metrics for upstream data sources."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from core.bet_validation import has_complete_team_identity


def build_identity_health(matches: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(matches)
    complete = sum(not bool(row.get("_identity_incomplete")) and has_complete_team_identity(row)
                   for row in rows)
    diagnostics: Dict[str, int] = {}
    for row in rows:
        reason = row.get("_identity_diagnostic")
        if not reason and not has_complete_team_identity(row):
            reason = "missing_placeholder_or_duplicate_team"
        if reason:
            diagnostics[str(reason)] = diagnostics.get(str(reason), 0) + 1
    return {
        "identity_total_count": len(rows),
        "identity_complete_count": complete,
        "identity_incomplete_count": len(rows) - complete,
        "identity_completeness_rate": round(complete / len(rows), 4) if rows else None,
        "identity_diagnostic_counts": diagnostics,
    }


def append_source_health_observation(path: Optional[Path], alliance_id: str,
                                     status: Dict[str, Any], health: Dict[str, Any]) -> None:
    """Append counts/provenance only; never persist team or selection identities."""
    if path is None:
        return
    observation = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "alliance_id": str(alliance_id),
        "source_status": status.get("source_status"),
        "source_url": status.get("source_url"),
        "observed_at": status.get("observed_at"),
        "attempted_at": status.get("attempted_at"),
        "failure_status": status.get("failure_status"),
        "match_count": status.get("match_count", health["identity_total_count"]),
        **health,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(observation, ensure_ascii=False) + "\n")
