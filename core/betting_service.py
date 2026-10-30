#!/usr/bin/env python3
"""Service layer for sports lottery wagers, settlement, and ledger reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .ticket_recorder import TicketRecorder
from .wallet import DEFAULT_DB_PATH, DEFAULT_PROFILE_ID, WeeklyWalletManager


class BettingService:
    """Coordinates betting operations across tickets and wallet ledger."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        profile_id: Optional[str] = None,
        recorder: Optional[TicketRecorder] = None,
        wallet: Optional[WeeklyWalletManager] = None,
    ):
        self.profile_id = str(profile_id or DEFAULT_PROFILE_ID).strip()
        self.db_path = db_path
        self.wallet = wallet or WeeklyWalletManager(db_path=db_path, profile_id=self.profile_id)
        self.recorder = recorder or TicketRecorder(wallet=self.wallet, db_path=db_path, profile_id=self.profile_id)

    def place_ticket(
        self,
        legs: List[Dict[str, Any]],
        stake: float,
        total_odds: float,
        recommendation_odds: Optional[float] = None,
        placed_odds: Optional[float] = None,
        notes: str = "",
        entry_mode: str = "manual",
        idempotency_key: Optional[str] = None,
        client_source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record wager and deduct stake from player wallet atomically."""
        return self.recorder.place_ticket(
            legs=legs,
            stake=stake,
            total_odds=total_odds,
            recommendation_odds=recommendation_odds,
            placed_odds=placed_odds,
            notes=notes,
            entry_mode=entry_mode,
            idempotency_key=idempotency_key,
            client_source=client_source,
        )

    def settle_ticket(
        self,
        ticket_id: str,
        won: bool,
        custom_payout: Optional[float] = None,
        is_void: bool = False,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Settle wager and credit winnings/refunds to owner wallet atomically."""
        return self.recorder.settle_ticket(
            ticket_id=ticket_id,
            won=won,
            custom_payout=custom_payout,
            is_void=is_void,
            notes=notes,
        )

    def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a ticket by ID."""
        return self.recorder.get_ticket(ticket_id)

    def get_ticket_owner(self, ticket_id: str) -> Optional[str]:
        """Retrieve the profile_id owner for a ticket."""
        return self.recorder.get_ticket_owner(ticket_id)

    def list_tickets(
        self,
        status_filter: Optional[str] = None,
        limit: int = 50,
        profile_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List tickets filtered by status and profile."""
        return self.recorder.list_tickets(
            status_filter=status_filter,
            limit=limit,
            profile_id=profile_id,
        )

    def get_wallet_status(self) -> Dict[str, Any]:
        """Retrieve player wallet status."""
        return self.wallet.get_status()

    def update_closing_odds(self, ticket_id: str, closing_odds: float) -> Optional[Dict[str, Any]]:
        """Update closing odds and recalculate CLV for a ticket."""
        return self.recorder.update_closing_odds(ticket_id=ticket_id, closing_odds=closing_odds)

    def get_clv_analytics(self, profile_id: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve CLV analytics for player or all players."""
        return self.recorder.get_clv_analytics(profile_id=profile_id)

