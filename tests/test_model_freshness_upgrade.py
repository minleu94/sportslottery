import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations.common.models import ModelQualityLabel, TaiwanLeg
from integrations.models.external import live_mlb_elo
from integrations.models.external.live_mlb_elo import LiveMLBEloAdapter
from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter
from scripts.update_mlb_elo import update_mlb_elo


class MockStatsClient:
    def __init__(self, games):
        self.games = games
        self.calls = []

    def fetch_games(self, start_date, end_date):
        self.calls.append((start_date, end_date))
        return self.games


def game(pk, time, away, home, away_runs=2, home_runs=3):
    return {
        "gamePk": pk,
        "gameDate": time,
        "status": {"abstractGameState": "Final", "codedGameState": "F"},
        "teams": {
            "away": {"team": {"name": away}},
            "home": {"team": {"name": home}},
        },
        "linescore": {"teams": {"away": {"runs": away_runs}, "home": {"runs": home_runs}}},
    }


def test_mlb_missing_state_is_unknown_experimental_and_pitcher_adjustment_is_false(tmp_path):
    adapter = LiveMLBEloAdapter(tmp_path / "missing.json")
    leg = TaiwanLeg(event_id="e1", sport="baseball", league="MLB", market="不讓分",
                    selection="道奇主勝", taiwan_odds=1.9, side="主", home_team="Los Angeles Dodgers",
                    away_team="New York Yankees", start_time_utc="2027-04-01T20:00:00Z")
    signal = adapter.evaluate_leg(leg)
    assert signal is not None
    assert signal.quality_label == ModelQualityLabel.MODEL_EXPERIMENTAL
    assert signal.freshness_status == "UNKNOWN"
    assert signal.data_as_of is None
    assert signal.metadata["starting_pitcher_adjustment_used"] is False
    assert signal.metadata["empirically_calibrated"] is False


def test_mlb_official_games_are_sorted_deduped_and_doubleheaders_preserved(tmp_path):
    state = tmp_path / "elo.json"
    games = [
        game(9002, "2026-07-01T22:00:00Z", "New York Yankees", "Boston Red Sox", 1, 4),
        game(9001, "2026-07-01T16:00:00Z", "New York Yankees", "Boston Red Sox", 5, 2),
    ]
    client = MockStatsClient(games)
    out = update_mlb_elo(date(2026, 7, 1), date(2026, 7, 1), state_file=state, client=client)
    assert out["updated_games"] == 2
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["processed_game_pks"] == ["9001", "9002"]
    assert [item["game_pk"] for item in saved["history"]] == ["9001", "9002"]
    first_ratings = saved["ratings"]
    retry = update_mlb_elo(date(2026, 7, 1), date(2026, 7, 1), state_file=state, client=client)
    assert retry["updated_games"] == 0
    assert json.loads(state.read_text(encoding="utf-8"))["ratings"] == first_ratings


def test_mlb_future_state_does_not_feed_earlier_prediction_and_unknown_team_fails(tmp_path):
    state = tmp_path / "elo.json"
    update_mlb_elo(date(2026, 7, 1), date(2026, 7, 1), state_file=state,
                   client=MockStatsClient([game(1, "2026-07-01T22:00:00Z", "New York Yankees", "Boston Red Sox")]))
    adapter = LiveMLBEloAdapter(state)
    leg = TaiwanLeg(event_id="early", sport="baseball", league="MLB", market="不讓分",
                    selection="道奇主勝", taiwan_odds=1.9, side="主", home_team="Los Angeles Dodgers",
                    away_team="New York Yankees", start_time_utc="2026-07-01T20:00:00Z")
    assert adapter.evaluate_leg(leg) is None
    before = state.read_bytes()
    with pytest.raises(ValueError, match="無法映射"):
        update_mlb_elo(date(2026, 7, 2), date(2026, 7, 2), state_file=state,
                       client=MockStatsClient([game(2, "2026-07-02T20:00:00Z", "Mystery Club", "Boston Red Sox")]))
    assert state.read_bytes() == before


def test_mlb_failed_atomic_save_does_not_claim_success(tmp_path, monkeypatch):
    state = tmp_path / "elo.json"
    def fail_save(self):
        raise OSError("disk unavailable")
    monkeypatch.setattr(LiveMLBEloAdapter, "_save_state", fail_save)
    with pytest.raises(OSError, match="disk unavailable"):
        update_mlb_elo(date(2026, 7, 1), date(2026, 7, 1), state_file=state,
                       client=MockStatsClient([game(1, "2026-07-01T22:00:00Z", "New York Yankees", "Boston Red Sox")]))
    assert not state.exists()


def test_mlb_legacy_state_is_preserved_and_old_canonical_aliases_migrate(tmp_path):
    state = tmp_path / "elo.json"
    state.write_text(json.dumps({"ratings": {"MLB_AZ": 1512.5}, "history": [{"legacy": True}],
                                 "old_custom_field": "preserve-me"}), encoding="utf-8")
    adapter = LiveMLBEloAdapter(state)
    assert adapter.get_rating("MLB_ARI") == 1512.5
    assert adapter._history == [{"legacy": True}]
    adapter.apply_official_games([game(71, "2026-07-01T18:00:00Z", "New York Yankees", "Boston Red Sox")])
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["old_custom_field"] == "preserve-me"
    assert saved["history"][0] == {"legacy": True}
    assert saved["ratings"]["MLB_ARI"] == 1512.5


@pytest.mark.parametrize("bad_score", [1.9, True])
def test_mlb_official_scores_must_be_raw_nonnegative_integers(tmp_path, bad_score):
    state = tmp_path / "elo.json"
    with pytest.raises(ValueError, match="原始非負整數"):
        update_mlb_elo(date(2026, 7, 1), date(2026, 7, 1), state_file=state,
                       client=MockStatsClient([game(81, "2026-07-01T18:00:00Z",
                                                      "New York Yankees", "Boston Red Sox",
                                                      away_runs=bad_score)]))
    assert not state.exists()


def test_mlb_rejects_new_results_older_than_existing_data_as_of(tmp_path):
    state = tmp_path / "elo.json"
    update_mlb_elo(date(2026, 7, 2), date(2026, 7, 2), state_file=state,
                   client=MockStatsClient([game(82, "2026-07-02T20:00:00Z",
                                                  "New York Yankees", "Boston Red Sox")]))
    before = state.read_bytes()
    with pytest.raises(ValueError, match="完整重播賽季"):
        update_mlb_elo(date(2026, 7, 1), date(2026, 7, 1), state_file=state,
                       client=MockStatsClient([game(83, "2026-07-01T20:00:00Z",
                                                      "New York Yankees", "Boston Red Sox")]))
    assert state.read_bytes() == before


def test_mlb_mixed_processed_game_ids_have_a_stable_sort_order(tmp_path):
    state = tmp_path / "elo.json"
    state.write_text(json.dumps({"processed_game_pks": ["club-game-x", "10", "9"]}), encoding="utf-8")
    adapter = LiveMLBEloAdapter(state)
    adapter.apply_official_games([game(11, "2026-07-01T18:00:00Z", "New York Yankees", "Boston Red Sox")])
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["processed_game_pks"] == ["9", "10", "11", "club-game-x"]


def test_mlb_partial_invalid_state_resets_neutral_and_update_refuses_overwrite(tmp_path):
    state = tmp_path / "elo.json"
    original = json.dumps({"ratings": {"MLB_ARI": 1600.0, "MLB_BOS": "not-a-rating"},
                           "history": [{"existing": "must not be partly loaded"}],
                           "history_count": 25, "processed_game_pks": ["90"],
                           "data_as_of": "2026-07-01T18:00:00+00:00", "source": "legacy"}).encode()
    state.write_bytes(original)
    adapter = LiveMLBEloAdapter(state)
    assert adapter.get_rating("MLB_ARI") == 1500.0
    assert adapter._history == []
    assert adapter._history_count == 0
    assert adapter._processed_game_pks == set()
    assert adapter.data_as_of is None
    assert adapter._has_state is False
    assert adapter._load_error

    with pytest.raises(ValueError, match="備份並人工修復"):
        update_mlb_elo(date(2026, 7, 2), date(2026, 7, 2), state_file=state,
                       client=MockStatsClient([game(91, "2026-07-02T20:00:00Z",
                                                      "New York Yankees", "Boston Red Sox")]))
    assert state.read_bytes() == original


def football_matches(count=64):
    start = date(2024, 1, 1)
    teams = ("Arsenal", "Chelsea", "Liverpool", "Manchester City")
    records = []
    for i in range(count):
        day = start + timedelta(days=i * 3)
        records.append({"date": day.isoformat(), "home_team": teams[i % 4], "away_team": teams[(i + 1) % 4],
                        "home_goals": i % 4, "away_goals": (i + 1) % 3})
    return records


class FakeDixonColes:
    fit_calls = 0
    def __init__(self, goals_home, goals_away, teams_home, teams_away, weights=None):
        self.teams = set(teams_home) | set(teams_away)
        self.weights = weights
    def fit(self):
        FakeDixonColes.fit_calls += 1


def write_match_file(path: Path, matches):
    path.mkdir(parents=True, exist_ok=True)
    (path / "real_matches_eng.1.json").write_text(json.dumps({"matches": matches, "downloaded_at": "source-time"}), encoding="utf-8")


def test_penaltyblog_cache_cutoff_file_hash_and_official_weight_base_date(tmp_path, monkeypatch):
    import integrations.models.external.penaltyblog_dixon_coles as module
    FakeDixonColes.fit_calls = 0
    base_weights = []
    monkeypatch.setattr(module.pb.models, "DixonColesGoalModel", FakeDixonColes)
    monkeypatch.setattr(module.pb.models, "dixon_coles_weights",
                        lambda dates, xi, base_date=None: base_weights.append(base_date) or [1.0] * len(dates))
    write_match_file(tmp_path, football_matches())
    adapter = PenaltyblogDixonColesAdapter(cache_dir=str(tmp_path))
    model1, prov1 = adapter._get_or_fit_model("eng.1", "2024-07-01", "Arsenal", "Chelsea")
    model2, prov2 = adapter._get_or_fit_model("eng.1", "2024-07-01", "Liverpool", "Manchester City")
    assert model1 is model2
    assert FakeDixonColes.fit_calls == 1
    assert base_weights == [date(2024, 7, 1)]
    assert prov1.point_in_time_verified is True
    assert prov1.latest_match_date < "2024-07-01"
    # Source file content changes invalidate the cache even at the same cutoff.
    changed = football_matches() + [{"date": "2024-06-30", "home_team": "Arsenal", "away_team": "Chelsea", "home_goals": 2, "away_goals": 0}]
    write_match_file(tmp_path, changed)
    adapter._get_or_fit_model("eng.1", "2024-07-01", "Arsenal", "Chelsea")
    assert FakeDixonColes.fit_calls == 2


def test_penaltyblog_model_cache_is_bounded_lru(tmp_path, monkeypatch):
    import integrations.models.external.penaltyblog_dixon_coles as module
    FakeDixonColes.fit_calls = 0
    monkeypatch.setattr(module.pb.models, "DixonColesGoalModel", FakeDixonColes)
    monkeypatch.setattr(module.pb.models, "dixon_coles_weights",
                        lambda dates, xi, base_date=None: [1.0] * len(dates))
    write_match_file(tmp_path, football_matches())
    adapter = PenaltyblogDixonColesAdapter(cache_dir=str(tmp_path))
    adapter.MODEL_CACHE_MAXSIZE = 2
    adapter._get_or_fit_model("eng.1", "2025-07-01", "Arsenal", "Chelsea")
    adapter._get_or_fit_model("eng.1", "2025-07-02", "Arsenal", "Chelsea")
    # A hit refreshes recency, so this cutoff becomes the one to evict.
    adapter._get_or_fit_model("eng.1", "2025-07-01", "Liverpool", "Manchester City")
    adapter._get_or_fit_model("eng.1", "2025-07-03", "Arsenal", "Chelsea")
    assert len(adapter._model_cache) == 2
    assert all(key[1] != "2025-07-02" for key in adapter._model_cache)
    fits_before = FakeDixonColes.fit_calls
    adapter._get_or_fit_model("eng.1", "2025-07-02", "Arsenal", "Chelsea")
    assert FakeDixonColes.fit_calls == fits_before + 1
    assert len(adapter._model_cache) == 2


@pytest.mark.parametrize("bad_score", [1.9, True, -1])
def test_penaltyblog_invalid_raw_scores_are_excluded_and_mark_provenance(tmp_path, monkeypatch, bad_score):
    import integrations.models.external.penaltyblog_dixon_coles as module
    FakeDixonColes.fit_calls = 0
    trained = []
    monkeypatch.setattr(module.pb.models, "DixonColesGoalModel", FakeDixonColes)
    monkeypatch.setattr(module.pb.models, "dixon_coles_weights",
                        lambda dates, xi, base_date=None: trained.extend(dates) or [1.0] * len(dates))
    matches = football_matches() + [
        {"date": "2024-06-28", "home_team": "Arsenal", "away_team": "Chelsea",
         "home_goals": bad_score, "away_goals": 0},
    ]
    write_match_file(tmp_path, matches)
    adapter = PenaltyblogDixonColesAdapter(cache_dir=str(tmp_path))
    model, prov = adapter._get_or_fit_model("eng.1", "2024-07-01", "Arsenal", "Chelsea")
    assert model is not None
    assert prov.invalid_score_records == 1
    assert prov.point_in_time_verified is False
    assert prov.freshness_status == "UNKNOWN"
    assert len(trained) == prov.match_count
    assert date(2024, 6, 28) not in trained


def test_penaltyblog_unknown_date_is_not_point_in_time_and_future_rows_are_excluded(tmp_path, monkeypatch):
    import integrations.models.external.penaltyblog_dixon_coles as module
    dates_received = []
    monkeypatch.setattr(module.pb.models, "DixonColesGoalModel", FakeDixonColes)
    monkeypatch.setattr(module.pb.models, "dixon_coles_weights",
                        lambda dates, xi, base_date=None: dates_received.extend(dates) or [1.0] * len(dates))
    matches = football_matches() + [{"date": "2027-01-01", "home_team": "Arsenal", "away_team": "Chelsea", "home_goals": 3, "away_goals": 0}]
    write_match_file(tmp_path, matches)
    adapter = PenaltyblogDixonColesAdapter(cache_dir=str(tmp_path))
    _, unknown = adapter._get_or_fit_model("eng.1", None, "Arsenal", "Chelsea")
    assert unknown.point_in_time_verified is False
    assert unknown.freshness_status == "UNKNOWN"
    dates_received.clear()
    adapter2 = PenaltyblogDixonColesAdapter(cache_dir=str(tmp_path))
    _, known = adapter2._get_or_fit_model("eng.1", "2024-07-01", "Arsenal", "Chelsea")
    assert known.point_in_time_verified is True
    assert all(d < date(2024, 7, 1) for d in dates_received)


def test_penaltyblog_spread_is_not_derived_from_1x2_estimate(tmp_path):
    adapter = PenaltyblogDixonColesAdapter(cache_dir=str(tmp_path))
    leg = TaiwanLeg(event_id="e", sport="soccer", league="英超", market="讓分",
                    selection="主隊讓分", taiwan_odds=1.9, side="主", home_team="Arsenal",
                    away_team="Chelsea", line="-0.5", start_time_utc="2024-07-01T20:00:00Z")
    assert adapter.evaluate_leg(leg) is None
