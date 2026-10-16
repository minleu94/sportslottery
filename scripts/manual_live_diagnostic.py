"""Manual live scrape + optimizer diagnostic; intentionally not a pytest test."""
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.optimizer import ParlayOptimizer
from core.scraper import PlaysportScraper


def main() -> int:
    print("Starting scraper for MLB...", flush=True)
    started = time.time()
    matches = PlaysportScraper().fetch_scale_matches("1", force_refresh=True)
    print(f"Scraped {len(matches)} MLB matches in {time.time() - started:.2f}s", flush=True)

    print("Starting optimizer...", flush=True)
    started = time.time()
    results = ParlayOptimizer(min_odds=10.0, max_odds=500.0).optimize(
        matches, min_odds=10.0, max_odds=500.0, top_n=5, stake=200.0)
    print(f"Optimization finished in {time.time() - started:.2f}s! Found {len(results)} combinations.", flush=True)
    for result in results:
        print(f"Rank {result['rank']}: {result['parlay_name']} | Odds: {result['total_odds']}x | "
              f"EV: {result['ev_percent']}% | Win%: {result['win_prob_percent']}% | "
              f"Payout: NT$ {result['potential_payout']}", flush=True)
        for leg in result["legs"]:
            print(f"   -> [{leg['league']}] {leg['away_team']} vs {leg['home_team']}: {leg['selection']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
