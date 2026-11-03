#!/usr/bin/env python3
"""Tests for Global Market Intelligence REST API Endpoints.

Milestone 6 Verification:
- Tests /api/market/status returns healthy configuration & quota status
- Tests /api/market/benchmark returns aligned international quotes & EV
- Tests /api/market/splits returns ticket % vs money % splits
- Tests /api/market/evaluation returns three-way forward evaluation report
"""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import pytest

from server import service_registry
from server.routers import market as market_routes
from server.api import app
from core.profile_manager import DEFAULT_PROFILE_ID, ProfileManager
from integrations.odds.the_odds_api import TheOddsApiClient
from integrations.odds.betting_splits_client import BettingSplitsClient
from core.snapshot_logger import PredictionSnapshotLogger
from server.auth import session_manager

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def authenticated_admin_client(tmp_path_factory):
    """Use an isolated temporary profile database for this offline endpoint suite."""
    profile_db = tmp_path_factory.mktemp("market-api-auth") / "profiles.sqlite3"
    profile_manager = ProfileManager(db_path=profile_db)
    admin_profile = profile_manager.get_profile(DEFAULT_PROFILE_ID)
    assert admin_profile is not None
    admin_check = patch.object(ProfileManager, "is_default_admin_pin", return_value=False)
    admin_check.start()
    token = session_manager.create_session(admin_profile)
    client.headers.update({"Authorization": f"Bearer {token}"})
    try:
        yield
    finally:
        client.headers.pop("Authorization", None)
        session_manager.revoke_session(token)
        admin_check.stop()


@pytest.fixture(autouse=True)
def prevent_odds_api_requests(monkeypatch):
    """Keep endpoint tests offline and isolated from local research data."""
    monkeypatch.setattr(TheOddsApiClient, "fetch_market_odds", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        TheOddsApiClient, "get_source_status",
        lambda self: {"has_api_key": True, "key_source": "LOCAL_CONFIG", "status": "HEALTHY"},
    )
    monkeypatch.setattr(TheOddsApiClient, "save_api_key", lambda self, key: True)
    monkeypatch.setattr(TheOddsApiClient, "reload_api_key", lambda self: None)
    monkeypatch.setattr(BettingSplitsClient, "get_betting_splits", lambda self, league: [])
    monkeypatch.setattr(PredictionSnapshotLogger, "get_all_snapshots", lambda self: [])
    monkeypatch.setattr(
        service_registry, "get_services",
        lambda: (MagicMock(get_taiwan_legs=lambda leagues, **kwargs: []), MagicMock(),
                 MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()),
    )
    monkeypatch.setattr(
        market_routes, "get_market_scheduler",
        lambda: MagicMock(pipeline=MagicMock()),
    )


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
    summary = {
        "live_status": "SYNTHETIC_FIXTURE",
        "live_status_scope": "ODDS_API_SOURCE_STATUS_ONLY",
        "alignment": {"status": "NO_RECORDED_CYCLE"},
        "the_odds_api": {"status": "HEALTHY"},
        "snapshots": {"total_count": 0},
        "forward_evaluation": {"sample_size": 0},
        "as_of_utc": "2026-11-02T00:00:00+00:00",
    }
    pipeline = MagicMock()
    pipeline.get_research_status_summary.return_value = summary
    with patch("core.market_forward_pipeline.MarketForwardPipeline", return_value=pipeline), patch(
        "server.routers.market.get_market_scheduler", return_value=MagicMock(get_status=lambda: {"enabled": False})
    ):
        resp = client.get("/api/market/research-summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "live_status" in data
    assert data["live_status_scope"] == "ODDS_API_SOURCE_STATUS_ONLY"
    assert "alignment" in data
    assert data["alignment"]["status"] in {
        "NO_RECORDED_CYCLE", "REAL_QUOTES_MATCHED", "NO_REAL_QUOTES_MATCHED"
    }
    assert "the_odds_api" in data
    assert "snapshots" in data
    assert "forward_evaluation" in data
    assert "total_count" in data["snapshots"]
    assert "sample_size" in data["forward_evaluation"]


def test_post_market_config():
    # Saving is mocked by the offline fixture; this validates route semantics
    # without replacing a developer's local API configuration.
    resp = client.post("/api/market/config", json={"the_odds_api_key": "test_key_api_12345"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    bad_resp = client.post("/api/market/config", json={"the_odds_api_key": "bad; key!@#$"})
    assert bad_resp.status_code == 400


def test_post_market_pipeline_cycle():
    from unittest.mock import MagicMock
    scheduler = MagicMock()
    scheduler.run_cycle_now.return_value = {
        "status": "SUCCESS",
        "cycle_status": "NO_QUALIFIED_REAL_MARKET_DATA",
    }
    with patch("server.routers.market.get_market_scheduler", return_value=scheduler):
        resp = client.post("/api/market/pipeline/cycle?leagues=MLB")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cycle_status"] == "NO_QUALIFIED_REAL_MARKET_DATA"


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
    assert data["regions"] == "us,eu"
    assert data["region_count"] == 2
    assert data["estimated_credits"] == 4


def test_pipeline_audit_snapshots(tmp_path):
    """Verify MarketForwardPipeline.audit_snapshots classifies historical vs eligible records accurately."""
    from core.market_forward_pipeline import MarketForwardPipeline
    from datetime import datetime, timezone, timedelta

    p = MarketForwardPipeline(
        odds_adapter=MagicMock(), odds_client=MagicMock(), signal_hub=MagicMock(),
        aligner=MagicMock(), fair_engine=MagicMock(), snapshot_logger=MagicMock(),
        settlement_engine=MagicMock(), evaluation_engine=MagicMock(),
        summary_path=tmp_path / "summary.json",
    )
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
            "forward_validation_eligible": True,
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
    from core.snapshot_logger import compute_prediction_payload_hash
    sample_records[3]["prediction_hash_schema"] = 3
    sample_records[3]["prediction_payload_hash"] = compute_prediction_payload_hash(sample_records[3])

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



