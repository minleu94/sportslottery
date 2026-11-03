"""Thread-safe construction of services shared by FastAPI routes.

The registry publishes a complete set only after construction succeeds. The
tuple-compatible named bundle preserves the historic route destructuring API
while giving new code explicit field names.
"""

from __future__ import annotations

import threading
from typing import NamedTuple, Optional

from core.betting_service import BettingService
from core.market_scheduler import get_market_scheduler, stop_market_scheduler_if_initialized
from core.parlay_engine import ParlayEngine
from core.performance_metrics import PerformanceMetricsEngine
from core.profile_manager import DEFAULT_PROFILE_ID, ProfileManager
from core.season_radar import SeasonRadar
from core.shadow_portfolio import ShadowPortfolioManager
from core.signal_hub import SignalHub
from core.snapshot_logger import PredictionSnapshotLogger
from core.ticket_recorder import TicketRecorder
from core.wallet import WeeklyWalletManager
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter


class ServiceBundle(NamedTuple):
    odds_adapter: PlaysportOddsAdapter
    signal_hub: SignalHub
    parlay_engine: ParlayEngine
    season_radar: SeasonRadar
    profile_mgr: ProfileManager
    snapshot_logger: PredictionSnapshotLogger
    metrics_engine: PerformanceMetricsEngine
    shadow_portfolio: ShadowPortfolioManager


class _SharedServices(NamedTuple):
    odds_adapter: PlaysportOddsAdapter
    signal_hub: SignalHub
    parlay_engine: ParlayEngine
    season_radar: SeasonRadar
    snapshot_logger: PredictionSnapshotLogger
    metrics_engine: PerformanceMetricsEngine
    shadow_portfolio: ShadowPortfolioManager


_services_init_lock = threading.Lock()
_shared_services: Optional[_SharedServices] = None
_profile_mgr: Optional[ProfileManager] = None


def get_services() -> ServiceBundle:
    """Return the shared services, constructing and publishing them atomically."""
    global _shared_services, _profile_mgr
    with _services_init_lock:
        if _shared_services is None:
            odds_adapter = PlaysportOddsAdapter()
            signal_hub = SignalHub()
            parlay_engine = ParlayEngine(signal_hub=signal_hub)
            season_radar = SeasonRadar()
            snapshot_logger = PredictionSnapshotLogger()
            metrics_engine = PerformanceMetricsEngine()
            shadow_portfolio = ShadowPortfolioManager()
            candidate = _SharedServices(
                odds_adapter,
                signal_hub,
                parlay_engine,
                season_radar,
                snapshot_logger,
                metrics_engine,
                shadow_portfolio,
            )
            _shared_services = candidate

        if _profile_mgr is None:
            _profile_mgr = ProfileManager()

        return ServiceBundle(
            _shared_services.odds_adapter,
            _shared_services.signal_hub,
            _shared_services.parlay_engine,
            _shared_services.season_radar,
            _profile_mgr,
            _shared_services.snapshot_logger,
            _shared_services.metrics_engine,
            _shared_services.shadow_portfolio,
        )


def get_wallet(profile_id: str = DEFAULT_PROFILE_ID) -> WeeklyWalletManager:
    return WeeklyWalletManager(profile_id=profile_id)


def get_recorder(profile_id: str = DEFAULT_PROFILE_ID) -> TicketRecorder:
    wallet = get_wallet(profile_id=profile_id)
    return TicketRecorder(wallet=wallet, profile_id=profile_id)


def get_betting_service(profile_id: str = DEFAULT_PROFILE_ID) -> BettingService:
    return BettingService(profile_id=profile_id)


__all__ = [
    "ServiceBundle",
    "get_betting_service",
    "get_market_scheduler",
    "get_recorder",
    "get_services",
    "get_wallet",
    "stop_market_scheduler_if_initialized",
]
