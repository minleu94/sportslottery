#!/usr/bin/env python3
"""Integration test for Live Taiwan Sports Lottery Odds Source."""

import pytest
from core.scraper import PlaysportScraper
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter

pytestmark = pytest.mark.live


def test_live_taiwan_odds_source(tmp_path):
    """Verify live scraping and normalization of Taiwan Sports Lottery odds."""
    scraper = PlaysportScraper(cache_dir=tmp_path / "cache", snapshot_dir=tmp_path / "snapshots")
    adapter = PlaysportOddsAdapter(scraper=scraper)
    legs = adapter.get_taiwan_legs(alliance_ids=["1"], force_refresh=True)

    assert isinstance(legs, list)
    assert len(legs) > 0, "Failed to retrieve any live Taiwan Sports Lottery legs from Playsport"

    # Verify that each TaiwanLeg meets strict Taiwan betting standards
    for leg in legs[:10]:
        assert leg.taiwan_odds > 1.0, f"Invalid Taiwan odds: {leg.taiwan_odds}"
        assert leg.event_id != "", "Missing Taiwan Sports Lottery event ID"
        assert leg.market in ["讓分", "不讓分", "大小", "和局"], f"Unexpected market: {leg.market}"
        assert leg.eligible_for_parlay is True
