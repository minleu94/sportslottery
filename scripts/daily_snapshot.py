#!/usr/bin/env python3
"""Daily Prediction & Parlay Snapshot Job.

Executes daily forward pipeline:
1. Refreshes live Taiwan odds across all active sports leagues
2. Evaluates signals & evidence under the current version from core.strategy_version
3. Appends all evaluated TaiwanLegs to `data/historical/prediction_snapshots.jsonl`
4. Searches parlay candidates across 10-25x, 25-75x, 75-200x, 200-500x
5. Appends parlay candidate snapshots to `data/historical/parlay_snapshots.jsonl`
6. Places daily Top HIGH, Top MED, and Top Target simulated bets into Shadow Portfolio
7. Prints clean audit summary.

Usage:
  python scripts/daily_snapshot.py
"""

from __future__ import annotations

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

from core.parlay_engine import ParlayEngine
from core.scraper import PlaysportScraper
from core.shadow_parlay_logger import ShadowParlayLogger
from core.shadow_portfolio import ShadowPortfolioManager
from core.signal_hub import SignalHub
from core.snapshot_logger import PredictionSnapshotLogger
from core.strategy_version import STRATEGY_VERSION, get_strategy_metadata
from integrations.experts.playsport_crowd import PlaysportCrowdAdapter
from integrations.experts.playsport_expert import PlaysportExpertAdapter
from integrations.models.external.fivethirtyeight_mlb_elo import FiveThirtyEightMLBEloAdapter
from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_daily_snapshot():
    now_iso = datetime.now(timezone.utc).isoformat()
    meta = get_strategy_metadata()

    print("=" * 68)
    print("📸 執行每日影子預測快照 (DAILY SHADOW PREDICTION SNAPSHOT)")
    print(f"   策略版本: {STRATEGY_VERSION} | 程式版本: {meta['code_version']}")
    print(f"   快照時間: {now_iso}")
    print("=" * 68)

    # Initialize components
    scraper = PlaysportScraper()
    odds_adapter = PlaysportOddsAdapter(scraper=scraper)
    expert_adapter = PlaysportExpertAdapter(scraper=scraper)
    crowd_adapter = PlaysportCrowdAdapter()
    hub = SignalHub(
        expert_adapter=expert_adapter,
        crowd_adapter=crowd_adapter,
    )


    engine = ParlayEngine(signal_hub=hub)
    snap_logger = PredictionSnapshotLogger()
    parlay_logger = ShadowParlayLogger()
    portfolio = ShadowPortfolioManager()

    # 1. Fetch live Taiwan legs
    print("\n[Step 1/5] 抓取今日台灣運彩實際盤口...")
    alliances = ["1", "4", "93", "6", "2", "7"]
    raw_legs = odds_adapter.get_taiwan_legs(alliances)
    print(f"  ✓ 成功取得盤口注項: {len(raw_legs)} 筆")

    # 2. Evaluate signals & evidence
    print("\n[Step 2/5] 透過 Signal Hub 進行外部情報聚合與勝率評估...")
    enriched_legs = []
    for leg in raw_legs:
        enriched = hub.evaluate_taiwan_leg(leg)
        enriched_legs.append(enriched)
    print(f"  ✓ 完成情報注入: {len(enriched_legs)} 筆")

    # 3. Save prediction snapshots (append-only)
    print("\n[Step 3/5] 保存單場預測快照至 prediction_snapshots.jsonl (Append-Only)...")
    snaps = snap_logger.log_batch(enriched_legs)
    for leg, snapshot in zip(enriched_legs, snaps):
        leg.signal_evidence["snapshot_id"] = snapshot["snapshot_id"]
        leg.signal_evidence["forward_validation_eligible"] = snapshot["forward_validation_eligible"]
        leg.signal_evidence["forward_exclusion_reason"] = snapshot.get("exclusion_reason")
    print(f"  ✓ 已寫入單場快照: {len(snaps)} 筆")

    # 4. Search parlay candidates across all multiplier tiers
    print("\n[Step 4/5] 執行 4 大倍率階梯串關搜尋 (10x~500x)...")
    tiers = [
        ("10-25x", 10.0, 25.0),
        ("25-75x", 25.0, 75.0),
        ("75-200x", 75.0, 200.0),
        ("200-500x", 200.0, 500.0),
    ]

    tier_results = {}
    for tier_name, min_o, max_o in tiers:
        res = engine.search_parlays(
            legs=enriched_legs,
            min_odds=min_o,
            max_odds=max_o,
            signal_filter="wild",
            min_legs=2,
            max_legs=6,
        )
        tier_results[tier_name] = res
        hc_cnt = len(res.get("high_consensus", []))
        ag_cnt = len(res.get("aggressive", []))
        ms_cnt = len(res.get("moonshot", []))
        print(f"  • {tier_name:<9}: HIGH={hc_cnt} | AGGRESSIVE={ag_cnt} | MOONSHOT={ms_cnt} | 總計={hc_cnt+ag_cnt+ms_cnt}")

    # Save parlay candidate snapshots (even when 0 candidates)
    saved_parlays = parlay_logger.log_daily_parlays(tier_results, prediction_snapshots=snaps)
    print(f"  ✓ 已保存串關候選快照至 parlay_snapshots.jsonl: {len(saved_parlays)} 組階梯紀錄")

    # 5. Place daily simulated picks into Shadow Portfolio
    print("\n[Step 5/5] 自動模擬下注本日 Top HIGH / MED / Target 組合至影子錢包...")
    placed_tickets = portfolio.place_daily_top_picks(tier_results)
    for pt in placed_tickets:
        print(f"  ✓ 下注成功: [{pt['category']}] 注單ID={pt['ticket_id']} | 賠率={pt['total_odds']}x | 虛擬注金=NT$ {pt['virtual_stake']}")

    summary = portfolio.get_portfolio_summary(strategy_version=STRATEGY_VERSION, eligible_only=True)
    print("\n=======================================================")
    print("今日快照與影子錢包狀態總覽:")
    print(f"  策略版本:           {STRATEGY_VERSION}")
    print(f"  今日盤口數:         {len(enriched_legs)} 筆")
    print(f"  今日影子下注:       {len(placed_tickets)} 張 (每張 NT$ 10.0)")
    print(f"  影子錢包累積注單:   {summary['total_tickets_logged']} 張 (已結算: {summary['settled_tickets']})")
    print(f"  真實 NT$200 錢包:   嚴格隔離 · 未受任何影響 (FROZEN)")
    print("=======================================================\n")


if __name__ == "__main__":
    run_daily_snapshot()
