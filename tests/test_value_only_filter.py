"""Test value_only signal filter in ParlayEngine."""
from datetime import datetime, timedelta, timezone
from core.parlay_engine import ParlayEngine
from integrations.common.models import TaiwanLeg


def test_value_only_filter_retains_positive_ev_and_bankers():
    now = datetime.now(timezone.utc)
    engine = ParlayEngine(signal_hub=object())

    leg_pos_ev = TaiwanLeg(
        event_id="e1",
        sport="baseball",
        league="MLB",
        home_team="紅襪",
        away_team="洋基",
        market="不讓分",
        selection="主",
        taiwan_odds=2.10,
        odds_status="FRESH",
        odds_scraped_at=now.isoformat(),
        start_time_utc=(now + timedelta(hours=2)).isoformat(),
        evidence_quality="HIGH",
        signal_evidence={
            "agreement": "HIGH",
            "evidence_quality": "HIGH",
            "is_positive_ev": True,
            "expected_value": 0.05,
            "expected_value_pct": 5.0,
        },
    )

    leg_banker = TaiwanLeg(
        event_id="e2",
        sport="basketball",
        league="NBA",
        home_team="塞爾提克",
        away_team="湖人",
        market="不讓分",
        selection="客",
        taiwan_odds=1.60,
        odds_status="FRESH",
        odds_scraped_at=now.isoformat(),
        start_time_utc=(now + timedelta(hours=3)).isoformat(),
        evidence_quality="HIGH",
        signal_evidence={
            "agreement": "HIGH",
            "evidence_quality": "HIGH",
            "consensus_probability": 0.65,
            "expected_value": 0.04,
        },
    )

    leg_negative_ev = TaiwanLeg(
        event_id="e3",
        sport="soccer",
        league="PREMIER",
        home_team="曼城",
        away_team="兵工廠",
        market="不讓分",
        selection="和",
        taiwan_odds=3.20,
        odds_status="FRESH",
        odds_scraped_at=now.isoformat(),
        start_time_utc=(now + timedelta(hours=4)).isoformat(),
        evidence_quality="LOW",
        signal_evidence={
            "agreement": "LOW",
            "evidence_quality": "LOW",
            "is_positive_ev": False,
            "expected_value": -0.15,
            "consensus_probability": 0.25,
        },
    )

    all_legs = [leg_pos_ev, leg_banker, leg_negative_ev]

    diag = {}
    res = engine.search_parlays(
        legs=all_legs,
        min_odds=1.5,
        max_odds=10.0,
        min_legs=2,
        max_legs=2,
        signal_filter="value_only",
        diagnostics=diag,
    )

    # In value_only, leg_negative_ev is excluded
    assert diag["quality_option_count"] == 2
    assert diag["search_event_count"] == 2
    combos = res.get("high_consensus", []) + res.get("aggressive", []) + res.get("moonshot", [])
    assert len(combos) >= 1
    # Check that leg_negative_ev is not in any combo
    for c in combos:
        events = [l["event_id"] for l in c["legs"]]
        assert "e3" not in events
        assert "e1" in events and "e2" in events
