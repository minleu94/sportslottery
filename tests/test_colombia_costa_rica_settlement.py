"""Real ESPN scoreboard evidence for the two highest-volume unsupported leagues."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.identity.league_mapping import normalize_league_and_sport
from core.settlement_engine import SettlementEngine
from integrations.results.espn import ESPN_LEAGUES, parse_espn_event
from integrations.schedules.espn_schedule import ESPN_SPORT_MAP
from scripts.settle_results import settle_snapshot_results


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "artifacts" / "improvements_20261014" / "football_sources"
SOURCE_MANIFEST = SOURCE_ROOT / "manifest.json"


def _feed(filename: str, league: str) -> list[dict]:
    return json.loads((SOURCE_ROOT / filename).read_text(encoding="utf-8"))["events"]


def test_league_routing_is_exact_and_result_coverage_is_declared():
    assert normalize_league_and_sport("哥倫比亞甲級聯賽", "4") == ("COLOMBIA_PRIMERA_A", "soccer")
    assert normalize_league_and_sport("哥斯大黎加甲級聯賽", "4") == ("COSTA_RICA_PRIMERA", "soccer")
    assert normalize_league_and_sport("UNKNOWN_哥倫比亞甲級聯賽") == ("COLOMBIA_PRIMERA_A", "soccer")
    assert normalize_league_and_sport("UNKNOWN_哥斯大黎加甲級聯賽") == ("COSTA_RICA_PRIMERA", "soccer")
    assert normalize_league_and_sport("哥倫比亞乙級聯賽", "4") == ("UNKNOWN_哥倫比亞乙級聯賽", "soccer")
    assert ESPN_LEAGUES[("soccer", "COLOMBIA_PRIMERA_A")] == "soccer/col.1"
    assert ESPN_LEAGUES[("soccer", "COSTA_RICA_PRIMERA")] == "soccer/crc.1"
    assert ESPN_SPORT_MAP["COLOMBIA_PRIMERA_A"] == "soccer/col.1"
    assert ESPN_SPORT_MAP["COSTA_RICA_PRIMERA"] == "soccer/crc.1"
    coverage = SettlementEngine.supported_result_coverage()
    assert coverage["soccer/COLOMBIA_PRIMERA_A"]["provider"] == "ESPN_PUBLIC_SCOREBOARD"
    assert coverage["soccer/COSTA_RICA_PRIMERA"]["coverage"] == "available_third_party"


def test_saved_real_feed_hashes_match_manifest():
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    sources = {row["file"]: row for row in manifest}
    for filename, digest in {
        "col.1_scoreboard_20261013.json": "066816a1eee24ac8751dc09a79410c346b4dc1c49462444e883dc0970c6c6e4b",
        "crc.1_scoreboard_20261013.json": "f7cdadc83350432a75ca87a1eda3be19e8bf1a83faa84a316af72455de5deddc",
    }.items():
        assert sources[filename]["http_status"] == 200
        assert sources[filename]["sha256"] == digest
        assert hashlib.sha256((SOURCE_ROOT / filename).read_bytes()).hexdigest() == digest


def test_real_colombia_and_costa_rica_fixtures_match_without_provider_ids_and_settle_90m():
    from datetime import datetime, timezone

    feed_files = {
        "COLOMBIA_PRIMERA_A": "col.1_scoreboard_20261013.json",
        "COSTA_RICA_PRIMERA": "crc.1_scoreboard_20261013.json",
    }
    events_by_league = {league: _feed(filename, league) for league, filename in feed_files.items()}

    class FixtureSettlementEngine(SettlementEngine):
        def __init__(self):
            # Avoid initializing production loggers or touching persisted results.
            self.odds_watcher = object()
            self.settlements = []

        def fetch_results(self, sport, league, date_str, source_ids=None):
            if date_str != "2026-10-13":
                return []
            events = events_by_league[league]
            return [parse_espn_event(event, sport, league,
                                     source_url=f"https://site.api.espn.com/apis/site/v2/sports/soccer/{'col.1' if league == 'COLOMBIA_PRIMERA_A' else 'crc.1'}/scoreboard?dates=20261013",
                                     observed_at_utc="2026-10-14T22:08:10Z").to_dict()
                    for event in events]

        def settle_single_prediction_direct(self, **kwargs):
            self.settlements.append(kwargs)

    snapshots = [
        {"snapshot_id": "col-draw", "sport": "soccer", "league": "UNKNOWN_哥倫比亞甲級聯賽",
         "event_start": "2026-10-13T23:30:00Z", "away_team": "里奧內格羅金鷹", "home_team": "布卡拉曼加競技",
         "market": "不讓分", "selection": "和局", "side": "和", "is_settled": False},
        {"snapshot_id": "col-postponed", "sport": "soccer", "league": "UNKNOWN_哥倫比亞甲級聯賽",
         "event_start": "2026-10-14T01:30:00Z", "away_team": "卡爾達斯", "home_team": "百萬富翁",
         "market": "不讓分", "selection": "百萬富翁 不讓分勝", "side": "主", "is_settled": False},
        {"snapshot_id": "crc-final-one", "sport": "soccer", "league": "UNKNOWN_哥斯大黎加甲級聯賽",
         "event_start": "2026-10-14T00:00:00Z", "away_team": "普塔雷納斯", "home_team": "肯塔吉內斯",
         "market": "不讓分", "selection": "肯塔吉內斯 不讓分勝", "side": "主", "is_settled": False},
        {"snapshot_id": "crc-final-two", "sport": "soccer", "league": "UNKNOWN_哥斯大黎加甲級聯賽",
         "event_start": "2026-10-14T02:00:00Z", "away_team": "國際聖卡洛斯", "home_team": "聖卡洛斯",
         "market": "不讓分", "selection": "國際聖卡洛斯 不讓分勝", "side": "客", "is_settled": False},
    ]
    engine = FixtureSettlementEngine()

    audit = settle_snapshot_results(engine, snapshots, now=datetime(2026, 10, 15, tzinfo=timezone.utc))

    assert audit["games"] == 4
    assert audit["settled"] == 3
    assert audit["unresolved"] == 1
    assert audit["coverage"]["soccer/COLOMBIA_PRIMERA_A"]["matched_snapshots"] == 2
    assert audit["coverage"]["soccer/COSTA_RICA_PRIMERA"]["matched_snapshots"] == 2
    statuses = {row["snapshot_id"]: row["settlement_status"] for row in engine.settlements}
    assert statuses == {"col-draw": "WON", "col-postponed": "PENDING",
                        "crc-final-one": "WON", "crc-final-two": "WON"}
    draw = next(row for row in engine.settlements if row["snapshot_id"] == "col-draw")
    assert draw["result_source"] == "ESPN_PUBLIC_SCOREBOARD"
    assert "90分鐘" in draw["settlement_reason"]
