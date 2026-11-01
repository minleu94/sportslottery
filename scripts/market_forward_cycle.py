#!/usr/bin/env python3
"""CLI Script to execute Market Intelligence & Continuous Forward Validation Cycle.

Usage:
  python scripts/market_forward_cycle.py [--leagues MLB,NBA,SOCCER] [--force-refresh]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Fix console encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.market_forward_pipeline import MarketForwardPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run continuous market snapshot and forward evaluation cycle.")
    parser.add_argument("--leagues", default="MLB,NBA,NFL,SOCCER", help="Comma-separated leagues")
    parser.add_argument("--force-refresh", action="store_true", help="Force live fetch ignoring cache TTL")
    args = parser.parse_args()

    leagues = [l.strip().upper() for l in args.leagues.split(",") if l.strip()]
    logger.info("Starting Market Forward Validation Cycle for leagues: %s", leagues)

    pipeline = MarketForwardPipeline()
    result = pipeline.run_full_cycle(leagues=leagues, force_refresh=args.force_refresh)

    print("\n" + "=" * 65)
    print("🚀 MARKET FORWARD VALIDATION CYCLE EXECUTION SUMMARY")
    print("=" * 65)
    print(f"Status: {result.get('cycle_status')}")
    print(f"Timestamp: {result.get('timestamp_utc')}")

    snap = result.get("snapshot_cycle", {})
    print("\n[Snapshots]")
    print(f"  Processed Legs: {snap.get('total_legs_processed')}")
    print(f"  Matched International: {snap.get('total_matched')}")
    print(f"  Unmatched: {snap.get('total_unmatched')}")
    print(f"  Snapshots Logged: {snap.get('snapshots_logged')}")

    ev = result.get("evaluation_summary", {})
    print("\n[Forward Acceptance Evaluation]")
    print(f"  Sample Size (N): {ev.get('sample_size')} (Threshold: >= 30)")
    print(f"  Status: {ev.get('status')}")
    print(f"  Active Champion: {ev.get('champion_source')}")
    print(f"  Shadow Mode: {ev.get('shadow_mode_recommendation')}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
