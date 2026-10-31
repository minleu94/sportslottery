#!/usr/bin/env python3
"""Tests for Signal Hub Redesign and Source Independence (Milestone 4).

Verification:
1. Explicit signal classification: CROWD_SENTIMENT, EXPERT_PICKS, BET_COUNT_SPLITS,
   MONEY_VOLUME_SPLITS, MARKET_BENCHMARK, STATISTICAL_MODEL
2. Null preservation in betting splits and ticket/money divergence
3. Deduplication of syndicated upstream data feeds
4. Ensuring crowd sentiment alone cannot inflate agreement to HIGH
"""

from unittest.mock import MagicMock
import pytest

from core.correlation_guard import check_source_independence
from core.signal_hub import SignalHub
from integrations.common.models import PredictionSignal, TaiwanLeg
from integrations.odds.market_models import BettingSplitsSnapshot


def test_source_independence_deduplication():
    # Two signals citing the same underlying bookmaker handle (e.g. DraftKings via Action Network & VSiN)
    sig1 = PredictionSignal(
        source_id="action_net_dk",
        source_name="Action Network (DraftKings)",
        source_type="BETTING_SPLITS",
        event_id="101",
        market="讓分",
        selection="主",
        metadata={"reporting_bookmaker": "DraftKings", "sample_size": 5000},
    )
    sig2 = PredictionSignal(
        source_id="vsin_dk",
        source_name="VSiN (DraftKings)",
        source_type="BETTING_SPLITS",
        event_id="101",
        market="讓分",
        selection="主",
        metadata={"reporting_bookmaker": "DraftKings", "sample_size": 5000},
    )

    res = check_source_independence([sig1, sig2])
    assert res["total_signals_evaluated"] == 2
    assert res["independent_count"] == 1
    assert res["excluded_count"] == 1
    assert "Syndicated upstream feed" in res["excluded_duplicates"][0]["reason"]


def test_signal_hub_with_splits_and_breakdown():
    mock_splits_client = MagicMock()
    mock_splits_client.get_betting_splits.return_value = [
        BettingSplitsSnapshot(
            source_id="vsin_circa",
            source_type="BETTING_SPLITS",
            event_id="syn_1",
            league="NBA",
            home_team="Boston Celtics",
            away_team="Milwaukee Bucks",
            start_time_utc="2026-10-31T00:00:00Z",
            market_type="SPREAD",
            selection="home",
            line=-4.5,
            bet_percentage=45.0,
            money_percentage=72.0,
            sample_size=9500,
            reporting_bookmaker="Circa Sports",
            reporting_scope="VEGAS_COMMERCIAL",
            observed_at_utc="2026-10-31T00:00:00Z",
            retrieved_at_utc="2026-10-31T00:00:00Z",
            freshness_status="LIVE",
        )
    ]

    hub = SignalHub(splits_client=mock_splits_client)
    leg = TaiwanLeg(
        event_id="201",
        sport="basketball",
        league="NBA",
        home_team="塞爾提克",
        away_team="公鹿",
        market="讓分",
        selection="塞爾提克 -4.5",
        side="主",
        line="-4.5",
        taiwan_odds=1.75,
    )

    evaluated_leg = hub.evaluate_taiwan_leg(leg)
    ev = evaluated_leg.signal_evidence

    assert ev is not None
    assert ev.get("bet_percentage") == 45.0
    assert ev.get("money_percentage") == 72.0
    assert ev.get("splits_divergence_pp") == 27.0
    assert ev.get("is_sharp_money_divergence") is True
    assert ev.get("splits_reporting_book") == "Circa Sports"

    # Verify classification breakdown exists
    breakdown = ev.get("signal_classification_breakdown")
    assert breakdown is not None
    assert "crowd_sentiment" in breakdown
    assert "betting_splits" in breakdown
    assert "market_benchmark" in breakdown
    assert "statistical_models" in breakdown


def test_crowd_sentiment_alone_cannot_reach_high_agreement():
    # Only crowd sentiment without accepted engine or sharp value
    hub = SignalHub(splits_client=MagicMock(get_betting_splits=lambda l: []))
    leg = TaiwanLeg(
        event_id="202",
        sport="baseball",
        league="MLB",
        home_team="道奇",
        away_team="教士",
        market="不讓分",
        selection="道奇勝",
        side="主",
        taiwan_odds=1.55,
    )

    # Mock crowd signal only (high popularity 85%)
    crowd_sig = PredictionSignal(
        source_id="playsport_crowd",
        source_name="玩運彩彩迷選票",
        source_type="CROWD",
        source_category="CROWD_CONSENSUS",
        independence_group="PLAYSPORT_CROWD",
        event_id=leg.event_id,
        market=leg.market,
        selection=leg.selection,
        score=85.0,
        freshness_status="LIVE",
        metadata={"vote_count": 500},
    )

    result_leg = hub.synthesize_signals_for_leg(leg, [crowd_sig])
    # Crowd alone must be LOW or INSUFFICIENT, definitely not HIGH
    assert result_leg.evidence_quality != "HIGH"
