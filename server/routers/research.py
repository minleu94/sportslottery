from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends

from server import service_registry
from server.auth import require_active_admin_session
from server.responses import ResearchAnalyticsResponse

logger = logging.getLogger("server.api")
_analytics_cache = None
_analytics_cache_mtime = 0
_analytics_cache_time = 0
_analytics_cache_lock = threading.Lock()

router = APIRouter()



@router.get("/api/research/analytics", response_model=ResearchAnalyticsResponse)
def get_research_analytics():
    global _analytics_cache, _analytics_cache_mtime, _analytics_cache_time
    _, _, _, _, _, snapshot_logger, metrics_engine, shadow_portfolio = service_registry.get_services()

    mtime_ns = 0
    try:
        if snapshot_logger.log_path.exists():
            mtime_ns = snapshot_logger.log_path.stat().st_mtime_ns
    except Exception:
        pass

    now_ts = time.time()
    with _analytics_cache_lock:
        if (
            _analytics_cache is not None
            and _analytics_cache_mtime == mtime_ns
            and (now_ts - _analytics_cache_time) < 120.0
        ):
            return _analytics_cache

    try:
        snaps = snapshot_logger.get_all_snapshots()
    except Exception:
        snaps = []

    try:
        cohort = metrics_engine.forward_cohort(snaps)
        agreement = metrics_engine.evaluate_agreement_buckets(snaps)
        ev_data = metrics_engine.evaluate_ev_buckets(snaps)
        crowd_data = metrics_engine.evaluate_crowd_buckets(snaps)
        expert_data = metrics_engine.evaluate_expert_metrics(snaps)
    except Exception:
        cohort, agreement, ev_data, crowd_data, expert_data = {}, {}, {}, {}, {}

    try:
        portfolio_summary = shadow_portfolio.get_portfolio_summary()
    except Exception:
        portfolio_summary = {}

    result = {
        "total_snapshots": len(snaps),
        "cohort": cohort,
        "agreement": agreement,
        "ev_data": ev_data,
        "crowd_data": crowd_data,
        "expert_data": expert_data,
        "shadow_portfolio": portfolio_summary,
    }

    with _analytics_cache_lock:
        _analytics_cache = result
        _analytics_cache_mtime = mtime_ns
        _analytics_cache_time = now_ts

    return result


@router.get("/api/system/storage_status")
def get_system_storage_status(
    session: Dict[str, Any] = Depends(require_active_admin_session),
):
    """System runtime and storage status (restricted to active admin sessions; hides absolute server paths)."""
    from core.storage_config import get_storage_stats, get_scheduled_task_status, get_storage_root
    try:
        stats = get_storage_stats()
    except Exception:
        stats = {}
    try:
        task_status = get_scheduled_task_status()
    except Exception:
        task_status = {"installed": False, "enabled": False}

    raw_root = str(get_storage_root())
    masked_root = f".../{Path(raw_root).name}"
    return {
        "storage_root": masked_root,
        "stats": stats,
        "scheduled_task": task_status,
    }
