from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import time

import pytest
from bs4 import BeautifulSoup

from core.research_pipeline import ResearchPipeline
from core.scraper import PlaysportScraper


SOURCE_DIR = (Path(__file__).resolve().parents[1]
              / "artifacts" / "research_completion_20261014" / "source_dom")


class _Response:
    status_code = 200

    def __init__(self, text):
        self.text = text


class _Session:
    def __init__(self, page):
        self.page = page
        self.headers = {}

    def get(self, url, timeout=10):
        return _Response(self.page)


@pytest.mark.parametrize("alliance_id", ["6", "7", "93"])
def test_real_current_empty_pages_are_healthy_and_replace_prior_odds(tmp_path, alliance_id):
    manifest = json.loads((SOURCE_DIR / "manifest.json").read_text(encoding="utf-8"))
    evidence = next(row for row in manifest if row["alliance_id"] == alliance_id)
    html_path = SOURCE_DIR / f"scale_{alliance_id}.html"
    assert hashlib.sha256(html_path.read_bytes()).hexdigest() == evidence["sha256"]
    html = html_path.read_text(encoding="utf-8")
    table = BeautifulSoup(html, "html.parser").find("table", class_="predictgame-table")
    assert evidence["http_status"] == 200
    assert evidence["table_found"] is True
    assert evidence["game_set_row_count"] == 0
    assert "此日無比賽" in table.get_text(" ", strip=True)
    assert not table.select("tr.game-set")

    scraper = PlaysportScraper(session=_Session(html), cache_dir=tmp_path / "cache")
    scraper.write_cache("scale_" + alliance_id, {
        "matches": [{"match_id": "old-event", "options": [{"odds": 1.9}]}],
    })
    matches = scraper.fetch_scale_matches(alliance_id, force_refresh=True)

    assert matches == []
    status = scraper.get_scale_source_status()[alliance_id]
    assert status["source_status"] == "LIVE_NO_EVENTS"
    assert status["no_events_confirmed"] is True
    assert status["observed_at"]
    assert status["failure_status"] is None
    assert status["error"] is None
    assert status["match_count"] == status["option_count"] == 0
    # The cache is atomically replaced by an empty tombstone, so the next TTL
    # read cannot resurrect an older market.
    cached = json.loads(scraper.get_cache_path("scale_" + alliance_id).read_text(encoding="utf-8"))
    assert cached["matches"] == []
    assert cached["source_status"] == "LIVE_NO_EVENTS"
    assert scraper.fetch_scale_matches(alliance_id) == []
    assert scraper.get_scale_source_status()[alliance_id]["source_status"] == "LIVE_NO_EVENTS"


def test_empty_marker_with_event_row_is_not_treated_as_no_events():
    table = BeautifulSoup(
        '<table><tr class="game-set"><td class="td-gameinfo">event</td></tr>'
        '<tr><td>此日無比賽</td></tr></table>', "html.parser"
    ).find("table")
    assert not PlaysportScraper._is_explicit_no_events_page(table, [])


def test_unmarked_parse_empty_still_reports_failure_and_uses_stale_fallback(tmp_path):
    scraper = PlaysportScraper(session=_Session(
        '<table class="predictgame-table"><tr><td>載入中</td></tr></table>'
    ), cache_dir=tmp_path / "cache")
    scraper.write_cache("scale_6", {"matches": [{"match_id": "old", "options": []}]})
    path = scraper.get_cache_path("scale_6")
    cached = json.loads(path.read_text(encoding="utf-8"))
    cached["cached_at"] = time.time() - 3600
    path.write_text(json.dumps(cached), encoding="utf-8")

    matches = scraper.fetch_scale_matches("6", force_refresh=True)
    status = scraper.get_scale_source_status()["6"]
    assert matches[0]["match_id"] == "old"
    assert status["source_status"] == "STALE_CACHE"
    assert status["failure_status"] == "PARSE_EMPTY"
    assert status.get("no_events_confirmed") is None


def test_research_source_summary_counts_confirmed_no_event_sources(tmp_path):
    class _Adapter:
        def get_taiwan_legs(self, alliances, force_refresh=False):
            return []

        def get_source_status(self):
            return {
                "6": {"source_status": "LIVE_NO_EVENTS", "no_events_confirmed": True,
                      "failure_status": None, "observed_at": "2026-10-14T01:01:37Z"},
                "7": {"source_status": "PARSE_EMPTY", "failure_status": "PARSE_EMPTY"},
            }

    pipeline = ResearchPipeline(data_root=tmp_path / "research", odds_adapter=_Adapter())
    summary = pipeline._stage_source("20261014T0100Z", datetime.now(timezone.utc), tmp_path / "stage")
    assert summary["confirmed_no_event_source_count"] == 1
    assert summary["source_status_counts"] == {"LIVE_NO_EVENTS": 1, "PARSE_EMPTY": 1}
    assert summary["source_error_count"] == 1
