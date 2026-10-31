#!/usr/bin/env python3
"""Tests for Forward Evaluation, Leakage Prevention, and Shadow Mode (Milestone 5).

Verification:
1. Tests data leakage prevention (prediction_timestamp >= event_start rejected)
2. Tests small sample size -> INSUFFICIENT_EVIDENCE
3. Tests three-way comparison (Taiwan Base vs Sharp Benchmark vs Model)
4. Tests objective champion selection without false claims
5. Tests shadow forward logging
"""

import os
from pathlib import Path
import pytest

from core.forward_evaluation_engine import (
    ForwardEvaluationEngine,
    compute_brier_score,
    compute_log_loss,
    compute_max_drawdown,
)


def test_brier_and_log_loss():
    probs = [0.9, 0.1]
    outcomes = [1, 0]
    brier = compute_brier_score(probs, outcomes)
    assert brier is not None
    assert brier < 0.05

    ll = compute_log_loss(probs, outcomes)
    assert ll is not None
    assert ll < 0.2


def test_max_drawdown():
    # Sequence of PnL: +1, -1, -2, +1, -1
    pnl = [1.0, -1.0, -2.0, 1.0, -1.0]
    mdd = compute_max_drawdown(pnl)
    # Peak is 1.0, drops to -2.0 -> Drawdown = 3.0
    assert mdd == 3.0


def test_data_leakage_omitted():
    engine = ForwardEvaluationEngine()

    # Create cohort where one prediction occurred AFTER match start (post-match leak)
    cohort = [
        {
            "event_id": "game_leak",
            "prediction_timestamp": "2026-10-31T03:30:00Z",  # AFTER match start!
            "event_start": "2026-10-31T02:00:00Z",
            "taiwan_odds": 1.80,
            "outcome": 1,
            "model_prob": 0.85,
        }
    ]

    report = engine.evaluate_cohort(cohort, scope_name="MLB")
    assert report.sample_size == 0
    assert report.status == "INSUFFICIENT_EVIDENCE"


def test_insufficient_evidence_when_n_under_30():
    engine = ForwardEvaluationEngine()
    cohort = [
        {
            "event_id": f"game_{i}",
            "prediction_timestamp": "2026-10-31T01:00:00Z",
            "event_start": "2026-10-31T02:00:00Z",
            "taiwan_odds": 1.75,
            "outcome": 1 if i % 2 == 0 else 0,
            "model_prob": 0.55,
        }
        for i in range(15)  # N = 15 < 30
    ]

    report = engine.evaluate_cohort(cohort, scope_name="MLB")
    assert report.sample_size == 15
    assert report.status == "INSUFFICIENT_EVIDENCE"
    assert report.acceptance_gate_qualified is False
    assert "MAINTAIN_SHADOW_LOGGING" in report.shadow_mode_recommendation


def test_forward_evaluation_three_way_comparison_and_champion(tmp_path: Path):
    log_file = tmp_path / "shadow_log.jsonl"
    engine = ForwardEvaluationEngine(shadow_log_path=log_file)

    # 40 events
    cohort = []
    for i in range(40):
        # Outcome is 1 for even, 0 for odd
        y = 1 if i % 2 == 0 else 0
        cohort.append({
            "event_id": f"ev_{i}",
            "prediction_timestamp": "2026-10-30T10:00:00Z",
            "event_start": "2026-10-30T14:00:00Z",
            "taiwan_odds": 1.90,
            "sharp_fair_prob": 0.51 if y == 1 else 0.49,  # Sharp is accurate
            "model_prob": 0.45 if y == 1 else 0.55,        # Model is inverted/weaker
            "outcome": y,
        })

    report = engine.evaluate_cohort(cohort, scope_name="MLB_MONEYLINE")
    assert report.sample_size == 40
    assert report.status == "VALIDATED"
    # Since sharp had better calibration than the weak model, Sharp benchmark must win:
    assert report.champion_source == "INTERNATIONAL_SHARP_BENCHMARK"
    assert report.acceptance_gate_qualified is False
    assert "MAINTAIN_SHARP_BENCHMARK_PRIORITY" in report.shadow_mode_recommendation

    # Test shadow logging
    engine.log_shadow_record({"event_id": "test_1", "model_prob": 0.60})
    assert log_file.exists()
