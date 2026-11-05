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
6. A statistical advantage report requires a stable accepted model lineage,
   at least 30 paired events, and a 95% interval showing lower Brier loss than
   the Sharp benchmark. It is not automatic production approval.
7. Shadow Logging mechanism for new uncertified signals.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.persistence import append_jsonl
from core.snapshot_logger import compute_prediction_payload_hash
from core.observation_scope import qualifies_formal_strategy
from core.experiment_identity import validate_experiment_identity

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
    pnl_drawdown_amount: Optional[float]     # absolute currency units; not a percentage
    win_rate_pct: Optional[float]
    status: str                             # SAMPLE_AVAILABLE or INSUFFICIENT_EVIDENCE
    bet_count: int = 0
    simulated_roi_pct: Optional[float] = None
    simulated_roi_ci_95: Optional[Tuple[float, float]] = None
    simulated_bet_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.roi_ci_95:
            data["roi_ci_95"] = [round(x, 2) for x in self.roi_ci_95]
        if self.simulated_roi_ci_95:
            data["simulated_roi_ci_95"] = [round(x, 2) for x in self.simulated_roi_ci_95]
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
    champion_source: str                    # active model, qualified benchmark, or no benchmark
    acceptance_gate_qualified: bool
    status: str
    shadow_mode_recommendation: str
    international_market_benchmark: Optional[QuantitativeMetrics] = None
    market_paired_sample_size: int = 0
    sharp_paired_sample_size: int = 0
    delta_brier_vs_market_benchmark: Optional[float] = None
    delta_brier_market_ci_95: Optional[Tuple[float, float]] = None
    data_quality_status: str = "UNKNOWN"
    evaluation_protocol_status: str = "UNKNOWN"
    statistical_evidence_status: str = "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_scope": self.evaluation_scope,
            "as_of_utc": self.as_of_utc,
            "sample_size": self.sample_size,
            "paired_sample_size": self.paired_sample_size,
            "taiwan_market_baseline": self.taiwan_market_baseline.to_dict(),
            "international_sharp_benchmark": self.international_sharp_benchmark.to_dict(),
            "international_market_benchmark": (
                self.international_market_benchmark.to_dict()
                if self.international_market_benchmark else None
            ),
            "active_model_strategy": self.active_model_strategy.to_dict(),
            "market_paired_sample_size": self.market_paired_sample_size,
            "sharp_paired_sample_size": self.sharp_paired_sample_size,
            "delta_roi_vs_taiwan_base_pp": self.delta_roi_vs_taiwan_base_pp,
            "delta_roi_vs_sharp_benchmark_pp": self.delta_roi_vs_sharp_benchmark_pp,
            "delta_brier_vs_sharp_benchmark": self.delta_brier_vs_sharp_benchmark,
            "delta_brier_ci_95": ([round(x, 4) for x in self.delta_brier_ci_95]
                                   if self.delta_brier_ci_95 else None),
            "delta_brier_vs_market_benchmark": (
                round(self.delta_brier_vs_market_benchmark, 4)
                if self.delta_brier_vs_market_benchmark is not None else None
            ),
            "delta_brier_market_ci_95": (
                [round(x, 4) for x in self.delta_brier_market_ci_95]
                if self.delta_brier_market_ci_95 else None
            ),
            "champion_source": self.champion_source,
            "acceptance_gate_qualified": self.acceptance_gate_qualified,
            "status": self.status,
            "data_quality_status": self.data_quality_status,
            "evaluation_protocol_status": self.evaluation_protocol_status,
            "statistical_evidence_status": self.statistical_evidence_status,
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


def compute_max_drawdown_amount(pnl_series: List[float]) -> float:
    """Return the largest absolute-currency fall from cumulative PnL high-water mark."""
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


def _valid_model_protocol_signature(row: Dict[str, Any]) -> Optional[Tuple[Any, ...]]:
    """Return a stable, accepted model lineage only when snapshot identity is intact."""
    identity = row.get("experiment_identity")
    metadata = row.get("strategy_metadata") or {}
    if (not validate_experiment_identity(identity)
            or metadata.get("experiment_identity") != identity
            or row.get("strategy_config_hashes") != identity.get("config_hashes")):
        return None

    accepted = []
    for item in row.get("model_candidate_provenances") or []:
        if not isinstance(item, dict):
            continue
        status = item.get("acceptance_status_at_prediction") or item.get("acceptance_status")
        artifact = item.get("artifact_hash")
        protocol = item.get("protocol_hash")
        model_id = item.get("model_id")
        model_version = item.get("model_version")
        if (status != "ACCEPTED" or not model_id or not model_version
                or not isinstance(artifact, str) or not re.fullmatch(r"[0-9a-f]{64}", artifact)
                or not isinstance(protocol, str) or not re.fullmatch(r"[0-9a-f]{64}", protocol)):
            continue
        accepted.append((str(model_id), str(model_version), artifact, protocol))
    if not accepted:
        return None
    return (
        identity.get("experiment_id"),
        tuple(sorted(set(accepted))),
        tuple(sorted((str(k), str(v)) for k, v in identity.get("config_hashes", {}).items())),
    )


def _validated_market_probabilities(
    row: Dict[str, Any], prediction_time: datetime,
) -> Tuple[Optional[float], Optional[float], Optional[Dict[str, Any]]]:
    """Extract fresh, hashed The Odds API benchmark evidence; keep market and Sharp separate."""
    wrapper = row.get("market_evidence") or {}
    signal_evidence = row.get("signal_evidence") or {}
    benchmark = (wrapper.get("market_benchmark") if isinstance(wrapper, dict) else None)
    if not isinstance(benchmark, dict):
        benchmark = signal_evidence.get("market_benchmark")
    if not isinstance(benchmark, dict):
        return None, None, None
    if (benchmark.get("eligible") is not True or benchmark.get("complete") is not True
            or benchmark.get("is_synthetic") is not False
            or not str(benchmark.get("source_id") or "").startswith("the_odds_api:")
            or benchmark.get("taiwan_event_id") != str(row.get("event_id"))
            or benchmark.get("taiwan_selection") != str(row.get("selection"))
            or str(benchmark.get("sport") or "").casefold() != str(row.get("sport") or "").casefold()
            or str(benchmark.get("league") or "").casefold() != str(row.get("league") or "").casefold()):
        return None, None, None

    market_type = str(benchmark.get("market_type") or "").upper()
    market_name = str(row.get("market") or "").strip().lower()
    expected_type = (
        "MONEYLINE" if any(token in market_name for token in ("moneyline", "不讓分", "獨贏", "勝負")) else
        "SPREAD" if any(token in market_name for token in ("spread", "讓分", "讓球")) else
        "TOTAL" if any(token in market_name for token in ("total", "大小", "總分")) else
        None
    )
    if expected_type is None or market_type != expected_type:
        return None, None, None
    side_to_selection = {
        "主": "home", "客": "away", "和": "draw", "大": "over", "小": "under",
    }
    side = str(row.get("side") or "").strip().casefold()
    expected_selection = side_to_selection.get(side, side if side in {"home", "away", "draw", "over", "under"} else None)
    if expected_selection is not None and expected_selection != str(benchmark.get("selection") or "").casefold():
        return None, None, None
    if market_type in {"SPREAD", "TOTAL"}:
        try:
            row_line = float(row.get("line"))
            benchmark_line = float(benchmark.get("line"))
            if not math.isfinite(row_line) or not math.isfinite(benchmark_line):
                return None, None, None
            lines_match = (math.isclose(abs(row_line), abs(benchmark_line), abs_tol=0.01)
                           if market_type == "SPREAD"
                           else math.isclose(row_line, benchmark_line, abs_tol=0.01))
            if not lines_match:
                return None, None, None
        except (TypeError, ValueError, OverflowError):
            return None, None, None

    try:
        canonical_id = str(benchmark.get("canonical_event_id") or "")
        kickoff_match = re.search(
            r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)$",
            canonical_id,
        )
        if kickoff_match is None:
            return None, None, None
        benchmark_start = datetime.fromisoformat(kickoff_match.group(1).replace("Z", "+00:00"))
        event_start = datetime.fromisoformat(
            str(row.get("event_start") or row.get("start_time_utc") or "").replace("Z", "+00:00")
        )
        if benchmark_start.tzinfo is None or event_start.tzinfo is None:
            return None, None, None
        if abs((benchmark_start.astimezone(timezone.utc) - event_start.astimezone(timezone.utc)).total_seconds()) > 7200:
            return None, None, None
    except (TypeError, ValueError, OverflowError):
        return None, None, None

    try:
        fair = float(benchmark.get("fair_probability"))
        if not math.isfinite(fair) or not 0.0 < fair < 1.0:
            fair = None
    except (TypeError, ValueError, OverflowError):
        fair = None

    sharp = None
    if benchmark.get("source_qualification") == "SHARP_QUALIFIED":
        try:
            candidate = float(benchmark.get("sharp_fair_probability"))
            sharp_ids = benchmark.get("sharp_qualified_source_ids") or []
            if sharp_ids and math.isfinite(candidate) and 0.0 < candidate < 1.0:
                sharp = candidate
        except (TypeError, ValueError, OverflowError):
            sharp = None

    # All quoted sides must have a market-level timestamp before the prediction
    # and within the 15-minute snapshot freshness window.
    observation_map = benchmark.get("market_observation_times")
    raw_odds = benchmark.get("raw_outcome_odds")
    if not isinstance(observation_map, dict) or not isinstance(raw_odds, dict) or not observation_map:
        return None, None, None
    sharp_ids = benchmark.get("sharp_qualified_source_ids") or []
    if sharp is not None and (not sharp_ids or not set(sharp_ids).issubset(set(raw_odds))):
        sharp = None
    observed_times: List[datetime] = []
    for source_id, outcomes in raw_odds.items():
        source_times = observation_map.get(source_id)
        if not isinstance(outcomes, dict) or not outcomes or not isinstance(source_times, dict):
            return None, None, None
        for outcome, price in outcomes.items():
            try:
                value = float(price)
                observed = datetime.fromisoformat(str(source_times.get(outcome)).replace("Z", "+00:00"))
                if observed.tzinfo is None or not math.isfinite(value) or value <= 1.0:
                    return None, None, None
                observed = observed.astimezone(timezone.utc)
                age = (prediction_time - observed).total_seconds()
                if age < 0 or age > 900:
                    return None, None, None
                observed_times.append(observed)
            except (TypeError, ValueError, OverflowError):
                return None, None, None
    if not observed_times:
        return None, None, None

    retrieved = None
    try:
        retrieved = datetime.fromisoformat(str(benchmark.get("retrieved_at_utc")).replace("Z", "+00:00"))
        if retrieved.tzinfo is None:
            return None, None, None
        retrieved = retrieved.astimezone(timezone.utc)
        retrieval_age = (prediction_time - retrieved).total_seconds()
        if retrieval_age < 0 or retrieval_age > 900:
            return None, None, None
    except (TypeError, ValueError, OverflowError):
        return None, None, None

    return fair, sharp, benchmark


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
            if raw.get("forward_validation_eligible") is not True:
                continue
            # Strategy and paired international/Sharp comparisons are limited
            # to formal 60-minute observations. Shadow candidates remain in
            # the snapshot ledger for the separate model-calibration gate.
            if not qualifies_formal_strategy(raw):
                continue
            try:
                hash_schema = int(raw.get("prediction_hash_schema", 0) or 0)
                saved_hash = raw.get("prediction_payload_hash")
                if (hash_schema < 3 or not isinstance(saved_hash, str)
                        or compute_prediction_payload_hash(raw) != saved_hash):
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
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
            market_value, sharp_value, benchmark = _validated_market_probabilities(raw, pred_time)
            model_protocol_signature = _valid_model_protocol_signature(raw) if model_value is not None else None
            has_independent_evidence = bool(model_value is not None or market_value is not None)
            if not has_independent_evidence:
                continue

            key = event_key(raw, event_start)
            if key is None:
                continue
            row = dict(raw)
            row.update({"outcome": int(outcome), "taiwan_odds": odds,
                        "model_prob": model_value, "sharp_fair_prob": sharp_value,
                        "market_fair_prob": market_value,
                        "validated_market_benchmark": benchmark,
                        "_model_protocol_signature": model_protocol_signature,
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
        market_paired_rows = [row for row in clean_rows
                              if row["model_prob"] is not None and row["market_fair_prob"] is not None]
        sharp_paired_rows = [row for row in clean_rows
                             if row["model_prob"] is not None and row["sharp_fair_prob"] is not None]
        n = len(clean_rows)
        market_paired_n = len(market_paired_rows)
        sharp_paired_n = len(sharp_paired_rows)
        default_benchmark = (
            "INTERNATIONAL_SHARP_BENCHMARK" if sharp_paired_n else
            "INTERNATIONAL_MARKET_BENCHMARK" if market_paired_n else
            "NO_QUALIFIED_BENCHMARK"
        )

        def metrics(rows: List[Dict[str, Any]], probability_key: str, *, bet_all: bool = False,
                    clv: bool = False) -> QuantitativeMetrics:
            sample_size = len(rows)
            outcomes = [int(row["outcome"]) for row in rows]
            probs = [float(row[probability_key]) for row in rows]
            brier = compute_brier_score(probs, outcomes)
            logloss = compute_log_loss(probs, outcomes)
            simulated_returns: List[float] = []
            for row, prob in zip(rows, probs):
                if bet_all or (prob * row["taiwan_odds"] - 1.0) > edge_threshold:
                    simulated_returns.append(
                        ((row["taiwan_odds"] - 1.0) if row["outcome"] == 1 else -1.0) * 100.0
                    )
            actual_profit = 0.0
            actual_stake = 0.0
            actual_returns: List[float] = []
            actual_net_profits: List[float] = []
            for row in rows:
                if row.get("actual_bet_placed") is not True:
                    continue
                try:
                    stake = float(row.get("actual_stake"))
                    profit = float(row.get("actual_net_profit"))
                    if not math.isfinite(stake) or stake <= 0 or not math.isfinite(profit):
                        continue
                    actual_stake += stake
                    actual_profit += profit
                    actual_returns.append(profit / stake * 100.0)
                    actual_net_profits.append(profit)
                except (TypeError, ValueError, OverflowError):
                    continue
            actual_roi = (actual_profit / actual_stake) * 100.0 if actual_stake else None
            simulated_roi = sum(simulated_returns) / len(simulated_returns) if simulated_returns else None
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
                settled_roi_pct=round(actual_roi, 2) if actual_roi is not None else None,
                roi_ci_95=bootstrap_ci_mean(actual_returns),
                brier_ci_95=bootstrap_ci_mean(losses),
                pnl_drawdown_amount=round(compute_max_drawdown_amount(actual_net_profits), 2)
                if actual_net_profits else None,
                win_rate_pct=round(sum(value > 0 for value in actual_returns) / len(actual_returns) * 100.0, 1)
                if actual_returns else None,
                status="SAMPLE_AVAILABLE" if sample_size else "INSUFFICIENT_EVIDENCE",
                bet_count=len(actual_returns),
                simulated_roi_pct=round(simulated_roi, 2) if simulated_roi is not None else None,
                simulated_roi_ci_95=bootstrap_ci_mean(simulated_returns),
                simulated_bet_count=len(simulated_returns),
            )

        def empty_metrics(sample_size: int = 0) -> QuantitativeMetrics:
            return QuantitativeMetrics(
                sample_size=sample_size, brier_score=None, log_loss=None, clv_mean_pct=None,
                settled_roi_pct=None, roi_ci_95=None, brier_ci_95=None,
                pnl_drawdown_amount=None, win_rate_pct=None, status="INSUFFICIENT_EVIDENCE", bet_count=0,
                simulated_roi_pct=None, simulated_roi_ci_95=None, simulated_bet_count=0,
            )

        if n < MIN_FORWARD_EVALUATION_SAMPLE:
            empty = empty_metrics(n)
            return StrategyComparisonReport(
                evaluation_scope=scope_name, as_of_utc=now_utc, sample_size=n,
                paired_sample_size=sharp_paired_n,
                taiwan_market_baseline=empty, international_sharp_benchmark=empty,
                active_model_strategy=empty, delta_roi_vs_taiwan_base_pp=None,
                delta_roi_vs_sharp_benchmark_pp=None, delta_brier_vs_sharp_benchmark=None,
                delta_brier_ci_95=None, champion_source=default_benchmark,
                acceptance_gate_qualified=False, status="SHADOW_MODE_ACCUMULATING",
                shadow_mode_recommendation=(
                    f"MAINTAIN_SHADOW_LOGGING_UNTIL_N_GTE_30 ({n}/{MIN_FORWARD_EVALUATION_SAMPLE} "
                    "UNIQUE ELIGIBLE EVENTS)"
                ),
                international_market_benchmark=empty,
                market_paired_sample_size=market_paired_n,
                sharp_paired_sample_size=sharp_paired_n,
                data_quality_status="INSUFFICIENT_UNIQUE_ELIGIBLE_EVENTS",
                evaluation_protocol_status="NOT_ENOUGH_EVENTS_TO_ASSESS",
                statistical_evidence_status="NOT_ENOUGH_EVENTS",
            )

        taiwan_rows = clean_rows
        market_rows = [row for row in clean_rows if row["market_fair_prob"] is not None]
        sharp_rows = [row for row in clean_rows if row["sharp_fair_prob"] is not None]
        model_rows = [row for row in clean_rows if row["model_prob"] is not None]
        # Keep the per-row probability explicit for the shared metric builder.
        for row in taiwan_rows:
            row["_taiwan_prob"] = 1.0 / row["taiwan_odds"]
        taiwan_probs = {row["_event_key"]: row["_taiwan_prob"] for row in taiwan_rows}
        tw_metrics = metrics(taiwan_rows, "_taiwan_prob", bet_all=True)
        market_metrics = metrics(market_rows, "market_fair_prob", clv=True)
        sharp_metrics = metrics(sharp_rows, "sharp_fair_prob", clv=True)
        model_metrics = metrics(model_rows, "model_prob", clv=True)

        if market_paired_rows:
            for row in market_paired_rows:
                row["_taiwan_prob"] = taiwan_probs[row["_event_key"]]
            market_brier_differences = [
                (row["model_prob"] - row["outcome"]) ** 2
                - (row["market_fair_prob"] - row["outcome"]) ** 2
                for row in market_paired_rows
            ]
            market_delta_brier = sum(market_brier_differences) / market_paired_n
            market_delta_ci = bootstrap_ci_mean(market_brier_differences)
        else:
            market_delta_brier = None
            market_delta_ci = None

        if sharp_paired_rows:
            for row in sharp_paired_rows:
                row["_taiwan_prob"] = taiwan_probs[row["_event_key"]]
            paired_tw = metrics(sharp_paired_rows, "_taiwan_prob", bet_all=True)
            paired_sharp = metrics(sharp_paired_rows, "sharp_fair_prob", clv=True)
            paired_model_sharp = metrics(sharp_paired_rows, "model_prob", clv=True)
            sharp_brier_differences = [
                (row["model_prob"] - row["outcome"]) ** 2
                - (row["sharp_fair_prob"] - row["outcome"]) ** 2
                for row in sharp_paired_rows
            ]
            sharp_delta_brier = sum(sharp_brier_differences) / sharp_paired_n
            sharp_delta_ci = bootstrap_ci_mean(sharp_brier_differences)
            delta_roi_taiwan = (
                round(paired_model_sharp.settled_roi_pct - paired_tw.settled_roi_pct, 2)
                if paired_model_sharp.settled_roi_pct is not None and paired_tw.settled_roi_pct is not None else None
            )
            delta_roi_sharp = (
                round(paired_model_sharp.settled_roi_pct - paired_sharp.settled_roi_pct, 2)
                if paired_model_sharp.settled_roi_pct is not None and paired_sharp.settled_roi_pct is not None else None
            )
        else:
            sharp_delta_brier = None
            sharp_delta_ci = None
            delta_roi_taiwan = None
            delta_roi_sharp = None

        model_signatures = [row["_model_protocol_signature"] for row in model_rows]
        protocol_consistent = bool(
            model_signatures and all(signature is not None for signature in model_signatures)
            and len(set(model_signatures)) == 1
        )

        qualified = bool(
            sharp_paired_n >= MIN_FORWARD_EVALUATION_SAMPLE
            and protocol_consistent
            and sharp_delta_ci is not None
            and sharp_delta_ci[1] < 0.0
        )
        if sharp_paired_n < MIN_FORWARD_EVALUATION_SAMPLE:
            recommendation = (
                "MAINTAIN_SHADOW_MODE_UNTIL_N_GTE_30_PAIRED_MODEL_AND_SHARP_EVENTS "
                f"({sharp_paired_n}/{MIN_FORWARD_EVALUATION_SAMPLE})"
            )
        elif qualified:
            recommendation = "MODEL_BRIER_ADVANTAGE_SUPPORTED_FOR_REVIEW; NOT_AUTOMATIC_PRODUCTION_APPROVAL"
        else:
            recommendation = "KEEP_MODEL_IN_SHADOW_MODE; SHARP_COMPARISON_HAS_NOT_ESTABLISHED_A_REPRODUCIBLE_ADVANTAGE"

        if sharp_paired_n < MIN_FORWARD_EVALUATION_SAMPLE:
            statistical_status = "INSUFFICIENT_PAIRED_SHARP_EVENTS"
        elif not protocol_consistent:
            statistical_status = "MODEL_LINEAGE_OR_PROTOCOL_UNVERIFIED"
        elif qualified:
            statistical_status = "MODEL_ADVANTAGE_SUPPORTED"
        else:
            statistical_status = "MODEL_ADVANTAGE_NOT_ESTABLISHED"
        if n < MIN_FORWARD_EVALUATION_SAMPLE:
            report_status = "SHADOW_MODE_ACCUMULATING"
        elif not protocol_consistent or sharp_paired_n < MIN_FORWARD_EVALUATION_SAMPLE:
            report_status = "MODEL_EVIDENCE_UNVERIFIED"
        elif qualified:
            report_status = "STATISTICAL_ADVANTAGE_SUPPORTED"
        else:
            report_status = "STATISTICAL_ADVANTAGE_NOT_ESTABLISHED"

        return StrategyComparisonReport(
            evaluation_scope=scope_name, as_of_utc=now_utc, sample_size=n,
            paired_sample_size=sharp_paired_n, taiwan_market_baseline=tw_metrics,
            international_sharp_benchmark=sharp_metrics, active_model_strategy=model_metrics,
            delta_roi_vs_taiwan_base_pp=delta_roi_taiwan,
            delta_roi_vs_sharp_benchmark_pp=delta_roi_sharp,
            delta_brier_vs_sharp_benchmark=round(sharp_delta_brier, 4) if sharp_delta_brier is not None else None,
            delta_brier_ci_95=sharp_delta_ci,
            champion_source="ACTIVE_MODEL" if qualified else default_benchmark,
            acceptance_gate_qualified=qualified,
            status=report_status,
            shadow_mode_recommendation=recommendation,
            international_market_benchmark=market_metrics,
            market_paired_sample_size=market_paired_n,
            sharp_paired_sample_size=sharp_paired_n,
            delta_brier_vs_market_benchmark=(
                round(market_delta_brier, 4) if market_delta_brier is not None else None
            ),
            delta_brier_market_ci_95=market_delta_ci,
            data_quality_status="PASS" if n >= MIN_FORWARD_EVALUATION_SAMPLE else "INSUFFICIENT_UNIQUE_ELIGIBLE_EVENTS",
            evaluation_protocol_status=(
                "CONSISTENT_ACCEPTED_MODEL_LINEAGE" if protocol_consistent
                else "MISSING_OR_MIXED_MODEL_LINEAGE"
            ),
            statistical_evidence_status=statistical_status,
        )
