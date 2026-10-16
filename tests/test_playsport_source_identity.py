import json
from pathlib import Path

from bs4 import BeautifulSoup

from core.scraper import PlaysportScraper
from core.source_health import build_identity_health
from core.identity.league_mapping import normalize_league_and_sport
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter
from integrations.experts.playsport_expert import ALLIANCE_MAP as EXPERT_ALLIANCE_MAP, PlaysportExpertAdapter
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
LIVE_FIXTURE = ROOT / "artifacts" / "source_integrity_review_20261013" / "playsport_soccer_live_excerpt.html"


def test_live_soccer_dom_uses_participant_order_and_keeps_three_outcomes(tmp_path):
    table = BeautifulSoup(LIVE_FIXTURE.read_text(encoding="utf-8"), "html.parser").find("table")
    scraper = PlaysportScraper(cache_dir=tmp_path / "cache")

    matches = scraper._parse_predict_table(table, "足球 (各大聯賽)", "4")

    assert len(matches) == 3
    assert len({match["match_id"] for match in matches}) == 3
    assert [(m["away_team"], m["home_team"]) for m in matches] == [
        ("阿爾希拉爾", "阿爾薩德"),
        ("布拉格斯拉維亞", "薩巴赫.馬薩齊爾"),
        ("符茲堡踢球者", "哈維爾斯"),
    ]
    assert all(not m["_identity_incomplete"] for m in matches)
    assert all(m["_identity_source"] == "participant_dom_order" for m in matches)
    assert all(len(m["options"]) == 5 for m in matches)
    assert [m["source_competition"] for m in matches] == [
        "亞洲冠軍聯賽", "歐洲冠軍聯賽", "德國丙級聯賽"
    ]
    assert [m["canonical_league"] for m in matches] == [
        "UNKNOWN_ASIAN_CHAMPIONS_LEAGUE", "CHAMPIONS", "UNKNOWN_德國丙級聯賽"
    ]
    assert [m["start_time_utc"] for m in matches] == [
        "2026-10-13T16:00:00+00:00", "2026-10-13T16:45:00+00:00",
        "2026-10-13T17:00:00+00:00",
    ]
    for match in matches:
        result_market = [o for o in match["options"] if o["market_type"] in {"不讓分", "和局"}]
        assert {(o["market_type"], o["side"]) for o in result_market} == {
            ("不讓分", "客"), ("不讓分", "主"), ("和局", "和")
        }


def test_soccer_draw_and_moneyline_share_complete_three_way_market(tmp_path):
    table = BeautifulSoup(LIVE_FIXTURE.read_text(encoding="utf-8"), "html.parser").find("table")
    parsed = PlaysportScraper(cache_dir=tmp_path / "cache")._parse_predict_table(
        table, "足球 (各大聯賽)", "4"
    )
    now = datetime.now(timezone.utc)
    for match in parsed:
        match.update({"_cache_status": "LIVE", "_cached_at": now.timestamp(),
                      "_cached_iso": now.isoformat()})

    class FixtureScraper:
        def fetch_scale_matches(self, alliance_id, force_refresh=False):
            return parsed if alliance_id == "4" else []

    legs = PlaysportOddsAdapter(scraper=FixtureScraper()).get_taiwan_legs(["4"])
    match_legs = [leg for leg in legs if leg.event_id == "1000" and leg.market in {"不讓分", "和局"}]
    assert len(match_legs) == 3
    for leg in match_legs:
        assert leg.signal_evidence["market_complete"] is True
        assert set(leg.signal_evidence["market_outcome_odds"]) == {"客", "主", "和"}
        assert leg.signal_evidence["market_outcome_odds"] == {"客": 1.4, "主": 3.95, "和": 3.8}


def test_league_mapping_does_not_guess_sport_family_leagues():
    assert normalize_league_and_sport("", "4") == ("UNKNOWN_UNSPECIFIED", "soccer")
    assert normalize_league_and_sport("籃球 (WNBA/NBA)", "7") == ("UNKNOWN_籃球_WNBA_NBA", "basketball")
    assert normalize_league_and_sport("WNBA", "7") == ("WNBA", "basketball")
    assert normalize_league_and_sport("NBA", "3") == ("NBA", "basketball")
    assert normalize_league_and_sport("", None) == ("OTHER", "other")
    assert EXPERT_ALLIANCE_MAP["NBA"] == "3"
    assert EXPERT_ALLIANCE_MAP["WNBA"] == "7"


def test_member_prediction_page_uses_alliance_family_not_hardcoded_mlb(tmp_path):
    html = (ROOT / "tests" / "fixtures" / "playsport_expert_asukajohn.html").read_text(encoding="utf-8")
    adapter = PlaysportExpertAdapter(scraper=PlaysportScraper(cache_dir=tmp_path / "cache"))
    ranker = {"userid": "fixture", "nickname": "fixture", "rank": 1, "historical_win_rate": 50}
    expected = {"2": ("NPB", "baseball"), "7": ("WNBA", "basketball"), "93": ("NFL", "football")}
    for alliance_id, (league, sport) in expected.items():
        picks = adapter._parse_member_prediction_html(html, alliance_id, ranker)
        assert picks
        assert all((pick.league, pick.sport) == (league, sport) for pick in picks)

    soccer_picks = adapter._parse_member_prediction_html(html, "4", ranker)
    assert all(pick.sport == "soccer" for pick in soccer_picks)
    assert all(pick.league.startswith("UNKNOWN_") for pick in soccer_picks)


def test_source_health_history_reports_completeness_without_team_names(tmp_path):
    matches = [
        {"_identity_incomplete": False, "away_team":"洋基", "home_team":"紅襪"},
        {"_identity_incomplete": True, "_identity_diagnostic": "placeholder_or_duplicate_team",
         "away_team": "客隊", "home_team": "主隊"},
    ]
    health = build_identity_health(matches)
    assert health == {
        "identity_total_count": 2,
        "identity_complete_count": 1,
        "identity_incomplete_count": 1,
        "identity_completeness_rate": 0.5,
        "identity_diagnostic_counts": {"placeholder_or_duplicate_team": 1},
    }

    path = tmp_path / "source-health.jsonl"
    scraper = PlaysportScraper(cache_dir=tmp_path / "cache", source_health_history_path=path)
    scraper._store_scale_source_status("4", {
        "source_status": "LIVE", "source_url": "https://www.playsport.cc/predict/scale?allianceid=4",
        "match_count": 2, "observed_at": "2026-10-14T00:09:28+00:00",
    }, matches)
    assert scraper.get_scale_source_status()["4"]["identity_completeness_rate"] == 0.5
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["identity_completeness_rate"] == 0.5
    assert row["match_count"] == 2
    assert "away_team" not in row and "home_team" not in row
    assert "客隊" not in json.dumps(row, ensure_ascii=False)


def test_source_health_checks_actual_identity_even_without_parser_flag():
    health = build_identity_health([{}, {"away_team":"客隊", "home_team":"主隊"},
                                    {"away_team":"洋基", "home_team":"洋基"}])
    assert health["identity_complete_count"] == 0
    assert health["identity_diagnostic_counts"] == {"missing_placeholder_or_duplicate_team":3}


def test_unmapped_source_event_identity_distinguishes_reused_daily_numbers(tmp_path):
    html = LIVE_FIXTURE.read_text(encoding="utf-8")
    scraper = PlaysportScraper(cache_dir=tmp_path / "cache")
    first = scraper._parse_predict_table(BeautifulSoup(html, "html.parser").find("table"),
                                        "足球 (各大聯賽)", "4")[0]
    next_day = scraper._parse_predict_table(
        BeautifulSoup(html.replace("20261014", "20261015"), "html.parser").find("table"),
        "足球 (各大聯賽)", "4")[0]
    assert first["match_id"] == next_day["match_id"]
    assert first["canonical_event_id"] != next_day["canonical_event_id"]
    from core.parlay_validation import shared_event_exposure
    assert shared_event_exposure([{"legs":[first]}, {"legs":[next_day]}])[0]["shared_event_count"] == 0
