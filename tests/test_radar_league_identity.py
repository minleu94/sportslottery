from core.season_radar import SeasonRadar
from integrations.common.models import TaiwanLeg


def test_wnba_never_counts_as_nba_and_unknown_soccer_never_counts_as_epl():
    legs = [TaiwanLeg(event_id=str(i), sport=sport, league=league, market="不讓分",
                      selection="客勝", taiwan_odds=2.0)
            for i, (sport, league) in enumerate((
                ("basketball", "WNBA"), ("basketball", "NBA"),
                ("soccer", "UNKNOWN_德國丙級聯賽"), ("soccer", "PREMIER")))]
    rows = {row["code"]:row for row in SeasonRadar().get_radar_summary(taiwan_legs=legs)}
    assert rows["NBA"]["taiwan_market_count"] == 1
    assert rows["WNBA"]["taiwan_market_count"] == 1
    assert rows["PREMIER"]["taiwan_market_count"] == 1
    assert rows["CHAMPIONS"]["taiwan_market_count"] == 0
    assert SeasonRadar.LEAGUES["NBA"]["playsport_aid"] == "3"


def test_generic_soccer_alliance_does_not_invent_competition():
    matches = [{"alliance_id":"4", "match_id":"unknown", "league":"足球 (各大聯賽)"},
               {"alliance_id":"4", "match_id":"ucl", "canonical_league":"CHAMPIONS"}]
    rows = {row["code"]:row for row in SeasonRadar().get_radar_summary(live_matches=matches)}
    assert rows["PREMIER"]["taiwan_market_count"] == 0
    assert rows["CHAMPIONS"]["taiwan_market_count"] == 1
