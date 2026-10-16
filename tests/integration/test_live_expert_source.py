#!/usr/bin/env python3
"""Integration test for Live Playsport Expert Billboard Source."""

import pytest
from core.scraper import PlaysportScraper
from integrations.common.models import TaiwanLeg
from integrations.experts.playsport_expert import PlaysportExpertAdapter

pytestmark = pytest.mark.live


def test_live_expert_source(tmp_path):
    """Verify live fetch of verified leaderboard experts from Playsport."""
    scraper = PlaysportScraper(cache_dir=tmp_path / "cache", snapshot_dir=tmp_path / "snapshots")
    rankers = scraper.fetch_expert_leaderboard(alliance_id="1")

    assert isinstance(rankers, list)
    assert len(rankers) > 0, "No expert rankers returned from Playsport billboard"

    top1 = rankers[0]
    assert "nickname" in top1
    assert "winpercentage" in top1
    assert top1["winpercentage"] > 50, "Top expert should have > 50% win rate"

    # Test adapter signal extraction
    adapter = PlaysportExpertAdapter(scraper=scraper)
    expert_picks = adapter._load_expert_picks_for_alliance("1")

    # If any verified picks exist in live or cached pages, verify matching
    if expert_picks:
        pick0 = expert_picks[0]
        matching_leg = TaiwanLeg(
            event_id="test_exp_001",
            sport="baseball",
            league="MLB",
            market=pick0["market"],
            selection=f"{pick0['away_raw']} vs {pick0['home_raw']}",
            taiwan_odds=1.75,
            start_time="10:00",
            away_team=pick0["away_raw"],
            home_team=pick0["home_raw"],
            side=pick0["side"],
        )
        sig = adapter.get_expert_signal(matching_leg)
        assert sig is not None
        assert sig.source_type == "EXPERT"
        assert sig.rank is not None
        assert "verified_pick" in sig.metadata

    # Crucial Reality Check: Unpicked match MUST return None (no fake synthesis!)
    unpicked_leg = TaiwanLeg(
        event_id="test_unpicked",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="虛構比賽",
        taiwan_odds=1.52,
        start_time="12:00",
        away_team="未推之隊A",
        home_team="未推之隊B",
        side="客",
        signal_evidence={"consensus_ratio": 0.85},
    )
    assert adapter.get_expert_signal(unpicked_leg) is None
