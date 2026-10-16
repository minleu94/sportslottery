#!/usr/bin/env python3
"""Weekly Shadow Evaluation Performance Report Generator.

Generates `reports/YYYY-Www.md` summarizing:
1. Total and settled predictions
2. HIGH vs MED vs LOW vs INSUFFICIENT bucket performance
3. Expert leaderboard and consensus performance
4. Model metrics (Brier, Log Loss, Calibration)
5. Crowd consensus buckets
6. Model-Market delta buckets
7. Shadow Portfolio virtual P/L & candidate parlay performance
8. Real User Wallet activity (strictly isolated section)
9. Progress toward First Milestone (>= 30 days or >= 200 settled single-leg predictions).

Usage:
  python scripts/generate_weekly_report.py [--week YYYY-Www]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sys

# Fix console encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.performance_metrics import PerformanceMetricsEngine
from ui.metric_format import metric_number
from core.experiment_identity import get_current_experiment_identity
from core.parlay_validation import evaluate_parlay_forward
from core.shadow_parlay_logger import ShadowParlayLogger
from core.shadow_portfolio import ShadowPortfolioManager
from core.snapshot_logger import PredictionSnapshotLogger
from core.strategy_version import STRATEGY_VERSION, get_strategy_metadata
from core.ticket_recorder import TicketRecorder
from core.wallet import WeeklyWalletManager, get_current_iso_week

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def generate_weekly_report(target_week: str | None = None) -> Path:
    week_str = target_week or get_current_iso_week()
    out_file = REPORTS_DIR / f"{week_str}.md"
    now_iso = datetime.now(timezone.utc).isoformat()
    meta = get_strategy_metadata()

    # Load data
    snap_logger = PredictionSnapshotLogger()
    parlay_logger = ShadowParlayLogger()
    portfolio = ShadowPortfolioManager()
    wallet_mgr = WeeklyWalletManager()
    recorder = TicketRecorder(wallet=wallet_mgr)

    snapshots = [s for s in snap_logger.get_all_snapshots() if s.get("strategy_version") == STRATEGY_VERSION]
    year, week = (int(part) for part in week_str.split("-W", 1))
    week_start = datetime.fromisocalendar(year, week, 1).replace(tzinfo=timezone.utc)
    week_end = week_start + timedelta(days=7)
    weekly_candidates = []
    for snapshot in snapshots:
        raw_timestamp = snapshot.get("snapshot_timestamp") or snapshot.get("timestamp")
        try:
            stamp = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
            if stamp.tzinfo is not None and week_start <= stamp.astimezone(timezone.utc) < week_end:
                weekly_candidates.append(snapshot)
        except (TypeError, ValueError, OverflowError):
            continue
    settled_snaps = PerformanceMetricsEngine.forward_cohort(snapshots)["observations"]

    # Evaluate metrics
    metrics = PerformanceMetricsEngine()
    experiment_id = get_current_experiment_identity()["experiment_id"]
    parlay_validation = evaluate_parlay_forward(parlay_logger.get_all_parlay_snapshots(), experiment_id)
    weekly_model_metrics = metrics.evaluate_model_overall_metrics(
        weekly_candidates, target_experiment_id=experiment_id)
    agree_metrics = metrics.evaluate_agreement_buckets(snapshots)
    delta_metrics = metrics.evaluate_model_market_delta_buckets(snapshots)
    expert_metrics = metrics.evaluate_expert_metrics(snapshots)
    crowd_metrics = metrics.evaluate_crowd_buckets(snapshots)
    calib_metrics = metrics.evaluate_calibration_bins(snapshots)
    model_overall = metrics.evaluate_model_overall_metrics(snapshots)
    portfolio_summary = portfolio.get_portfolio_summary(strategy_version=STRATEGY_VERSION, eligible_only=True)
    wallet_status = wallet_mgr.get_status()

    # Build report markdown
    lines = [
        f"# Weekly Shadow Evaluation & Performance Report: `{week_str}`",
        "",
        f"- **Generated At**: `{now_iso}`",
        f"- **Strategy Version**: `{STRATEGY_VERSION}`",
        "- **範圍**：本策略版本的累積前瞻結果；週別是報告產出標籤，並非只含該週事件。市場基準不列入模型校準。",
        f"- **Code Hash**: `{meta['code_version']}`",
        f"- **Experiment Identity**: `{experiment_id}`",
        f"- **Frozen Rules**: `NO_MID_TEST_WEIGHT_TUNING`, `MIN_SAMPLE_N30`",
        "",
        "---",
        "",
        "## 本週新增前瞻監測（按 snapshot_timestamp）",
        "",
        f"- **UTC 週期**：`{week_start.isoformat()}` 至 `{week_end.isoformat()}`（右端不含）",
        f"- **本週快照候選**：{len(weekly_candidates)} 筆；僅同一 experiment identity、有效且已結算的前瞻觀測會進指標。",
        f"- **有效支持數 N**：{weekly_model_metrics['sample_size']} · **打平門檻樣本不足 30**：`{weekly_model_metrics['is_insufficient_sample']}`",
        f"- **Brier**：{weekly_model_metrics['brier_score']} · **Log loss**：{weekly_model_metrics['log_loss']} · **命中率**：{metric_number(weekly_model_metrics['hit_rate'], '.4f')} · **ROI**：{metric_number(weekly_model_metrics['roi_pct'], '.2f', suffix='%')}",
        f"- **覆蓋稽核**：唯一賽事 {weekly_model_metrics['unique_event_count']} / 候選快照 {weekly_model_metrics['observation_count']}；Experiment `{experiment_id}`。",
        "- 此週報是台灣運彩生產前瞻監測；小樣本結果只作監看，不代表模型估計已驗證準確。",
        "",
        "---",
        "",
        "## 1. Executive Summary & Data Accumulation Milestone",
        "",
        f"- **Total Prediction Snapshots**: {len(snapshots)} 筆",
        f"- **Settled Prediction Snapshots**: {len(settled_snaps)} 筆",
        f"- **First Milestone Target**: $\\ge 200$ settled single-leg predictions 或 $\\ge 30$ 天實盤前瞻驗證",
        f"- **Milestone Progress**: {len(settled_snaps)} / 200 ({round(len(settled_snaps)/200.0*100, 1) if len(settled_snaps) < 200 else 100.0}%)",
        "",
        "> [!IMPORTANT]",
        "> **Small-Sample Safeguard**: 任何分類樣本數 $N < 30$ 一律標示為 `INSUFFICIENT_SAMPLE`，不得作為調參、加減權重或宣稱獲利之依據。",
        "",
        "---",
        "",
        "## 2. Research Data Quality & Exclusion Audit (資料品質與排除審查)",
        "",
        f"- **總預測快照 (Total Snapshots)**: {len(snapshots)} 筆",
        f"- **合格前瞻預測 (Forward Eligible)**: {sum(1 for s in snapshots if s.get('forward_validation_eligible') is True)} 筆",
        f"- **排除不計入指標 (Excluded Predictions)**: {sum(1 for s in snapshots if s.get('forward_validation_eligible') is not True)} 筆",
        "",
        "### 排除原因細目 (Research Exclusion Breakdown)",
        f"- **開賽後時間穿越 (POST_START_DATA)**: {sum(1 for s in snapshots if s.get('exclusion_reason') == 'POST_START_DATA')} 筆",
        f"- **大神發文時間未定 (EXPERT_TIME_UNKNOWN)**: {sum(1 for s in snapshots if s.get('exclusion_reason') == 'EXPERT_TIME_UNKNOWN')} 筆",
        f"- **過期盤口 (ODDS_STALE)**: {sum(1 for s in snapshots if s.get('exclusion_reason') in {'STALE_ODDS', 'ODDS_STALE'})} 筆",
        f"- **無有效關盤賠率 (NO_CLOSING_ODDS)**: {sum(1 for s in snapshots if s.get('closing_odds') is None and s.get('is_settled'))} 筆",
        f"- **賽果來源衝突/待定 (UNRESOLVED / PENDING)**: {sum(1 for s in snapshots if s.get('settlement_status') in ['UNRESOLVED', 'PENDING'])} 筆",
        f"- **重複串關去重節省 (Duplicate Wager Protection)**: 總串關候選單 {portfolio_summary['total_tickets_logged']} 組 ➔ 獨立投注單 {portfolio_summary.get('unique_parlays_count', portfolio_summary['total_tickets_logged'])} 組",
        "",
        "---",
        "",
        "## 3. Agreement Bucket Performance (信號品質階梯表現)",
        "",
        "最核心問題：**HIGH 共識是否真的在實盤表現上優於 MED 與 LOW？**",
        "",
        "| Agreement Bucket | Sample Size (N) | Wins | Hit Rate | Avg Odds | ROI (%) | Sample Status |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |",

    ]

    for bucket in ["HIGH", "MED", "LOW", "INSUFFICIENT"]:
        b_data = agree_metrics.get(bucket, {})
        n = b_data.get("sample_size", 0)
        wins = b_data.get("wins", 0)
        hr = metric_number(b_data.get('hit_rate'), ".1f", scale=100, suffix="%")
        avg_o = metric_number(b_data.get('average_odds'), ".2f")
        roi = metric_number(b_data.get('roi_pct'), "+.1f", suffix="%")
        status = "⚠️ INSUFFICIENT_SAMPLE" if b_data.get("is_insufficient_sample") else "✅ VALID_SAMPLE"
        lines.append(f"| **{bucket}** | {n} | {wins} | {hr} | {avg_o} | {roi} | {status} |")

    lines.extend([
        "",
        "---",
        "",
        "## 3. Model vs Market Delta Buckets (模型與台彩盤口差距表現)",
        "",
        "核心問題：**當模型與台彩賠率差距極大時，誰勝出的機率更高？**",
        "",
        "| Delta pp (Model - Market) | Sample Size (N) | Hit Rate | ROI (%) | Brier Score | Sample Status |",
        "| :--- | :---: | :---: | :---: | :---: | :--- |",
    ])

    for d_name, d_val in delta_metrics.items():
        n = d_val.get("sample_size", 0)
        hr = metric_number(d_val.get('hit_rate'), ".1f", scale=100, suffix="%")
        roi = metric_number(d_val.get('roi_pct'), "+.1f", suffix="%")
        brier = f"{d_val.get('brier_score', 0.0):.4f}" if d_val.get("brier_score") is not None else "N/A"
        status = "⚠️ INSUFFICIENT_SAMPLE" if d_val.get("is_insufficient_sample") else "✅ VALID_SAMPLE"
        lines.append(f"| **{d_name}** | {n} | {hr} | {roi} | {brier} | {status} |")

    lines.extend([
        "",
        "---",
        "",
        "## 4. Expert Leaderboard & Consensus Performance (大神實盤表現)",
        "",
        "### 大神支持數量分佈",
        "| Expert Consensus Count | Sample Size (N) | Hit Rate | ROI (%) | Sample Status |",
        "| :--- | :---: | :---: | :---: | :--- |",
    ])

    for c_name, c_val in expert_metrics.get("consensus_count_buckets", {}).items():
        n = c_val.get("sample_size", 0)
        hr = metric_number(c_val.get('hit_rate'), ".1f", scale=100, suffix="%")
        roi = metric_number(c_val.get('roi_pct'), "+.1f", suffix="%")
        status = "⚠️ INSUFFICIENT_SAMPLE" if c_val.get("is_insufficient_sample") else "✅ VALID_SAMPLE"
        lines.append(f"| **{c_name}** | {n} | {hr} | {roi} | {status} |")

    lines.extend([
        "",
        "### 獨立驗證大神個人表現排行榜",
        "| Expert Name | Sample Size (N) | Wins | Win Rate | Avg Odds | ROI (%) | Status |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ])

    leaderboard = expert_metrics.get("leaderboard", {})
    if not leaderboard:
        lines.append("| *尚無已結算專家注項* | 0 | 0 | 0.0% | 0.00 | 0.0% | ⚠️ INSUFFICIENT_SAMPLE |")
    else:
        for name, ev in sorted(leaderboard.items(), key=lambda x: x[1]["sample_size"], reverse=True):
            n = ev.get("sample_size", 0)
            w = ev.get("wins", 0)
            wr = metric_number(ev.get('win_rate'), ".1f", scale=100, suffix="%")
            ao = metric_number(ev.get('average_odds'), ".2f")
            roi = metric_number(ev.get('roi_pct'), "+.1f", suffix="%")
            status = "⚠️ INSUFFICIENT_SAMPLE" if ev.get("is_insufficient_sample") else "✅ VALID"
            lines.append(f"| **{name}** | {n} | {w} | {wr} | {ao} | {roi} | {status} |")

    lines.extend([
        "",
        "---",
        "",
        "## 5. Crowd Consensus Buckets (彩迷選票盲從性檢驗)",
        "",
        "核心問題：**極高彩迷支持率（>70%）是真實領先指標，抑或純粹是大眾熱門偏誤？**",
        "",
        "| Crowd Support Range | Sample Size (N) | Hit Rate | ROI (%) | Sample Status |",
        "| :--- | :---: | :---: | :---: | :--- |",
    ])

    for cr_name, cr_val in crowd_metrics.items():
        n = cr_val.get("sample_size", 0)
        hr = metric_number(cr_val.get('hit_rate'), ".1f", scale=100, suffix="%")
        roi = metric_number(cr_val.get('roi_pct'), "+.1f", suffix="%")
        status = "⚠️ INSUFFICIENT_SAMPLE" if cr_val.get("is_insufficient_sample") else "✅ VALID_SAMPLE"
        lines.append(f"| **{cr_name}** | {n} | {hr} | {roi} | {status} |")

    lines.extend([
        "",
        "---",
        "",
        "## 6. Model Overall & Calibration (機率模型校準表現)",
        "",
        f"- **Model Sample Size**: {model_overall.get('sample_size', 0)} 筆",
        f"- **Accuracy**: {metric_number(model_overall.get('classification_accuracy'), scale=100, suffix='%')}",
        f"- **Brier Score**: {model_overall.get('brier_score', 'N/A')}",
        f"- **Log Loss**: {model_overall.get('log_loss', 'N/A')}",
        "",
        "### Calibration Table (預測機率區間 vs 實際命中率)",
        "| Probability Bin | Sample Size (N) | Avg Predicted Prob | Empirical Hit Rate | Calibration Error |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ])

    for bin_name, bin_val in calib_metrics.items():
        n = bin_val.get("sample_size", 0)
        pred_p = metric_number(bin_val.get('avg_predicted_prob'), ".1f", scale=100, suffix="%")
        emp_h = metric_number(bin_val.get('empirical_hit_rate'), ".1f", scale=100, suffix="%")
        err = metric_number(bin_val.get('calibration_error'), ".2f", scale=100, suffix=" pp")
        lines.append(f"| **{bin_name}** | {n} | {pred_p} | {emp_h} | {err} |")

    lines.extend([
        "",
        "---",
        "",
        "## 7. Shadow Portfolio Performance (虛擬影子投資組合)",
        "",
        f"- **虛擬單筆注金**: NT$ 10.0 (固定注額)",
        f"- **累積已結算單數**: {portfolio_summary['settled_tickets']} 張 (待開獎: {portfolio_summary['open_tickets']} 張)",
        f"- **累積命中單數**: {portfolio_summary['wins']} 張 (勝率: {portfolio_summary['win_rate']*100:.1f}%)",
        f"- **累積虛擬投注金**: NT$ {portfolio_summary['total_virtual_staked']:.2f}",
        f"- **累積虛擬獲賠額**: NT$ {portfolio_summary['total_virtual_payout']:.2f}",
        f"- **淨損益 (Net P/L)**: NT$ {portfolio_summary['net_pl']:+.2f}",
        f"- **虛擬投資回報率 (ROI)**: {portfolio_summary['roi_pct']:+.2f}% (N = {portfolio_summary['settled_tickets']})",
        "",
        "> [!NOTE]",
        "> 串關高倍率具有天然極高方差。在樣本數累積至數百張前，單次大獎可能使短線 ROI 劇烈震盪，此處僅供前瞻策略評估。",
        "",
        "---",
        "",
        "## 8. Real User Betting Ledger (真實使用者每週 NT$200 錢包 - 嚴格獨立)",
        "",
        "> [!IMPORTANT]",
        "> 本區塊為真實使用者下注記錄，與上方 Shadow Portfolio 完全隔離，彼此無任何依賴或資料滲透。",
        "",
        f"- **本週錢包餘額**: NT$ {wallet_status['weekly_wallet_balance']:.2f}",
        f"- **本週已下注額**: NT$ {wallet_status['weekly_staked']:.2f}",
        f"- **累積獲利池 (Prize Pool)**: NT$ {wallet_status['prize_pool']:.2f}",
        f"- **本週外部儲值額**: NT$ {wallet_status['weekly_external_deposited']:.2f}",
        "",
        "---",
        "",
        "## 9. Next Governance Review & Product Reality",
        "",
        "- **當前定位**: 決策支援與前瞻研究系統（Decision Support / Research Tool），不宣稱為穩賺保證獲利系統。",
        "- **下次月度治理審查（Monthly Review）**: 需累積至第一里程碑（$N \\ge 200$ 筆已結算預測）後，方可召開審查會討論是否調整信號權重或門檻值。",
    ])

    lines.extend(["", "## 整張串關前瞻驗證", "",
                  "只計同實驗、賽前封存且各關都有來源可追查的完整二元結果；退盤／打平另行排除。",
                  "相同選擇的重複候選只留最早紀錄。信賴區間按共用賽事與 UTC 賽事日連通群抽樣，群數不足時保持未知。", "",
                  "| 倍率 | 唯一注單 N | 事件日群數 | 平均估計機率 | 實際命中率 | Brier | Log loss | 固定單位 ROI |", 
                  "|---|---:|---:|---:|---:|---:|---:|---:|"])
    interval_notes = []
    for tier, values in parlay_validation["tiers"].items():
        display = lambda value: "未知" if value is None else f"{value:.5f}"
        lines.append(f"| {tier} | {values['n']} | {values['event_slate_cluster_count']} | "
                     f"{display(values['mean_estimated_probability'])} | {display(values['hit_rate'])} | "
                     f"{display(values['brier'])} | {display(values['log_loss'])} | {display(values['roi_pct'])}% |")
        interval_notes.append(f"\n{tier} 95% 群組 bootstrap：{values['cluster_bootstrap_ci95'] or '未知：事件日群數不足'}；"
                     f"未折扣 Brier={display(values['naive_brier'])}，機率仍為未驗證規則估計。\n")
    lines.extend(interval_notes)
    lines.append(f"排除稽核：{parlay_validation['excluded_counts']}")
    out_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ 成功生成週報: {out_file}")
    return out_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate weekly shadow report")
    parser.add_argument("--week", type=str, default=None, help="Target week format YYYY-Www")
    args = parser.parse_args()
    generate_weekly_report(args.week)
