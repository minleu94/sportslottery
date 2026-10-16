#!/usr/bin/env python3
"""Integration test for Signal Data Lineage & Independence."""

import pytest
from core.signal_hub import SignalHub
from integrations.common.models import TaiwanLeg


def test_signal_data_lineage_and_independence():
    """Verify signal lineage and conservative agreement for a timestamped fixture."""
    from datetime import datetime, timedelta, timezone
    hub = SignalHub()
    # This lineage test exercises local aggregation only; external source
    # behavior has dedicated opt-in live tests.
    hub.expert_adapter.get_expert_signal = lambda leg: None

    leg = TaiwanLeg(
        event_id="118",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="道奇客勝 (1.38)",
        taiwan_odds=1.38,
        start_time="AM 12:40",
        start_time_utc=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        odds_scraped_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        odds_age_minutes=1.0,
        away_team="道奇",
        home_team="紅人",
        side="客",
        signal_evidence={"consensus_ratio": 0.87, "vote_count": 243, "crowd_snapshot_timestamp": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), "crowd_age_minutes": 1.0, "source_url": "https://fixture.invalid/crowd"},
    )

    evaluated = hub.evaluate_taiwan_leg(leg)
    evidence = evaluated.signal_evidence

    # Verify that signals come from multiple distinct source types
    source_types = {s.source_type for s in evaluated.signals}
    assert "BETTING_MARKET" in source_types
    assert "CROWD" in source_types
    assert "MODEL" in source_types

    # Verify no fake MOONSHOT in confidence
    for s in evaluated.signals:
        assert s.confidence in ["HIGH", "MED", "LOW", "REFERENCE_ONLY", None]

    # Verify agreement level
    assert evidence["agreement"] in ["HIGH", "MED", "LOW", "INSUFFICIENT_SIGNAL"]
    assert evidence["support_count"] >= 1
    assert "taiwan_odds" in evidence
