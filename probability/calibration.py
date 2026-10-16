#!/usr/bin/env python3
"""Probability calibration, signal shrinkage, and conservative uncertainty discounting."""

from __future__ import annotations

import math
from typing import Sequence
from typing import Optional, Tuple

# Conservative empirical shrinkage priors
DEFAULT_BETA_EXPERT = 0.05   # Expert pick share modest positive prior
DEFAULT_BETA_CROWD = 0.00    # Crowd sentiment default zero (often noise or negative)
Z_90_PERCENT = 1.645         # 90% single-tailed confidence lower bound


def logit(p: float) -> float:
    """Compute logit (log-odds) with boundary clamping."""
    p_clamped = max(0.0001, min(0.9999, p))
    return math.log(p_clamped / (1.0 - p_clamped))


def inv_logit(z: float) -> float:
    """Compute inverse logit (sigmoid) with numerical stability."""
    if z > 20.0:
        return 0.9999
    if z < -20.0:
        return 0.0001
    return 1.0 / (1.0 + math.exp(-z))


def apply_binary_temperature(probability: float, temperature: float) -> float:
    """Apply a fitted scalar temperature to a binary probability."""
    if not math.isfinite(float(temperature)) or temperature <= 0:
        raise ValueError("temperature must be positive and finite")
    return max(1e-6, min(1.0 - 1e-6, inv_logit(logit(float(probability)) / float(temperature))))


def fit_binary_temperature(probabilities: Sequence[float], outcomes: Sequence[int]) -> float | None:
    """Fit temperature by training-set log loss only; caller owns chronology/split."""
    if len(probabilities) != len(outcomes) or len(probabilities) < 2:
        return None
    pairs = []
    for p, y in zip(probabilities, outcomes):
        if (isinstance(p, bool) or not isinstance(p, (int, float))
                or type(y) not in {int, bool} or y not in (0, 1)):
            continue
        p, y = float(p), int(y)
        if math.isfinite(p) and 0 < p < 1 and y in (0, 1):
            pairs.append((p, y))
    if len(pairs) < 2 or len({y for _, y in pairs}) < 2:
        return None
    best = None
    for step in range(25, 401):
        temperature = step / 100.0
        loss = 0.0
        for p, y in pairs:
            calibrated = apply_binary_temperature(p, temperature)
            loss -= y * math.log(calibrated) + (1-y) * math.log(1-calibrated)
        score = loss / len(pairs)
        if best is None or score < best[0]:
            best = (score, temperature)
    return best[1] if best else None


def apply_multiclass_temperature(probabilities: Sequence[float], temperature: float) -> list[float]:
    """Temperature-scale a multiclass probability vector and renormalize."""
    if not math.isfinite(float(temperature)) or temperature <= 0:
        raise ValueError("temperature must be positive and finite")
    if not probabilities:
        raise ValueError("probabilities cannot be empty")
    logs = [math.log(max(1e-12, float(p))) / float(temperature) for p in probabilities]
    peak = max(logs)
    exps = [math.exp(value-peak) for value in logs]
    total = sum(exps)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("probability vector is not normalizable")
    return [value / total for value in exps]


def fit_multiclass_temperature(probability_vectors: Sequence[Sequence[float]], outcomes: Sequence[int]) -> float | None:
    """Fit a single temperature using only the supplied training rows."""
    if len(probability_vectors) != len(outcomes) or len(outcomes) < 2:
        return None
    rows = []
    for vector, outcome in zip(probability_vectors, outcomes):
        if type(outcome) not in {int, bool} or isinstance(vector, (str, bytes)):
            continue
        try:
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in vector):
                continue
            values = [float(x) for x in vector]
            y = int(outcome)
        except (TypeError, ValueError, OverflowError):
            continue
        if len(values) >= 2 and all(math.isfinite(x) and x >= 0 for x in values) and 0 <= y < len(values) and sum(values) > 0:
            total = sum(values)
            rows.append(([x / total for x in values], y))
    if len(rows) < 2 or len({len(vector) for vector, _ in rows}) != 1:
        return None
    best = None
    for step in range(50, 301):
        temperature = step / 100.0
        loss = 0.0
        for vector, outcome in rows:
            calibrated = apply_multiclass_temperature(vector, temperature)
            loss -= math.log(max(1e-12, calibrated[outcome]))
        score = loss / len(rows)
        if best is None or score < best[0]:
            best = (score, temperature)
    return best[1] if best else None


def calibrate_with_signals(
    market_fair_prob: float,
    expert_share: Optional[float] = None,
    crowd_share: Optional[float] = None,
    beta_expert: float = DEFAULT_BETA_EXPERT,
    beta_crowd: float = DEFAULT_BETA_CROWD,
) -> float:
    """Adjust market baseline probability using expert and crowd signals via logit model.

    logit(P_adj) = logit(P_market) + beta_1*(expert_share - 0.5) + beta_2*(crowd_share - 0.5)
    """
    base_logit = logit(market_fair_prob)
    adjustment = 0.0

    if expert_share is not None and 0.0 <= expert_share <= 1.0:
        adjustment += beta_expert * (expert_share - 0.5)

    if crowd_share is not None and 0.0 <= crowd_share <= 1.0:
        adjustment += beta_crowd * (crowd_share - 0.5)

    adj_prob = inv_logit(base_logit + adjustment)
    return max(0.02, min(0.98, adj_prob))


def calculate_conservative_lower_bound(
    estimated_prob: float,
    sample_size: int = 50,
    confidence_z: float = Z_90_PERCENT,
    min_discount_pp: float = 0.015,
) -> float:
    """Calculate the conservative lower-bound probability.

    P_conservative = max(0.01, P_est - max(min_discount, z * sigma / sqrt(n + 10)))
    Where sigma = sqrt(p * (1 - p)) is the Bernoulli standard error.
    """
    p = max(0.01, min(0.99, estimated_prob))
    sigma = math.sqrt(p * (1.0 - p))
    effective_n = max(5, sample_size)
    stat_uncertainty = confidence_z * (sigma / math.sqrt(effective_n + 10))

    # Apply both statistical uncertainty and a minimum conservative safety margin
    total_penalty = max(min_discount_pp, stat_uncertainty)
    conservative_p = max(0.005, p - total_penalty)

    return round(conservative_p, 4)
