from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.profile_manager import DEFAULT_PROFILE_ID
from integrations.common.models import TaiwanLeg
from server import service_registry
from server.auth import require_authenticated_session, verify_profile_ownership
from server.schemas import DepositRequest, PlaceTicketRequest, SettleTicketRequest, WithdrawRequest

logger = logging.getLogger("server.api")

router = APIRouter()



@router.get("/api/wallet/status")
def get_wallet_status(
    profile_id: str = Query(DEFAULT_PROFILE_ID),
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(profile_id, session)
    wallet = service_registry.get_wallet(profile_id=profile_id)
    status = wallet.get_status()
    return status


@router.post("/api/wallet/deposit")
def wallet_deposit(
    req: DepositRequest,
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(req.profile_id, session)
    wallet = service_registry.get_wallet(profile_id=req.profile_id)
    try:
        res = wallet.deposit_external(amount=req.amount, notes=req.notes)
        return {"success": True, "result": res, "wallet_status": wallet.get_status()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/wallet/withdraw")
def wallet_withdraw(
    req: WithdrawRequest,
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(req.profile_id, session)
    wallet = service_registry.get_wallet(profile_id=req.profile_id)
    try:
        res = wallet.withdraw_from_prize_pool(amount=req.amount)
        return {"success": True, "result": res, "wallet_status": wallet.get_status()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/wallet/ledger")
def get_wallet_ledger(
    profile_id: str = Query(DEFAULT_PROFILE_ID),
    limit: int = 50,
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(profile_id, session)
    wallet = service_registry.get_wallet(profile_id=profile_id)
    history = wallet.get_ledger_history(limit=limit)
    return {"ledger": history}


@router.get("/api/tickets")
def list_tickets(
    profile_id: str = Query(DEFAULT_PROFILE_ID),
    status: Optional[str] = Query(None, description="PENDING, WON, LOST, VOID"),
    limit: int = Query(50, ge=1, le=200),
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(profile_id, session)
    service = service_registry.get_betting_service(profile_id=profile_id)
    tickets = service.list_tickets(status_filter=status, limit=limit, profile_id=profile_id)
    return {"tickets": tickets}


@router.post("/api/tickets/place")
def place_ticket(
    req: PlaceTicketRequest,
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    verify_profile_ownership(req.profile_id, session)
    service = service_registry.get_betting_service(profile_id=req.profile_id)
    _, _, _, _, _, snapshot_logger, _, _ = service_registry.get_services()

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


@router.post("/api/tickets/settle")
def settle_ticket(
    req: SettleTicketRequest,
    session: Dict[str, Any] = Depends(require_authenticated_session),
):
    _, _, _, _, _, _, _, _ = service_registry.get_services()
    service = service_registry.get_betting_service()
    ticket = service.get_ticket(req.ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"找不到注單 ID: {req.ticket_id}")
    profile_id = str(ticket.get("profile_id") or DEFAULT_PROFILE_ID).strip()
    verify_profile_ownership(profile_id, session)

    target_service = service_registry.get_betting_service(profile_id=profile_id)
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
