#!/usr/bin/env python3
"""Tests for Global Market Intelligence REST API Endpoints.

Milestone 6 Verification:
- Tests /api/market/status returns healthy configuration & quota status
- Tests /api/market/benchmark returns aligned international quotes & EV
- Tests /api/market/splits returns ticket % vs money % splits
- Tests /api/market/evaluation returns three-way forward evaluation report
"""

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from server.api import app

client = TestClient(app)


def test_get_market_status():
    resp = client.get("/api/market/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "HEALTHY"
    assert "the_odds_api" in data
    assert "alignment_engine" in data
    assert "fair_odds_engine" in data
    assert "as_of_utc" in data


def test_get_market_benchmark():
    resp = client.get("/api/market/benchmark?league=MLB")
    assert resp.status_code == 200
    data = resp.json()
    assert data["league"] == "MLB"
    assert "total_taiwan_legs" in data
    assert "benchmarks" in data
    assert "as_of_utc" in data
    for bm in data.get("benchmarks", []):
        # Synthetic benchmarks must NEVER be flagged as reliable positive EV
        if bm.get("is_synthetic"):
            assert bm.get("is_positive_ev") is False
            assert bm.get("ev_status") == "SYNTHETIC_DATA_DISPLAY_ONLY"
            # Verify no fake 0.98 multiplier was used: if counterpart odds missing, fair_probability is None
            if bm.get("matched_international_odds") is not None and bm.get("counterpart_odds") is None:
                assert bm.get("fair_probability") is None
                assert bm.get("theoretical_ev") is None


def test_market_benchmark_counterpart_missing_fail_closed():
    # Calling benchmark on an isolated or unaligned market returns fail-closed EV
    resp = client.get("/api/market/benchmark?league=UNKNOWN_LEAGUE")
    assert resp.status_code == 200
    data = resp.json()
    assert data["benchmarks"] == []


def test_market_benchmark_soccer_three_way_fail_closed():
    # Test soccer benchmark endpoint: verify 3-way handling
    resp = client.get("/api/market/benchmark?league=EPL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["league"] == "EPL"
    for bm in data.get("benchmarks", []):
        if bm.get("market") in {"不讓分", "獨贏"} and bm.get("is_three_way"):
            # In 3-way market, if draw_odds or counterpart_odds is missing, EV must be None
            if bm.get("draw_odds") is None or bm.get("counterpart_odds") is None:
                assert bm.get("fair_probability") is None
                assert bm.get("theoretical_ev") is None
                assert bm.get("is_positive_ev") is False
                assert bm.get("ev_status") in {"INCOMPLETE_THREE_WAY_MARKET", "NO_COUNTERPART_ODDS", "UNVERIFIED_MARKET_EVIDENCE"}
        # If synthetic, positive EV is strictly prohibited
        if bm.get("is_synthetic"):
            assert bm.get("is_positive_ev") is False
            assert bm.get("ev_status") == "SYNTHETIC_DATA_DISPLAY_ONLY"


def test_get_market_splits():
    resp = client.get("/api/market/splits?league=MLB")
    assert resp.status_code == 200
    data = resp.json()
    assert data["league"] == "MLB"
    assert "splits_count" in data
    assert "splits" in data
    if data["splits"]:
        s = data["splits"][0]
        assert "bet_percentage" in s
        assert "money_percentage" in s
        assert "source_type" in s


def test_get_market_evaluation():
    resp = client.get("/api/market/evaluation?scope=GLOBAL")
    assert resp.status_code == 200
    data = resp.json()
    assert "evaluation_scope" in data
    assert "taiwan_market_baseline" in data
    assert "international_sharp_benchmark" in data
    assert "active_model_strategy" in data
    assert "champion_source" in data
    assert "shadow_mode_recommendation" in data


def test_get_market_research_summary():
    resp = client.get("/api/market/research-summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "live_status" in data
    assert "the_odds_api" in data
    assert "snapshots" in data
    assert "forward_evaluation" in data
    assert "total_count" in data["snapshots"]
    assert "sample_size" in data["forward_evaluation"]


def test_post_market_config():
    local_cfg = Path("config/odds_api.local.yaml")
    try:
        # Test valid key update
        resp = client.post("/api/market/config", json={"the_odds_api_key": "test_key_api_12345"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert data["the_odds_api"]["has_api_key"] is True
        assert data["the_odds_api"]["key_source"] == "LOCAL_CONFIG"

        # Test invalid key rejection (e.g. invalid symbols / injection attempt)
        bad_resp = client.post("/api/market/config", json={"the_odds_api_key": "bad; key!@#$"})
        assert bad_resp.status_code == 400
    finally:
        local_cfg.unlink(missing_ok=True)


def test_post_market_pipeline_cycle():
    from unittest.mock import patch
    from integrations.common.models import TaiwanLeg
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    mock_leg = TaiwanLeg(
        sport="baseball",
        league="MLB",
        event_id="test_mock_1",
        home_team="Los Angeles Dodgers",
        away_team="San Diego Padres",
        market="moneyline",
        selection="home",
        taiwan_odds=1.85,
        odds_status="LIVE",
        odds_scraped_at=now.isoformat(),
        start_time_utc=(now + timedelta(hours=3)).isoformat(),
    )
    with patch("core.market_forward_pipeline.PlaysportOddsAdapter.get_taiwan_legs", return_value=[mock_leg]):
        resp = client.post("/api/market/pipeline/cycle?leagues=MLB")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cycle_status"] == "SUCCESS"
        assert "snapshot_cycle" in data
        assert "evaluation_summary" in data


