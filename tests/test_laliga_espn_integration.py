from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from core.identity.league_mapping import normalize_league_and_sport
from core.identity.team_alias import GLOBAL_TEAM_REGISTRY
from core.season_radar import SeasonRadar
from core.settlement.taiwan_rules import resolve_settlement_rule_id
from core.settlement_engine import SettlementEngine
from integrations.common.models import TaiwanLeg
from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter
from integrations.results.espn import ESPNResultProvider
from integrations.schedules.espn_schedule import ESPNScheduleAdapter, ESPN_SPORT_MAP


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "artifacts" / "research_completion_20261014" / "laliga_sources"


def _source_manifest(file_name):
    manifest = json.loads((SOURCE_DIR / "manifest.json").read_text(encoding="utf-8"))
    return next(row for row in manifest if row["file"] == file_name)


class _Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}
        self.urls = []

    def get(self, url, timeout=10):
        self.urls.append(url)
        return _Response(self.payload)


def test_exact_laliga_aliases_resolve_without_guessing_generic_soccer(tmp_path):
    for label in ("LALIGA", "esp.1", "西甲", "西班牙甲級聯賽"):
        assert normalize_league_and_sport(label) == ("LALIGA", "soccer")
    assert normalize_league_and_sport("足球", "4") == ("UNKNOWN_足球", "soccer")
    assert resolve_settlement_rule_id("soccer", "LALIGA", "不讓分") == "SOCCER_90MIN_1X2"
    assert "soccer/LALIGA" in SettlementEngine.supported_result_coverage()
    assert SeasonRadar.LEAGUES["LALIGA"]["espn_code"] == "LALIGA"
    assert PenaltyblogDixonColesAdapter(cache_dir=str(tmp_path))\
        ._resolve_league_code("LALIGA") == "esp.1"


def test_official_espn_laliga_roster_names_resolve_in_team_registry():
    source = SOURCE_DIR / "teams.json"
    manifest = _source_manifest("teams.json")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["sha256"]
    payload = json.loads(source.read_text(encoding="utf-8"))
    teams = payload["sports"][0]["leagues"][0]["teams"]
    assert payload["sports"][0]["leagues"][0]["abbreviation"] == "LALIGA"
    assert len(teams) == 20
    expected_ids = {
        "Alavés": "SOC_ESP_ALA", "Athletic Club": "SOC_ESP_ATH",
        "Atlético Madrid": "SOC_ESP_ATM", "Barcelona": "SOC_BAR",
        "Celta Vigo": "SOC_ESP_CEL", "Deportivo": "SOC_ESP_LAC",
        "Elche": "SOC_ESP_ELC", "Espanyol": "SOC_ESP_ESP",
        "Getafe": "SOC_ESP_GET", "Levante": "SOC_ESP_LEV",
        "Málaga": "SOC_ESP_MAL", "Osasuna": "SOC_ESP_OSA",
        "Racing Santander": "SOC_ESP_RSC", "Rayo Vallecano": "SOC_ESP_RAY",
        "Real Betis": "SOC_ESP_BET", "Real Madrid": "SOC_RMA",
        "Real Sociedad": "SOC_ESP_SOC", "Sevilla": "SOC_ESP_SEV",
        "Valencia": "SOC_ESP_VAL", "Villarreal": "SOC_ESP_VIL",
    }
    resolved_ids = {}
    for row in teams:
        team = row["team"]
        name = team.get("displayName") or team.get("name")
        resolved = GLOBAL_TEAM_REGISTRY.resolve(name, sport="soccer", league="LALIGA")
        resolved_ids[name] = resolved.canonical_id if resolved else None
    assert resolved_ids == expected_ids
    # These exact traditional-Chinese forms were present in Playsport's saved
    # public scale_4 response; they are aliases, not substring guesses.
    assert GLOBAL_TEAM_REGISTRY.resolve("馬德里競技", sport="soccer", league="LALIGA").canonical_id == "SOC_ESP_ATM"
    assert GLOBAL_TEAM_REGISTRY.resolve("比亞雷亞爾", sport="soccer", league="LALIGA").canonical_id == "SOC_ESP_VIL"


def test_official_espn_scoreboard_parses_and_matches_laliga_result():
    source = SOURCE_DIR / "scoreboard_20261012.json"
    manifest = _source_manifest(source.name)
    assert manifest["http_status"] == 200
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["sha256"]
    payload = json.loads(source.read_text(encoding="utf-8"))
    assert len(payload["events"]) == manifest["events"] == 1

    session = _Session(payload)
    provider = ESPNResultProvider(session=session)
    results = provider.fetch("soccer", "LALIGA", "20261012")
    assert session.urls == [manifest["url"]]
    assert len(results) == 1
    result = results[0].to_dict()
    assert result["provider_event_id"] == "401882852"
    assert result["league"] == "LALIGA"
    assert result["status"] == "FINAL"
    assert result["away_team"] == "SOC_ESP_SEV"
    assert result["home_team"] == "SOC_ESP_LEV"
    assert result["unresolved_reason"] is None
    from core.settlement.taiwan_rules import TaiwanSettlementRules
    tie_settlement = TaiwanSettlementRules.evaluate_taiwan_market(
        resolve_settlement_rule_id("soccer", "LALIGA", "不讓分"),
        market="不讓分", selection="和局", line=None,
        away_score=result["away_score"], home_score=result["home_score"], side="和",
        soccer_regulation_away=result["soccer_regulation_away"],
        soccer_regulation_home=result["soccer_regulation_home"],
        official_completion_status=result["official_completion_status"],
    )
    assert tie_settlement.status == "WON"

    snapshot = {
        "provider_event_id": result["provider_event_id"],
        "result_provider": "ESPN_PUBLIC_SCOREBOARD",
        "sport": "soccer", "league": "LALIGA",
        "away_team": "Sevilla", "home_team": "Levante",
        "event_start": result["start_time_utc"],
    }
    assert SettlementEngine.match_result_game(snapshot, [result]) == result
    # Also require exact team+start matching without a provider event ID.
    identity_only_snapshot = {
        "sport": "soccer", "league": "LALIGA",
        "away_team": "塞維亞", "home_team": "萊萬特",
        "event_start": result["start_time_utc"],
    }
    assert SettlementEngine.match_result_game(identity_only_snapshot, [result]) == result


def test_schedule_adapter_uses_official_laliga_endpoint():
    payload = json.loads((SOURCE_DIR / "scoreboard_20261012.json").read_text(encoding="utf-8"))
    session = _Session(payload)
    adapter = ESPNScheduleAdapter(session=session)
    events = adapter.fetch_live_events("LALIGA")
    assert ESPN_SPORT_MAP["LALIGA"] == "soccer/esp.1"
    assert session.urls == ["http://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/scoreboard"]
    assert events[0]["id"] == "401882852"


def test_configured_esp1_model_emits_a_signal_through_laliga_alias(tmp_path):
    source = ROOT / "artifacts" / "research_completion_20261014" / "runtime_probe" / "cache" / "models" / "penaltyblog_dixon_coles" / "real_matches_esp.1.json"
    assert source.is_file()
    data = json.loads(source.read_text(encoding="utf-8"))
    assert len(data["matches"]) >= 60
    shutil.copyfile(source, tmp_path / "real_matches_esp.1.json")
    adapter = PenaltyblogDixonColesAdapter(cache_dir=str(tmp_path))
    from integrations.models.external.penaltyblog_dixon_coles import _canonical_model_team_name
    assert _canonical_model_team_name("瓦倫西亞")[0] == "Valencia"
    assert _canonical_model_team_name("皇家馬德里")[0] == "Real Madrid"
    leg = TaiwanLeg(
        event_id="laliga-model-alias", canonical_event_id="laliga-model-alias",
        sport="soccer", league="LALIGA", market="不讓分", selection="主勝", side="主",
        taiwan_odds=2.1, start_time="2026-10-14T20:00:00+00:00",
        start_time_utc="2026-10-14T20:00:00+00:00", away_team="瓦倫西亞", home_team="皇家馬德里",
    )
    signal = adapter.evaluate_leg(leg)
    assert signal is not None
    assert signal.metadata["league"] == "esp.1"
    assert 0.0 < signal.probability < 1.0
