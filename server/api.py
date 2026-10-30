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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Body, Request, BackgroundTasks, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.bet_validation import assess_leg
from core.line_notifier import LineNotifier
from core.model_registry import ModelRegistry
from core.parlay_engine import ParlayEngine
from core.performance_metrics import PerformanceMetricsEngine
from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID
from core.scraper import ALLIANCE_MAP
from core.season_radar import SeasonRadar
from core.shadow_portfolio import ShadowPortfolioManager
from core.signal_hub import SignalHub
from core.snapshot_logger import PredictionSnapshotLogger
from core.strategy_version import get_strategy_metadata
from core.ticket_recorder import TicketRecorder
from core.wallet import WeeklyWalletManager
from integrations.common.models import TaiwanLeg
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter

app = FastAPI(
    title="Taiwan Sports Lottery API",
    description="台灣運彩「瘋狗流」高倍串關決策後端 API",
    version="2.0.0",
)

# CORS middleware to allow local React/Vite development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


class SettleTicketRequest(BaseModel):
    ticket_id: str
    result: str  # WON, LOST, VOID
    custom_payout: Optional[float] = None
    notes: Optional[str] = None


class ProfileLoginRequest(BaseModel):
    profile_id: str
    pin_code: str


class ProfileUpdateRequest(BaseModel):
    profile_id: str
    name: Optional[str] = None
    weekly_play_cap: Optional[float] = None
    current_pin: str
    new_pin: Optional[str] = None


# --- Endpoints ---

@app.get("/api/health")
def health_check():
    meta = get_strategy_metadata()
    return {
        "status": "ok",
        "service": "sportslottery-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy_metadata": meta,
        "alliances": ALLIANCE_MAP,
    }


@app.get("/api/radar")
def get_radar(force_refresh: bool = False):
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


@app.get("/api/legs")
def get_legs(
    alliances: Optional[str] = Query(None, description="Comma-separated alliance IDs"),
    force_refresh: bool = False,
    limit: int = Query(200, ge=1, le=1000),
):
    odds_adapter, signal_hub, _, _, _, _, _, _ = get_services()
    selected = [a.strip() for a in alliances.split(",")] if alliances else list(ALLIANCE_MAP.keys())
    legs = odds_adapter.get_taiwan_legs(selected, force_refresh=force_refresh)
    
    # Return formatted legs
    results = []
    for leg in legs[:limit]:
        d = leg.to_dict() if hasattr(leg, "to_dict") else leg.__dict__
        # Clean signals for JSON serialization
        results.append(d)
        
    return {
        "total": len(legs),
        "returned": len(results),
        "alliances": selected,
        "legs": results,
    }


@app.post("/api/parlays/search")
def search_parlays(req: ParlaySearchRequest):
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
            # Ensure legs in parlay are dicts
            clean_legs = []
            for l in p.get("legs", []):
                clean_legs.append(l.to_dict() if hasattr(l, "to_dict") else l)
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
def get_wallet_status(profile_id: str = Query(DEFAULT_PROFILE_ID)):
    wallet = get_wallet(profile_id=profile_id)
    status = wallet.get_status()
    return status


@app.post("/api/wallet/deposit")
def wallet_deposit(req: DepositRequest):
    wallet = get_wallet(profile_id=req.profile_id)
    try:
        res = wallet.deposit_external(amount=req.amount, notes=req.notes)
        return {"success": True, "result": res, "wallet_status": wallet.get_status()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/wallet/withdraw")
def wallet_withdraw(req: WithdrawRequest):
    wallet = get_wallet(profile_id=req.profile_id)
    try:
        res = wallet.withdraw_from_prize_pool(amount=req.amount)
        return {"success": True, "result": res, "wallet_status": wallet.get_status()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/wallet/ledger")
def get_wallet_ledger(profile_id: str = Query(DEFAULT_PROFILE_ID), limit: int = 50):
    wallet = get_wallet(profile_id=profile_id)
    history = wallet.get_ledger_history(limit=limit)
    return {"ledger": history}


@app.get("/api/tickets")
def list_tickets(
    profile_id: str = Query(DEFAULT_PROFILE_ID),
    status: Optional[str] = Query(None, description="PENDING, WON, LOST, VOID"),
    limit: int = Query(50, ge=1, le=200),
):
    recorder = get_recorder(profile_id=profile_id)
    tickets = recorder.list_tickets(status_filter=status, limit=limit, profile_id=profile_id)
    return {"tickets": tickets}


@app.post("/api/tickets/place")
def place_ticket(req: PlaceTicketRequest):
    recorder = get_recorder(profile_id=req.profile_id)
    _, _, _, _, _, snapshot_logger, _, _ = get_services()
    
    # Calculate idempotency key based on legs + stake
    payload_raw = {
        "legs": req.legs,
        "stake": req.stake,
        "placed_odds": req.placed_odds,
        "profile_id": req.profile_id,
    }
    key = hashlib.sha256(json.dumps(payload_raw, sort_keys=True, default=str).encode()).hexdigest()
    
    try:
        rec_odds = req.recommendation_odds or req.placed_odds
        res = recorder.place_ticket(
            legs=req.legs,
            stake=req.stake,
            total_odds=req.placed_odds,
            recommendation_odds=rec_odds,
            placed_odds=req.placed_odds,
            entry_mode="frontend_api",
            idempotency_key=key,
            notes=f"{req.parlay_name or '瘋狗串關'} (Web API 下注)",
        )
        
        # Snapshot legs
        for leg_dict in req.legs:
            try:
                leg_obj = TaiwanLeg(**{k: v for k, v in leg_dict.items() if k in TaiwanLeg.__annotations__})
                snapshot_logger.log_snapshot(leg_obj)
            except Exception:
                pass
                
        wallet = get_wallet(profile_id=req.profile_id)
        return {
            "success": True,
            "ticket": res,
            "wallet_status": wallet.get_status(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/tickets/settle")
def settle_ticket(req: SettleTicketRequest):
    _, _, _, _, _, _, _, _ = get_services()
    # Find ticket to get profile_id
    ticket_recorder = TicketRecorder()
    tickets = ticket_recorder.list_tickets(limit=100)
    target = next((t for t in tickets if t["ticket_id"] == req.ticket_id), None)
    profile_id = target.get("profile_id", DEFAULT_PROFILE_ID) if target else DEFAULT_PROFILE_ID
    
    recorder = get_recorder(profile_id=profile_id)
    is_won = (req.result.upper() == "WON")
    is_void = (req.result.upper() == "VOID")
    
    try:
        res = recorder.settle_ticket(
            ticket_id=req.ticket_id,
            won=is_won,
            custom_payout=req.custom_payout,
            is_void=is_void,
            notes=req.notes or f"Web API Settle: {req.result}",
        )
        wallet = get_wallet(profile_id=profile_id)
        return {
            "success": True,
            "result": res,
            "wallet_status": wallet.get_status(),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/profiles")
def list_profiles():
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    profiles = profile_mgr.list_profiles()
    # Strip PIN codes for security
    safe_profiles = []
    for p in profiles:
        p_dict = dict(p)
        p_dict.pop("pin_code", None)
        safe_profiles.append(p_dict)
    return {"profiles": safe_profiles}


@app.post("/api/profiles/verify_pin")
def verify_profile_pin(req: ProfileLoginRequest):
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    is_valid = profile_mgr.verify_pin(profile_id=req.profile_id, pin_code=req.pin_code)
    if not is_valid:
        raise HTTPException(status_code=401, detail="PIN 碼錯誤。")
    profile = profile_mgr.get_profile(req.profile_id)
    p_dict = dict(profile)
    p_dict.pop("pin_code", None)
    return {"success": True, "profile": p_dict}


@app.post("/api/profiles/update")
def update_profile(req: ProfileUpdateRequest):
    _, _, _, _, profile_mgr, _, _, _ = get_services()
    is_valid = profile_mgr.verify_pin(profile_id=req.profile_id, pin_code=req.current_pin)
    if not is_valid:
        raise HTTPException(status_code=401, detail="目前 PIN 碼驗證失敗。")
    
    kwargs: Dict[str, Any] = {}
    if req.name is not None:
        kwargs["name"] = req.name
    if req.weekly_play_cap is not None:
        kwargs["weekly_play_cap"] = req.weekly_play_cap
    if req.new_pin is not None:
        kwargs["pin_code"] = req.new_pin
        
    profile_mgr.update_profile(profile_id=req.profile_id, **kwargs)
    updated = profile_mgr.get_profile(req.profile_id)
    p_dict = dict(updated)
    p_dict.pop("pin_code", None)
    return {"success": True, "profile": p_dict}


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


# ======================================================================
# LINE Bot Webhook Single-Port Integration
# ======================================================================

_line_notifier = LineNotifier()

# Mount static folder for serving QR code PNGs
(ROOT_DIR / "static" / "qr").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")


def verify_line_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    """Validate X-Line-Signature against channel secret."""
    if not secret:
        return True
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
                    if reply_token:
                        _line_notifier.reply_message(
                            reply_token=reply_token,
                            text=reply_text,
                            quick_replies=_line_notifier.default_quick_replies(),
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
        except Exception:
            pass


@app.post("/callback")
async def line_webhook_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: Optional[str] = Header(None),
):
    """Webhook callback endpoint for LINE Messaging API."""
    body_bytes = await request.body()
    secret = _line_notifier.config.get("channel_secret")
    if secret:
        if not x_line_signature or not verify_line_signature(body_bytes, x_line_signature, secret):
            raise HTTPException(status_code=400, detail="Invalid signature")

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
