"""Comprehensive test suite for the modern FastAPI backend and SPA integration."""

import pytest
from fastapi.testclient import TestClient
from server.api import app

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "strategy_metadata" in data
    assert "alliances" in data


def test_wallet_status():
    response = client.get("/api/wallet/status?profile_id=default")
    assert response.status_code == 200
    data = response.json()
    assert "weekly_wallet_balance" in data
    assert "prize_pool" in data
    assert "weekly_play_cap" in data
    assert data["weekly_play_cap"] == 200.0


def test_profiles_and_pin():
    from core.profile_manager import ProfileManager
    pm = ProfileManager()
    actual_pin = pm.get_profile("default")["pin_code"]

    # 1. List profiles
    response = client.get("/api/profiles")
    assert response.status_code == 200
    data = response.json()
    assert len(data["profiles"]) >= 1
    default_p = next(p for p in data["profiles"] if p["id"] == "default")
    assert isinstance(default_p["name"], str) and len(default_p["name"]) > 0

    # 2. Verify correct PIN
    verify_res = client.post(
        "/api/profiles/verify_pin",
        json={"profile_id": "default", "pin_code": actual_pin},
    )
    assert verify_res.status_code == 200
    assert verify_res.json()["success"] is True

    # 3. Verify incorrect PIN
    bad_res = client.post(
        "/api/profiles/verify_pin",
        json={"profile_id": "default", "pin_code": "9998" if actual_pin != "9998" else "9997"},
    )
    assert bad_res.status_code == 401


def test_radar_and_legs():
    # Test radar summary
    res_radar = client.get("/api/radar")
    assert res_radar.status_code == 200
    r_data = res_radar.json()
    assert "radar" in r_data
    assert "status_counts" in r_data
    assert isinstance(r_data["radar"], list)

    # Test legs
    res_legs = client.get("/api/legs?limit=10")
    assert res_legs.status_code == 200
    l_data = res_legs.json()
    assert "legs" in l_data
    assert l_data["returned"] <= 10


def test_parlay_search():
    res = client.post(
        "/api/parlays/search",
        json={
            "target_odds": 20.0,
            "tolerance": 0.4,
            "min_legs": 2,
            "max_legs": 4,
            "signal_filter": "wild",
            "search_budget": 5000,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "tiers" in data
    assert "high_consensus" in data["tiers"]
    assert "aggressive" in data["tiers"]
    assert "moonshot" in data["tiers"]
    assert "diagnostics" in data


def test_research_analytics():
    res = client.get("/api/research/analytics")
    assert res.status_code == 200
    data = res.json()
    assert "total_snapshots" in data
    assert "cohort" in data
    assert "shadow_portfolio" in data


def test_frontend_spa_serving():
    # Verify root index.html is served
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert '<div id="root">' in res.text


def test_line_callback():
    # Verify LINE webhook endpoint responds with status ok
    res = client.post("/callback", json={"events": []})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["events_processed"] == 0
