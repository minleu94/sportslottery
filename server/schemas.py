from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from core.profile_manager import DEFAULT_PROFILE_ID


class ParlaySearchRequest(BaseModel):
    target_odds: Optional[float] = Field(default=20.0, ge=1.5, le=5000.0)
    min_odds: Optional[float] = Field(default=None, ge=1.05, le=5000.0)
    max_odds: Optional[float] = Field(default=None, ge=1.05, le=5000.0)
    tolerance: float = Field(default=0.25, ge=0.01, le=1.0)
    min_legs: int = Field(default=1, ge=1, le=8)
    max_legs: int = Field(default=6, ge=1, le=8)
    alliances: Optional[List[str]] = None
    signal_filter: str = Field(default="normal")  # normal, value_only, strict, wild
    ranking_mode: str = Field(default="WIN_PROBABILITY")  # WIN_PROBABILITY or VALUE
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
    profile_id: str = Field(..., min_length=1, max_length=128)
    pin_code: str = Field(..., min_length=1, max_length=8)


class ProfileLoginByNameRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=128)
    pin_code: str = Field(..., min_length=1, max_length=8)


class ProfileRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    weekly_play_cap: float = Field(default=200.0, gt=0)
    pin_code: str = Field(default="0000", min_length=4, max_length=4)


class ProfileUpdateRequest(BaseModel):
    profile_id: str = Field(..., min_length=1, max_length=128)
    name: Optional[str] = Field(None, max_length=64)
    weekly_play_cap: Optional[float] = None
    current_pin: str = Field(..., min_length=1, max_length=8)
    new_pin: Optional[str] = Field(None, min_length=4, max_length=8)


class AdminDeletePlayerRequest(BaseModel):
    profile_id: str = Field(..., min_length=1, max_length=128)
    admin_pin: Optional[str] = Field(None, min_length=1, max_length=8)


class MarketKeyConfigRequest(BaseModel):
    the_odds_api_key: str = Field(..., min_length=1, max_length=128, description="API Key for The Odds API")


class MarketSchedulerConfigRequest(BaseModel):
    enabled: Optional[bool] = Field(None, description="Toggle automated forward cycle scheduler on/off")
    interval_seconds: Optional[int] = Field(None, ge=300, le=86400, description="Cadence interval in seconds (300~86400)")


class TheOddsTestConnectionRequest(BaseModel):
    fetch_sample: bool = False
    sport_league: Optional[str] = None


class AdminResetPinRequest(BaseModel):
    profile_id: str = Field(..., min_length=1, max_length=128)
    new_pin: str = Field("0000", min_length=4, max_length=4)
    admin_pin: Optional[str] = Field(None, min_length=1, max_length=8)


class AdminUpdatePlayerRequest(BaseModel):
    profile_id: str = Field(..., min_length=1, max_length=128)
    name: Optional[str] = Field(None, max_length=64)
    weekly_play_cap: Optional[float] = None
    new_pin: Optional[str] = Field(None, min_length=4, max_length=8)
    admin_pin: Optional[str] = Field(None, min_length=1, max_length=8)

__all__ = ['AdminDeletePlayerRequest', 'AdminResetPinRequest', 'AdminUpdatePlayerRequest', 'DepositRequest', 'MarketKeyConfigRequest', 'MarketSchedulerConfigRequest', 'ParlaySearchRequest', 'PlaceTicketRequest', 'ProfileLoginByNameRequest', 'ProfileLoginRequest', 'ProfileRegisterRequest', 'ProfileUpdateRequest', 'SettleTicketRequest', 'TheOddsTestConnectionRequest', 'WithdrawRequest']
