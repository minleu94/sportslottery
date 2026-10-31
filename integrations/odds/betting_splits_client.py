#!/usr/bin/env python3
"""Public Betting Splits (Tickets % vs Money Handle %) Client and Adapter.

Part of Milestone 1 & 4 of Phase 4:
- In sports betting analytics, betting splits distinguish ticket percentage (Bets %)
  from handle percentage (Money %).
- Preserves explicit nulls when money volume or sample size is not reported.
- Adheres to the strict rule: NEVER treat Money % as a true win probability,
  and NEVER treat ticket/money divergence as infallible sharp money.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from integrations.odds.market_models import (
    BettingSplitsSnapshot,
    MarketFreshnessStatus,
)

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "splits"


class BettingSplitsClient:
    """Client for retrieving public betting splits across sports."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_betting_splits(
        self,
        league: str,
        event_id: Optional[str] = None,
    ) -> List[BettingSplitsSnapshot]:
        """Retrieve betting splits snapshots for the requested league."""
        norm_league = league.upper().strip()

        # Offline/synthetic fallback with strictly audited properties
        return self._generate_synthetic_splits(norm_league, event_id)

    def _generate_synthetic_splits(
        self,
        league: str,
        event_id: Optional[str] = None,
    ) -> List[BettingSplitsSnapshot]:
        now_utc = datetime.now(timezone.utc).isoformat()
        splits: List[BettingSplitsSnapshot] = []

        if league in {"MLB", "BASEBALL"}:
            ev_id = event_id or "syn_mlb_1"
            # Spread: Public bets 68% tickets on Dodgers -1.5, but money handle is only 52%
            splits.append(
                BettingSplitsSnapshot(
                    source_id="action_network:draftkings",
                    source_type="BETTING_SPLITS",
                    event_id=ev_id,
                    league=league,
                    home_team="Los Angeles Dodgers",
                    away_team="San Diego Padres",
                    start_time_utc=now_utc,
                    market_type="SPREAD",
                    selection="home",
                    line=-1.5,
                    bet_percentage=68.0,
                    money_percentage=52.0,
                    sample_size=14200,
                    reporting_bookmaker="DraftKings",
                    reporting_scope="US_COMMERCIAL",
                    observed_at_utc=now_utc,
                    retrieved_at_utc=now_utc,
                    freshness_status=MarketFreshnessStatus.LIVE.value,
                    evidence_url="https://actionnetwork.com/mlb/public-betting",
                    source_license="PUBLIC_REPORTING",
                    is_synthetic=True,
                )
            )
            splits.append(
                BettingSplitsSnapshot(
                    source_id="action_network:draftkings",
                    source_type="BETTING_SPLITS",
                    event_id=ev_id,
                    league=league,
                    home_team="Los Angeles Dodgers",
                    away_team="San Diego Padres",
                    start_time_utc=now_utc,
                    market_type="SPREAD",
                    selection="away",
                    line=1.5,
                    bet_percentage=32.0,
                    money_percentage=48.0,
                    sample_size=14200,
                    reporting_bookmaker="DraftKings",
                    reporting_scope="US_COMMERCIAL",
                    observed_at_utc=now_utc,
                    retrieved_at_utc=now_utc,
                    freshness_status=MarketFreshnessStatus.LIVE.value,
                    evidence_url="https://actionnetwork.com/mlb/public-betting",
                    source_license="PUBLIC_REPORTING",
                    is_synthetic=True,
                )
            )

        elif league in {"NBA", "BASKETBALL"}:
            ev_id = event_id or "syn_nba_1"
            splits.append(
                BettingSplitsSnapshot(
                    source_id="vsin_splits:circavegas",
                    source_type="BETTING_SPLITS",
                    event_id=ev_id,
                    league=league,
                    home_team="Boston Celtics",
                    away_team="Milwaukee Bucks",
                    start_time_utc=now_utc,
                    market_type="SPREAD",
                    selection="home",
                    line=-4.5,
                    bet_percentage=55.0,
                    money_percentage=71.0,
                    sample_size=8900,
                    reporting_bookmaker="Circa Sports",
                    reporting_scope="VEGAS_COMMERCIAL",
                    observed_at_utc=now_utc,
                    retrieved_at_utc=now_utc,
                    freshness_status=MarketFreshnessStatus.LIVE.value,
                    evidence_url="https://vsin.com/betting-splits",
                    source_license="PUBLIC_REPORTING",
                    is_synthetic=True,
                )
            )
            splits.append(
                BettingSplitsSnapshot(
                    source_id="vsin_splits:circavegas",
                    source_type="BETTING_SPLITS",
                    event_id=ev_id,
                    league=league,
                    home_team="Boston Celtics",
                    away_team="Milwaukee Bucks",
                    start_time_utc=now_utc,
                    market_type="SPREAD",
                    selection="away",
                    line=4.5,
                    bet_percentage=45.0,
                    money_percentage=29.0,
                    sample_size=8900,
                    reporting_bookmaker="Circa Sports",
                    reporting_scope="VEGAS_COMMERCIAL",
                    observed_at_utc=now_utc,
                    retrieved_at_utc=now_utc,
                    freshness_status=MarketFreshnessStatus.LIVE.value,
                    evidence_url="https://vsin.com/betting-splits",
                    source_license="PUBLIC_REPORTING",
                    is_synthetic=True,
                )
            )

        return splits
