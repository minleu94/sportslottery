"""Test Actionable Season Radar opportunity metrics and badges."""
from core.season_radar import SeasonRadar
from integrations.common.models import TaiwanLeg


def test_actionable_season_radar_badges():
    radar = SeasonRadar()
    
    # Create sample evaluated legs
    leg1 = TaiwanLeg(
        event_id="101",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="主勝",
        taiwan_odds=1.75,
        signal_evidence={
            "is_positive_ev": True,
            "expected_value": 0.08,
            "consensus_probability": 0.62,
            "market_fair_probability": 0.60,
        },
    )
    setattr(leg1, "signal_agreement", "HIGH")

    leg2 = TaiwanLeg(
        event_id="102",
        sport="basketball",
        league="NBA",
        market="不讓分",
        selection="客勝",
        taiwan_odds=2.10,
        signal_evidence={
            "is_positive_ev": True,
            "is_sharp_value_bet": True,
            "expected_value": 0.05,
            "consensus_probability": 0.50,
        },
    )

    leg3 = TaiwanLeg(
        event_id="103",
        sport="soccer",
        league="PREMIER",
        market="不讓分",
        selection="主勝",
        taiwan_odds=1.40,
        signal_evidence={
            "is_positive_ev": False,
            "expected_value": -0.01,
            "consensus_probability": 0.70,
        },
    )

    summary = radar.get_radar_summary(
        taiwan_legs=[leg1, leg2, leg3],
        evaluated_legs=[leg1, leg2, leg3],
    )
    by_code = {r["code"]: r for r in summary}

    # MLB should have positive_ev and banker
    assert by_code["MLB"]["taiwan_market_count"] == 1
    assert by_code["MLB"]["positive_ev_count"] == 1
    assert by_code["MLB"]["banker_count"] == 1
    assert "🔥" in by_code["MLB"]["opportunity_badge"]
    assert "🛡️" in by_code["MLB"]["opportunity_badge"]

    # NBA should have positive EV
    assert by_code["NBA"]["taiwan_market_count"] == 1
    assert by_code["NBA"]["positive_ev_count"] == 1
    assert "🔥" in by_code["NBA"]["opportunity_badge"]

    # Premier league has banker
    assert by_code["PREMIER"]["taiwan_market_count"] == 1
    assert by_code["PREMIER"]["banker_count"] == 1
    assert "🛡️" in by_code["PREMIER"]["opportunity_badge"]
