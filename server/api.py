#!/usr/bin/env python3
"""FastAPI Backend Server for Taiwan Sports Lottery Decision System.

Provides high-performance RESTful API endpoints for:
- Season Radar & Live Odds Feed (Playsport / ESPN)
- Crazy Dog Parlay Combinatorial Search (10~500x)
- Weekly Wallet Accounting (NT$200 weekly cap, prize pool isolation)
- Bet Ticket Recording & Settlement
- Player Profile & PIN Authentication
- Model Research Analytics
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Body, Request, BackgroundTasks, Header, Response, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

logger = logging.getLogger("server.api")

from core.bet_validation import assess_leg
from core.app_meta import APP_BUILD, APP_VERSION
from core.line_notifier import LineNotifier
from core.model_registry import ModelRegistry
from core.parlay_engine import ParlayEngine
from core.performance_metrics import PerformanceMetricsEngine
from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID
from core.scraper import ALLIANCE_MAP
from core.season_radar import SeasonRadar
from core.shadow_portfolio import ShadowPortfolioManager
from core.forward_evaluation_engine import ForwardEvaluationEngine
from core.market_aligner import MarketAligner
from core.market_fair_odds import MarketFairOddsEngine
from core.signal_hub import SignalHub
from core.snapshot_logger import PredictionSnapshotLogger
from core.strategy_version import get_strategy_metadata
from core.ticket_recorder import TicketRecorder
from core.wallet import WeeklyWalletManager
from core.betting_service import BettingService
from integrations.common.models import TaiwanLeg
from integrations.odds.betting_splits_client import BettingSplitsClient
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter
from integrations.odds.the_odds_api import TheOddsApiClient
from server.auth import (
    session_manager,
    require_any_authenticated_session,
    require_authenticated_session,
    require_active_admin_session,
    verify_no_pending_password_change,
    verify_profile_ownership,
    get_current_session_optional,
    SESSION_TTL_SECONDS,
)
from server.security import login_rate_limiter, get_client_ip, log_security_event

app = FastAPI(
    title="Taiwan Sports Lottery API",
    description="台灣運彩「瘋狗流」高倍串關決策後端 API",
    version=APP_VERSION,
)

# CORS middleware with strict origin whitelist & LAN/tunnel regex (no wildcard credentials)
cors_env = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
if cors_env:
    cors_origins = [o.strip() for o in cors_env.split(",") if o.strip()]
    cors_origin_regex = None
else:
    cors_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    cors_origin_regex = r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?$|^https://[a-zA-Z0-9-]+\.(trycloudflare\.com|ngrok-free\.app|ngrok\.app|ngrok\.io)(:\d+)?$"

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
    """Inject defensive HTTP security headers."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# Global lazy singletons
_odds_adapter: Optional[PlaysportOddsAdapter] = None
_signal_hub: Optional[SignalHub] = None
_parlay_engine: Optional[ParlayEngine] = None
_season_radar: Optional[SeasonRadar] = None
_profile_mgr: Optional[ProfileManager] = None
_snapshot_logger: Optional[PredictionSnapshotLogger] = None
_metrics_engine: Optional[PerformanceMetricsEngine] = None
_shadow_portfolio: Optional[ShadowPortfolioManager] = None


def get_services():
    global _odds_adapter, _signal_hub, _parlay_engine, _season_radar
    global _profile_mgr, _snapshot_logger, _metrics_engine, _shadow_portfolio
    if _odds_adapter is None:
        _odds_adapter = PlaysportOddsAdapter()
        _signal_hub = SignalHub()
        _parlay_engine = ParlayEngine(signal_hub=_signal_hub)
        _season_radar = SeasonRadar()
        _profile_mgr = ProfileManager()
        _snapshot_logger = PredictionSnapshotLogger()
        _metrics_engine = PerformanceMetricsEngine()
        _shadow_portfolio = ShadowPortfolioManager()
    return (
        _odds_adapter,
        _signal_hub,
        _parlay_engine,
        _season_radar,
        _profile_mgr,
        _snapshot_logger,
        _metrics_engine,
        _shadow_portfolio,
    )


def get_wallet(profile_id: str = DEFAULT_PROFILE_ID) -> WeeklyWalletManager:
    return WeeklyWalletManager(profile_id=profile_id)


def get_recorder(profile_id: str = DEFAULT_PROFILE_ID) -> TicketRecorder:
    wallet = get_wallet(profile_id=profile_id)
    return TicketRecorder(wallet=wallet, profile_id=profile_id)


def get_betting_service(profile_id: str = DEFAULT_PROFILE_ID) -> BettingService:
    return BettingService(profile_id=profile_id)


# --- Request/Response Models ---

class ParlaySearchRequest(BaseModel):
    target_odds: float = Field(default=20.0, ge=2.0, le=5000.0)
    min_odds: Optional[float] = None
    max_odds: Optional[float] = None
    tolerance: float = Field(default=0.25, ge=0.01, le=1.0)
    min_legs: int = Field(default=2, ge=2, le=8)
    max_legs: int = Field(default=6, ge=2, le=8)
    alliances: Optional[List[str]] = None
    signal_filter: str = Field(default="normal")  # normal, value_only, strict, wild
    exclude_traps: bool = False
    prefer_steam: bool = True
    search_budget: int = Field(default=50000, ge=1000, le=1000000)
    force_refresh: bool = False


class DepositRequest(BaseModel):
    profile_id: str = DEFAULT_PROFILE_ID
    amount: float = Field(gt=0)
    notes: str = ""


class WithdrawRequest(BaseModel):
    profile_id: str = DEFAULT_PROFILE_ID
    amount: float = Field(gt=0)


class PlaceTicketRequest(BaseModel):
    profile_id: str = DEFAULT_PROFILE_ID
    legs: List[Dict[str, Any]]
    stake: float = Field(ge=10.0)
    placed_odds: float = Field(gt=1.0)
    recommendation_odds: Optional[float] = None
    parlay_name: Optional[str] = "瘋狗串關"
    notes: Optional[str] = "前端下注記錄"
    idempotency_key: Optional[str] = None
    client_request_id: Optional[str] = None
    entry_mode: Optional[str] = None


class SettleTicketRequest(BaseModel):
    ticket_id: str
    result: str  # WON, LOST, VOID
    custom_payout: Optional[float] = None
    notes: Optional[str] = None


class ProfileLoginRequest(BaseModel):
    profile_id: str
    pin_code: str


class ProfileLoginByNameRequest(BaseModel):
    identifier: str
    pin_code: str


class ProfileRegisterRequest(BaseModel):
    name: str
    weekly_play_cap: float = Field(default=200.0, gt=0)
    pin_code: str = Field(default="0000")


class ProfileUpdateRequest(BaseModel):
    profile_id: str
    name: Optional[str] = None
    weekly_play_cap: Optional[float] = None
    current_pin: str
    new_pin: Optional[str] = None


class AdminDeletePlayerRequest(BaseModel):
    profile_id: str
    admin_pin: Optional[str] = None


class AdminResetPinRequest(BaseModel):
    profile_id: str
    new_pin: str = "0000"
    admin_pin: Optional[str] = None


class AdminUpdatePlayerRequest(BaseModel):
    profile_id: str
    name: Optional[str] = None
    weekly_play_cap: Optional[float] = None
    new_pin: Optional[str] = None
    admin_pin: Optional[str] = None


def clean_league_name(league: Optional[str]) -> str:
    if not league:
        return "綜合賽事"
    s = re.sub(r"^unknown[_\-\s]*", "", str(league).strip(), flags=re.IGNORECASE).strip()
    upper = s.upper()
    league_map = {
        "COLOMBIA_PRIMERA_A": "哥倫比亞甲級聯賽",
        "SAUDI_PRO_LEAGUE": "沙烏地職業聯賽",
        "KBO": "韓國職棒 (KBO)",
        "NBA": "美國職籃 (NBA)",
        "WNBA": "美國女子職籃 (WNBA)",
        "MLB": "美國職棒 (MLB)",
        "NPB": "日本職棒 (NPB)",
        "CPBL": "中華職棒 (CPBL)",
        "NFL": "美式足球 (NFL)",
        "NHL": "國家冰球 (NHL)",
        "SOCCER": "綜合足球",
        "BASKETBALL": "綜合籃球",
        "BASEBALL": "綜合棒球",
        "FOOTBALL": "美式足球",
    }
    return league_map.get(upper, s) or "綜合賽事"


# --- Endpoints ---

@app.get("/api/health")
def health_check():
    meta = get_strategy_metadata()
    return {
        "status": "ok",
        "service": "sportslottery-api",
        "app_build": APP_BUILD,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy_metadata": meta,
        "alliances": ALLIANCE_MAP,
    }


@app.get("/api/radar")
def get_radar(
    force_refresh: bool = False,
    _session: Optional[Dict[str, Any]] = Depends(verify_no_pending_password_change),
):
    odds_adapter, _, _, season_radar, _, _, _, _ = get_services()
    all_alliances = list(ALLIANCE_MAP.keys())
    legs = odds_adapter.get_taiwan_legs(all_alliances, force_refresh=force_refresh)
    radar_summary = season_radar.get_radar_summary(legs)
    source_status = odds_adapter.get_source_status()
    
    # Counts by status
    status_counts = {"GREEN": 0, "YELLOW": 0, "RED": 0}
    for item in radar_summary:
        st = item.get("status", "RED")
        if st in status_counts:
            status_counts[st] += 1

    return {
        "radar": radar_summary,
        "status_counts": status_counts,
        "total_legs": len(legs),
        "source_status": source_status,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/market/status")
def get_market_intelligence_status():
    """Retrieve operational capabilities, API quota, and data freshness across market intelligence sources."""
    odds_client = TheOddsApiClient()
    return {
        "status": "HEALTHY",
        "the_odds_api": odds_client.get_source_status(),
        "splits_source": "action_network / vsin (Tickets% vs Money%)",
        "alignment_engine": "MarketAligner (Bi-directional, threshold-enforced)",
        "fair_odds_engine": "MarketFairOddsEngine (De-vigged multiplicative / power)",
        "forward_evaluation": "ForwardEvaluationEngine (Pre-match, Leak-free, Shadow Mode)",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/market/benchmark")
def get_market_benchmark_comparison(
    league: str = Query("MLB", description="League identifier (e.g. MLB, NBA, SOCCER)"),
    force_refresh: bool = False,
):
    """Retrieve precision aligned international market benchmark odds, de-vigged fair probabilities, and theoretical EV."""
    odds_client = TheOddsApiClient()
    odds_adapter, signal_hub, _, _, _, _, _, _ = get_services()
    raw_legs = odds_adapter.get_taiwan_legs([league], force_refresh=force_refresh)
    int_odds = odds_client.fetch_market_odds(league, force_refresh=force_refresh)
    aligner = MarketAligner()

    matched_results = []
    unmatched_count = 0
    stale_count = 0

    for leg in raw_legs:
        leg_enriched = signal_hub.evaluate_taiwan_leg(leg)
        matched_cand, record = aligner.align_leg_with_candidates(leg_enriched, int_odds)
        if matched_cand and record.status.value == "MATCHED":
            fair_prob = (leg_enriched.signal_evidence or {}).get("market_fair_probability")
            if not fair_prob:
                fair_prob = round((1.0 / matched_cand.decimal_odds) * 0.98, 4) if matched_cand.decimal_odds > 1.0 else 0.5
            ev = (fair_prob * leg.taiwan_odds) - 1.0
            matched_results.append({
                "taiwan_event_id": leg.event_id,
                "league": leg.league,
                "home_team": leg.home_team,
                "away_team": leg.away_team,
                "market": leg.market,
                "selection": leg.selection,
                "side": leg.side,
                "line": leg.line,
                "taiwan_odds": leg.taiwan_odds,
                "international_book": matched_cand.source_id,
                "international_odds": matched_cand.decimal_odds,
                "fair_probability": round(fair_prob, 4),
                "theoretical_ev_pct": round(ev * 100.0, 1),
                "is_positive_ev": ev >= 0.02,
                "alignment_status": record.status.value,
                "observed_at_utc": matched_cand.observed_at_utc,
                "is_synthetic": matched_cand.is_synthetic,
            })
        elif record.status.value == "STALE":
            stale_count += 1
        else:
            unmatched_count += 1

    return {
        "league": league,
        "total_taiwan_legs": len(raw_legs),
        "matched_count": len(matched_results),
        "unmatched_count": unmatched_count,
        "stale_count": stale_count,
        "benchmarks": matched_results,
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/market/splits")
def get_market_betting_splits(
    league: str = Query("MLB", description="League identifier (e.g. MLB, NBA)"),
):
    """Retrieve public betting splits (Tickets % vs Money handle %) with strictly preserved nulls."""
    splits_client = BettingSplitsClient()
    splits = splits_client.get_betting_splits(league)
    return {
        "league": league,
        "splits_count": len(splits),
        "splits": [s.to_dict() for s in splits],
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/market/evaluation")
def get_forward_evaluation_report(
    scope: str = Query("GLOBAL", description="Evaluation scope or league"),
):
    """Retrieve chronological 3-way benchmark comparison (Taiwan Base vs Sharp Benchmark vs Model)."""
    engine = ForwardEvaluationEngine()
    snapshots: List[Dict[str, Any]] = []
    try:
        snapshots = PredictionSnapshotLogger().get_all_snapshots()[-100:]
    except Exception as exc:
        logger.warning("Error reading snapshots for evaluation: %s", exc)
    report = engine.evaluate_cohort(snapshots, scope_name=scope)
    return report.to_dict()


@app.get("/api/legs")
def get_legs(
    alliances: Optional[str] = Query(None, description="Comma-separated alliance IDs"),
    force_refresh: bool = False,
    limit: int = Query(1000, ge=1, le=5000),
    _session: Optional[Dict[str, Any]] = Depends(verify_no_pending_password_change),
):
    odds_adapter, signal_hub, _, _, _, _, _, _ = get_services()
    selected = [a.strip() for a in alliances.split(",")] if alliances else list(ALLIANCE_MAP.keys())
    legs = odds_adapter.get_taiwan_legs(selected, force_refresh=force_refresh)
    
    # Return formatted legs
    results = []
    for leg in legs[:limit]:
        d = leg.to_dict() if hasattr(leg, "to_dict") else dict(leg.__dict__)
        d["display_league"] = clean_league_name(d.get("league"))
        results.append(d)
        
    return {
        "total": len(legs),
        "returned": len(results),
        "alliances": selected,
        "legs": results,
    }


@app.post("/api/parlays/search")
def search_parlays(
    req: ParlaySearchRequest,
    _session: Optional[Dict[str, Any]] = Depends(verify_no_pending_password_change),
):
    odds_adapter, signal_hub, parlay_engine, _, _, _, _, _ = get_services()
    
    selected_alliances = req.alliances if req.alliances else list(ALLIANCE_MAP.keys())
    raw_legs = odds_adapter.get_taiwan_legs(selected_alliances, force_refresh=req.force_refresh)
    
    # Enrich legs with signals
    enriched_legs = [signal_hub.evaluate_taiwan_leg(leg) for leg in raw_legs]
    
    min_o = req.min_odds if req.min_odds is not None else round(req.target_odds * (1 - req.tolerance), 2)
    max_o = req.max_odds if req.max_odds is not None else round(req.target_odds * (1 + req.tolerance), 2)
    
    diagnostics: Dict[str, Any] = {}
    parlay_results = parlay_engine.search_parlays(
        legs=enriched_legs,
        min_odds=max(1.5, min_o),
        max_odds=max_o,
        target_odds=req.target_odds,
        tolerance=req.tolerance,
        signal_filter=req.signal_filter,
        exclude_traps=req.exclude_traps,
        prefer_steam=req.prefer_steam,
        min_legs=req.min_legs,
        max_legs=req.max_legs,
        diagnostics=diagnostics,
        search_budget=req.search_budget,
    )
    
    # Clean tier items
    def format_parlays(items: List[Dict[str, Any]]):
        formatted = []
        for p in items:
            p_copy = dict(p)
            p_copy["parlay_id"] = p.get("candidate_id") or p.get("parlay_id", "")
            p_copy["expected_value"] = p.get("parlay_expected_value", 0.0)
            p_copy["parlay_ev_pct"] = p.get("parlay_ev_pct", round(p.get("parlay_expected_value", 0.0) * 100.0, 1))
            p_copy["sharp_parlay_ev_pct"] = p.get("sharp_parlay_ev_pct", 0.0)
            p_copy["joint_probability"] = p.get("joint_probability", 0.0)
            p_copy["sharp_badge"] = p.get("sharp_badge", "")
            p_copy["is_positive_ev"] = p.get("is_positive_ev", False)

            # Ensure legs in parlay are dicts and have display_league & signal fields
            clean_legs = []
            for l in p.get("legs", []):
                ld = l.to_dict() if hasattr(l, "to_dict") else dict(l.__dict__ if hasattr(l, "__dict__") else l)
                ld["display_league"] = clean_league_name(ld.get("league"))
                sig = ld.get("signal_evidence") or {}
                t_odds = float(ld.get("taiwan_odds") or ld.get("odds") or 1.0)
                prob = float(sig.get("consensus_probability") or sig.get("sharp_fair_probability") or sig.get("market_fair_probability") or (1.0 / t_odds if t_odds > 0 else 0.5))
                leg_ev = sig.get("sharp_expected_value_pct")
                if leg_ev is None:
                    leg_ev = sig.get("expected_value_pct")
                if leg_ev is None and prob and t_odds:
                    leg_ev = round(((prob * t_odds) - 1.0) * 100.0, 1)

                ld["expected_value_pct"] = leg_ev
                ld["consensus_probability"] = prob
                ld["market_implied_pct"] = sig.get("market_implied_pct", round((1.0 / t_odds) * 100.0, 1) if t_odds > 0 else 0.0)
                ld["agreement_badge"] = sig.get("agreement_badge", "")
                ld["is_positive_ev"] = bool(leg_ev and leg_ev > 0)
                ld["is_sharp_value_bet"] = bool(sig.get("is_sharp_value_bet", False) or (leg_ev and leg_ev >= 5.0))
                ld["crowd_desc"] = sig.get("crowd_desc", "")
                ld["line_movement_label"] = (sig.get("line_movement") or {}).get("text_label", "")
                clean_legs.append(ld)
            p_copy["legs"] = clean_legs
            formatted.append(p_copy)
        return formatted

    return {
        "target_odds": req.target_odds,
        "min_odds": min_o,
        "max_odds": max_o,
        "tolerance": req.tolerance,
        "tiers": {
            "high_consensus": format_parlays(parlay_results.get("high_consensus", [])),
            "aggressive": format_parlays(parlay_results.get("aggressive", [])),
            "moonshot": format_parlays(parlay_results.get("moonshot", [])),
        },
        "diagnostics": diagnostics,
        "search_complete": diagnostics.get("search_complete", True),
        "total_combinations_searched": diagnostics.get("evaluated_combinations", 0),
        "enriched_legs_count": len(enriched_legs),
    }


@app.get("/api/wallet/status")
def get_wallet_status(
    profile_id: str = Query(DEFAULT_PROFILE_ID),
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(profile_id, session)
    wallet = get_wallet(profile_id=profile_id)
    status = wallet.get_status()
    return status


@app.post("/api/wallet/deposit")
def wallet_deposit(
    req: DepositRequest,
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(req.profile_id, session)
    wallet = get_wallet(profile_id=req.profile_id)
    try:
        res = wallet.deposit_external(amount=req.amount, notes=req.notes)
        return {"success": True, "result": res, "wallet_status": wallet.get_status()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/wallet/withdraw")
def wallet_withdraw(
    req: WithdrawRequest,
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(req.profile_id, session)
    wallet = get_wallet(profile_id=req.profile_id)
    try:
        res = wallet.withdraw_from_prize_pool(amount=req.amount)
        return {"success": True, "result": res, "wallet_status": wallet.get_status()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/wallet/ledger")
def get_wallet_ledger(
    profile_id: str = Query(DEFAULT_PROFILE_ID),
    limit: int = 50,
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(profile_id, session)
    wallet = get_wallet(profile_id=profile_id)
    history = wallet.get_ledger_history(limit=limit)
    return {"ledger": history}


@app.get("/api/tickets")
def list_tickets(
    profile_id: str = Query(DEFAULT_PROFILE_ID),
    status: Optional[str] = Query(None, description="PENDING, WON, LOST, VOID"),
    limit: int = Query(50, ge=1, le=200),
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(profile_id, session)
    service = get_betting_service(profile_id=profile_id)
    tickets = service.list_tickets(status_filter=status, limit=limit, profile_id=profile_id)
    return {"tickets": tickets}


@app.post("/api/tickets/place")
def place_ticket(
    req: PlaceTicketRequest,
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(req.profile_id, session)
    service = get_betting_service(profile_id=req.profile_id)
    _, _, _, _, _, snapshot_logger, _, _ = get_services()
    
    # Use client-provided idempotency key (or client_request_id) if available,
    # otherwise generate a new unique UUID so deliberate identical bets create distinct tickets.
    client_key = (req.idempotency_key or req.client_request_id or "").strip()
    idempotency_key = client_key if client_key else str(uuid.uuid4())
    
    raw_mode = (req.entry_mode or "").strip().lower()
    if raw_mode == "recommendation":
        entry_mode = "recommendation"
    else:
        entry_mode = "manual"
    
    client_source = "frontend_api"
    
    try:
        rec_odds = req.recommendation_odds or req.placed_odds
        res = service.place_ticket(
            legs=req.legs,
            stake=req.stake,
            total_odds=req.placed_odds,
            recommendation_odds=rec_odds,
            placed_odds=req.placed_odds,
            entry_mode=entry_mode,
            idempotency_key=idempotency_key,
            client_source=client_source,
            notes=f"{req.parlay_name or '瘋狗串關'} (Web API 下注)",
        )
        
        # Snapshot legs
        for leg_dict in req.legs:
            try:
                leg_obj = TaiwanLeg(**{k: v for k, v in leg_dict.items() if k in TaiwanLeg.__annotations__})
                snapshot_logger.log_snapshot(leg_obj)
            except Exception:
                pass
                
        wallet_status = service.get_wallet_status()
        logger.info(
            "[BET_PLACED] profile_id=%s ticket_id=%s stake=%.2f odds=%.2f mode=%s key=%s",
            req.profile_id,
            res.get("ticket_id"),
            req.stake,
            req.placed_odds,
            entry_mode,
            idempotency_key,
        )
        return {
            "success": True,
            "ticket": res,
            "wallet_status": wallet_status,
        }
    except ValueError as exc:
        logger.warning(
            "[BET_REJECTED] profile_id=%s reason=%s mode=%s",
            req.profile_id,
            str(exc),
            raw_mode,
        )
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/tickets/settle")
def settle_ticket(
    req: SettleTicketRequest,
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    _, _, _, _, _, _, _, _ = get_services()
    service = get_betting_service()
    ticket = service.get_ticket(req.ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"找不到注單 ID: {req.ticket_id}")
    profile_id = str(ticket.get("profile_id") or DEFAULT_PROFILE_ID).strip()
    verify_profile_ownership(profile_id, session)
    
    target_service = get_betting_service(profile_id=profile_id)
    is_won = (req.result.upper() == "WON")
    is_void = (req.result.upper() == "VOID")
    
    try:
        res = target_service.settle_ticket(
            ticket_id=req.ticket_id,
            won=is_won,
            custom_payout=req.custom_payout,
            is_void=is_void,
            notes=req.notes or f"Web API Settle: {req.result}",
        )
        wallet_status = target_service.get_wallet_status()
        logger.info(
            "[BET_SETTLED] ticket_id=%s profile_id=%s result=%s payout=%.2f",
            req.ticket_id,
            profile_id,
            req.result,
            res.get("payout", 0.0),
        )
        return {
            "success": True,
            "result": res,
            "wallet_status": wallet_status,
        }
    except Exception as exc:
        logger.warning(
            "[SETTLE_FAILED] ticket_id=%s reason=%s",
            req.ticket_id,
            str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/profiles")
def list_profiles(session: Optional[Dict[str, Any]] = Depends(get_current_session_optional)):
    """List profiles with privacy boundaries:
    - Admin session: receives all profiles (without PIN)
    - Regular user session: receives only their own profile
    - Unauthenticated: receives minimal public structure (id and name only for selector)
    """
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    profiles = profile_mgr.list_profiles()

    if session and (session.get("is_admin") or session.get("profile_id") == DEFAULT_PROFILE_ID):
        safe_profiles = []
        for p in profiles:
            p_dict = dict(p)
            p_dict.pop("pin_code", None)
            safe_profiles.append(p_dict)
        return {"profiles": safe_profiles}

    if session and session.get("profile_id"):
        my_prof = profile_mgr.get_profile(session["profile_id"])
        if my_prof:
            p_dict = dict(my_prof)
            p_dict.pop("pin_code", None)
            return {"profiles": [p_dict]}

    minimal_profiles = [{"id": p["id"], "name": p["name"]} for p in profiles]
    return {"profiles": minimal_profiles}


@app.get("/api/profiles/public_list")
def list_public_profiles():
    """Explicit public endpoint returning only minimal identifier & name for login dropdown."""
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    profiles = profile_mgr.list_profiles()
    return {"profiles": [{"id": p["id"], "name": p["name"]} for p in profiles]}


@app.post("/api/profiles/login")
def profile_login(
    req: ProfileLoginByNameRequest,
    request: Request,
    response: Response,
):
    """Authenticate by player name or profile ID with rate limiting, lockout, and HttpOnly cookie."""
    ip = get_client_ip(request)
    ident = str(req.identifier or "").strip()

    # 1. Anti-brute-force check
    lock_rem = login_rate_limiter.check_rate_limit(ident, ip)
    if lock_rem is not None:
        log_security_event("LOGIN_ATTEMPT_LOCKED", ident, ip, {"retry_after": lock_rem})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"【安全鎖定】登入嘗試失敗次數過多，帳號或IP已暫時鎖定，請於 {lock_rem} 秒後再試。",
            headers={"Retry-After": str(lock_rem)},
        )

    _, _, _, _, profile_mgr, _, _, _ = get_services()
    success, profile, msg = profile_mgr.verify_login(ident, req.pin_code)

    if not success or not profile:
        fail_cnt, is_locked, lock_sec = login_rate_limiter.record_failure(ident, ip)
        log_security_event("LOGIN_FAILED", ident, ip, {"fail_count": fail_cnt, "locked": is_locked})
        if is_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"【安全鎖定】登入連續失敗達 {fail_cnt} 次，帳號已鎖定，請於 {lock_sec} 秒後再試。",
                headers={"Retry-After": str(lock_sec)},
            )
        rem_attempts = max(0, login_rate_limiter.max_failures - fail_cnt)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{msg or '登入失敗，PIN 碼或帳號錯誤。'}（剩餘嘗試次數：{rem_attempts} 次）",
        )

    # Success: reset rate limiter
    login_rate_limiter.record_success(ident, ip)
    log_security_event("LOGIN_SUCCESS", ident, ip, {"profile_id": profile["id"]})
    token = session_manager.create_session(profile)

    # Set secure HttpOnly Cookie
    is_secure = (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https")
    response.set_cookie(
        key="auth_session_token",
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )

    # Check for default admin weak PIN
    is_admin = (profile["id"] == DEFAULT_PROFILE_ID) or (profile.get("name") == "Archie")
    is_weak_pin = (str(req.pin_code).strip() == "0000")
    requires_pin_change = bool(is_admin and is_weak_pin)

    p_dict = dict(profile)
    p_dict.pop("pin_code", None)
    return {
        "success": True,
        "token": token,
        "profile": p_dict,
        "message": msg,
        "requires_pin_change": requires_pin_change,
        "warning": "【安全警告】管理員帳號目前使用預設弱 PIN 碼 (0000)，請立即修改為自訂安全密碼！" if requires_pin_change else None,
    }


@app.post("/api/profiles/logout")
def profile_logout(
    response: Response,
    session: Dict[str, Any] = Depends(require_any_authenticated_session),
):
    session_manager.revoke_session(session.get("token"))
    response.delete_cookie(key="auth_session_token", path="/")
    return {"success": True, "message": "已成功登出。"}


@app.get("/api/auth/me")
def get_auth_me(session: Dict[str, Any] = Depends(require_any_authenticated_session)):
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    profile = profile_mgr.get_profile(session.get("profile_id"))
    if not profile:
        raise HTTPException(status_code=404, detail="找不到目前登入者的 Profile。")
    p_dict = dict(profile)
    p_dict.pop("pin_code", None)
    return {"success": True, "profile": p_dict, "session": session}


@app.post("/api/profiles/register")
def profile_register(
    req: ProfileRegisterRequest,
    request: Request,
    response: Response,
):
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    try:
        new_prof = profile_mgr.create_profile(
            name=req.name,
            weekly_play_cap=req.weekly_play_cap,
            pin_code=req.pin_code,
        )
        token = session_manager.create_session(new_prof)
        is_secure = (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https")
        response.set_cookie(
            key="auth_session_token",
            value=token,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            secure=is_secure,
            path="/",
        )
        p_dict = dict(new_prof)
        p_dict.pop("pin_code", None)
        return {"success": True, "token": token, "profile": p_dict}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/profiles/verify_pin")
def verify_profile_pin(
    req: ProfileLoginRequest,
    request: Request,
    response: Response,
):
    """Verify profile PIN with rate limiting and issue session with HttpOnly cookie."""
    ip = get_client_ip(request)
    ident = str(req.profile_id or "").strip()

    lock_rem = login_rate_limiter.check_rate_limit(ident, ip)
    if lock_rem is not None:
        log_security_event("VERIFY_PIN_LOCKED", ident, ip, {"retry_after": lock_rem})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"【安全鎖定】PIN 碼嘗試次數過多，帳號或IP已暫時鎖定，請於 {lock_rem} 秒後再試。",
            headers={"Retry-After": str(lock_rem)},
        )

    _, _, _, _, profile_mgr, _, _, _ = get_services()
    is_valid = profile_mgr.verify_pin(profile_id=req.profile_id, pin_code=req.pin_code)
    if not is_valid:
        fail_cnt, is_locked, lock_sec = login_rate_limiter.record_failure(ident, ip)
        log_security_event("VERIFY_PIN_FAILED", ident, ip, {"fail_count": fail_cnt, "locked": is_locked})
        if is_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"【安全鎖定】PIN 碼嘗試失敗達 {fail_cnt} 次，帳號已鎖定，請於 {lock_sec} 秒後再試。",
                headers={"Retry-After": str(lock_sec)},
            )
        rem_attempts = max(0, login_rate_limiter.max_failures - fail_cnt)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"PIN 碼錯誤。（剩餘嘗試次數：{rem_attempts} 次）",
        )

    login_rate_limiter.record_success(ident, ip)
    profile = profile_mgr.get_profile(req.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="找不到玩家 Profile。")

    log_security_event("VERIFY_PIN_SUCCESS", ident, ip, {"profile_id": profile["id"]})
    token = session_manager.create_session(profile)

    is_secure = (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https")
    response.set_cookie(
        key="auth_session_token",
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )

    is_admin = (profile["id"] == DEFAULT_PROFILE_ID) or (profile.get("name") == "Archie")
    is_weak_pin = (str(req.pin_code).strip() == "0000")
    requires_pin_change = bool(is_admin and is_weak_pin)

    p_dict = dict(profile)
    p_dict.pop("pin_code", None)
    return {
        "success": True,
        "token": token,
        "profile": p_dict,
        "requires_pin_change": requires_pin_change,
        "warning": "【安全警告】管理員帳號目前使用預設弱 PIN 碼 (0000)，請立即修改為自訂安全密碼！" if requires_pin_change else None,
    }


@app.post("/api/profiles/update")
def update_profile(
    req: ProfileUpdateRequest,
    request: Request,
    response: Response,
    session: Dict[str, Any] = Depends(require_any_authenticated_session),
):
    verify_profile_ownership(req.profile_id, session)
    if session.get("must_change_password") and not req.new_pin:
        raise HTTPException(
            status_code=403,
            detail="【安全限制】管理員使用預設密碼 0000，必須設定新密碼（剛好 8 位純數字）。",
        )
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    is_valid = profile_mgr.verify_pin(profile_id=req.profile_id, pin_code=req.current_pin)
    if not is_valid:
        raise HTTPException(status_code=401, detail="目前 PIN 碼驗證失敗。")

    try:
        updated = profile_mgr.update_profile(
            profile_id=req.profile_id,
            current_pin=req.current_pin,
            new_name=req.name,
            new_weekly_play_cap=req.weekly_play_cap,
            new_pin_code=req.new_pin,
        )

        p_dict = dict(updated)
        p_dict.pop("pin_code", None)

        # If PIN was updated, revoke all existing sessions for this profile across devices
        new_token = None
        if req.new_pin:
            session_manager.revoke_all_for_profile(req.profile_id)
            new_token = session_manager.create_session(updated)
            is_secure = (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https")
            response.set_cookie(
                key="auth_session_token",
                value=new_token,
                max_age=SESSION_TTL_SECONDS,
                httponly=True,
                samesite="lax",
                secure=is_secure,
                path="/",
            )

        res = {"success": True, "profile": p_dict}
        if new_token:
            res["token"] = new_token
            res["message"] = "PIN 碼已更新，其他裝置已強制登出。"
        return res
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/admin/players_overview")
def get_admin_players_overview(
    admin_profile_id: str = Query("default"),
    session: Dict[str, Any] = Depends(require_active_admin_session),
):
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    all_profs = profile_mgr.list_profiles()
    overview = []
    for p in all_profs:
        try:
            bs = get_betting_service(profile_id=p["id"])
            ws = bs.get_wallet_status()
            bal = ws.get("weekly_wallet_balance", 0.0)
            staked = ws.get("weekly_staked", 0.0)
            prize = ws.get("prize_pool", 0.0)
            pnl = ws.get("lifetime_net_profit", 0.0)
            cap = p.get("weekly_play_cap", 200.0)
        except Exception:
            bal, staked, prize, pnl, cap = 0.0, 0.0, 0.0, 0.0, 200.0

        try:
            bs = get_betting_service(profile_id=p["id"])
            t_list = bs.list_tickets(limit=100, profile_id=p["id"])
            active_cnt = sum(1 for t in t_list if t.get("status") == "OPEN")
            total_cnt = len(t_list)
        except Exception:
            active_cnt, total_cnt = 0, 0

        overview.append({
            "id": p["id"],
            "name": p["name"],
            "weekly_play_cap": cap,
            "weekly_wallet_balance": bal,
            "weekly_staked": staked,
            "prize_pool": prize,
            "lifetime_net_profit": pnl,
            "is_line_bound": bool(p.get("line_user_id")),
            "created_at": p.get("created_at", ""),
            "active_tickets_count": active_cnt,
            "total_tickets_count": total_cnt,
        })
    return {"players": overview, "total_players": len(overview)}


@app.delete("/api/admin/players/{profile_id}")
def admin_delete_player(
    profile_id: str,
    admin_pin: Optional[str] = None,
    session: Dict[str, Any] = Depends(require_active_admin_session),
):
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    profile = profile_mgr.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"找不到 ID 為 {profile_id} 的玩家。")
    if profile_id == "default" or profile.get("name") == "Archie":
        raise HTTPException(status_code=400, detail="管理者帳號「Archie」不可被刪除。")

    try:
        profile_mgr.admin_delete_profile(
            target_profile_id=profile_id,
            admin_pin=admin_pin,
            admin_profile_id=session.get("profile_id", "default"),
        )
        session_manager.revoke_all_for_profile(profile_id)
        return {
            "success": True,
            "message": f"已成功刪除玩家【{profile['name']}】及其相關錢包帳本與投注注單！",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/players/delete")
def admin_delete_player_post(
    req: AdminDeletePlayerRequest,
    session: Dict[str, Any] = Depends(require_active_admin_session),
):
    return admin_delete_player(profile_id=req.profile_id, admin_pin=req.admin_pin, session=session)


@app.post("/api/admin/players/reset_pin")
def admin_reset_player_pin(
    req: AdminResetPinRequest,
    session: Optional[Dict[str, Any]] = Depends(get_current_session_optional),
):
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    is_admin = bool(session and (session.get("is_admin") or session.get("profile_id") == "default"))

    if is_admin:
        if session.get("must_change_password"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="【安全限制】管理員使用預設密碼 0000，必須先變更為 8 位純數字密碼方可操作管理功能。",
            )
    else:
        # If not authenticated as admin via session, verify admin_pin against Archie (default profile)
        if session and not req.admin_pin:
            raise HTTPException(status_code=403, detail="【權限不足】僅系統管理者可重設玩家 PIN 碼。")
        if not req.admin_pin:
            raise HTTPException(status_code=401, detail="【需要管理員授權】請輸入管理員 Archie 的密碼以執行重設。")
        if profile_mgr.is_default_admin_pin():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="【安全限制】管理員使用預設密碼 0000，必須先登入變更為 8 位純數字密碼方可授權重設。",
            )
        if not profile_mgr.verify_pin("default", req.admin_pin):
            raise HTTPException(status_code=401, detail="【管理員密碼驗證失敗】輸入的管理員密碼不正確。")

    try:
        updated = profile_mgr.admin_reset_pin(
            target_profile_id=req.profile_id,
            new_pin_code=req.new_pin,
        )
        session_manager.revoke_all_for_profile(req.profile_id)
        p_dict = dict(updated)
        p_dict.pop("pin_code", None)
        return {
            "success": True,
            "profile": p_dict,
            "message": f"已成功將【{updated['name']}】的 PIN 碼重設為 {req.new_pin}！已強制登出該帳號所有作用中 Session。",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/players/update")
def admin_update_player_settings(
    req: AdminUpdatePlayerRequest,
    session: Dict[str, Any] = Depends(require_active_admin_session),
):
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    try:
        updated = profile_mgr.admin_update_player(
            target_profile_id=req.profile_id,
            new_name=req.name,
            new_weekly_play_cap=req.weekly_play_cap,
            new_pin_code=req.new_pin,
            admin_pin=req.admin_pin,
            admin_profile_id=session.get("profile_id", "default"),
        )
        p_dict = dict(updated)
        p_dict.pop("pin_code", None)
        return {
            "success": True,
            "profile": p_dict,
            "message": f"已成功更新玩家【{updated['name']}】的管理設定！",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/research/analytics")
def get_research_analytics():
    _, _, _, _, _, snapshot_logger, metrics_engine, shadow_portfolio = get_services()
    
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
    
    return {
        "total_snapshots": len(snaps),
        "cohort": cohort,
        "agreement": agreement,
        "ev_data": ev_data,
        "crowd_data": crowd_data,
        "expert_data": expert_data,
        "shadow_portfolio": portfolio_summary,
    }


@app.get("/api/system/storage_status")
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


# ======================================================================
# LINE Bot Webhook Single-Port Integration
# ======================================================================

_line_notifier = LineNotifier()

# Mount static folder for serving QR code PNGs
(ROOT_DIR / "static" / "qr").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")


def verify_line_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    """Validate X-Line-Signature against channel secret."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    expected_b64 = base64.b64encode(expected).decode("utf-8")
    return hmac.compare_digest(expected_b64, signature)


def process_line_events(events: list[Dict[str, Any]]) -> None:
    """Process accepted LINE events asynchronously outside the webhook response path."""
    for ev in events:
        try:
            ev_type = ev.get("type")
            reply_token = ev.get("replyToken")
            source = ev.get("source", {})
            user_id = source.get("userId")

            if user_id and not _line_notifier.config.get("user_id"):
                _line_notifier.save_config({"user_id": user_id, "enabled": True})

            if ev_type == "message":
                msg = ev.get("message", {})
                if msg.get("type") == "text":
                    user_text = str(msg.get("text", "")).strip()
                    full_res = _line_notifier.handle_user_message_full(user_text, line_user_id=user_id)
                    reply_text = full_res.get("text", "")
                    image_url = full_res.get("image_url")
                    quick_replies = full_res.get("quick_replies") or _line_notifier.default_quick_replies()
                    if reply_token:
                        _line_notifier.reply_message(
                            reply_token=reply_token,
                            text=reply_text,
                            quick_replies=quick_replies,
                            image_url=image_url,
                        )

            elif ev_type == "follow":
                welcome_text = (
                    "🎉 歡迎加入【台灣運彩 瘋狗流決策助手】(v2.3.0 Dev)！\n"
                    "---------------------------\n"
                    "本官方助手能為您即時提供：\n"
                    "• 🎯 智慧串關推薦（直接輸入目標倍率，如「20倍」）\n"
                    "• 💰 每週 NT$200 風控錢包與儲備池查詢\n"
                    "• ☀️ 每日賽季開盤雷達焦點賽事\n"
                    "• 🛡️ 串關聽牌對沖保本提醒\n\n"
                    "請點選下方快捷按鈕開始體驗！🐕"
                )
                if reply_token:
                    _line_notifier.reply_message(
                        reply_token=reply_token,
                        text=welcome_text,
                        quick_replies=_line_notifier.default_quick_replies(),
                    )
        except Exception as exc:
            logger.warning("[LINE_BOT_EVENT_ERROR] event_type=%s user_id=%s error=%s", ev_type, user_id, str(exc), exc_info=True)


@app.post("/callback")
async def line_webhook_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: Optional[str] = Header(None, alias="X-Line-Signature"),
):
    """Webhook callback endpoint for LINE Messaging API with mandatory cryptographic signature verification."""
    body_bytes = await request.body()
    secret = str(_line_notifier.config.get("channel_secret") or "").strip()
    is_test_mode = os.environ.get("ALLOW_INSECURE_LINE_WEBHOOK", "").lower() in ("1", "true", "yes")

    if not is_test_mode:
        if not secret:
            logger.warning("LINE webhook rejected: channel_secret is not configured on this server.")
            raise HTTPException(
                status_code=503,
                detail="LINE webhook service unavailable: channel_secret is not configured",
            )
        if not x_line_signature or not verify_line_signature(body_bytes, x_line_signature, secret):
            logger.warning("LINE webhook rejected: invalid or missing X-Line-Signature header.")
            raise HTTPException(status_code=400, detail="Invalid LINE webhook signature")
    else:
        if secret and x_line_signature and not verify_line_signature(body_bytes, x_line_signature, secret):
            raise HTTPException(status_code=400, detail="Invalid LINE webhook signature")
        logger.debug("LINE webhook running in test mode (ALLOW_INSECURE_LINE_WEBHOOK=true).")

    try:
        data = await request.json()
    except Exception:
        return Response(content="Invalid JSON", status_code=400)

    events = data.get("events", [])
    if events:
        background_tasks.add_task(process_line_events, events)
    return {"status": "ok", "events_processed": len(events)}


# Mount built frontend dist directory if it exists
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.api:app", host="127.0.0.1", port=8000, reload=True)
