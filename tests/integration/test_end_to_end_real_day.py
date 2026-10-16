#!/usr/bin/env python3
"""End-to-End Real Day Integration Test (No Mocks).

Executes the entire workflow on live today's data:
Live Taiwan Odds -> TaiwanLeg candidates -> SignalHub -> ParlayEngine (10x~500x) ->
Weekly Wallet (NT$ 200) -> Ticket Placement -> Settlement to Prize Pool.
"""

import tempfile
from pathlib import Path
import pytest
from core.scraper import PlaysportScraper
from integrations.experts.playsport_crowd import PlaysportCrowdAdapter
from integrations.experts.playsport_expert import PlaysportExpertAdapter
from integrations.models.external.live_mlb_elo import LiveMLBEloAdapter

from core.parlay_engine import ParlayEngine
from core.season_radar import SeasonRadar
from core.signal_hub import SignalHub
from core.ticket_recorder import TicketRecorder
from core.wallet import WeeklyWalletManager
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter

pytestmark = pytest.mark.live


def test_end_to_end_real_day_pipeline(tmp_path):
    """Execute complete real-data pipeline without mocks."""
    # 1. Fetch live Taiwan Sports Lottery odds
    scraper = PlaysportScraper(cache_dir=tmp_path / "cache", snapshot_dir=tmp_path / "snapshots")
    odds_adapter = PlaysportOddsAdapter(scraper=scraper)
    taiwan_legs = odds_adapter.get_taiwan_legs(alliance_ids=["1"], force_refresh=True)

    assert len(taiwan_legs) > 0, "No live Taiwan Sports Lottery legs retrieved"

    # 2. Season Radar assessment
    radar = SeasonRadar()
    radar_summary = radar.get_radar_summary(taiwan_legs=taiwan_legs, check_live_espn=True)
    mlb_status = next((r for r in radar_summary if r["code"] == "MLB"), None)

    assert mlb_status is not None
    assert mlb_status["status"] == "GREEN", "MLB should be GREEN because Taiwan Sports Lottery has open markets today"

    # 3. Signal Hub enrichment with genuine open models
    class TemporaryModelRegistry:
        def __init__(self):
            self.elo = LiveMLBEloAdapter(state_file=tmp_path / "elo.json")
        def evaluate_leg_across_models(self, leg):
            signal = self.elo.evaluate_leg(leg)
            return [signal] if signal else []

    signal_hub = SignalHub(expert_adapter=PlaysportExpertAdapter(scraper=scraper),
                           crowd_adapter=PlaysportCrowdAdapter(),
                           model_registry=TemporaryModelRegistry())
    enriched_legs = [signal_hub.evaluate_taiwan_leg(leg) for leg in taiwan_legs]

    # Verify at least one leg has a real open-source model evaluation
    has_model_signal = any(
        any(s.source_type == "MODEL" for s in leg.signals)
        for leg in enriched_legs
    )
    assert has_model_signal is True, "Open-source models failed to evaluate any TaiwanLeg"

    # 4. Parlay Search within target odds [10x, 50x]
    parlay_engine = ParlayEngine(signal_hub=signal_hub)
    results = parlay_engine.search_parlays(
        legs=enriched_legs,
        min_odds=10.0,
        max_odds=50.0,
        min_legs=2,
        max_legs=4,
    )

    all_combos = results["high_consensus"] + results["aggressive"] + results["moonshot"]
    assert len(all_combos) > 0, "No valid parlays found within [10x, 50x]"

    best_ticket = all_combos[0]
    assert 10.0 <= best_ticket["total_odds"] <= 50.0

    # Verify mutual exclusion: no event_id repeated
    leg_event_ids = [leg["event_id"] for leg in best_ticket["legs"]]
    assert len(leg_event_ids) == len(set(leg_event_ids)), "Same-match parlay violation in Taiwan lottery"

    # 5. Financial Wallet Execution with NT$ 200 rule
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tf:
        db_path = Path(tf.name)

    try:
        wallet = WeeklyWalletManager(db_path=db_path)
        recorder = TicketRecorder(wallet=wallet)

        # Deposit NT$ 200
        wallet.deposit_external(200.0)
        assert wallet.get_status()["weekly_wallet_balance"] == 200.0

        # Place the best parlay ticket with NT$ 50 stake
        placed = recorder.place_ticket(
            legs=best_ticket["legs"],
            stake=50.0,
            total_odds=best_ticket["total_odds"],
            notes="Real Day Integration Ticket",
        )
        assert placed["status"] == "OPEN"
        assert wallet.get_status()["weekly_wallet_balance"] == 150.0

        # Settle ticket as WON
        settle = recorder.settle_ticket(placed["ticket_id"], won=True)
        assert settle["won"] is True
        payout = settle["payout"]
        assert payout > 500.0

        # Verify payout went straight to Prize Pool (locked profit)
        wallet_st = wallet.get_status()
        assert wallet_st["weekly_wallet_balance"] == 150.0
        assert wallet_st["prize_pool"] == payout

    finally:
        try:
            db_path.unlink(missing_ok=True)
        except Exception:
            pass
