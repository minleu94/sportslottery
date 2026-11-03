"""FastAPI composition root and backward-compatible import facade."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.app_meta import APP_VERSION
from core.market_scheduler import get_market_scheduler, stop_market_scheduler_if_initialized
from server.lifecycle import lifespan
from server.formatters import clean_league_name
from server.service_registry import (
    ServiceBundle, get_betting_service, get_recorder, get_services, get_wallet,
)
from server.schemas import (
    AdminDeletePlayerRequest, AdminResetPinRequest, AdminUpdatePlayerRequest,
    DepositRequest, MarketKeyConfigRequest, MarketSchedulerConfigRequest,
    ParlaySearchRequest, PlaceTicketRequest, ProfileLoginByNameRequest,
    ProfileLoginRequest, ProfileRegisterRequest, ProfileUpdateRequest,
    SettleTicketRequest, TheOddsTestConnectionRequest, WithdrawRequest,
)
from server.routers import market as market_routes, parlay as parlay_routes, wallet as wallet_routes
from server.routers import identity as identity_routes, research as research_routes, line as line_routes
from server.routers.market import (
    health_check, get_radar, get_market_intelligence_status, get_market_research_summary,
    get_market_scheduler_status, update_market_scheduler_config, update_market_api_key,
    test_the_odds_api_connection, estimate_pipeline_cost, trigger_market_pipeline_cycle,
    get_market_benchmark_comparison, get_market_betting_splits, get_forward_evaluation_report, get_legs,
)
from server.routers.parlay import search_parlays, _execute_parlay_search, _get_prepared_parlay_legs
from server.routers.wallet import (
    get_wallet_status, wallet_deposit, wallet_withdraw, get_wallet_ledger, list_tickets, place_ticket, settle_ticket,
)
from server.routers.identity import (
    list_profiles, list_public_profiles, profile_login, profile_logout, get_auth_me, profile_register,
    verify_profile_pin, update_profile, get_admin_players_overview, admin_delete_player,
    admin_delete_player_post, admin_reset_player_pin, admin_update_player_settings,
)
from server.routers.research import get_research_analytics, get_system_storage_status
from server.routers.line import _line_notifier, verify_line_signature, process_line_events, line_webhook_callback
from server.auth import session_manager

logger = logging.getLogger("server.api")

app = FastAPI(
    title="Taiwan Sports Lottery API",
    description="台灣運彩「瘋狗流」高倍串關決策後端 API",
    version=APP_VERSION,
    lifespan=lifespan,
)

cors_env = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
if cors_env:
    cors_origins = [o.strip() for o in cors_env.split(",") if o.strip()]
    cors_origin_regex = None
else:
    cors_origins = [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:8000", "http://127.0.0.1:8000",
        "http://localhost:3000", "http://127.0.0.1:3000",
    ]
    cors_origin_regex = r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?$|^https://[a-zA-Z0-9-]+\.(trycloudflare\.com|ngrok-free\.app|ngrok\.app|ngrok\.io)(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Session-Token", "X-Line-Signature"],
)

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

for router in (
    market_routes.router, parlay_routes.router, wallet_routes.router,
    identity_routes.router, research_routes.router, line_routes.router,
):
    app.include_router(router)

(ROOT_DIR / "static" / "qr").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.api:app", host="127.0.0.1", port=8000, reload=True)
