"""Offline regression tests for multi-sport result normalization and identity."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from core.settlement_engine import SettlementEngine
from core.identity.team_alias import GLOBAL_TEAM_REGISTRY
from core.identity.team_alias import CanonicalTeam
from integrations.results.espn import parse_espn_event
from integrations.results.official_asian_baseball import parse_kbo_scoreboard, parse_npb_scoreboard
from integrations.results.cpbl import parse_cpbl_game_page, parse_cpbl_schedule_page


FIXTURE = Path(__file__).parent / "fixtures" / "results" / "multisport_source_samples.json"


def _samples():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["espn_samples"]


def test_epl_normalizes_provider_order_and_result():
    sample = next(s for s in _samples() if s["league"] == "PREMIER")
    result = parse_espn_event(sample["event"], "soccer", "PREMIER", source_url=sample["source_url"])
    assert result.status == "FINAL"
    assert result.away_score == 1
    assert result.home_score == 3
    assert result.away_provider_team_id == "393"
    assert result.home_provider_team_id == "384"
    assert result.soccer_regulation_away == 1
    assert result.soccer_regulation_home == 3
    assert result.provider == "ESPN_PUBLIC_SCOREBOARD"


def test_ucl_aet_regulation_excludes_extra_time_goal():
    sample = next(s for s in _samples() if s["event"]["id"] == "633241")
    result = parse_espn_event(sample["event"], "soccer", "CHAMPIONS")
    assert result.status == "FINAL"
    assert (result.away_score, result.home_score) == (3, 2)  # final including extra time
    assert (result.soccer_regulation_away, result.soccer_regulation_home) == (3, 1)


def test_ucl_penalty_events_are_excluded_from_regulation():
    sample = next(s for s in _samples() if s["event"]["id"] == "700722")
    result = parse_espn_event(sample["event"], "soccer", "CHAMPIONS")
    assert result.status == "FINAL"
    assert "STATUS_FINAL_PEN" in result.provider_status
    assert "FT-Pens" in result.provider_status
    assert (result.soccer_regulation_away, result.soccer_regulation_home) == (1, 1)


def test_missing_score_and_identity_become_unresolved():
    sample = next(s for s in _samples() if s["league"] == "PREMIER")
    event = json.loads(json.dumps(sample["event"]))
    event["competitions"][0]["competitors"][0]["score"] = None
    result = parse_espn_event(event, "soccer", "PREMIER")
    assert result.status == "UNRESOLVED"
    assert result.away_score is None or result.home_score is None
    assert result.unresolved_reason


def test_in_progress_and_postponed_states_are_not_finalized():
    sample = next(s for s in _samples() if s["league"] == "PREMIER")
    event = json.loads(json.dumps(sample["event"]))
    event["status"]["type"] = {"name": "STATUS_POSTPONED", "state": "pre", "completed": False}
    event["competitions"][0]["status"] = event["status"]
    result = parse_espn_event(event, "soccer", "PREMIER")
    assert result.status == "PENDING"
    assert result.away_score == 1  # source facts retained, but not settled as final


def test_source_id_is_authoritative_and_never_falls_back_on_miss():
    games = [
        {"provider": "ESPN_PUBLIC_SCOREBOARD", "provider_event_id": "one", "sport": "baseball", "league": "MLB"},
        {"provider": "ESPN_PUBLIC_SCOREBOARD", "provider_event_id": "two", "sport": "baseball", "league": "MLB"},
    ]
    snap = {"source_game_id": "two", "sport": "baseball", "league": "MLB"}
    assert SettlementEngine.match_result_game(snap, games) is games[1]
    snap["source_game_id"] = "missing"
    assert SettlementEngine.match_result_game(snap, games) is None


def test_complete_identity_match_requires_unique_aware_time():
    snap = {
        "sport": "soccer", "league": "PREMIER", "away_team": "Nottingham Forest",
        "home_team": "Crystal Palace", "event_start": "2026-10-11T13:00:00Z",
    }
    game = {
        "sport": "soccer", "league": "PREMIER", "away_team": "Nottingham Forest",
        "home_team": "Crystal Palace", "start_time_utc": "2026-10-11T13:00:00+00:00",
    }
    assert SettlementEngine.match_result_game(snap, [game]) is game
    assert SettlementEngine.match_result_game(snap, [game, dict(game)]) is None
    assert SettlementEngine.match_result_game({**snap, "event_start": "unknown"}, [game]) is None


def test_source_id_match_rejects_conflicting_known_teams():
    snap = {
        "source_game_id": "401879266", "sport": "soccer", "league": "PREMIER",
        "away_team": "Manchester City", "home_team": "Crystal Palace",
        "event_start": "2026-10-11T13:00:00Z",
    }
    game = {
        "provider": "ESPN_PUBLIC_SCOREBOARD", "provider_event_id": "401879266",
        "sport": "soccer", "league": "PREMIER", "away_team": "Nottingham Forest",
        "home_team": "Crystal Palace", "start_time_utc": "2026-10-11T13:00:00Z",
    }
    assert SettlementEngine.match_result_game(snap, [game]) is None


def test_asian_baseball_date_only_match_is_scoped_to_local_date_and_unique(monkeypatch):
    # Use isolated names so this test does not depend on the root registry's
    # rollout timing for the NPB team list.
    teams = {
        "away": CanonicalTeam("NPB_TEST_A", "baseball", "NPB", "A", "NPB Away Test", "A客隊", "A客隊"),
        "home": CanonicalTeam("NPB_TEST_H", "baseball", "NPB", "H", "NPB Home Test", "H主隊", "H主隊"),
    }
    original_resolve = GLOBAL_TEAM_REGISTRY.resolve
    def resolve(name, sport=None, league=None, playsport_team_id=None):
        if name in {"NPB Away Test", "A客隊"}: return teams["away"]
        if name in {"NPB Home Test", "H主隊"}: return teams["home"]
        return original_resolve(name, sport=sport, league=league, playsport_team_id=playsport_team_id)
    monkeypatch.setattr(GLOBAL_TEAM_REGISTRY, "resolve", resolve)
    snap = {
        "sport": "baseball", "league": "NPB", "away_team": "A客隊", "home_team": "H主隊",
        "event_start": "2026-09-12T16:00:00Z",  # 2026-09-13 in Tokyo
    }
    game = {
        "sport": "baseball", "league": "NPB", "away_team": "NPB Away Test", "home_team": "NPB Home Test",
        "event_date_local": "2026-09-13", "start_time_utc": None,
    }
    assert SettlementEngine.match_result_game(snap, [game]) is game
    assert SettlementEngine.match_result_game(snap, [game, dict(game)]) is None


def test_unknown_rule_never_defaults_to_mlb():
    engine = SettlementEngine.__new__(SettlementEngine)
    result = engine.evaluate_leg_settlement("不讓分", "客勝", None, 2, 1)
    assert result.status == "UNRESOLVED"


def test_npb_official_day_page_uses_stable_game_id_and_home_away_roles():
    html = '''<html><title>Sunday, September 13, 2026 (Scores)</title><a class="link_box" href="/bis/eng/2026/games/s2026091301434.html"><div class="unit"><div class="team_left"><div class="team_name">Yakult</div><div class="score_text">3</div></div><div class="team_right"><div class="score_text">1</div><div class="team_name">Hiroshima</div></div></div></a></html>'''
    games = parse_npb_scoreboard(html, "20260913", "https://npb.jp/bis/eng/2026/games/gm20260913.html")
    assert len(games) == 1
    assert games[0].provider_event_id == "s2026091301434"
    assert (games[0].away_team, games[0].home_team) == ("Hiroshima", "Yakult")
    assert (games[0].away_score, games[0].home_score) == (1, 3)
    assert games[0].status == "FINAL"


def test_kbo_official_scoreboard_preserves_state_and_aware_start():
    html = '''<div class="scoreboard_time"><span class="team_name">KT</span><span class="team_score">16</span><span class="timer">FINAL</span><span class="team_score">4</span><span class="team_name">LG</span></div><div class="scoreboard_local"><span class="local_time">JAMSIL 19:00</span></div>'''
    games = parse_kbo_scoreboard(html, "2026-08-20", "https://eng.koreabaseball.com/Schedule/Scoreboard.aspx?searchDate=2026-08-20")
    assert len(games) == 1
    assert (games[0].away_team, games[0].home_team) == ("KT", "LG")
    assert (games[0].away_score, games[0].home_score) == (16, 4)
    assert games[0].status == "FINAL"
    assert games[0].start_time_utc == "2026-08-20T10:00:00Z"


def test_kbo_missing_score_stays_pending():
    html = '''<div class="scoreboard_time"><span class="team_name">KT</span><span class="team_score"></span><span class="timer">SCHEDULED</span><span class="team_score"></span><span class="team_name">LG</span></div>'''
    game = parse_kbo_scoreboard(html, "2026-08-20", "https://example.invalid")[0]
    assert game.status == "PENDING"
    assert game.away_score is None and game.home_score is None


def test_cpbl_official_game_page_uses_structured_home_away_and_score_evidence():
    event = {
        "@type": "SportsEvent", "url": "https://stats.cpbl.com.tw/schedule/2026-A-354",
        "startDate": "2026-09-26T17:05:00", "eventStatus": "https://schema.org/EventScheduled",
        "homeTeam": {"@type": "SportsTeam", "name": "富邦悍將"},
        "awayTeam": {"@type": "SportsTeam", "name": "中信兄弟"},
    }
    html = f'''<html><head><title>中信兄弟 7:3 富邦悍將 | 中華職棒進階數據</title><meta name="description" content="一軍例行賽 | 2026/9/26 | 新莊 | 勝投: pitcher | 敗投: pitcher"/><script type="application/ld+json">{json.dumps(event, ensure_ascii=False)}</script></head></html>'''
    result = parse_cpbl_game_page(html, "2026-A-354", event["url"])
    assert result.status == "FINAL"
    assert (result.away_team, result.home_team) == ("中信兄弟", "富邦悍將")
    assert (result.away_score, result.home_score) == (7, 3)
    assert result.start_time_utc == "2026-09-26T09:05:00Z"
    assert result.provider_event_id == "2026-A-354"


def test_cpbl_daily_feed_filters_official_ids_by_local_date():
    event = {
        "@type": "SportsEvent", "url": "https://stats.cpbl.com.tw/schedule/2026-A-354",
        "startDate": "2026-09-26T17:05:00", "homeTeam": {"name": "富邦悍將"}, "awayTeam": {"name": "中信兄弟"},
    }
    html = f'<script type="application/ld+json">{json.dumps({"@type":"ItemList","itemListElement":[{"@type":"ListItem","item":event}]}, ensure_ascii=False)}</script>'
    assert parse_cpbl_schedule_page(html, "2026-09-26") == ["2026-A-354"]
    assert parse_cpbl_schedule_page(html, "2026-09-27") == []


def test_settlement_dispatch_preserves_a_real_loss_and_provider_provenance():
    from scripts.settle_results import settle_snapshot_results

    sample = next(s for s in _samples() if s["league"] == "PREMIER")
    game = parse_espn_event(sample["event"], "soccer", "PREMIER", source_url=sample["source_url"]).to_dict()

    class Watcher:
        def get_closing_odds(self, **kwargs): return None, None

    class FakeEngine:
        odds_watcher = Watcher()
        settled = []
        def fetch_results(self, sport, league, target_date):
            return [game] if target_date == "2026-10-11" else []
        match_result_game = staticmethod(SettlementEngine.match_result_game)
        evaluate_leg_settlement = SettlementEngine.evaluate_leg_settlement
        def settle_single_prediction_direct(self, **kwargs): self.settled.append(kwargs)

    engine = FakeEngine()
    snap = {
        "snapshot_id": "fixture-loss", "sport": "soccer", "league": "PREMIER",
        "event_start": "2026-10-11T13:00:00Z", "away_team": "諾丁漢森林", "home_team": "水晶宮",
        "market": "不讓分", "selection": "客勝", "side": "客", "is_settled": False,
    }
    counts = settle_snapshot_results(engine, [snap])
    assert counts["games"] == 1
    assert counts["settled"] == 1
    assert counts["coverage"]["soccer/PREMIER"]["matched_snapshots"] == 1
    assert counts["coverage"]["soccer/PREMIER"]["unique_matches"] == 1
    assert engine.settled[0]["settlement_status"] == "LOST"
    assert engine.settled[0]["actual_outcome"] is False
    assert engine.settled[0]["result_source"] == "ESPN_PUBLIC_SCOREBOARD"
    assert "source=https://site.api.espn.com" in engine.settled[0]["settlement_reason"]


def test_settlement_reports_multisport_unmatched_snapshot_and_writes_additive_audit(tmp_path):
    from scripts.settle_results import settle_snapshot_results, write_settlement_audit_report

    class FakeEngine:
        def fetch_results(self, sport, league, target_date):
            return []

    snapshot = {"snapshot_id": "unmatched-1", "sport": "soccer", "league": "PREMIER",
                "event_start": "2026-10-11T13:00:00Z", "away_team": "Away", "home_team": "Home",
                "source_game_id": "source-1", "is_settled": False}
    result = settle_snapshot_results(FakeEngine(), [snapshot])
    assert result["games"] == 0
    assert result["coverage"]["soccer/PREMIER"]["snapshots"] == 1
    assert result["coverage"]["soccer/PREMIER"]["unmatched_snapshots"] == 1
    assert result["unmatched_observations"][0]["reason"] == "NO_RESULTS_AVAILABLE"
    path = write_settlement_audit_report(result, tmp_path / "audit.json")
    assert '"unmatched-1"' in path.read_text(encoding="utf-8")


def test_settlement_audits_missing_sport_and_league_metadata_without_provider_fetch():
    from scripts.settle_results import settle_snapshot_results

    class NoFetchEngine:
        def fetch_results(self, *args, **kwargs):
            raise AssertionError("provider must not be called without sport/league metadata")

    result = settle_snapshot_results(NoFetchEngine(), [{"snapshot_id": "missing-scope", "is_settled": False}])
    coverage = result["coverage"]["unknown/unknown"]
    assert coverage["fetch_status"] == "NOT_ATTEMPTED"
    assert coverage["unmatched_snapshots"] == 1
    assert coverage["unmatched_reason_counts"]["MISSING_SPORT_OR_LEAGUE_METADATA"] == 1
    assert result["unmatched_observations"][0]["snapshot_id"] == "missing-scope"
    assert result["unmatched_observation_sample_limit"] == 100


def test_unknown_result_league_is_audited_without_calling_provider():
    from scripts.settle_results import settle_snapshot_results

    class CoverageEngine:
        calls = 0

        @staticmethod
        def supported_result_coverage():
            return SettlementEngine.supported_result_coverage()

        def fetch_results(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("unsupported league must not reach the provider")

    snapshot = {
        "snapshot_id": "unknown-soccer-league", "sport": "soccer",
        "league": "UNKNOWN_哥倫比亞乙級聯賽", "event_start": "2026-10-10T20:00:00Z",
        "away_team": "Away", "home_team": "Home", "is_settled": False,
    }
    engine = CoverageEngine()

    result = settle_snapshot_results(engine, [snapshot], now="2026-10-13T12:00:00Z")

    coverage = result["coverage"]["soccer/UNKNOWN_哥倫比亞乙級聯賽"]
    assert engine.calls == 0
    assert coverage["status"] == "UNSUPPORTED"
    assert coverage["fetch_status"] == "NOT_ATTEMPTED"
    assert coverage["unmatched_snapshots"] == 1
    assert coverage["coverage_reason"] == "No declared result source coverage"
    assert result["unresolved"] == 1
    assert result["unmatched_observations"][0]["reason"] == "RESULT_SOURCE_UNSUPPORTED"


def test_schedule_only_league_is_not_mistaken_for_result_feed_support():
    from scripts.settle_results import settle_snapshot_results

    class CoverageEngine:
        calls = 0

        @staticmethod
        def supported_result_coverage():
            return SettlementEngine.supported_result_coverage()

        def fetch_results(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("schedule-only coverage is not result-feed support")

    engine = CoverageEngine()
    result = settle_snapshot_results(engine, [{
        "snapshot_id": "nhl-unverified-feed", "sport": "hockey", "league": "NHL",
        "event_start": "2026-10-10T20:00:00Z", "is_settled": False,
    }], now="2026-10-13T12:00:00Z")

    assert engine.calls == 0
    assert result["coverage"]["hockey/NHL"]["status"] == "UNSUPPORTED"
    assert result["coverage"]["hockey/NHL"]["fetch_status"] == "NOT_ATTEMPTED"


def test_broken_coverage_metadata_fails_explicitly_instead_of_skipping():
    from scripts.settle_results import settle_snapshot_results

    class BrokenCoverageEngine:
        @staticmethod
        def supported_result_coverage():
            raise OSError("coverage file unavailable")

    snapshot = {"sport": "soccer", "league": "UNKNOWN", "event_start": "2026-10-10T20:00:00Z"}
    with pytest.raises(RuntimeError, match="Result coverage metadata failed"):
        settle_snapshot_results(BrokenCoverageEngine(), [snapshot], now="2026-10-13T12:00:00Z")
