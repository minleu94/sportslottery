from __future__ import annotations

import json
from pathlib import Path

from core.scraper import PlaysportScraper
from integrations.common.models import TaiwanLeg
from integrations.experts.playsport_expert import PlaysportExpertAdapter
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "playsport_public_sources_20261012"


class _Response:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class _FixtureSession:
    def __init__(self, pages):
        self.pages = pages
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=10):
        self.calls.append(url)
        for key, page in self.pages.items():
            if key in url:
                if isinstance(page, tuple):
                    return _Response(page[1], page[0])
                return _Response(page)
        return _Response("", 404)


def test_public_board_raw_html_is_parsed_and_cross_board_users_are_merged(tmp_path):
    pages = {
        "mainPrediction": (FIXTURE_DIR / "main_prediction.html").read_text(encoding="utf-8"),
        "winRate": (FIXTURE_DIR / "win_rate.html").read_text(encoding="utf-8"),
    }
    scraper = PlaysportScraper(session=_FixtureSession(pages), cache_dir=tmp_path / "cache")

    result = scraper.fetch_expert_leaderboards("1", force_refresh=True)

    assert result["source_status"] == "LIVE"
    assert len(result["boards"]["main_prediction"]["rankers"]) == 60
    assert len(result["boards"]["win_rate"]["rankers"]) == 90
    aoosoo = next(row for row in result["rankers"] if row["userid"] == "aoosoo1")
    assert set(aoosoo["board_kinds"]) == {"main_prediction", "win_rate"}
    assert len(aoosoo["board_entries"]) == 2
    assert "process_time" in aoosoo["board_entries"][0]
    assert not (tmp_path / "snapshots").exists()


def test_http_failure_and_empty_board_are_visible_and_never_live(tmp_path):
    scraper_403 = PlaysportScraper(
        session=_FixtureSession({"mainPrediction": (403, "Forbidden"), "winRate": (200, "<html></html>")}),
        cache_dir=tmp_path / "cache403",
    )
    result = scraper_403.fetch_expert_leaderboards("1", force_refresh=True)
    assert result["source_status"] == "UNAVAILABLE"
    assert result["boards"]["main_prediction"]["source_status"] == "HTTP_403"
    assert result["boards"]["win_rate"]["source_status"] == "PARSE_EMPTY"
    assert result["rankers"] == []


def test_unknown_pick_date_is_not_filled_with_today_and_taipei_date_is_used():
    adapter = PlaysportExpertAdapter()
    html = """<table class="bank-tablecon"><table class="sellpredict-item">
      <tr><td>1</td><td>小熊 紅人</td></tr>
      <tr><td></td><td class="bonusinfo betinfo">小熊 不讓分勝</td></tr>
    </table></table>"""
    ranker = {"userid": "u1", "nickname": "公開玩家", "rank": 1,
              "historical_win_rate": 71, "wingame": 71, "losegame": 29}
    picks = adapter._parse_member_prediction_html(html, "1", ranker)
    assert picks[0].pick_date is None
    assert picks[0].pick_timestamp == "TIMESTAMP_UNKNOWN"
    leg = TaiwanLeg(event_id="1", sport="baseball", league="MLB", market="不讓分",
                    selection="小熊 不讓分勝", taiwan_odds=1.9,
                    start_time_utc="2026-10-12T17:00:00+00:00", away_team="小熊", home_team="紅人", side="客")
    assert adapter._matches_date(picks[0], leg) is False


def test_expert_signal_keeps_historical_rate_separate_from_probability_and_support():
    class FakeScraper:
        def fetch_expert_leaderboards(self, alliance_id="1", force_refresh=False):
            return {
                "rankers": [{"userid": "u1", "nickname": "玩家", "rank": 1,
                             "winpercentage": 74, "wingame": 74, "losegame": 26,
                             "board_kinds": ["main_prediction", "win_rate"], "board_entries": []}],
                "source_status": "LIVE", "source_urls": ["https://www.playsport.cc/billboard/mainPrediction?allianceid=1",
                                  "https://www.playsport.cc/billboard/winRate?allianceid=1"],
                "observed_at": "2026-10-12T16:00:00+00:00", "cache_age_minutes": 0,
            }

        def fetch_member_prediction_page_result(self, userid, alliance_id):
            return {"html": """<div>發文日期：2026-10-13</div>
              <table class="bank-tablecon"><table class="sellpredict-item">
              <tr><td>1</td><td>小熊 紅人</td></tr>
              <tr><td></td><td class="bonusinfo betinfo">小熊 不讓分勝</td></tr>
              </table></table>""", "source_url": f"https://www.playsport.cc/member/{userid}/prediction?allianceid={alliance_id}",
                    "source_status": "LIVE", "observed_at": "2026-10-12T16:00:00+00:00", "cache_age_minutes": 0}
    adapter = PlaysportExpertAdapter(scraper=FakeScraper())
    leg = TaiwanLeg(event_id="game", sport="baseball", league="MLB", market="不讓分",
                    selection="小熊 不讓分勝", taiwan_odds=1.9,
                    start_time_utc="2026-10-12T17:00:00+00:00", away_team="小熊", home_team="紅人", side="客")
    signal = adapter.get_expert_signal(leg)

    assert signal is not None
    assert signal.probability is None
    assert signal.score == 74
    assert signal.metadata["historical_win_rate"] == 74
    assert signal.metadata["support_ratio"] == 1.0
    assert signal.metadata["board_kinds"] == ["main_prediction", "win_rate"]
    assert signal.metadata["publication_time_precision"] == "DATE_ONLY"
    assert signal.metadata["source_status"] == "LIVE"
    assert signal.confidence == "MED"
    assert signal.metadata["verified_pick_count"] == 1
    assert signal.metadata["total_voted"] == 1


def test_post_event_source_observation_cannot_create_pregame_signal():
    class FakeScraper:
        def fetch_expert_leaderboards(self, alliance_id="1", force_refresh=False):
            return {"rankers": [{"userid": "u1", "nickname": "玩家", "rank": 1, "winpercentage": 74,
                                 "wingame": 74, "losegame": 26, "board_kinds": ["main_prediction"],
                                 "board_entries": []}], "source_status": "LIVE", "source_urls": [],
                    "observed_at": "2026-10-12T22:00:00+00:00", "cache_age_minutes": 0}

        def fetch_member_prediction_page_result(self, userid, alliance_id):
            return {"html": """<div>發文日期：2026-10-13</div>
              <table class="sellpredict-item"><tr><td>1</td><td>小熊 紅人</td></tr>
              <tr><td></td><td class="bonusinfo betinfo">小熊 不讓分勝</td></tr></table>""",
                    "source_url": "https://www.playsport.cc/member/u1/prediction?allianceid=1",
                    "source_status": "LIVE", "observed_at": "2026-10-12T22:00:00+00:00", "cache_age_minutes": 0}

    adapter = PlaysportExpertAdapter(scraper=FakeScraper())
    leg = TaiwanLeg(event_id="game", sport="baseball", league="MLB", market="不讓分",
                    selection="小熊 不讓分勝", taiwan_odds=1.9,
                    start_time_utc="2026-10-12T17:00:00+00:00", away_team="小熊", home_team="紅人", side="客")
    assert adapter.get_expert_signal(leg) is None


def test_explicit_taipei_publication_datetime_is_preserved_as_utc_instant():
    html = """<div>發文時間 2026-10-13 08:30</div>
      <table class="sellpredict-item"><tr><td>1</td><td>小熊 紅人</td></tr>
      <tr><td></td><td class="bonusinfo betinfo">小熊 不讓分勝</td></tr></table>"""
    pick = PlaysportExpertAdapter()._parse_member_prediction_html(
        html, "1", {"userid": "u1", "nickname": "玩家", "rank": 1, "winpercentage": 50, "wingame": 1, "losegame": 1}
    )[0]
    assert pick.pick_date == "2026-10-13"
    assert pick.pick_timestamp == "2026-10-13T00:30:00+00:00"
    assert pick.publication_time_precision == "DATETIME"


def test_original_asukajohn_html_fixture_contains_real_parseable_picks():
    fixture = Path(__file__).parent / "fixtures" / "playsport_expert_asukajohn.html"
    adapter = PlaysportExpertAdapter()
    picks = adapter._parse_member_prediction_html(
        fixture.read_text(encoding="utf-8"), "1",
        {"userid": "asukajohn", "nickname": "AsukaJohn", "rank": 1,
         "winpercentage": 55, "wingame": 11, "losegame": 9},
    )
    assert len(picks) == 3
    assert any(p.market == "讓分" and p.line is not None for p in picks)


def test_saved_aa5220_rows_do_not_turn_settled_international_text_into_a_pick():
    fixture = FIXTURE_DIR / "member_aa5220.html"
    adapter = PlaysportExpertAdapter()
    picks = adapter._parse_member_prediction_html(
        fixture.read_text(encoding="utf-8"), "1",
        {"userid": "aa5220", "nickname": "公開玩家", "rank": 3,
         "source_url": "https://www.playsport.cc/member/aa5220/prediction?allianceid=1",
         "source_status": "LIVE", "observed_at": "2026-10-12T16:00:00+00:00",
         "board_kinds": ["main_prediction", "win_rate"]},
    )
    diagnostics = adapter._last_parse_diagnostics
    assert picks == []
    assert len(diagnostics) == 2
    assert all(row["reason"] == "INTERNATIONAL_NON_TAIWAN" for row in diagnostics)
    assert diagnostics[1]["raw_pick"] == "主讓 1分輸50% | 大7分贏50%"
    assert diagnostics[1]["source_url"].endswith("member/aa5220/prediction?allianceid=1")
    assert diagnostics[1]["observed_at"] == "2026-10-12T16:00:00+00:00"
    assert diagnostics[1]["pick_date"] is None
    assert diagnostics[1]["publication_time_precision"] == "UNKNOWN"


def test_mixed_fullwidth_market_separator_is_rejected_before_result_text_is_parsed():
    html = """<table class="bank-tablecon"><table class="sellpredict-item">
      <tr><td>1</td><td>小熊 紅人</td></tr>
      <tr><td></td><td class="bonusinfo betinfo">主讓 1 分輸50%｜大 7 分贏50%</td></tr>
    </table></table>"""
    adapter = PlaysportExpertAdapter()
    picks = adapter._parse_member_prediction_html(
        html, "1", {"userid": "mixed", "nickname": "公開玩家", "rank": 1}
    )
    assert picks == []
    assert adapter._last_parse_diagnostics[0]["reason"] == "MULTI_CONTEXT"
    assert adapter._last_parse_diagnostics[0]["raw_pick"] == "主讓 1 分輸50%｜大 7 分贏50%"


def test_saved_go108792_html_only_verifies_single_taiwan_spread_row():
    adapter = PlaysportExpertAdapter()
    picks = adapter._parse_member_prediction_html(
        (FIXTURE_DIR / "member_GO108792.html").read_text(encoding="utf-8"), "1",
        {"userid": "GO108792", "nickname": "公開玩家", "rank": 2},
    )
    assert [(pick.market, pick.side, pick.line, pick.raw_pick) for pick in picks] == [
        ("讓分", "主", "+1.5", "主 +1.5")
    ]
    assert [row["reason"] for row in adapter._last_parse_diagnostics] == [
        "INTERNATIONAL_NON_TAIWAN", "MULTI_CONTEXT"
    ]
    assert picks[0].pick_date is None
    assert picks[0].publication_time_precision == "UNKNOWN"


def test_parser_v2_contract_supports_single_ml_spread_total_and_precise_taipei_time():
    adapter = PlaysportExpertAdapter()
    fixture = FIXTURE_DIR / "parser_contract_synthetic.html"
    picks = adapter._parse_member_prediction_html(
        fixture.read_text(encoding="utf-8"), "1",
        {"userid": "synthetic", "nickname": "fixture", "rank": 1},
    )
    assert [(pick.market, pick.side, pick.line) for pick in picks] == [
        ("不讓分", "客", None), ("讓分", "客", "-1.5"), ("大小", "大", "8.5")
    ]
    assert all(pick.pick_date == "2026-10-12" for pick in picks)
    assert all(pick.pick_timestamp == "2026-10-12T07:00:00+00:00" for pick in picks)
    assert all(pick.publication_time_precision == "DATETIME" for pick in picks)
    assert [row["reason"] for row in adapter._last_parse_diagnostics] == [
        "MULTI_CONTEXT", "INTERNATIONAL_NON_TAIWAN"
    ]
    # Even with an exact event row and an explicit publication time, an
    # international/multi-market row cannot turn into support.
    assert not any(pick.away_team == "洋基" for pick in picks)


def test_missing_market_source_label_stays_unknown_and_is_not_a_verified_pick():
    html = """<table class="sellpredict-item"><tr><td>1</td><td>小熊 紅人(主)</td></tr>
      <tr><td></td><td class="bonusinfo">小熊 不讓分勝</td></tr></table>"""
    adapter = PlaysportExpertAdapter()
    assert adapter._parse_member_prediction_html(
        html, "1", {"userid": "u1", "nickname": "公開玩家", "rank": 1}
    ) == []
    assert adapter._last_parse_diagnostics[0]["reason"] == "UNKNOWN_MARKET_SOURCE_LABEL"


def test_unknown_or_naive_event_dates_and_missing_spread_lines_are_rejected():
    adapter = PlaysportExpertAdapter()
    pick = adapter._parse_member_prediction_html(
        (Path(__file__).parent / "fixtures" / "playsport_expert_asukajohn.html").read_text(encoding="utf-8"),
        "1", {"userid": "u1", "nickname": "player", "rank": 1, "winpercentage": 50, "wingame": 1, "losegame": 1},
    )[0]
    leg = TaiwanLeg(event_id="g", sport="baseball", league="MLB", market="讓分", selection="x",
                    taiwan_odds=1.9, start_time_utc=None, away_team=pick.away_team, home_team=pick.home_team,
                    side=pick.side, line=pick.line)
    pick.pick_date = "2026-10-12"
    assert adapter._matches_date(pick, leg) is False
    leg.start_time_utc = "2026-10-12T17:00:00"  # Naive timestamps are not silently treated as UTC.
    assert adapter._matches_date(pick, leg) is False
    pick.line = None
    leg.start_time_utc = "2026-10-12T17:00:00+00:00"
    leg.line = "-1.5"
    assert adapter._matches_line(pick, leg) is False


def test_parsed_pick_cache_without_timestamp_is_not_reused_forever():
    class EmptyScraper:
        def fetch_expert_leaderboards(self, alliance_id="1", force_refresh=False):
            return {"rankers": [], "source_status": "UNAVAILABLE", "source_urls": [],
                    "observed_at": None, "cache_age_minutes": None, "boards": {}}

    adapter = PlaysportExpertAdapter(scraper=EmptyScraper())
    adapter._parsed_picks_cache["1"] = [object()]
    # Manually seeded data without an insertion time is not a valid TTL cache entry.
    assert adapter._load_expert_picks_for_alliance("1") == []


def test_event_matching_uses_exact_full_team_names_and_rejects_placeholders():
    adapter = PlaysportExpertAdapter()
    pick = PlaysportExpertAdapter()._parse_member_prediction_html(
        (Path(__file__).parent / "fixtures" / "playsport_expert_asukajohn.html").read_text(encoding="utf-8"),
        "1", {"userid": "u1", "nickname": "player", "rank": 1, "winpercentage": 50, "wingame": 1, "losegame": 1},
    )[0]
    leg = TaiwanLeg(event_id="g", sport="baseball", league="MLB", market=pick.market, selection="x",
                    taiwan_odds=1.9, away_team=pick.away_team, home_team=pick.home_team)
    assert adapter._matches_event(pick, leg)
    leg.away_team = pick.away_team[:1]
    assert not adapter._matches_event(pick, leg)
    leg.away_team, leg.home_team = "客隊", "主隊"
    assert not adapter._matches_event(pick, leg)


def test_odds_adapter_emits_complete_three_way_prices_and_keeps_unknown_time_unknown():
    class FakeOddsScraper:
        def fetch_scale_matches(self, alliance_id, force_refresh=False):
            return [{
                "match_id": "soccer-1", "league": "足球", "away_team": "客隊", "home_team": "主隊",
                "start_time_utc": "2026-10-12T17:00:00+00:00",
                "options": [
                    {"market_type": "不讓分", "side": "客", "line": None, "odds": 2.4, "selection": "客隊勝"},
                    {"market_type": "不讓分", "side": "和", "line": None, "odds": 3.1, "selection": "和局"},
                    {"market_type": "不讓分", "side": "主", "line": None, "odds": 2.8, "selection": "主隊勝"},
                ],
            }, {
                "match_id": "soccer-2", "league": "足球", "away_team": "客隊", "home_team": "主隊",
                "start_time_utc": "2026-10-12T18:00:00+00:00", "options": [],
            }]

    legs = PlaysportOddsAdapter(scraper=FakeOddsScraper()).get_taiwan_legs(alliance_ids=["4"])
    assert len(legs) == 3
    assert all(leg.signal_evidence["market_complete"] is True for leg in legs)
    assert legs[0].signal_evidence["market_outcome_odds"] == {"客": 2.4, "和": 3.1, "主": 2.8}
    assert legs[0].signal_evidence["market_outcome_sources"]["和"]["observed_at"] is None
    assert all(leg.odds_status == "UNKNOWN" for leg in legs)
    assert all(leg.odds_scraped_at is None and leg.odds_age_minutes is None for leg in legs)
    assert all(leg.signal_evidence["same_team_day_event_count"] == 2 for leg in legs)
    assert all(leg.signal_evidence["identity_ambiguous"] is True for leg in legs)


def test_refresh_bypasses_parsed_board_and_member_caches(tmp_path):
    class RefreshScraper:
        def __init__(self):
            self.board_force = []
            self.member_force = []

        def fetch_expert_leaderboards(self, alliance_id="1", force_refresh=False):
            self.board_force.append(force_refresh)
            return {"rankers": [{"userid": "u1", "nickname": "Player", "rank": 1,
                                 "board_kinds": ["main_prediction"]}], "boards": {},
                    "source_status": "LIVE", "source_urls": [], "observed_at": None}

        def fetch_member_prediction_page_result(self, userid, alliance_id, force_refresh=False):
            self.member_force.append(force_refresh)
            return {"html": "<html></html>", "source_url": f"https://www.playsport.cc/member/{userid}/prediction",
                    "source_status": "LIVE", "observed_at": None}

    scraper = RefreshScraper()
    adapter = PlaysportExpertAdapter(scraper=scraper)
    adapter._load_expert_picks_for_alliance("1")
    assert scraper.board_force == [False]
    assert scraper.member_force == [False]
    adapter.refresh("1")
    adapter._load_expert_picks_for_alliance("1")
    assert scraper.board_force == [False, True]
    assert scraper.member_force == [False, True]


def test_legacy_scale_cache_without_timestamps_is_unknown_not_fresh(tmp_path):
    cache = tmp_path / "cache"
    scraper = PlaysportScraper(session=_FixtureSession({"scale": (403, "Forbidden")}), cache_dir=cache)
    scraper.get_cache_path("scale_1").write_text(
        json.dumps({"matches": [{"match_id": "legacy", "options": []}]}), encoding="utf-8")
    matches = scraper.fetch_scale_matches("1", force_refresh=True)
    assert matches[0]["_cached_at"] is None
    assert matches[0]["_cached_iso"] is None
    assert matches[0]["_cache_status"] == "UNKNOWN"
    assert matches[0]["_is_stale_cache"] is False


def test_scraper_exposes_observed_http_failure_separately_from_no_market(tmp_path):
    import time
    scraper = PlaysportScraper(session=_FixtureSession({"scale": (503, "Unavailable")}), cache_dir=tmp_path / "cache")
    scraper.write_cache("scale_4", {"matches": [{"match_id": "x", "away_team": "A", "home_team": "H", "options": []}]})
    cache_path = scraper.get_cache_path("scale_4")
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["cached_at"] = time.time() - 3600
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    matches = scraper.fetch_scale_matches("4", force_refresh=True)
    status = scraper.get_scale_source_status()["4"]
    assert matches[0]["_cache_status"] == "STALE_CACHE"
    assert status["source_status"] == "STALE_CACHE"
    assert status["failure_status"] == "HTTP_503"
    assert status["market_match_count"] == 0
    assert status["observed_at"] is not None
    assert status["attempted_at"] is not None


def test_recent_ttl_cache_is_fresh_and_placeholder_identity_is_not_recommendable():
    import time
    from datetime import datetime, timezone
    from core.bet_validation import assess_leg

    observed = datetime.now(timezone.utc).isoformat()
    class CachedScraper:
        def fetch_scale_matches(self, alliance_id, force_refresh=False):
            return [{"match_id": "1000", "canonical_event_id": "PREMIER_1000", "sport": "soccer",
                     "league": "PREMIER", "game_time": "2027-01-01", "start_time_utc": "2027-01-01T12:00:00Z",
                     "away_team": "客隊", "home_team": "主隊", "options": [{"market_type": "不讓分",
                     "side": "客", "odds": 2.2, "selection": "客勝"}],
                     "_cached_at": time.time() - 360, "_cached_iso": observed, "_cache_status": "CACHED",
                     "_identity_incomplete": True, "_identity_source": "unresolved",
                     "_identity_diagnostic": "placeholder_or_duplicate_team"}]

    leg = PlaysportOddsAdapter(scraper=CachedScraper()).get_taiwan_legs(["4"])[0]
    assert leg.odds_status == "FRESH"
    assert 5.9 <= leg.odds_age_minutes <= 6.2
    assert leg.eligible_for_parlay is False
    assert "EVENT_IDENTITY_INCOMPLETE" in assess_leg(leg)["reasons"]
    assert leg.signal_evidence["identity_diagnostic"] == "placeholder_or_duplicate_team"


def test_member_page_force_refresh_bypasses_valid_http_cache(tmp_path):
    session = _FixtureSession({"member/u1": "<html>fresh</html>"})
    scraper = PlaysportScraper(session=session, cache_dir=tmp_path / "cache")
    scraper.write_cache("member_pred_1_u1", {
        "html": "<html>old</html>",
        "source_url": "https://www.playsport.cc/member/u1/prediction?allianceid=1",
    })
    cached = scraper.fetch_member_prediction_page_result("u1", "1")
    assert cached["source_status"] == "CACHED"
    assert "old" in cached["html"]
    assert not session.calls

    refreshed = scraper.fetch_member_prediction_page_result("u1", "1", force_refresh=True)
    assert refreshed["source_status"] == "LIVE"
    assert "fresh" in refreshed["html"]
    assert len(session.calls) == 1
