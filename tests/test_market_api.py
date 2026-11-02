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


def test_the_odds_test_connection_endpoint():
    """Verify /api/market/the-odds/test-connection returns zero-cost health check results."""
    from unittest.mock import patch

    mock_res = {
        "status": "SUCCESS",
        "official_remaining": 494,
        "requests_used": 6,
        "credits_consumed": 0,
        "endpoint_called": "/v4/sports",
        "operating_mode": "LIVE_VERIFIED",
    }
    with patch("integrations.odds.the_odds_api.TheOddsApiClient.test_connection", return_value=mock_res):
        resp = client.post("/api/market/the-odds/test-connection", json={"fetch_sample": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert data["credits_consumed"] == 0
        assert data["official_remaining"] == 494


def test_estimate_pipeline_cost_endpoint():
    """Verify /api/market/pipeline/estimate-cost returns correct credits estimation."""
    resp = client.get("/api/market/pipeline/estimate-cost?leagues=NBA,MLB&markets=h2h")
    assert resp.status_code == 200
    data = resp.json()
    assert data["league_count"] == 2
    assert data["market_count"] == 1
    assert data["estimated_credits"] == 2


def test_pipeline_audit_snapshots():
    """Verify MarketForwardPipeline.audit_snapshots classifies historical vs eligible records accurately."""
    from core.market_forward_pipeline import MarketForwardPipeline
    from datetime import datetime, timezone, timedelta

    p = MarketForwardPipeline()
    now = datetime.now(timezone.utc)

    sample_records = [
        # 1. Settled legacy record (no model, no sharp market)
        {
            "event_id": "leg_1",
            "is_settled": True,
            "outcome": 1,
            "taiwan_odds": 1.75,
            "prediction_timestamp": (now - timedelta(hours=5)).isoformat(),
            "event_start": (now - timedelta(hours=3)).isoformat(),
            "probability_status": "MARKET_BASELINE_ONLY",
            "model_probability": None,
            "market_source": None,
        },
        # 2. Settled post-match leak record (pred_time >= event_start)
        {
            "event_id": "leak_1",
            "is_settled": True,
            "outcome": 1,
            "taiwan_odds": 1.90,
            "prediction_timestamp": (now - timedelta(hours=2)).isoformat(),
            "event_start": (now - timedelta(hours=3)).isoformat(),
            "model_probability": 0.55,
            "market_source": "the_odds_api",
        },
        # 3. Settled synthetic record
        {
            "event_id": "syn_1",
            "is_settled": True,
            "outcome": 0,
            "taiwan_odds": 1.80,
            "is_synthetic": True,
            "prediction_timestamp": (now - timedelta(hours=5)).isoformat(),
            "event_start": (now - timedelta(hours=3)).isoformat(),
            "model_probability": 0.60,
            "market_source": "SYNTHETIC",
        },
        # 4. Verified eligible forward sample
        {
            "event_id": "fwd_eligible_1",
            "is_settled": True,
            "outcome": 1,
            "taiwan_odds": 2.10,
            "is_synthetic": False,
            "prediction_timestamp": (now - timedelta(hours=6)).isoformat(),
            "event_start": (now - timedelta(hours=4)).isoformat(),
            "model_probability": 0.52,
            "market_source": "the_odds_api",
        },
        # 5. Unsettled pending record
        {
            "event_id": "pending_1",
            "is_settled": False,
            "taiwan_odds": 1.95,
            "prediction_timestamp": (now - timedelta(hours=1)).isoformat(),
            "event_start": (now + timedelta(hours=2)).isoformat(),
            "model_probability": 0.51,
            "market_source": "the_odds_api",
        },
    ]

    audit = p.audit_snapshots(sample_records)
    assert audit["total_count"] == 5
    assert audit["settled_count"] == 4
    assert audit["unsettled_pending_count"] == 1
    assert audit["pre_match_verified_count"] == 4
    assert audit["post_match_leak_count"] == 1
    assert audit["legacy_unverified_count"] == 1
    assert audit["synthetic_fixture_count"] == 1
    assert audit["eligible_forward_samples_count"] == 1
    assert audit["eligible_samples"][0]["event_id"] == "fwd_eligible_1"



