#!/usr/bin/env python3
"""Lightweight Taiwan Odds Watcher Job.

Polls Taiwan Lottery odds without invoking expensive AI models.
Records odds observations into `data/historical/odds_history.jsonl`
to capture genuine pre-game closing odds.

Usage:
  python scripts/odds_watcher.py
"""

from __future__ import annotations

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

from core.odds_watcher import OddsWatcher
from core.scraper import PlaysportScraper
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_odds_watcher():
    now_iso = datetime.now(timezone.utc).isoformat()
    print("=" * 65)
    print("⏱️ 執行台灣運彩輕量盤口監控 (LIGHTWEIGHT ODDS WATCHER)")
    print(f"   觀測時間: {now_iso}")
    print("=" * 65)

    scraper = PlaysportScraper()
    odds_adapter = PlaysportOddsAdapter(scraper=scraper)
    watcher = OddsWatcher()

    alliances = ["1", "4", "93", "6", "2", "7"]
    raw_legs = odds_adapter.get_taiwan_legs(alliances)
    print(f"  ✓ 成功抓取最新盤口注項: {len(raw_legs)} 筆")

    recorded = watcher.record_batch_from_legs(raw_legs)
    print(f"  ✓ 已保存盤口時間序列至 odds_history.jsonl: {recorded} 點")
    print("=" * 65)


if __name__ == "__main__":
    run_odds_watcher()
