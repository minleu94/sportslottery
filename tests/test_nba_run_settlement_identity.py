from __future__ import annotations

import hashlib
import json
from pathlib import Path

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


def _scoreboard_payload():
    path = SOURCE_DIR / "nba_scoreboard_20261013.json"
    manifest = json.loads((SOURCE_DIR / "manifest.json").read_text(encoding="utf-8"))
    row = next(item for item in manifest if item["file"] == path.name)
    assert row["http_status"] == 200
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["events"]) == row["events"] == 5
    return row, payload


def test_exact_nba_team_aliases_are_sport_scoped():
    expected = {
        "勇士": "NBA_GSW", "Golden State Warriors": "NBA_GSW", "GSW": "NBA_GSW",
        "湖人": "NBA_LAL", "Los Angeles Lakers": "NBA_LAL", "LAL": "NBA_LAL",
        "拓荒者": "NBA_POR", "Portland Trail Blazers": "NBA_POR", "POR": "NBA_POR",
        "國王": "NBA_SAC", "Sacramento Kings": "NBA_SAC", "SAC": "NBA_SAC",
    }
    for label, canonical_id in expected.items():
        assert GLOBAL_TEAM_REGISTRY.resolve(label, sport="basketball", league="NBA").canonical_id == canonical_id
    # 勇士 is ambiguous without sport scope because MLB also uses that short form.
    assert GLOBAL_TEAM_REGISTRY.resolve("勇士", sport="baseball", league="MLB").canonical_id == "MLB_ATL"
    assert GLOBAL_TEAM_REGISTRY.resolve("Portland Trail Blazers", sport="basketball", league="WNBA") is None


def test_saved_espn_nba_feed_matches_exact_chinese_snapshots_and_settles():
    manifest, payload = _scoreboard_payload()
    session = _Session(payload)
    results = ESPNResultProvider(session=session).fetch("basketball", "NBA", "20261013")
    assert session.urls == [manifest["url"]]

    by_id = {row.provider_event_id: row.to_dict() for row in results}
    warriors_game = by_id["401898718"]
    blazers_game = by_id["401901826"]
    assert warriors_game["away_provider_team_id"] == "9"
    assert warriors_game["home_provider_team_id"] == "13"
    assert (warriors_game["away_team"], warriors_game["home_team"]) == ("NBA_GSW", "NBA_LAL")
    assert (warriors_game["away_score"], warriors_game["home_score"]) == (101, 89)
    assert blazers_game["away_provider_team_id"] == "22"
    assert blazers_game["home_provider_team_id"] == "23"
    assert (blazers_game["away_team"], blazers_game["home_team"]) == ("NBA_POR", "NBA_SAC")
    assert (blazers_game["away_score"], blazers_game["home_score"]) == (110, 98)
    assert warriors_game["status"] == blazers_game["status"] == "FINAL"
    assert warriors_game["unresolved_reason"] is None
    assert blazers_game["unresolved_reason"] is None

    snapshots = [
        {
            "sport": "basketball", "league": "NBA", "away_team": "勇士", "home_team": "湖人",
            "event_start": "2026-10-14T02:00:00+00:00", "market": "讓分",
            "selection": "勇士 -2.5", "side": "客", "line": -2.5,
        },
        {
            "sport": "basketball", "league": "NBA", "away_team": "拓荒者", "home_team": "國王",
            "event_start": "2026-10-14T02:00:00Z", "market": "不讓分",
            "selection": "拓荒者 不讓分勝", "side": "客", "line": None,
        },
    ]
    matched = [
        SettlementEngine.match_result_game(snapshots[0], list(by_id.values())),
        SettlementEngine.match_result_game(snapshots[1], list(by_id.values())),
    ]
    assert matched == [warriors_game, blazers_game]

    spread = TaiwanSettlementRules.evaluate_taiwan_market(
        resolve_settlement_rule_id("basketball", "NBA", snapshots[0]["market"]),
        market=snapshots[0]["market"], selection=snapshots[0]["selection"], line=snapshots[0]["line"],
        away_score=matched[0]["away_score"], home_score=matched[0]["home_score"], side=snapshots[0]["side"],
        official_completion_status=matched[0]["official_completion_status"],
    )
    moneyline = TaiwanSettlementRules.evaluate_taiwan_market(
        resolve_settlement_rule_id("basketball", "NBA", snapshots[1]["market"]),
        market=snapshots[1]["market"], selection=snapshots[1]["selection"], line=None,
        away_score=matched[1]["away_score"], home_score=matched[1]["home_score"], side=snapshots[1]["side"],
        official_completion_status=matched[1]["official_completion_status"],
    )
    assert spread.status == "WON"
    assert moneyline.status == "WON"

    # Exact identity is necessary but not enough: a different start time cannot
    # be made to match by the newly added aliases.
    assert SettlementEngine.match_result_game(
        {**snapshots[0], "event_start": "2026-10-14T02:16:00Z"}, list(by_id.values())
    ) is None
