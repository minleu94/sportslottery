#!/usr/bin/env python3
"""Automated Unit and Lifecycle Tests for Market Intelligence Background Scheduler.

Phase 4.5: Validates in-service scheduler start/stop lifecycle, quota-adaptive cadence,
anti-overlap execution locks, fail-closed handling, and REST API controls.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.market_scheduler import (
    MarketScheduler,
    compute_adaptive_interval_seconds,
    get_market_scheduler,
)
from server.api import app


@pytest.fixture
def test_client():
    return TestClient(app)


def test_compute_adaptive_interval_seconds():
    """Verify quota-adaptive cadence adjusts properly based on remaining API quota."""
    # 1. Quota safety pause / exhausted -> 24h backoff
    assert compute_adaptive_interval_seconds({"operating_mode": "QUOTA_SAFETY_PAUSE", "requests_remaining_est": 4}) == 86400
    assert compute_adaptive_interval_seconds({"operating_mode": "QUOTA_EXHAUSTED", "requests_remaining_est": 0}) == 86400
    assert compute_adaptive_interval_seconds({"operating_mode": "LIVE_API", "requests_remaining_est": 5}) == 86400

    # 2. Low quota (<= 20) -> 12h
    assert compute_adaptive_interval_seconds({"operating_mode": "LIVE_API", "requests_remaining_est": 18}) == 43200

    # 3. Medium quota (<= 100) -> 6h
    assert compute_adaptive_interval_seconds({"operating_mode": "LIVE_API", "requests_remaining_est": 85}) == 21600

    # 4. Healthy quota (> 100) -> 4h default (14400s)
    assert compute_adaptive_interval_seconds({"operating_mode": "LIVE_API", "requests_remaining_est": 450}) == 14400

    # 5. Synthetic fixture mode -> 4h default (does not burn quota)
    assert compute_adaptive_interval_seconds({"operating_mode": "SYNTHETIC_FIXTURE", "requests_remaining_est": 500}) == 14400


def test_scheduler_lifecycle_start_and_stop(tmp_path):
    """Verify scheduler worker thread starts and cleanly terminates via stop event."""
    mock_pipeline = MagicMock()
    mock_pipeline.odds_client.get_source_status.return_value = {
        "operating_mode": "SYNTHETIC_FIXTURE",
        "requests_remaining_est": 500,
    }

    cfg_file = tmp_path / "scheduler_test_cfg.json"
    scheduler = MarketScheduler(
        pipeline=mock_pipeline,
        base_interval_seconds=600,
        initial_delay_seconds=10,
        config_path=cfg_file,
    )

    # Initial state
    status = scheduler.get_status()
    assert status["enabled"] is True
    assert status["is_running"] is False
    assert status["last_status"] == "IDLE"

    # Start thread (with test env override)
    with patch.dict(os.environ, {"ENABLE_MARKET_SCHEDULER_IN_TEST": "1"}):
        started = scheduler.start()
        assert started is True
        assert scheduler.get_status()["is_running"] is True
        assert scheduler.next_run_utc is not None

        # Clean stop
        stopped = scheduler.stop(timeout=2.0)
        assert stopped is True
        assert scheduler.get_status()["is_running"] is False


def test_scheduler_concurrency_lock_prevents_overlap(tmp_path):
    """Verify that multiple concurrent executions are rejected via non-blocking lock."""
    mock_pipeline = MagicMock()
    mock_pipeline.odds_client.get_source_status.return_value = {
        "operating_mode": "SYNTHETIC_FIXTURE",
        "requests_remaining_est": 500,
    }

    # Simulate long-running cycle
    def slow_cycle(*args, **kwargs):
        time.sleep(0.3)
        return {"status": "SUCCESS"}

    mock_pipeline.run_full_cycle.side_effect = slow_cycle

    cfg_file = tmp_path / "scheduler_concurrency.json"
    scheduler = MarketScheduler(
        pipeline=mock_pipeline,
        base_interval_seconds=600,
        initial_delay_seconds=60,
        config_path=cfg_file,
    )

    results = []

    def run_worker():
        res = scheduler.run_cycle_now()
        results.append(res)

    t1 = threading.Thread(target=run_worker)
    t2 = threading.Thread(target=run_worker)

    t1.start()
    time.sleep(0.05)  # Ensure t1 acquires the lock
    t2.start()

    t1.join()
    t2.join()

    # One should succeed, one should be skipped
    statuses = [r["status"] for r in results]
    assert "SUCCESS" in statuses
    assert "SKIPPED_CONCURRENT" in statuses


def test_scheduler_config_update_and_persistence(tmp_path):
    """Verify enabling/disabling and interval updates persist to disk."""
    mock_pipeline = MagicMock()
    mock_pipeline.odds_client.get_source_status.return_value = {
        "operating_mode": "SYNTHETIC_FIXTURE",
        "requests_remaining_est": 500,
    }

    cfg_file = tmp_path / "scheduler_persist.json"
    scheduler = MarketScheduler(
        pipeline=mock_pipeline,
        base_interval_seconds=14400,
        config_path=cfg_file,
    )

    # Disable scheduler
    status = scheduler.update_config(enabled=False)
    assert status["enabled"] is False
    assert status["next_run_utc"] is None
    assert cfg_file.exists()

    # Re-instantiate from config file to test persistence
    reloaded = MarketScheduler(
        pipeline=mock_pipeline,
        config_path=cfg_file,
    )
    assert reloaded.enabled is False

    # Re-enable and update interval
    status_updated = reloaded.update_config(enabled=True, interval_seconds=7200)
    assert status_updated["enabled"] is True
    assert status_updated["interval_seconds"] == 7200
    assert status_updated["next_run_utc"] is not None


def test_scheduler_handles_pipeline_failure(tmp_path):
    """Verify that exceptions during cycle execution do not crash the scheduler and trigger backoff."""
    mock_pipeline = MagicMock()
    mock_pipeline.odds_client.get_source_status.return_value = {
        "operating_mode": "SYNTHETIC_FIXTURE",
        "requests_remaining_est": 500,
    }
    mock_pipeline.run_full_cycle.side_effect = RuntimeError("Network timeout simulation")

    cfg_file = tmp_path / "scheduler_fail.json"
    scheduler = MarketScheduler(
        pipeline=mock_pipeline,
        base_interval_seconds=600,
        config_path=cfg_file,
    )

    res = scheduler.run_cycle_now()
    assert res["status"] == "FAILED"
    assert "Network timeout simulation" in res["error"]

    status = scheduler.get_status()
    assert status["last_status"] == "FAILED"
    assert status["stats"]["failed_runs"] == 1
    assert status["stats"]["consecutive_failures"] == 1
    assert not scheduler._is_executing  # Lock must be released


def test_api_scheduler_endpoints(test_client):
    """Verify REST API endpoints for scheduler status, config update, and cycle execution."""
    # 1. GET /api/market/scheduler/status
    res = test_client.get("/api/market/scheduler/status")
    assert res.status_code == 200
    data = res.json()
    assert "enabled" in data
    assert "is_running" in data
    assert "interval_seconds" in data
    assert "stats" in data

    # 2. POST /api/market/scheduler/config (update settings)
    res_cfg = test_client.post(
        "/api/market/scheduler/config",
        json={"enabled": True, "interval_seconds": 3600},
    )
    assert res_cfg.status_code == 200
    updated_data = res_cfg.json()
    assert updated_data["enabled"] is True
    assert updated_data["interval_seconds"] == 3600

    # 3. GET /api/market/research-summary embeds scheduler status
    res_sum = test_client.get("/api/market/research-summary")
    assert res_sum.status_code == 200
    sum_data = res_sum.json()
    assert "scheduler" in sum_data
    assert sum_data["scheduler"]["enabled"] is True

    # 4. POST /api/market/pipeline/cycle delegates to scheduler
    res_cycle = test_client.post("/api/market/pipeline/cycle")
    assert res_cycle.status_code == 200
    cycle_data = res_cycle.json()
    assert cycle_data.get("status") in {"SUCCESS", "SKIPPED_CONCURRENT"}
