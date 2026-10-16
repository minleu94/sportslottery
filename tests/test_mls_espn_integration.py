from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime

from core.identity.league_mapping import normalize_league_and_sport
from core.identity.team_alias import GLOBAL_TEAM_REGISTRY
from core.settlement.taiwan_rules import TaiwanSettlementRules, resolve_settlement_rule_id
from core.settlement_engine import SettlementEngine
from integrations.results.espn import ESPNResultProvider


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "artifacts" / "improvements_20261014" / "football_sources"


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


def _source(name, expected_events=None):
    path = SOURCE_DIR / name
    manifest = json.loads((SOURCE_DIR / "manifest.json").read_text(encoding="utf-8"))
    row = next(item for item in manifest if item["file"] == name)
    assert row["http_status"] == 200
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if expected_events is not None:
        assert len(payload.get("events", [])) == expected_events
    return row, payload


def test_mls_exact_competition_identity_and_supported_routes():
    assert normalize_league_and_sport("MLS") == ("MLS", "soccer")
    assert normalize_league_and_sport("usa.1") == ("MLS", "soccer")
    assert normalize_league_and_sport("美國足球大聯盟") == ("MLS", "soccer")
    assert normalize_league_and_sport("美國職業足球大聯盟") == ("MLS", "soccer")
    assert normalize_league_and_sport("UNKNOWN_美國足球大聯盟") == ("MLS", "soccer")
    assert resolve_settlement_rule_id("soccer", "MLS", "不讓分") == "SOCCER_90MIN_1X2"
    assert resolve_settlement_rule_id("soccer", "MLS", "大小") == "SOCCER_90MIN_TOTAL"
    assert "soccer/MLS" in SettlementEngine.supported_result_coverage()


def test_mls_roster_ids_and_all_fifteen_playSport_pairs_match_exactly():
    scoreboard_manifest, scoreboard = _source("usa.1_scoreboard.json", 15)
    roster_manifest, roster = _source("usa.1_teams.json")
    assert roster["sports"][0]["leagues"][0]["abbreviation"] == "MLS"
    roster_teams = roster["sports"][0]["leagues"][0]["teams"]
    assert len(roster_teams) == 30
    for row in roster_teams:
        team = row["team"]
        resolved = GLOBAL_TEAM_REGISTRY.resolve(f"ESPN_TEAM_{team['id']}", sport="soccer", league="MLS")
        assert resolved is not None, team["displayName"]
        assert resolved.display_name_en == team["displayName"]

    games_by_source_id = {
        # Playsport game ID: ESPN event ID, exact source away/home labels.
        "1094": ("761865", "夏洛特", "哥倫布機員"),
        "1095": ("761862", "新英格蘭革命", "辛辛那提"),
        "1096": ("761860", "奧蘭多城", "多倫多"),
        "1097": ("761864", "亞特蘭大聯", "蒙特婁"),
        "1103": ("761861", "紐約城", "國際邁阿密"),
        "1104": ("761863", "紐約紅牛", "華盛頓特區聯"),
        "1109": ("761867", "西雅圖海灣者", "達拉斯"),
        "1110": ("761869", "費城聯", "芝加哥火焰"),
        "1111": ("761868", "溫哥華白浪", "聖路易城"),
        "1113": ("761866", "堪薩斯城體育", "納許維爾"),
        "1118": ("761870", "聖荷西地震", "皇家鹽湖城"),
        "1119": ("761871", "明尼蘇達聯", "科羅拉多急流"),
        "1121": ("761873", "奧斯汀", "洛杉磯"),
        "1122": ("761872", "休士頓發電機", "聖地牙哥"),
        "1123": ("761874", "波特蘭伐木者", "洛杉磯銀河"),
    }
    assert len(games_by_source_id) == 15
    parsed = ESPNResultProvider(session=_Session(scoreboard)).fetch("soccer", "MLS", "20261014")
    by_event_id = {game.provider_event_id: game.to_dict() for game in parsed}
    assert set(by_event_id) == {event_id for event_id, _, _ in games_by_source_id.values()}

    legs = json.loads((ROOT / "data/research_pipeline/runs/20261014T2215Z/data/source_legs.json").read_text(encoding="utf-8"))
    source_games = {}
    for leg in legs:
        if leg.get("league") == "UNKNOWN_美國足球大聯盟":
            source_games.setdefault(str(leg["event_id"]), leg)
    assert set(source_games) == set(games_by_source_id)

    for playsport_id, (espn_id, away_zh, home_zh) in games_by_source_id.items():
        source = source_games[playsport_id]
        result = by_event_id[espn_id]
        assert (source["away_team"], source["home_team"]) == (away_zh, home_zh)
        assert result["sport"] == "soccer" and result["league"] == "MLS"
        assert result["status"] == "PENDING"  # These are future fixtures; no result is fabricated.
        result_start = datetime.fromisoformat(result["start_time_utc"].replace("Z", "+00:00"))
        source_start = datetime.fromisoformat(source["start_time_utc"].replace("Z", "+00:00"))
        assert result_start == source_start
        assert result["away_provider_team_id"] and result["home_provider_team_id"]
        assert result["away_team"] == GLOBAL_TEAM_REGISTRY.resolve(away_zh, sport="soccer", league="MLS").canonical_id
        assert result["home_team"] == GLOBAL_TEAM_REGISTRY.resolve(home_zh, sport="soccer", league="MLS").canonical_id
        assert SettlementEngine.match_result_game(source, [result]) == result
        assert SettlementEngine.match_result_game(
            {**source, "start_time_utc": "2026-10-14T23:46:00Z"}, [result]
        ) is None

    assert scoreboard_manifest["sha256"] == "d679b829a8186f8270f1333e619bb8e639270c22ce4da21731a336fdc4689209"
    assert roster_manifest["sha256"] == "81b1074e351834171d7c3ae67bf0a8c454bfc805d26446d9602d64f779ff9961"


def test_mls_history_feed_settles_90_minute_result_without_extra_time():
    # This test consumes a historical scoreboard fixture captured from an
    # actual date in usa.1's official calendar. It is intentionally separate
    # from the future 15-game slate above.
    path = SOURCE_DIR / "usa.1_history_scoreboard.json"
    assert path.is_file(), "root must add a manifest-backed historical FT fixture before enabling MLS settlement"
    manifest, payload = _source(path.name, 1)
    raw = payload["events"][0]
    full_time = raw["status"]["type"]
    assert full_time["name"] == "STATUS_FULL_TIME"
    assert full_time["completed"] is True
    session = _Session(payload)
    result = ESPNResultProvider(session=session).fetch("soccer", "MLS", raw["date"][:10].replace("-", ""))[0].to_dict()
    assert result["status"] == "FINAL"
    assert (result["away_team"], result["home_team"]) == ("MLS_LAG", "MLS_STL")
    assert (result["away_score"], result["home_score"]) == (2, 6)
    assert (result["soccer_regulation_away"], result["soccer_regulation_home"]) == (2, 6)
    snapshot = {
        "sport": "soccer", "league": "MLS", "away_team": "洛杉磯銀河",
        "home_team": "聖路易城", "event_start": result["start_time_utc"],
    }
    assert SettlementEngine.match_result_game(snapshot, [result]) == result
    home_win = TaiwanSettlementRules.evaluate_taiwan_market(
        resolve_settlement_rule_id("soccer", "MLS", "不讓分"), market="不讓分", selection="主勝", line=None,
        away_score=result["away_score"], home_score=result["home_score"], side="主",
        soccer_regulation_away=result["soccer_regulation_away"],
        soccer_regulation_home=result["soccer_regulation_home"],
        official_completion_status=result["official_completion_status"],
    )
    draw = TaiwanSettlementRules.evaluate_taiwan_market(
        resolve_settlement_rule_id("soccer", "MLS", "不讓分"), market="不讓分", selection="和局", line=None,
        away_score=result["away_score"], home_score=result["home_score"], side="和",
        soccer_regulation_away=result["soccer_regulation_away"],
        soccer_regulation_home=result["soccer_regulation_home"],
        official_completion_status=result["official_completion_status"],
    )
    over = TaiwanSettlementRules.evaluate_taiwan_market(
        resolve_settlement_rule_id("soccer", "MLS", "大小"), market="大小", selection="大 2.5", line=2.5,
        away_score=result["away_score"], home_score=result["home_score"], side="大",
        soccer_regulation_away=result["soccer_regulation_away"],
        soccer_regulation_home=result["soccer_regulation_home"],
        official_completion_status=result["official_completion_status"],
    )
    assert (home_win.status, draw.status, over.status) == ("WON", "LOST", "WON")
    assert manifest["http_status"] == 200
    assert manifest["sha256"] == "275cc43520670dc82bb554729b0a03a63eae0f783c3b19edaeda5af239bfa543"
