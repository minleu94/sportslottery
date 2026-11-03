"""Stable, framework-free contracts shared by core and provider adapters."""

from core.contracts.common import ModelQualityLabel, PredictionSignal, TaiwanLeg, VerifiedExpertPick
from core.contracts.market import (
    BettingSplitsSnapshot,
    MarketAlignmentRecord,
    MarketAlignmentStatus,
    MarketBenchmarkEvidence,
    MarketFreshnessStatus,
    MarketOddsSnapshot,
    MarketSelectionIdentity,
    SignalClassification,
)

__all__ = [
    "ModelQualityLabel",
    "PredictionSignal",
    "TaiwanLeg",
    "VerifiedExpertPick",
    "BettingSplitsSnapshot",
    "MarketAlignmentRecord",
    "MarketAlignmentStatus",
    "MarketBenchmarkEvidence",
    "MarketFreshnessStatus",
    "MarketOddsSnapshot",
    "MarketSelectionIdentity",
    "SignalClassification",
]
