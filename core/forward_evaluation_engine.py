#!/usr/bin/env python3
"""Forward Validation, Shadow Logging, and Comparative Strategy Benchmarking.

Milestone 5 of Phase 4: Global Market Intelligence & Prediction Quality Upgrade.

Guarantees:
1. Strict pre-match provenance: Only forecasts prior to event_start count.
2. Event-level deduplication: Repeated snapshots cannot inflate the sample count.
3. Multi-dimensional metrics: Brier Score, Log Loss, Calibration, CLV, Settled ROI, Max Drawdown.
4. Bootstrap 95% Confidence Intervals and sample size thresholds.
5. Multi-baseline comparison:
   - Taiwan Lottery Naive Implied Baseline
   - International Sharp Market Benchmark
   - Model / Fused Strategy
6. Production-decision qualification requires at least 30 paired events and a
   95% bootstrap interval showing lower Brier loss than the sharp benchmark.
7. Shadow Logging mechanism for new uncertified signals.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.persistence import append_jsonl

SHADOW_FORWARD_LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "research" / "shadow_forward_records.jsonl"
MIN_FORWARD_EVALUATION_SAMPLE = 30


@dataclass
class QuantitativeMetrics:
    """Rigorous quantitative metrics for a single prediction strategy or benchmark."""
    sample_size: int
    brier_score: Optional[float]
    log_loss: Optional[float]
    clv_mean_pct: Optional[float]
    settled_roi_pct: Optional[float]
    roi_ci_95: Optional[Tuple[float, float]]
    brier_ci_95: Optional[Tuple[float, float]]
    max_drawdown_pct: Optional[float]
    win_rate_pct: Optional[float]
    status: str                             # 'VALIDATED', 'INSUFFICIENT_EVIDENCE', 'DATA_LEAK_REJECTED'
    bet_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.roi_ci_95:
            data["roi_ci_95"] = [round(x, 2) for x in self.roi_ci_95]
        if self.brier_ci_95:
            data["brier_ci_95"] = [round(x, 4) for x in self.brier_ci_95]
        return data


@dataclass
class StrategyComparisonReport:
    """Three-way benchmark comparing Taiwan Base, International Sharp, and Model."""
    evaluation_scope: str                   # e.g. "MLB_MONEYLINE"
    as_of_utc: str
    sample_size: int
    paired_sample_size: int
    taiwan_market_baseline: QuantitativeMetrics
    international_sharp_benchmark: QuantitativeMetrics
    active_model_strategy: QuantitativeMetrics
    delta_roi_vs_taiwan_base_pp: Optional[float]
    delta_roi_vs_sharp_benchmark_pp: Optional[float]
    delta_brier_vs_sharp_benchmark: Optional[float]
    delta_brier_ci_95: Optional[Tuple[float, float]]
    champion_source: str                    # 'INTERNATIONAL_SHARP_BENCHMARK' or 'ACTIVE_MODEL'
    acceptance_gate_qualified: bool
    status: str
    shadow_mode_recommendation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_scope": self.evaluation_scope,
            "as_of_utc": self.as_of_utc,
            "sample_size": self.sample_size,
            "paired_sample_size": self.paired_sample_size,
            "taiwan_market_baseline": self.taiwan_market_baseline.to_dict(),
            "international_sharp_benchmark": self.international_sharp_benchmark.to_dict(),
            "active_model_strategy": self.active_model_strategy.to_dict(),
            "delta_roi_vs_taiwan_base_pp": self.delta_roi_vs_taiwan_base_pp,
            "delta_roi_vs_sharp_benchmark_pp": self.delta_roi_vs_sharp_benchmark_pp,
            "delta_brier_vs_sharp_benchmark": self.delta_brier_vs_sharp_benchmark,
            "delta_brier_ci_95": ([round(x, 4) for x in self.delta_brier_ci_95]
                                   if self.delta_brier_ci_95 else None),
            "champion_source": self.champion_source,
            "acceptance_gate_qualified": self.acceptance_gate_qualified,
            "status": self.status,
            "shadow_mode_recommendation": self.shadow_mode_recommendation,
        }


def compute_brier_score(probs: List[float], outcomes: List[int]) -> Optional[float]:
    if not probs or len(probs) != len(outcomes):
        return None
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes)) / len(probs)


def compute_log_loss(probs: List[float], outcomes: List[int]) -> Optional[float]:
    if not probs or len(probs) != len(outcomes):
        return None
    eps = 1e-15
    losses = []
    for p, y in zip(probs, outcomes):
        p_clipped = max(eps, min(1.0 - eps, p))
        loss = -(y * math.log(p_clipped) + (1 - y) * math.log(1.0 - p_clipped))
        losses.append(loss)
    return sum(losses) / len(losses)


def compute_max_drawdown(pnl_series: List[float]) -> float:
    """Calculate maximum drawdown in percentage from sequential cumulative PnL."""
    if not pnl_series:
        return 0.0
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnl_series:
        cum += pnl
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    return max_dd


def bootstrap_ci_mean(values: List[float], rounds: int = 1000, seed: int = 42) -> Optional[Tuple[float, float]]:
    if len(values) < 5:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(rounds):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    return means[int(0.025 * rounds)], means[int(0.975 * rounds)]


class ForwardEvaluationEngine:
    """Evaluates forward prediction performance and shadow cohorts."""

    def __init__(self, shadow_log_path: Optional[Path] = None):
        self.shadow_log_path = shadow_log_path or SHADOW_FORWARD_LOG_PATH
        self.shadow_log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_shadow_record(self, record: Dict[str, Any]) -> None:
        """Append an immutable snapshot to shadow records for prospective verification."""
        record_copy = dict(record)
        record_copy.setdefault("logged_at_utc", datetime.now(timezone.utc).isoformat())
        record_copy.setdefault("is_shadow_mode", True)
        append_jsonl(self.shadow_log_path, [record_copy])

    def evaluate_cohort(
        self,
        cohort: List[Dict[str, Any]],
        scope_name: str = "GLOBAL",
    ) -> StrategyComparisonReport:
        """Compare strategies on unique events and qualify only paired evidence."""
        now_utc = datetime.now(timezone.utc).isoformat()
        edge_threshold = 0.02

        def probability(value: Any) -> Optional[float]:
            try:
                parsed = float(value)
                return parsed if math.isfinite(parsed) and 0.0 <= parsed <= 1.0 else None
            except (TypeError, ValueError, OverflowError):
                return None

        def aware_time(value: Any) -> Optional[datetime]:
            try:
                parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
            except (TypeError, ValueError, OverflowError):
                return None

        def event_key(row: Dict[str, Any], start: datetime) -> Optional[str]:
            scope = f"{row.get('sport') or ''}:{row.get('league') or ''}"
            for field_name in ("canonical_event_id", "source_game_id", "source_event_id", "provider_event_id", "game_pk"):
                value = row.get(field_name)
                if value:
                    return f"{scope}:{field_name}:{value}"
            event_id = row.get("event_id") or row.get("match_id")
            if event_id:
                return f"{row.get('sport') or ''}:{row.get('league') or ''}:{event_id}:{start.isoformat()}"
            away, home = row.get("away_team"), row.get("home_team")
            if away and home:
                return f"{row.get('sport') or ''}:{row.get('league') or ''}:{away}:{home}:{start.isoformat()}"
            return None

        # Keep the latest valid pre-match observation for each event. This
        # prevents repeated snapshots or multiple markets from inflating N.
        latest_by_event: Dict[str, Tuple[datetime, str, Dict[str, Any]]] = {}
        for raw in cohort:
            pred_time = aware_time(raw.get("prediction_timestamp") or raw.get("snapshot_timestamp") or raw.get("logged_at_utc"))
            event_start = aware_time(raw.get("event_start") or raw.get("start_time_utc"))
            if pred_time is None or event_start is None or pred_time >= event_start:
                continue

            outcome = raw.get("outcome")
            if outcome is None:
                if raw.get("actual_outcome") is True or raw.get("settlement_status") == "WON":
                    outcome = 1
                elif raw.get("actual_outcome") is False or raw.get("settlement_status") == "LOST":
                    outcome = 0
            if outcome not in {0, 1}:
                continue

            try:
                odds = float(raw.get("taiwan_odds") or raw.get("decimal_odds"))
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(odds) or odds <= 1.0:
                continue

            evidence = raw.get("signal_evidence") or {}
            if (raw.get("is_synthetic") or raw.get("is_market_synthetic")
                    or evidence.get("is_market_synthetic")
                    or str(raw.get("market_source") or evidence.get("market_source") or "").upper() in {"SYNTHETIC", "MOCK"}):
                continue

            model_value = raw.get("model_prob") if raw.get("model_prob") is not None else raw.get("model_probability")
            if raw.get("probability_status") == "MARKET_BASELINE_ONLY":
                model_value = None
            model_value = probability(model_value)
            market_evidence = raw.get("market_evidence") or {}
            market_source = raw.get("market_source") or evidence.get("market_source") or market_evidence.get("market_source")
            market_source_key = str(market_source or "").strip().upper()
            sharp_value = raw.get("sharp_fair_prob")
            if sharp_value is None:
                sharp_value = raw.get("market_fair_probability")
            if sharp_value is None:
                sharp_value = evidence.get("market_fair_probability")
            if sharp_value is None:
                sharp_value = market_evidence.get("market_fair_probability")
            sharp_value = probability(sharp_value)
            if market_source_key in {"SYNTHETIC", "MOCK", "PLAYSPORT_TAIWAN_ODDS"}:
                sharp_value = None

            has_independent_evidence = bool(
                model_value is not None
                or sharp_value is not None
                or (market_source and market_source_key not in {"SYNTHETIC", "MOCK", "PLAYSPORT_TAIWAN_ODDS"})
            )
            if not has_independent_evidence:
                continue

            key = event_key(raw, event_start)
            if key is None:
                continue
            row = dict(raw)
            row.update({"outcome": int(outcome), "taiwan_odds": odds,
                        "model_prob": model_value, "sharp_fair_prob": sharp_value,
                        "_event_key": key, "_prediction_time": pred_time})
            if row.get("clv_pct") is None and row.get("odds_clv_ratio") is not None:
                try:
                    row["clv_pct"] = float(row["odds_clv_ratio"]) * 100.0
                except (TypeError, ValueError, OverflowError):
                    row["clv_pct"] = None
            previous = latest_by_event.get(key)
            snapshot_id = str(row.get("snapshot_id") or "")
            if previous is None or (pred_time, snapshot_id) > (previous[0], previous[1]):
                latest_by_event[key] = (pred_time, snapshot_id, row)

        clean_rows = [item[2] for item in latest_by_event.values()]
        clean_rows.sort(key=lambda row: (row["_prediction_time"], row["_event_key"]))
        paired_rows = [row for row in clean_rows if row["model_prob"] is not None and row["sharp_fair_prob"] is not None]
        n = len(clean_rows)
        paired_n = len(paired_rows)

        def metrics(rows: List[Dict[str, Any]], probability_key: str, *, bet_all: bool = False,
                    clv: bool = False) -> QuantitativeMetrics:
            sample_size = len(rows)
            outcomes = [int(row["outcome"]) for row in rows]
            probs = [float(row[probability_key]) for row in rows]
            brier = compute_brier_score(probs, outcomes)
            logloss = compute_log_loss(probs, outcomes)
            pnl: List[float] = []
            bet_outcomes: List[int] = []
            for row, prob in zip(rows, probs):
                if bet_all or (prob * row["taiwan_odds"] - 1.0) > edge_threshold:
                    pnl.append((row["taiwan_odds"] - 1.0) if row["outcome"] == 1 else -1.0)
                    bet_outcomes.append(int(row["outcome"]))
            roi = (sum(pnl) / len(pnl)) * 100.0 if pnl else None
            clv_values = []
            if clv:
                for row in rows:
                    try:
                        value = float(row.get("clv_pct"))
                        if math.isfinite(value):
                            clv_values.append(value)
                    except (TypeError, ValueError, OverflowError):
                        continue
            losses = [(prob - outcome) ** 2 for prob, outcome in zip(probs, outcomes)]
            return QuantitativeMetrics(
                sample_size=sample_size,
                brier_score=round(brier, 4) if brier is not None else None,
                log_loss=round(logloss, 4) if logloss is not None else None,
                clv_mean_pct=round(sum(clv_values) / len(clv_values), 2) if clv_values else None,
                settled_roi_pct=round(roi, 2) if roi is not None else None,
                roi_ci_95=bootstrap_ci_mean([value * 100.0 for value in pnl]),
                brier_ci_95=bootstrap_ci_mean(losses),
                max_drawdown_pct=round(compute_max_drawdown(pnl) * 100.0, 1) if pnl else None,
                win_rate_pct=round(sum(bet_outcomes) / len(bet_outcomes) * 100.0, 1) if bet_outcomes else None,
                status="VALIDATED" if sample_size else "INSUFFICIENT_EVIDENCE",
                bet_count=len(pnl),
            )

        def empty_metrics(sample_size: int = 0) -> QuantitativeMetrics:
            return QuantitativeMetrics(
                sample_size=sample_size, brier_score=None, log_loss=None, clv_mean_pct=None,
                settled_roi_pct=None, roi_ci_95=None, brier_ci_95=None,
                max_drawdown_pct=None, win_rate_pct=None, status="INSUFFICIENT_EVIDENCE", bet_count=0,
            )

        if n < MIN_FORWARD_EVALUATION_SAMPLE:
            empty = empty_metrics(n)
            return StrategyComparisonReport(
                evaluation_scope=scope_name, as_of_utc=now_utc, sample_size=n,
                paired_sample_size=paired_n,
                taiwan_market_baseline=empty, international_sharp_benchmark=empty,
                active_model_strategy=empty, delta_roi_vs_taiwan_base_pp=None,
                delta_roi_vs_sharp_benchmark_pp=None, delta_brier_vs_sharp_benchmark=None,
                delta_brier_ci_95=None, champion_source="INTERNATIONAL_SHARP_BENCHMARK",
                acceptance_gate_qualified=False, status="SHADOW_MODE_ACCUMULATING",
                shadow_mode_recommendation=(
                    f"MAINTAIN_SHADOW_LOGGING_UNTIL_N_GTE_30 ({n}/{MIN_FORWARD_EVALUATION_SAMPLE} "
                    "UNIQUE ELIGIBLE EVENTS)"
                ),
            )

        taiwan_rows = clean_rows
        sharp_rows = [row for row in clean_rows if row["sharp_fair_prob"] is not None]
        model_rows = [row for row in clean_rows if row["model_prob"] is not None]
        # Keep the per-row probability explicit for the shared metric builder.
        for row in taiwan_rows:
            row["_taiwan_prob"] = 1.0 / row["taiwan_odds"]
        taiwan_probs = {row["_event_key"]: row["_taiwan_prob"] for row in taiwan_rows}
        tw_metrics = metrics(taiwan_rows, "_taiwan_prob", bet_all=True)
        sharp_metrics = metrics(sharp_rows, "sharp_fair_prob", clv=True)
        model_metrics = metrics(model_rows, "model_prob", clv=True)

        if paired_rows:
            for row in paired_rows:
                row["_taiwan_prob"] = taiwan_probs[row["_event_key"]]
            paired_tw = metrics(paired_rows, "_taiwan_prob", bet_all=True)
            paired_sharp = metrics(paired_rows, "sharp_fair_prob", clv=True)
            paired_model = metrics(paired_rows, "model_prob", clv=True)
            brier_differences = [
                (row["model_prob"] - row["outcome"]) ** 2
                - (row["sharp_fair_prob"] - row["outcome"]) ** 2
                for row in paired_rows
            ]
            delta_brier = sum(brier_differences) / paired_n
            delta_brier_ci = bootstrap_ci_mean(brier_differences)
            delta_roi_taiwan = (
                round(paired_model.settled_roi_pct - paired_tw.settled_roi_pct, 2)
                if paired_model.settled_roi_pct is not None and paired_tw.settled_roi_pct is not None else None
            )
            delta_roi_sharp = (
                round(paired_model.settled_roi_pct - paired_sharp.settled_roi_pct, 2)
                if paired_model.settled_roi_pct is not None and paired_sharp.settled_roi_pct is not None else None
            )
            champion = "ACTIVE_MODEL" if delta_brier < 0.0 else "INTERNATIONAL_SHARP_BENCHMARK"
        else:
            delta_brier = None
            delta_brier_ci = None
            delta_roi_taiwan = None
            delta_roi_sharp = None
            champion = "INTERNATIONAL_SHARP_BENCHMARK"

        qualified = bool(
            paired_n >= MIN_FORWARD_EVALUATION_SAMPLE
            and delta_brier_ci is not None
            and delta_brier_ci[1] < 0.0
        )
        if paired_n < MIN_FORWARD_EVALUATION_SAMPLE:
            recommendation = (
                "MAINTAIN_SHADOW_MODE_UNTIL_N_GTE_30_PAIRED_MODEL_AND_SHARP_EVENTS "
                f"({paired_n}/{MIN_FORWARD_EVALUATION_SAMPLE})"
            )
        elif qualified:
            recommendation = "MODEL_BRIER_SUPERIOR_WITH_PAIRED_95_PERCENT_CONFIDENCE"
        else:
            recommendation = "MAINTAIN_SHARP_BENCHMARK_PRIORITY_UNTIL_PAIRED_BRIER_SUPERIORITY_IS_SIGNIFICANT"

        return StrategyComparisonReport(
            evaluation_scope=scope_name, as_of_utc=now_utc, sample_size=n,
            paired_sample_size=paired_n, taiwan_market_baseline=tw_metrics,
            international_sharp_benchmark=sharp_metrics, active_model_strategy=model_metrics,
            delta_roi_vs_taiwan_base_pp=delta_roi_taiwan,
            delta_roi_vs_sharp_benchmark_pp=delta_roi_sharp,
            delta_brier_vs_sharp_benchmark=round(delta_brier, 4) if delta_brier is not None else None,
            delta_brier_ci_95=delta_brier_ci,
            champion_source=champion, acceptance_gate_qualified=qualified,
            status="VALIDATED", shadow_mode_recommendation=recommendation,
        )
