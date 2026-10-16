"""Isolated provenance and market-support checks for ESPN local fallback models."""
import json
from datetime import datetime, timezone

import pytest

import integrations.models.espn_pythagorean_mlb as mlb_module
import integrations.models.espn_poisson_soccer as soccer_module
from integrations.common.models import TaiwanLeg
from integrations.models.espn_pythagorean_mlb import ESPNPythagoreanMLBModel
from integrations.models.espn_poisson_soccer import ESPNPoissonSoccerFallback


class _Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        self.headers = {}

    def get(self, url, timeout=10):
        self.calls.append(url)
        return _Response(self.payload)


class _FailedSession(_Session):
    def get(self, url, timeout=10):
        self.calls.append(url)
        return type("FailedResponse", (), {"status_code": 403})()


def _mlb_payload():
    entries = []
    for name, abbr, runs_for, runs_against in [
        ("Los Angeles Dodgers", "LAD", 700, 500),
        ("New York Yankees", "NYY", 650, 520),
    ]:
        entries.append({
            "team": {"displayName": name, "abbreviation": abbr},
            "stats": [
                {"name": "pointsFor", "value": runs_for},
                {"name": "pointsAgainst", "value": runs_against},
                {"name": "gamesPlayed", "value": 100},
                {"name": "winPercent", "value": 0.6},
            ],
        })
    return {"season": {"year": 2026}, "children": [{"standings": {"entries": entries}}]}


def _soccer_payload():
    entries = []
    for name, gf, ga in [("Arsenal", 60, 30), ("Chelsea", 50, 40)]:
        entries.append({
            "team": {"displayName": name},
            "stats": [
                {"name": "pointsFor", "value": gf},
                {"name": "pointsAgainst", "value": ga},
                {"name": "gamesPlayed", "value": 30},
                {"name": "winPercent", "value": 0.6},
            ],
        })
    return {"season": {"year": 2026}, "children": [{"standings": {"entries": entries}}]}


def _mlb_leg(**kwargs):
    values = dict(
        event_id="mlb-1", sport="baseball", league="MLB", market="不讓分",
        selection="Dodgers 主勝", taiwan_odds=1.9, side="主",
        away_team="New York Yankees", home_team="Los Angeles Dodgers",
        start_time_utc="2026-10-14T00:00:00+00:00",
    )
    values.update(kwargs)
    return TaiwanLeg(**values)


def _soccer_leg(**kwargs):
    values = dict(
        event_id="soccer-1", sport="soccer", league="英超", market="不讓分",
        selection="Arsenal 主勝", taiwan_odds=1.9, side="主",
        away_team="Chelsea", home_team="Arsenal", start_time_utc="2026-10-14T00:00:00+00:00",
    )
    values.update(kwargs)
    return TaiwanLeg(**values)


def test_legacy_cache_without_timestamp_is_unknown_and_past_event_is_reference_only(tmp_path):
    cache_file = tmp_path / "legacy_mlb.json"
    model = ESPNPythagoreanMLBModel(str(cache_file))
    model.session = _FailedSession(_mlb_payload())
    cache_file.write_text(json.dumps({"teams": model._parse_espn_standings(_mlb_payload())}), encoding="utf-8")
    leg = _mlb_leg(start_time_utc="2026-10-11T00:00:00+00:00")

    signal = model.evaluate_leg(leg)

    assert signal is not None
    assert signal.freshness_status == "UNKNOWN"
    assert signal.confidence == "REFERENCE_ONLY"
    assert signal.data_as_of is None
    assert signal.metadata["source_status"] == "UNKNOWN"
    assert signal.metadata["initialized"] is False
    assert signal.metadata["point_in_time_status"] == "REFERENCE_ONLY"


def test_soccer_unknown_cache_cannot_enter_fusion(tmp_path):
    cache_file = tmp_path / "espn_soccer_eng.1.json"
    cache_file.write_text(json.dumps({"teams": ESPNPoissonSoccerFallback(str(tmp_path))._parse_soccer_standings(_soccer_payload())}), encoding="utf-8")
    model = ESPNPoissonSoccerFallback(str(tmp_path))
    model.session = _FailedSession(_soccer_payload())

    signal = model.evaluate_leg(_soccer_leg())

    assert signal is not None
    assert signal.freshness_status == "UNKNOWN"
    assert signal.confidence == "REFERENCE_ONLY"
    assert signal.metadata["source_status"] == "UNKNOWN"
    assert signal.metadata["initialized"] is False


@pytest.mark.parametrize("kind", ["mlb", "soccer"])
def test_memory_cache_obeys_ttl_and_refetches_after_expiration(tmp_path, monkeypatch, kind):
    clock = [1_800_000_000.0]
    monkeypatch.setattr((mlb_module if kind == "mlb" else soccer_module).time, "time", lambda: clock[0])
    if kind == "mlb":
        monkeypatch.setattr(mlb_module, "CACHE_TTL", 10)
        model = ESPNPythagoreanMLBModel(str(tmp_path / "mlb.json"))
        model.session = _Session(_mlb_payload())
        fetch = model._get_mlb_stats
    else:
        monkeypatch.setattr(soccer_module, "CACHE_TTL", 10)
        model = ESPNPoissonSoccerFallback(str(tmp_path))
        model.session = _Session(_soccer_payload())
        fetch = lambda: model._get_soccer_stats("eng.1")

    first = fetch()
    assert first
    assert len(model.session.calls) == 1
    fetch()
    assert len(model.session.calls) == 1
    clock[0] += 11
    fetch()
    assert len(model.session.calls) == 2


def test_season_and_observation_after_kickoff_are_reference_only(tmp_path):
    model = ESPNPythagoreanMLBModel(str(tmp_path / "mlb.json"))
    model._stats_cache = model._parse_espn_standings(_mlb_payload())
    now = datetime.now(timezone.utc)
    model._cache_meta = {"timestamp": now.timestamp(), "observed_at": now.isoformat(),
                         "data_as_of": now.isoformat(), "season": 2026, "source_status": "LIVE"}
    leg = _mlb_leg(start_time_utc="2026-10-11T00:00:00+00:00")

    signal = model.evaluate_leg(leg)

    assert signal is not None
    assert signal.confidence == "REFERENCE_ONLY"
    assert signal.freshness_status == "UNKNOWN"
    assert signal.metadata["point_in_time_status"] == "REFERENCE_ONLY"
    assert signal.metadata["source_season"] == signal.metadata["event_season"] == 2026


def test_expired_snapshot_is_reference_only_even_when_season_matches(tmp_path):
    cache_file = tmp_path / "stale_mlb.json"
    old_observed = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - mlb_module.CACHE_TTL - 3600,
                                          timezone.utc).isoformat()
    cache_file.write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).timestamp() - mlb_module.CACHE_TTL - 3600,
        "observed_at": old_observed, "season": 2026,
        "teams": ESPNPythagoreanMLBModel(str(cache_file))._parse_espn_standings(_mlb_payload()),
    }), encoding="utf-8")
    model = ESPNPythagoreanMLBModel(str(cache_file))
    model.session = _FailedSession(_mlb_payload())

    signal = model.evaluate_leg(_mlb_leg())

    assert signal is not None
    assert signal.freshness_status == "STALE"
    assert signal.confidence == "REFERENCE_ONLY"
    assert signal.metadata["source_status"] == "STALE"
    assert signal.metadata["failure_status"] == "HTTP_403"
    assert signal.metadata["initialized"] is False


def test_unknown_or_mismatched_season_is_reference_only(tmp_path):
    model = ESPNPoissonSoccerFallback(str(tmp_path))
    model._league_caches["eng.1"] = model._parse_soccer_standings(_soccer_payload())
    now = datetime.now(timezone.utc)
    model._cache_meta["eng.1"] = {"timestamp": now.timestamp(), "observed_at": now.isoformat(),
                                  "data_as_of": now.isoformat(), "season": 2025, "source_status": "LIVE"}

    signal = model.evaluate_leg(_soccer_leg())

    assert signal is not None
    assert signal.confidence == "REFERENCE_ONLY"
    assert signal.freshness_status == "UNKNOWN"
    assert signal.metadata["season_matches"] is False


@pytest.mark.parametrize("kind", ["mlb", "soccer"])
def test_unsupported_handicap_returns_none(tmp_path, kind):
    if kind == "mlb":
        model = ESPNPythagoreanMLBModel(str(tmp_path / "mlb.json"))
        model._stats_cache = model._parse_espn_standings(_mlb_payload())
        model._cache_meta = {"timestamp": datetime.now(timezone.utc).timestamp(),
                             "observed_at": "2026-10-12T00:00:00+00:00", "data_as_of": "2026-10-12T00:00:00+00:00",
                             "season": 2026, "source_status": "LIVE"}
        leg = _mlb_leg(market="讓分", selection="Dodgers -1.5", side="主", line="-1.5")
    else:
        model = ESPNPoissonSoccerFallback(str(tmp_path))
        model._league_caches["eng.1"] = model._parse_soccer_standings(_soccer_payload())
        model._cache_meta["eng.1"] = {"timestamp": datetime.now(timezone.utc).timestamp(),
                                       "observed_at": "2026-10-12T00:00:00+00:00", "data_as_of": "2026-10-12T00:00:00+00:00",
                                       "season": 2026, "source_status": "LIVE"}
        leg = _soccer_leg(market="讓分", selection="Arsenal -1", side="主", line="-1")
    assert model.evaluate_leg(leg) is None
