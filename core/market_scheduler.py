#!/usr/bin/env python3
"""Market Intelligence Background Scheduler & Lifecycle Manager.

Phase 4.5: Automated In-Service Scheduling & Quota-Adaptive Forward Cycles.

Responsibilities:
1. Lifecycle Management: Starts and terminates in-process with FastAPI / Tray.
2. Quota-Adaptive Cadence: Adjusts interval (4h/6h/12h/24h) to conserve 500 req/mo free quota.
3. Concurrency Protection: Non-blocking execution lock prevents overlapping cycles.
4. Clean Shutdown: Event-driven worker thread terminates cleanly within milliseconds.
5. REST API Control: Enables on/off toggle, status queries, and manual override.
6. Data Isolation: Maintains strict synthetic tagging and exclusion from positive EV.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.market_forward_pipeline import MarketForwardPipeline
from integrations.odds.the_odds_api import QUOTA_SAFETY_MARGIN, TheOddsApiClient

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "research" / "scheduler_config.json"


def compute_adaptive_interval_seconds(
    quota_status: Dict[str, Any],
    base_interval: int = 14400,  # 4 hours default
    min_interval: int = 300,    # 5 minutes minimum guard
) -> int:
    """Calculate the optimal scheduling interval to conserve free tier quota (500 req/mo).

    Cadence Strategy:
    - Quota safety pause (remaining <= 5) or exhausted: 24h backoff (86400s) to freeze live requests.
    - Low quota (remaining <= 20): 12h backoff (43200s) (~2 requests/day).
    - Moderate quota (remaining <= 100): 6h cadence (21600s) (~4 requests/day).
    - Healthy quota (> 100) or Synthetic fixture: 4h default (14400s) (~6 requests/day).
    """
    mode = quota_status.get("operating_mode", "SYNTHETIC_FIXTURE")
    remaining = quota_status.get("requests_remaining_est", 500)

    # 1. Quota safety pause or exhausted
    if mode in ("QUOTA_SAFETY_PAUSE", "QUOTA_EXHAUSTED") or remaining <= QUOTA_SAFETY_MARGIN:
        return 86400  # 24 hours

    # 2. Synthetic fixture mode: No external API consumption
    if mode == "SYNTHETIC_FIXTURE":
        return max(min_interval, base_interval)

    # 3. Live API mode - tier based on remaining requests
    if remaining <= 20:
        return 43200  # 12 hours
    elif remaining <= 100:
        return 21600  # 6 hours
    else:
        return max(min_interval, base_interval)  # default 4 hours


class MarketScheduler:
    """In-process background scheduler for automated market data accumulation and validation."""

    def __init__(
        self,
        pipeline: Optional[MarketForwardPipeline] = None,
        base_interval_seconds: int = 14400,
        initial_delay_seconds: int = 60,
        config_path: Optional[Path] = None,
    ):
        self.pipeline = pipeline or MarketForwardPipeline()
        self.base_interval_seconds = max(300, base_interval_seconds)
        self.initial_delay_seconds = initial_delay_seconds
        self.config_path = config_path or CONFIG_PATH
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        self.enabled = True
        self._load_config()

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_executing = False

        self.last_run_utc: Optional[str] = None
        self.last_status: str = "IDLE"
        self.last_error: Optional[str] = None
        self.next_run_utc: Optional[str] = None
        self.current_interval_seconds: int = self.base_interval_seconds

        self.total_runs: int = 0
        self.successful_runs: int = 0
        self.failed_runs: int = 0
        self.consecutive_failures: int = 0

    def _load_config(self) -> None:
        """Load persistent scheduler toggle from local disk if present."""
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.enabled = bool(data.get("enabled", True))
                if "base_interval_seconds" in data:
                    self.base_interval_seconds = max(300, int(data["base_interval_seconds"]))
            except Exception as exc:
                logger.warning("Failed to load scheduler config: %s", exc)

    def _save_config(self) -> None:
        """Persist scheduler settings locally."""
        try:
            payload = {
                "enabled": self.enabled,
                "base_interval_seconds": self.base_interval_seconds,
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save scheduler config: %s", exc)

    def start(self) -> bool:
        """Start the background scheduler thread if not already running."""
        # Suppress automatic startup in test runners unless explicitly requested
        if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("ENABLE_MARKET_SCHEDULER_IN_TEST"):
            logger.info("MarketScheduler: Detected pytest environment; auto-start suppressed.")
            return False

        with self._lock:
            if self._thread and self._thread.is_alive():
                logger.info("MarketScheduler: Thread already running.")
                return True

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="MarketSchedulerWorker",
                daemon=True,
            )
            now = datetime.now(timezone.utc)
            self.next_run_utc = (now + timedelta(seconds=self.initial_delay_seconds)).isoformat()
            self._thread.start()
            logger.info(
                "MarketScheduler: Started background worker thread (initial delay %ds, base interval %ds).",
                self.initial_delay_seconds,
                self.base_interval_seconds,
            )
            return True

    def stop(self, timeout: float = 5.0) -> bool:
        """Signal worker thread to stop and wait for termination."""
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
            logger.info("MarketScheduler: Worker thread stopped.")
            self._thread = None
            return True
        return False

    def run_cycle_now(
        self,
        leagues: Optional[List[str]] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Execute a forward cycle immediately, guarded against concurrent overlapping execution."""
        if not self._lock.acquire(blocking=False):
            logger.warning("MarketScheduler: Cycle already executing; skipping overlapping run.")
            return {
                "status": "SKIPPED_CONCURRENT",
                "message": "已有一輪前瞻驗證週期正在執行中，避免重複運算與配額消耗。",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }

        self._is_executing = True
        self.last_status = "RUNNING"
        self.last_error = None

        try:
            # Query quota status and adapt cadence
            odds_status = self.pipeline.odds_client.get_source_status()
            adaptive_interval = compute_adaptive_interval_seconds(
                odds_status,
                base_interval=self.base_interval_seconds,
            )
            self.current_interval_seconds = adaptive_interval

            result = self.pipeline.run_full_cycle(leagues=leagues, force_refresh=force_refresh)

            self.last_run_utc = datetime.now(timezone.utc).isoformat()
            self.last_status = "SUCCESS"
            self.consecutive_failures = 0
            self.total_runs += 1
            self.successful_runs += 1

            # Recalculate next execution time
            self.next_run_utc = (datetime.now(timezone.utc) + timedelta(seconds=adaptive_interval)).isoformat()

            return {
                "status": "SUCCESS",
                "cycle_status": result.get("cycle_status", "SUCCESS"),
                "cycle_result": result,
                "snapshot_cycle": result.get("snapshot_cycle"),
                "settlement_cycle": result.get("settlement_cycle"),
                "evaluation_summary": result.get("evaluation_summary"),
                "interval_seconds": adaptive_interval,
                "next_run_utc": self.next_run_utc,
                "timestamp_utc": self.last_run_utc,
            }
        except Exception as exc:
            logger.error("MarketScheduler: Cycle execution failed: %s", exc, exc_info=True)
            self.last_run_utc = datetime.now(timezone.utc).isoformat()
            self.last_status = "FAILED"
            self.last_error = str(exc)
            self.consecutive_failures += 1
            self.total_runs += 1
            self.failed_runs += 1

            # Exponential backoff on failure (capped at 24h)
            backoff_interval = min(86400, self.current_interval_seconds * (2 ** min(self.consecutive_failures, 4)))
            self.next_run_utc = (datetime.now(timezone.utc) + timedelta(seconds=backoff_interval)).isoformat()

            return {
                "status": "FAILED",
                "error": str(exc),
                "timestamp_utc": self.last_run_utc,
            }
        finally:
            self._is_executing = False
            self._lock.release()

    def _worker_loop(self) -> None:
        """Background daemon loop."""
        # Initial delay before first run
        if self.initial_delay_seconds > 0:
            if self._stop_event.wait(self.initial_delay_seconds):
                return

        while not self._stop_event.is_set():
            if self.enabled:
                logger.info("MarketScheduler: Triggering scheduled forward cycle...")
                self.run_cycle_now()
            else:
                logger.debug("MarketScheduler: Scheduler is paused; skipping execution.")

            # Compute next run time
            interval = max(300, self.current_interval_seconds)
            if self.enabled:
                self.next_run_utc = (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat()
            else:
                self.next_run_utc = None

            # Wait for next interval or stop signal
            if self._stop_event.wait(interval):
                break

    def get_status(self) -> Dict[str, Any]:
        """Return operational scheduler metrics."""
        odds_status = self.pipeline.odds_client.get_source_status()
        return {
            "enabled": self.enabled,
            "is_running": bool(self._thread and self._thread.is_alive()),
            "is_executing": self._is_executing,
            "last_run_utc": self.last_run_utc,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "next_run_utc": self.next_run_utc if self.enabled else None,
            "interval_seconds": self.current_interval_seconds,
            "base_interval_seconds": self.base_interval_seconds,
            "quota_operating_mode": odds_status.get("operating_mode", "SYNTHETIC_FIXTURE"),
            "requests_remaining_est": odds_status.get("requests_remaining_est", 500),
            "stats": {
                "total_runs": self.total_runs,
                "successful_runs": self.successful_runs,
                "failed_runs": self.failed_runs,
                "consecutive_failures": self.consecutive_failures,
            },
            "as_of_utc": datetime.now(timezone.utc).isoformat(),
        }

    def update_config(
        self,
        enabled: Optional[bool] = None,
        interval_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Update scheduler configuration dynamically."""
        if enabled is not None:
            self.enabled = bool(enabled)
        if interval_seconds is not None:
            self.base_interval_seconds = max(300, int(interval_seconds))
            self.current_interval_seconds = self.base_interval_seconds

        if self.enabled:
            self.next_run_utc = (datetime.now(timezone.utc) + timedelta(seconds=self.current_interval_seconds)).isoformat()
        else:
            self.next_run_utc = None

        self._save_config()
        return self.get_status()


_scheduler_instance: Optional[MarketScheduler] = None
_scheduler_lock = threading.Lock()


def get_market_scheduler() -> MarketScheduler:
    """Return singleton instance of the MarketScheduler."""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is None:
            _scheduler_instance = MarketScheduler()
        return _scheduler_instance
