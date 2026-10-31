#!/usr/bin/env python3
"""Tests for Global Market Intelligence REST API Endpoints.

Milestone 6 Verification:
- Tests /api/market/status returns healthy configuration & quota status
- Tests /api/market/benchmark returns aligned international quotes & EV
- Tests /api/market/splits returns ticket % vs money % splits
- Tests /api/market/evaluation returns three-way forward evaluation report
"""

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
