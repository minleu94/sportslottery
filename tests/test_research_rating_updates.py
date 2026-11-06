from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core.research_rating_updates import ResearchRatingUpdater
from integrations.models.external.asian_baseball_model import AsianBaseballModel
from integrations.models.external.nba_elo_engine import NBAEloEngine
from integrations.results.models import ResultGame


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class FakeESPN:
    def __init__(self, nba_game=None, fail_nba=False):
        self.nba_game = nba_game
        self.fail_nba = fail_nba

    def fetch(self, sport, league, date):
        if league == "NBA" and self.fail_nba:
            raise RuntimeError("offline fixture failure")
        if (league == "NBA" and self.nba_game
                and date == self.nba_game.event_date_local.replace("-", "")):
            return [self.nba_game]
        return []


class FakeAsian:
    def __init__(self, npb_game=None):
        self.npb_game = npb_game

    def fetch(self, league, date):
        if league == "NPB" and self.npb_game and date == self.npb_game.event_date_local:
            return [self.npb_game]
        return []


class FakeCPBL:
    def fetch(self, date):
        return []


def _scoreboard_game(*, provider, league, event_id, event_date, away, home,
                     away_score, home_score, observed_at, start_time=None):
    return ResultGame(
        provider=provider, provider_event_id=event_id, sport="basketball" if league == "NBA" else "baseball",
        league=league, event_date_local=event_date, start_time_utc=start_time,
        away_team=away, home_team=home, away_provider_team_id=None, home_provider_team_id=None,
        away_score=away_score, home_score=home_score, status="FINAL", provider_status="STATUS_FINAL",
        official_completion_status="REGULATION_COMPLETED", source_url=f"https://results.test/{event_id}",
        observed_at_utc=observed_at,
    )


def test_isolated_rating_updates_are_deduplicated_and_emit_pit_evidence(tmp_path):
    now = datetime.now(timezone.utc)
    clock = Clock(now)
    nba_date = (now.astimezone(ZoneInfo("America/New_York")).date() - timedelta(days=1)).isoformat()
    nba_start = (now - timedelta(hours=30)).isoformat()
    observed = (now - timedelta(minutes=5)).isoformat()
    nba_game = _scoreboard_game(
        provider="ESPN_PUBLIC_SCOREBOARD", league="NBA", event_id="nba-fixture-1", event_date=nba_date,
        away="Los Angeles Lakers", home="Boston Celtics", away_score=101, home_score=110,
        observed_at=observed, start_time=nba_start,
    )
    npb_date = (now.astimezone(ZoneInfo("Asia/Tokyo")).date() - timedelta(days=1)).isoformat()
    npb_game = _scoreboard_game(
        provider="NPB_OFFICIAL", league="NPB", event_id="npb-fixture-1", event_date=npb_date,
        away="Hanshin Tigers", home="Yomiuri Giants", away_score=2, home_score=3,
        observed_at=observed,
    )

    data_root = tmp_path / "research"
    stage = tmp_path / "run" / "data"
    stage.mkdir(parents=True)
    updater = ResearchRatingUpdater(data_root, clock, espn_provider=FakeESPN(nba_game),
                                    asian_provider=FakeAsian(npb_game), cpbl_provider=FakeCPBL())
    result = updater.run({"refresh_interval_hours": 12, "lookback_days": 3}, stage)

    assert result["status"] == "UPDATED_OR_NO_NEW_FINALS"
    nba_path = data_root / "model_state" / "nba_elo_engine.json"
    asian_path = data_root / "model_state" / "asian_baseball_model.json"
    assert nba_path.exists() and asian_path.exists()

    nba = NBAEloEngine(state_file=nba_path)
    assert nba.processed_games_count == 1
    leg_start = (now + timedelta(hours=4)).isoformat()
    from integrations.common.models import TaiwanLeg
    leg = TaiwanLeg(event_id="future-nba", sport="basketball", league="NBA", home_team="Boston Celtics",
                    away_team="Los Angeles Lakers", market="不讓分", selection="主勝", side="主",
                    taiwan_odds=1.8, start_time_utc=leg_start)
    signal = nba.evaluate_leg(leg)
    assert signal is not None
    assert signal.data_as_of == observed
    assert signal.freshness_status == "FRESH"
    assert signal.metadata["point_in_time_status"] == "VALID"
    assert signal.metadata["data_source"] == "ESPN_PUBLIC_SCOREBOARD"

    asian = AsianBaseballModel(state_file=asian_path)
    assert asian.processed_games_count == 1
    assert asian.data_as_of_by_league["NPB"] == observed
    assert asian.processed_events

    old_ratings = dict(nba.elo_ratings)
    clock.now += timedelta(hours=13)
    duplicate = updater.run({"refresh_interval_hours": 12, "lookback_days": 3}, stage)
    assert duplicate["status"] == "UPDATED_OR_NO_NEW_FINALS"
    reloaded = NBAEloEngine(state_file=nba_path)
    assert reloaded.processed_games_count == 1
    assert reloaded.elo_ratings == old_ratings


def test_npb_day_only_final_does_not_get_an_invented_start_time(tmp_path):
    now = datetime.now(timezone.utc)
    day = (now.astimezone(ZoneInfo("Asia/Tokyo")).date() - timedelta(days=1)).isoformat()
    game = _scoreboard_game(provider="NPB_OFFICIAL", league="NPB", event_id="npb-day-only", event_date=day,
                            away="Hanshin Tigers", home="Yomiuri Giants", away_score=1, home_score=2,
                            observed_at=(now - timedelta(minutes=2)).isoformat())
    root = tmp_path / "research"
    stage = tmp_path / "run" / "data"
    stage.mkdir(parents=True)
    result = ResearchRatingUpdater(root, Clock(now), espn_provider=FakeESPN(),
                                   asian_provider=FakeAsian(game), cpbl_provider=FakeCPBL()).run(
                                       {"lookback_days": 3}, stage)
    state = AsianBaseballModel(state_file=root / "model_state" / "asian_baseball_model.json")
    saved = next(iter(state.processed_events.values()))
    assert result["status"] == "UPDATED_OR_NO_NEW_FINALS"
    assert saved["event_order"] == day
    assert "T" not in saved["event_order"]


def test_result_fetch_failure_preserves_existing_rating_state(tmp_path):
    now = datetime.now(timezone.utc)
    root = tmp_path / "research"
    path = root / "model_state" / "nba_elo_engine.json"
    path.parent.mkdir(parents=True)
    original = NBAEloEngine(state_file=path)
    original.elo_ratings["NBA_BOS"] = 1701.0
    original.save_state()
    before = path.read_bytes()
    stage = tmp_path / "run" / "data"
    stage.mkdir(parents=True)
    result = ResearchRatingUpdater(root, Clock(now), espn_provider=FakeESPN(fail_nba=True),
                                   asian_provider=FakeAsian(), cpbl_provider=FakeCPBL()).run(
                                       {"lookback_days": 1}, stage)
    assert result["status"] == "PARTIAL"
    assert path.read_bytes() == before


def test_unknown_teams_are_reported_and_do_not_create_default_ratings(tmp_path):
    now = datetime.now(timezone.utc)
    date = (now.astimezone(ZoneInfo("America/New_York")).date() - timedelta(days=1)).isoformat()
    game = _scoreboard_game(
        provider="ESPN_PUBLIC_SCOREBOARD", league="NBA", event_id="nba-unknown", event_date=date,
        away="Imaginary Team", home="Unlisted Club", away_score=90, home_score=95,
        observed_at=(now - timedelta(minutes=1)).isoformat(), start_time=(now - timedelta(hours=8)).isoformat(),
    )
    root = tmp_path / "research"
    stage = tmp_path / "run" / "data"
    stage.mkdir(parents=True)
    result = ResearchRatingUpdater(root, Clock(now), espn_provider=FakeESPN(game),
                                   asian_provider=FakeAsian(), cpbl_provider=FakeCPBL()).run(
                                       {"lookback_days": 2}, stage)
    assert result["status"] == "UPDATED_OR_NO_NEW_FINALS"
    report = result["models"]["nba_elo_engine"]["NBA"]
    assert report["updated_games"] == 0
    assert report["exclusion_counts"]["TEAM_IDENTITY_UNSUPPORTED"] == 1
    assert not (root / "model_state" / "nba_elo_engine.json").exists()
