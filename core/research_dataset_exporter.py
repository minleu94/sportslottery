#!/usr/bin/env python3
"""Research Dataset Exporter for Forward Evaluation.

Generates clean, auditable CSV tables under `data/research/`:
1. `single_leg_forward.csv`: Audited single-leg predictions with pre-game cutoffs, closing prices, CLV, and exclusion reasons.
2. `parlay_forward.csv`: Candidate & shadow parlays with fingerprints, void-recalculated multipliers, and P/L.
3. `source_metrics.csv`: Aggregated performance metrics across agreement tiers, delta buckets, experts, and models.

All rows maintain traceable linkages back to original append-only snapshot IDs.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.performance_metrics import PerformanceMetricsEngine
from core.shadow_parlay_logger import ShadowParlayLogger
from core.snapshot_logger import PredictionSnapshotLogger

logger = logging.getLogger(__name__)

RESEARCH_DIR = Path(__file__).resolve().parents[1] / "data" / "research"


class ResearchDatasetExporter:
    """Exports structured audit and evaluation datasets to data/research/."""

    def __init__(
        self,
        snapshot_logger: Optional[PredictionSnapshotLogger] = None,
        parlay_logger: Optional[ShadowParlayLogger] = None,
        output_dir: Optional[Path] = None,
    ):
        self.snapshot_logger = snapshot_logger or PredictionSnapshotLogger()
        self.parlay_logger = parlay_logger or ShadowParlayLogger()
        self.output_dir = output_dir or RESEARCH_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_single_leg_forward(self) -> Path:
        """Export single_leg_forward.csv."""
        out_path = self.output_dir / "single_leg_forward.csv"
        snapshots = self.snapshot_logger.get_all_snapshots()

        headers = [
            "snapshot_id",
            "event_id",
            "event_start",
            "sport",
            "league",
            "away_team",
            "home_team",
            "market",
            "selection",
            "side",
            "line",
            "taiwan_odds",
            "odds_timestamp",
            "closing_odds",
            "odds_clv_ratio",
            "clv_probability_pp",
            "clv_status",
            "model_probability",
            "market_implied_prob",
            "model_market_delta_pp",
            "crowd_ratio",
            "crowd_votes",
            "evidence_quality",
            "strategy_version",
            "settlement_rule_id",
            "forward_validation_eligible",
            "exclusion_reason",
            "is_settled",
            "settlement_status",
            "actual_outcome",
            "final_score",
            "brier_score",
            "log_loss",
            "prediction_payload_hash",
        ]

        with open(out_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            for s in snapshots:
                writer.writerow(s)

        return out_path

    def export_parlay_forward(self) -> Path:
        """Export parlay_forward.csv."""
        out_path = self.output_dir / "parlay_forward.csv"
        parlays = self.parlay_logger.get_all_parlay_snapshots()

        headers = [
            "candidate_id",
            "snapshot_id",
            "date",
            "multiplier_tier",
            "parlay_fingerprint",
            "target_type",
            "original_total_odds",
            "recalculated_total_odds",
            "legs_count",
            "is_ready",
            "settled",
            "settlement_status",
            "won",
            "actual_payout",
            "profit_loss",
            "strategy_version",
        ]

        rows = []
        for p in parlays:
            snap_id = p.get("snapshot_id", "")
            date_str = p.get("date", "")
            tier = p.get("multiplier_tier", "")
            strat_ver = p.get("strategy_version", "")
            for c in p.get("candidates", []):
                rows.append({
                    "candidate_id": c.get("candidate_id"),
                    "snapshot_id": snap_id,
                    "date": date_str,
                    "multiplier_tier": tier,
                    "parlay_fingerprint": c.get("parlay_fingerprint", ""),
                    "target_type": c.get("target_type", ""),
                    "original_total_odds": c.get("original_total_odds", 1.0),
                    "recalculated_total_odds": c.get("recalculated_total_odds", 1.0),
                    "legs_count": c.get("legs_count", 0),
                    "is_ready": c.get("is_ready", True),
                    "settled": c.get("settled", False),
                    "settlement_status": c.get("settlement_status", "PENDING"),
                    "won": c.get("won"),
                    "actual_payout": c.get("actual_payout", 0.0),
                    "profit_loss": c.get("profit_loss", 0.0),
                    "strategy_version": strat_ver,
                })

        with open(out_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

        return out_path

    def export_source_metrics(self) -> Path:
        """Export source_metrics.csv."""
        out_path = self.output_dir / "source_metrics.csv"
        snapshots = self.snapshot_logger.get_all_snapshots()
        metrics = PerformanceMetricsEngine()

        agree = metrics.evaluate_agreement_buckets(snapshots)
        deltas = metrics.evaluate_model_market_delta_buckets(snapshots)
        crowd = metrics.evaluate_crowd_buckets(snapshots)

        headers = [
            "category",
            "bucket_name",
            "sample_size_N",
            "wins",
            "hit_rate",
            "roi_pct",
            "average_odds",
            "brier_score",
            "is_insufficient_sample",
        ]

        rows = []
        # Agreement buckets
        for k, v in agree.items():
            rows.append({
                "category": "AGREEMENT_BUCKET",
                "bucket_name": k,
                "sample_size_N": v["sample_size"],
                "wins": v["wins"],
                "hit_rate": v["hit_rate"],
                "roi_pct": v["roi_pct"],
                "average_odds": v["average_odds"],
                "brier_score": None,
                "is_insufficient_sample": v["is_insufficient_sample"],
            })

        # Delta buckets
        for k, v in deltas.items():
            rows.append({
                "category": "MODEL_DELTA_BUCKET",
                "bucket_name": k,
                "sample_size_N": v["sample_size"],
                "wins": v["wins"],
                "hit_rate": v["hit_rate"],
                "roi_pct": v["roi_pct"],
                "average_odds": None,
                "brier_score": v["brier_score"],
                "is_insufficient_sample": v["is_insufficient_sample"],
            })

        # Crowd buckets
        for k, v in crowd.items():
            rows.append({
                "category": "CROWD_CONSENSUS_BUCKET",
                "bucket_name": k,
                "sample_size_N": v["sample_size"],
                "wins": v["wins"],
                "hit_rate": v["hit_rate"],
                "roi_pct": v["roi_pct"],
                "average_odds": None,
                "brier_score": None,
                "is_insufficient_sample": v["is_insufficient_sample"],
            })

        with open(out_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

        return out_path

    def export_all(self) -> Dict[str, Path]:
        """Export all 3 research datasets."""
        f1 = self.export_single_leg_forward()
        f2 = self.export_parlay_forward()
        f3 = self.export_source_metrics()
        return {
            "single_leg_forward": f1,
            "parlay_forward": f2,
            "source_metrics": f3,
        }
