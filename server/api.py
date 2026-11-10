"""FastAPI composition root and backward-compatible import facade."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:8100",
    "http://127.0.0.1:8100",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


def _normalize_origin(value: str | None) -> str | None:
    """Return a canonical HTTP(S) origin, rejecting paths and wildcard forms."""
    if not value or "*" in value:
        return None
    try:
        parsed = urlsplit(value.strip())
        scheme = parsed.scheme.lower()
        if (
            scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        host = parsed.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        port = parsed.port
        if port is not None and not (scheme == "http" and port == 80) and not (scheme == "https" and port == 443):
            host = f"{host}:{port}"
        return f"{scheme}://{host}"
    except ValueError:
        return None


def _load_cors_origins(raw_origins: str) -> list[str]:
    """Load exact trusted browser origins; credentialed wildcard CORS is forbidden."""
    if not raw_origins.strip():
        return list(DEFAULT_CORS_ORIGINS)
    origins: list[str] = []
    for entry in raw_origins.split(","):
        value = entry.strip()
        if not value:
            continue
        normalized = _normalize_origin(value)
        if normalized is None:
            raise ValueError(
                "CORS_ALLOWED_ORIGINS must contain exact http(s) origins without paths or wildcards."
            )
        if normalized not in origins:
            origins.append(normalized)
    if not origins:
        raise ValueError("CORS_ALLOWED_ORIGINS must contain at least one exact origin.")
    return origins


cors_origins = _load_cors_origins(os.environ.get("CORS_ALLOWED_ORIGINS", ""))
cors_origin_regex = None
CSRF_EXEMPT_PUBLIC_PATHS = {
    "/api/profiles/register",
    "/api/profiles/login",
    "/api/profiles/verify_pin",
    "/callback",  # LINE requests have their own HMAC signature verification.
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Session-Token", "X-Session-Mode", "X-Line-Signature"],
)

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    unsafe_method = request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
    has_legacy_header_token = bool(
        request.headers.get("authorization") or request.headers.get("x-session-token")
    )
    origin = request.headers.get("origin")
    if (
        unsafe_method
        and request.url.path not in CSRF_EXEMPT_PUBLIC_PATHS
        and request.cookies.get("auth_session_token")
        and not has_legacy_header_token
    ):
        if not origin:
            referer = request.headers.get("referer", "")
            try:
                parsed_referer = urlsplit(referer)
                if parsed_referer.scheme and parsed_referer.netloc:
                    origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
            except ValueError:
                origin = None
        if not origin:
            return JSONResponse(status_code=403, content={"detail": "Request origin is required."})
        normalized_origin = _normalize_origin(origin)
        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
        scheme = forwarded_proto.lower() if forwarded_proto else request.url.scheme.lower()
        request_host = request.headers.get("host", "")
        same_origin = _normalize_origin(f"{scheme}://{request_host}")
        if normalized_origin is None or (
            normalized_origin not in cors_origins and normalized_origin != same_origin
        ):
            return JSONResponse(status_code=403, content={"detail": "Untrusted request origin."})

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
    uvicorn.run("server.api:app", host="127.0.0.1", port=8100, reload=True)
