#!/usr/bin/env python3
"""Lightweight Taiwan odds observation history.

Maintains an append-only time series of observed Taiwan Lottery odds in
`data/historical/odds_history.jsonl`.
Queries the last eligible pre-start observation and computes price movement:
1. Odds movement ratio: `prediction_odds / observed_odds - 1.0`
2. Implied probability movement: `(1/observed_odds - 1/prediction_odds) * 100.0`

Missing observations are recorded as `NOT_AVAILABLE`; fabrication from prediction
or post-match odds is strictly forbidden.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from core.bet_validation import MAX_ODDS_AGE, assess_leg, parse_aware_time
from core.research_paths import research_paths
from core.persistence import append_jsonl

logger = logging.getLogger(__name__)

HISTORICAL_DIR = Path(__file__).resolve().parents[1] / "data" / "historical"
ODDS_HISTORY_FILE = research_paths()["odds"]


class OddsWatcher:
    """Records real-time odds observations and extracts genuine pre-game closing odds."""

    def __init__(self, history_path: Optional[Path] = None):
        self.history_path = history_path or ODDS_HISTORY_FILE
        self.history_path.parent.mkdir(parents=True, exist_ok=True)

    def record_observation(
        self,
        event_id: str,
        sport: str,
        league: str,
        market: str,
        selection: str,
        odds: float,
        observed_at: Optional[str] = None,
        event_start: Optional[str] = None,
        line: Optional[float] = None,
        source: str = "PLAYSPORT_TAIWAN_ODDS",
        status: str = "LIVE",
        canonical_event_id: Optional[str] = None,
        side: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record an immutable odds observation point."""
        if not math.isfinite(float(odds)) or float(odds) <= 1:
            raise ValueError("觀測賠率必須是大於 1 的有限值。")
        now_iso = observed_at

        record = {
            "event_id": str(event_id),
            "canonical_event_id": canonical_event_id,
            "sport": sport,
            "league": league,
            "market": market,
            "selection": selection,
            "side": side,
            "line": line,
            "odds": float(odds),
            "observed_at": now_iso,
            "event_start": event_start,
            "source": source,
            "status": status if parse_aware_time(observed_at) else "UNKNOWN",
        }

        append_jsonl(self.history_path, record)

        return record

    def record_batch_from_legs(self, legs: List[Any], source: str = "PLAYSPORT_TAIWAN_ODDS", *, now=None) -> int:
        """Record observations for a batch of TaiwanLeg objects."""
        count = 0
        for leg in legs:
            odds = getattr(leg, "taiwan_odds", 0.0)
            if not assess_leg(leg, now=now)["is_ready"]:
                continue
            self.record_observation(
                event_id=getattr(leg, "event_id", ""),
                sport=getattr(leg, "sport", ""),
                league=getattr(leg, "league", ""),
                market=getattr(leg, "market", ""),
                selection=getattr(leg, "selection", ""),
                odds=odds,
                observed_at=getattr(leg, "odds_scraped_at", None),
                event_start=getattr(leg, "start_time_utc", None) or getattr(leg, "start_time", None),
                line=getattr(leg, "line", None),
                source=source,
                status=getattr(leg, "odds_status", "LIVE"),
                canonical_event_id=getattr(leg, "canonical_event_id", None),
                side=getattr(leg, "side", None),
            )
            count += 1
        return count

    def get_closing_odds(
        self,
        event_id: str,
        market: str,
        selection: str,
        event_start_iso: Optional[str],
        line: Optional[Any] = None,
        canonical_event_id: Optional[str] = None,
        sport: Optional[str] = None,
        league: Optional[str] = None,
    ) -> Tuple[Optional[float], str]:
        """Legacy API: find the last fresh observed odds strictly before start.

        Returns (observed_odds, status); this does not prove an official close.
        If no observation strictly before start time exists, returns (None, "NOT_AVAILABLE").
        """
        if not self.history_path.exists():
            return None, "NOT_AVAILABLE"

        matching_obs = []
        event_start_dt = parse_aware_time(event_start_iso)
        if event_start_dt is None:
            return None, "NOT_AVAILABLE"

        def same_line(first, second):
            if first is None or second is None:
                return first is None and second is None
            try:
                return math.isfinite(float(first)) and math.isfinite(float(second)) and float(first) == float(second)
            except (ValueError, TypeError):
                return False

        for raw_line in self.history_path.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
            except Exception:
                continue

            if (
                str(data.get("event_id")) == str(event_id)
                and data.get("market") == market
                and data.get("selection") == selection
                and same_line(data.get("line"), line)
                and (not canonical_event_id or data.get("canonical_event_id") == canonical_event_id)
                and (not sport or data.get("sport") == sport)
                and (not league or data.get("league") == league)
            ):
                observed = parse_aware_time(data.get("observed_at"))
                observation_start = parse_aware_time(data.get("event_start"))
                if (observed is None or observation_start != event_start_dt
                        or data.get("status") not in {"LIVE", "FRESH"}
                        or not observed < event_start_dt or event_start_dt - observed > MAX_ODDS_AGE):
                    continue
                try:
                    observed_odds = float(data["odds"])
                    if math.isfinite(observed_odds) and observed_odds > 1:
                        matching_obs.append((observed, observed_odds, data.get("sport"), data.get("league")))
                except (TypeError, ValueError, KeyError):
                    continue

        if not matching_obs:
            return None, "NOT_AVAILABLE"
        if len({(row[2], row[3]) for row in matching_obs}) > 1:
            return None, "NOT_AVAILABLE"

        # Sort chronologically and take the last pre-game observation
        matching_obs.sort(key=lambda x: x[0])
        closing_odds = matching_obs[-1][1]
        return closing_odds, "RECORDED"

    def get_last_prestart_observation(
        self,
        *,
        event_id: str,
        canonical_event_id: Optional[str],
        sport: str,
        league: str,
        market: str,
        side: str,
        selection: str,
        line: Optional[Any],
        event_start: str,
        as_of: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return the latest exact-match, source-backed quote observed pre-start.

        This reports the last stored pre-start observation, never an authoritative
        book close. All timestamps must be aware and quotes after ``as_of`` are ignored.
        """
        if not self.history_path.exists():
            return None
        try:
            rows = [json.loads(raw) for raw in self.history_path.read_text(encoding="utf-8").splitlines()]
        except (OSError, ValueError):
            return None
        return select_last_prestart_observation(
            rows, event_id=event_id, canonical_event_id=canonical_event_id, sport=sport,
            league=league, market=market, side=side, selection=selection, line=line,
            event_start=event_start, as_of=as_of,
        )



    @staticmethod
    def compute_clv_metrics(
        prediction_odds: float,
        closing_odds: Optional[float],
        reference_closing_odds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Calculate dual price-movement metrics against an observed reference price."""
        if (closing_odds is None or not math.isfinite(closing_odds) or closing_odds <= 1.0
                or not math.isfinite(prediction_odds) or prediction_odds <= 1.0):
            return {
                "closing_odds": None,
                "clv_status": "NOT_AVAILABLE",
                "odds_clv_ratio": None,
                "clv_probability_pp": None,
                "reference_closing_odds": reference_closing_odds,
            }

        # 1. Decimal Odds CLV Ratio: prediction_odds / closing_odds - 1.0
        odds_clv_ratio = round((prediction_odds / closing_odds) - 1.0, 4)

        # 2. Implied Probability Movement: (closing_implied - prediction_implied) * 100.0
        pred_implied = 1.0 / prediction_odds
        close_implied = 1.0 / closing_odds
        clv_prob_pp = round((close_implied - pred_implied) * 100.0, 2)

        status = "BEAT_CLOSING" if prediction_odds > closing_odds else "EQUAL_CLOSING" if prediction_odds == closing_odds else "TRAIL_CLOSING"

        return {
            "closing_odds": round(closing_odds, 2),
            "clv_status": status,
            "odds_clv_ratio": odds_clv_ratio,
            "clv_probability_pp": clv_prob_pp,
            "reference_closing_odds": reference_closing_odds,
        }

def select_last_prestart_observation(
    rows: List[Dict[str, Any]], *, event_id: str, canonical_event_id: Optional[str],
    sport: str, league: str, market: str, side: str, selection: str, line: Optional[Any],
    event_start: str, as_of: Optional[Any] = None, not_before: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Pure selector for exact-match, source-backed pre-start observations."""
    start_dt = parse_aware_time(event_start)
    cutoff = parse_aware_time(as_of) if as_of is not None else datetime.now(timezone.utc)
    lower_bound = parse_aware_time(not_before) if not_before is not None else None
    if start_dt is None or cutoff is None or (not_before is not None and lower_bound is None):
        return None

    def same_line(left: Any, right: Any) -> bool:
        if left is None or right is None:
            return left is None and right is None
        try:
            return math.isfinite(float(left)) and math.isfinite(float(right)) and float(left) == float(right)
        except (TypeError, ValueError, OverflowError):
            return False

    matches = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        observed = parse_aware_time(row.get("observed_at"))
        row_start = parse_aware_time(row.get("event_start"))
        if (str(row.get("event_id")) != str(event_id)
                or row.get("canonical_event_id") != canonical_event_id
                or row.get("sport") != sport or row.get("league") != league
                or row.get("market") != market or row.get("side") != side
                or row.get("selection") != selection or not same_line(row.get("line"), line)
                or row_start != start_dt or observed is None or not observed < start_dt
                or (lower_bound is not None and observed < lower_bound)
                or observed > cutoff or row.get("status") not in {"LIVE", "FRESH"}):
            continue
        source = row.get("source")
        if not isinstance(source, str) or not source.strip() or source.strip().upper() in {
                "UNKNOWN", "MANUAL", "TEST", "FIXTURE"}:
            continue
        try:
            odds = float(row.get("odds"))
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(odds) or odds <= 1:
            continue
        matches.append((observed, {**row, "odds": odds}))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[-1][1]

