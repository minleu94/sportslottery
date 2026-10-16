#!/usr/bin/env python3
"""Playsport Community Crowd Adapter (Layer A - Public Consensus).

Extracts public voting percentages from Playsport community scales.
Strictly labeled as CROWD to maintain complete data lineage integrity.
"""

from __future__ import annotations

from typing import Optional

from integrations.common.models import PredictionSignal, TaiwanLeg


class PlaysportCrowdAdapter:
    """Extracts public consensus data from Taiwan Sports Lottery community votes."""

    def get_crowd_signal(self, leg: TaiwanLeg) -> Optional[PredictionSignal]:
        consensus_ratio = leg.signal_evidence.get("consensus_ratio")
        observed_vote_count = leg.signal_evidence.get("vote_count")
        vote_count = int(observed_vote_count or 0)

        if consensus_ratio is None:
            return None

        ratio = float(consensus_ratio)
        confidence = "HIGH" if ratio >= 0.70 else "MED" if ratio >= 0.55 else "LOW"

        from datetime import datetime, timezone
        snapshot_ts = leg.signal_evidence.get("crowd_snapshot_timestamp") or leg.odds_scraped_at or datetime.now(timezone.utc).isoformat()
        data_age_min = float(leg.signal_evidence.get("crowd_age_minutes") or leg.odds_age_minutes or 0.0)

        if data_age_min <= 1.0:
            freshness = "LIVE"
        elif data_age_min <= 30.0:
            freshness = "FRESH"
        elif data_age_min <= 120.0:
            freshness = "AGING"
        else:
            freshness = "STALE"

        return PredictionSignal(
            source_id="playsport_crowd_consensus",
            source_name="玩運彩彩迷社群選票",
            source_type="CROWD",
            event_id=leg.event_id,
            market=leg.market,
            selection=leg.selection,
            probability=round(ratio, 3),
            score=round(ratio * 100.0, 1),
            confidence=confidence,
            pick=leg.selection,
            source_category="CROWD_CONSENSUS",
            independence_group="PLAYSPORT_CROWD",
            timestamp=snapshot_ts,
            data_as_of=snapshot_ts,
            data_age_hours=round(data_age_min / 60.0, 2),
            freshness_status=freshness,
            metadata={
                "source_category": "CROWD_CONSENSUS",
                "independence_group": "PLAYSPORT_CROWD",
                "snapshot_timestamp": snapshot_ts,
                "vote_count": int(observed_vote_count) if observed_vote_count is not None else None,
                "ratio": ratio,
                "data_age_minutes": data_age_min,
                "percentage": round(ratio * 100.0, 1),
                "is_heavy_sample": vote_count >= 100,
                "freshness_status": freshness,
            },
        )
