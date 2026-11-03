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
from integrations.odds.the_odds_api import QUOTA_SAFETY_MARGIN, SPORT_KEY_MAP, TheOddsApiClient

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "research" / "scheduler_config.json"


def _api_sport_request_count(leagues: Optional[List[str]]) -> int:
    """Count unique supported Odds API sport keys (aliases share one cached request)."""
    league_values = list(leagues or [])
    if not league_values:
        return 2
    mapped = {
        SPORT_KEY_MAP.get(str(league).upper())
        for league in league_values
    }
    supported = {key for key in mapped if key}
    return max(1, len(supported))


def _market_budget_setting(odds_client: Any) -> str:
    """Use the explicit scheduled allowlist, or the full configured cap for candidate-driven plans."""
    scheduled = getattr(odds_client, "scheduled_markets", "auto")
    if not isinstance(scheduled, str) or not scheduled.strip():
        scheduled = "auto"
    if scheduled.strip().casefold() in {"auto", "candidate", "candidate_driven"}:
        configured = getattr(odds_client, "markets", "h2h")
        return configured.strip() if isinstance(configured, str) and configured.strip() else "h2h"
    return scheduled.strip()


def compute_adaptive_interval_seconds(
    quota_status: Dict[str, Any],
    active_leagues: Optional[List[str]] = None,
    markets_per_sport: int = 1,
    region_count: int = 1,
    api_sport_count: Optional[int] = None,
    base_interval: int = 14400,  # 4 hours default
    min_interval: int = 14400,   # Minimum 4 hours to prevent high-frequency burn
    max_interval: int = 86400,   # 24 hours
) -> int:
    """Calculate Credit Budget-Aware scheduling interval.

    Enforces Phase 4.5 Budget Rules:
    1. Monthly Total: 500 credits.
    2. Manual Research Reserve: 50 credits strictly preserved.
    3. Max Automated Schedulable Budget: 450 credits.
    4. Quota Safety Pause: When remaining <= 50, pauses automated sync.
    5. Cadence adapts to: (Remaining Schedulable Credits / Days Left in Month) vs Cycle Cost.
    6. Never burns quota on high-frequency requests even when 500 credits remain.
    """
    mode = quota_status.get("operating_mode", "SYNTHETIC_FIXTURE")
    remaining = quota_status.get("requests_remaining_est", 500)
    manual_reserve = quota_status.get("manual_reserve_credits", 50)

    # 1. Quota safety pause / exhausted: strictly protect manual reserve
    if mode in ("QUOTA_SAFETY_PAUSE", "QUOTA_EXHAUSTED") or remaining <= manual_reserve:
        return max_interval  # 24h backoff

    # 2. Synthetic fixture or unconfigured mode: zero API consumption
    if mode in ("SYNTHETIC_FIXTURE", "UNCONFIGURED"):
        return max(300, base_interval)

    # 3. Calculate remaining days in current UTC month
    now_utc = datetime.now(timezone.utc)
    year = now_utc.year
    month = now_utc.month
    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    days_left = max(1, (next_month.date() - now_utc.date()).days)

    available_automated_credits = max(0, remaining - manual_reserve)
    daily_budget = available_automated_credits / days_left

    # Estimated cycle cost based on active leagues with Taiwan games
    leagues_count = api_sport_count or (len(active_leagues) if active_leagues else 2)
    cost_per_cycle = max(
        1,
        leagues_count * max(1, markets_per_sport) * max(1, region_count),
    )

    max_cycles_per_day = daily_budget / cost_per_cycle

    # Conservative distribution of budget
    if max_cycles_per_day < 1.0:
        return max_interval     # 24 hours (1 cycle/day or skip)
    elif max_cycles_per_day < 2.0:
        return 86400             # 24 hours
    elif max_cycles_per_day < 3.0:
        return 43200             # 12 hours (~2 cycles/day)
    elif max_cycles_per_day < 5.0:
        return 28800             # 8 hours (~3 cycles/day)
    else:
        # Ample budget: target base_interval (4 hours default), bounded by min_interval
        return max(min_interval, base_interval)


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
        self.last_cycle_summary: Optional[Dict[str, Any]] = None
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

        if (hasattr(self.pipeline, "scheduler_status_provider")
                and self.pipeline.scheduler_status_provider is None):
            self.pipeline.scheduler_status_provider = self.get_status

    def _load_config(self) -> None:
        """Load persistent scheduler toggle from local disk if present."""
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.enabled = bool(data.get("enabled", True))
                if "base_interval_seconds" in data:
                    self.base_interval_seconds = max(300, int(data["base_interval_seconds"]))
                summary = data.get("last_cycle_summary")
                if isinstance(summary, dict):
                    self.last_cycle_summary = summary
            except Exception as exc:
                logger.warning("Failed to load scheduler config: %s", exc)

    def _save_config(self) -> None:
        """Persist scheduler settings locally."""
        try:
            payload = {
                "enabled": self.enabled,
                "base_interval_seconds": self.base_interval_seconds,
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "last_cycle_summary": self.last_cycle_summary,
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
        automated: bool = False,
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
            if leagues is None and callable(getattr(type(self.pipeline), "resolve_target_leagues", None)):
                cycle_leagues = self.pipeline.resolve_target_leagues()
            else:
                cycle_leagues = leagues
            markets = _market_budget_setting(self.pipeline.odds_client)
            regions = getattr(self.pipeline.odds_client, "regions", "us") or "us"
            region_count = len([r for r in str(regions).split(",") if r.strip()])
            market_count = len([m for m in str(markets).split(",") if m.strip()])
            adaptive_interval = compute_adaptive_interval_seconds(
                odds_status,
                active_leagues=cycle_leagues,
                markets_per_sport=market_count,
                region_count=region_count,
                api_sport_count=_api_sport_request_count(cycle_leagues),
                base_interval=self.base_interval_seconds,
            )
            self.current_interval_seconds = adaptive_interval

            # Guard: If in safety pause or exhausted, skip automatic run to preserve 50-credit manual reserve
            if automated and odds_status.get("operating_mode") in ("QUOTA_SAFETY_PAUSE", "QUOTA_EXHAUSTED"):
                self.last_status = "SKIPPED_QUOTA_RESERVE"
                return {
                    "status": "SKIPPED_QUOTA_RESERVE_PROTECTION",
                    "cycle_status": "SKIPPED_QUOTA_RESERVE",
                    "message": "已達配額保護門檻 (剩餘 <= 50 credits)，自動排程已暫停以預留手動研究額度。",
                    "interval_seconds": adaptive_interval,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }

            result = self.pipeline.run_full_cycle(leagues=cycle_leagues, force_refresh=force_refresh, automated=automated)
            snapshot_cycle = result.get("snapshot_cycle") or {}
            self.last_cycle_summary = {
                "target_leagues": snapshot_cycle.get("target_leagues", cycle_leagues or []),
                "target_markets": snapshot_cycle.get("target_markets", markets),
                "target_regions": snapshot_cycle.get("target_regions", regions),
                "taiwan_snapshots_logged": snapshot_cycle.get("taiwan_snapshots_logged", 0),
                "valid_candidate_count": snapshot_cycle.get("valid_candidate_count", 0),
                "unique_candidate_event_count": snapshot_cycle.get("unique_candidate_event_count", 0),
                "real_market_quote_count": snapshot_cycle.get("real_market_quote_count", 0),
                "real_matched_count": snapshot_cycle.get("real_matched_count", 0),
                "complete_market_benchmark_count": snapshot_cycle.get("complete_market_benchmark_count", 0),
                "sharp_qualified_count": snapshot_cycle.get("sharp_qualified_count", 0),
                "ev_count": snapshot_cycle.get("ev_count", 0),
                "candidate_rejection_counts": snapshot_cycle.get("candidate_rejection_counts", {}),
                "alignment_rejection_counts": snapshot_cycle.get("alignment_rejection_counts", {}),
                "alignment_rejection_examples": snapshot_cycle.get("alignment_rejection_examples", {}),
                "query_diagnostics": snapshot_cycle.get("query_diagnostics", {}),
                "synthetic_market_quote_count": snapshot_cycle.get("synthetic_market_quote_count", 0),
                "synthetic_matched_count": snapshot_cycle.get("synthetic_matched_count", 0),
                "qualified_pending_candidate_count": snapshot_cycle.get("qualified_pending_candidate_count", 0),
                "credits_consumed": snapshot_cycle.get("credits_consumed", 0),
                "estimated_credits": snapshot_cycle.get("estimated_credits", 0),
                "official_credits_consumed": snapshot_cycle.get("official_credits_consumed"),
                "credit_accounting_source": snapshot_cycle.get("credit_accounting_source", "UNKNOWN"),
                "qualified_market_matches_per_credit": snapshot_cycle.get("qualified_market_matches_per_credit"),
                "settled_snapshot_count": (result.get("settlement_cycle") or {}).get("settled_count", 0),
                "unresolved_snapshot_count": (result.get("settlement_cycle") or {}).get("unresolved_count", 0),
                "result_fetch_errors": (result.get("settlement_cycle") or {}).get("result_fetch_errors", {}),
                "closure_status": result.get("cycle_status", "NO_QUALIFIED_REAL_MARKET_DATA"),
                "timestamp_utc": result.get("timestamp_utc"),
            }
            self._save_config()

            self.last_run_utc = datetime.now(timezone.utc).isoformat()
            result_fetch_errors = (result.get("settlement_cycle") or {}).get("result_fetch_errors") or {}
            if result.get("operation_status") == "PARTIAL" or result_fetch_errors:
                self.last_status = "PARTIAL"
                self.last_error = "賽果來源抓取失敗，已保留未結算快照並安排重試。"
                self.consecutive_failures += 1
                self.total_runs += 1
                self.failed_runs += 1
                backoff_interval = min(
                    86400,
                    adaptive_interval * (2 ** min(self.consecutive_failures, 4)),
                )
                self.current_interval_seconds = backoff_interval
                self.next_run_utc = (datetime.now(timezone.utc) + timedelta(seconds=backoff_interval)).isoformat()
                return {
                    "status": "PARTIAL",
                    "cycle_status": result.get("cycle_status", "NO_QUALIFIED_REAL_MARKET_DATA"),
                    "operation_status": "PARTIAL",
                    "error": self.last_error,
                    "cycle_result": result,
                    "snapshot_cycle": result.get("snapshot_cycle"),
                    "settlement_cycle": result.get("settlement_cycle"),
                    "evaluation_summary": result.get("evaluation_summary"),
                    "interval_seconds": backoff_interval,
                    "next_run_utc": self.next_run_utc,
                    "timestamp_utc": self.last_run_utc,
                }

            self.last_status = "SUCCESS"
            self.consecutive_failures = 0
            self.total_runs += 1
            self.successful_runs += 1

            # Recalculate next execution time
            self.next_run_utc = (datetime.now(timezone.utc) + timedelta(seconds=adaptive_interval)).isoformat()

            return {
                "status": "SUCCESS",
                "cycle_status": result.get("cycle_status", "NO_QUALIFIED_REAL_MARKET_DATA"),
                "operation_status": result.get("operation_status", "SUCCESS"),
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
                self.run_cycle_now(automated=True)
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
        """Return operational scheduler metrics and budget allocation."""
        odds_status = self.pipeline.odds_client.get_source_status()
        now_utc = datetime.now(timezone.utc)
        year, month = now_utc.year, now_utc.month
        next_m = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)
        days_left = max(1, (next_m.date() - now_utc.date()).days)

        rem_est = odds_status.get("requests_remaining_est", 500)
        sched_rem = max(0, rem_est - 50)
        daily_allowance = round(sched_rem / days_left, 1)
        regions = getattr(self.pipeline.odds_client, "regions", "us") or "us"
        markets = _market_budget_setting(self.pipeline.odds_client)
        estimated_leagues = (
            self.last_cycle_summary.get("target_leagues")
            if self.last_cycle_summary
            else ["MLB", "NBA", "NFL", "SOCCER"]
        )
        estimated_cycle_cost = (
            _api_sport_request_count(estimated_leagues or ["MLB", "NBA", "NFL", "SOCCER"])
            * len([m for m in str(markets).split(",") if m.strip()])
            * len([r for r in str(regions).split(",") if r.strip()])
        )

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
            "requests_remaining_est": rem_est,
            "credit_budget": {
                "monthly_total": 500,
                "manual_reserve": 50,
                "automated_budget": 450,
                "days_remaining_in_month": days_left,
                "daily_schedulable_budget": daily_allowance,
                "next_cycle_estimated_cost": estimated_cycle_cost,
                "estimated_cycle_leagues": estimated_leagues,
                "estimated_cycle_markets": markets,
                "estimated_cycle_regions": regions,
            },
            "last_cycle_summary": self.last_cycle_summary,
            "stats": {
                "total_runs": self.total_runs,
                "successful_runs": self.successful_runs,
                "failed_runs": self.failed_runs,
                "consecutive_failures": self.consecutive_failures,
            },
            "as_of_utc": now_utc.isoformat(),
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


def stop_market_scheduler_if_initialized() -> bool:
    """Stop an existing scheduler at process exit without constructing one during shutdown."""
    with _scheduler_lock:
        scheduler = _scheduler_instance
    return scheduler.stop() if scheduler is not None else False
