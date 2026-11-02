"""Repeatable CPU-only benchmark for cached parlay search computation.

Run from the repository root with ``python tests/benchmark_parlay_search.py``.
The input pool is deterministic and already contains Taiwan odds; this never
calls the odds provider or consumes API credits.
"""
from __future__ import annotations

import statistics
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.parlay_engine import ParlayEngine
from integrations.common.models import TaiwanLeg


SCOPE_AS_OF = "2026-11-01T12:00:00+00:00"
REPEATS = 20


def fixed_cached_legs() -> list[TaiwanLeg]:
    now = datetime.fromisoformat(SCOPE_AS_OF)
    return [
        TaiwanLeg(
            event_id=f"bench-event-{event:02d}", sport="baseball", league="MLB",
            market="不讓分", selection=f"selection-{option}", side=("主" if option % 2 else "客"),
            taiwan_odds=(1.55, 1.75, 2.05)[option],
            away_team=f"Away {event}", home_team=f"Home {event}",
            odds_status="FRESH", odds_scraped_at=SCOPE_AS_OF,
            start_time_utc=(now + timedelta(days=2, minutes=event)).isoformat(),
            evidence_quality=("HIGH", "MED", "LOW")[option],
            signal_evidence={"agreement": "MED", "evidence_quality": ("HIGH", "MED", "LOW")[option],
                             "non_market_supports": option % 2,
                             "line_movement": {"is_steam": option == 0, "is_trap_warning": False}},
        )
        for event in range(24) for option in range(3)
    ]


def run_once() -> tuple[float, dict, dict]:
    diagnostic: dict = {}
    started = time.perf_counter()
    result = ParlayEngine(signal_hub=object()).search_parlays(
        fixed_cached_legs(), min_odds=2.0, max_odds=20.0, min_legs=2, max_legs=4,
        signal_filter="wild", search_budget=25_000,
        scope_as_of=SCOPE_AS_OF, diagnostics=diagnostic,
    )
    elapsed = time.perf_counter() - started
    signature = {tier: [row["candidate_id"] for row in rows] for tier, rows in result.items()}
    return elapsed, diagnostic, signature


def main() -> None:
    runs = [run_once() for _ in range(REPEATS)]
    elapsed = [row[0] for row in runs]
    p95 = sorted(elapsed)[math.ceil(0.95 * len(elapsed)) - 1]
    baseline_diag = runs[-1][1]
    baseline_signature = runs[-1][2]
    assert all(row[2] == baseline_signature for row in runs), "deterministic candidate ranking changed between runs"
    print(f"runs={REPEATS} median_seconds={statistics.median(elapsed):.6f} p95_seconds={p95:.6f} min_seconds={min(elapsed):.6f}")
    print(f"input_options={baseline_diag['normalized_option_count']} events={baseline_diag['search_event_count']} "
          f"budget={baseline_diag['search_budget']} visited={baseline_diag['visited_nodes_this_call']} "
          f"checked={baseline_diag['checked_combinations']} odds_matches={baseline_diag['odds_matching_combinations']} "
          f"complete={baseline_diag['search_complete']}")
    print("top_candidate_ids=" + repr(baseline_signature))


if __name__ == "__main__":
    main()
