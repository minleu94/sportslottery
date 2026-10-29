#!/usr/bin/env python3
"""Automated User Ticket Settlement Engine (Taiwan Sports Lottery Protocol).

Audits active user tickets in `TicketRecorder`, matches official scores across
supported leagues (MLB, NBA, WNBA, NFL, Premier, La Liga, MLS, CPBL, NPB, KBO),
evaluates outcomes via `TaiwanSettlementRules` (including VOID=1.0 odds),
and atomically settles tickets into the Weekly Reserve Pool.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from core.bet_validation import parse_aware_time
from core.identity.league_mapping import normalize_league_and_sport
from core.settlement.taiwan_rules import (
    OfficialCompletionStatus,
    SettlementResult,
    TaiwanSettlementRules,
    resolve_settlement_rule_id,
)
from core.settlement_engine import SettlementEngine
from core.ticket_recorder import TicketRecorder
from core.line_notifier import LineNotifier

logger = logging.getLogger(__name__)


def _extract_leg_date(leg: Dict[str, Any]) -> Optional[str]:
    """Extract local game date string YYYY-MM-DD from leg metadata."""
    start_utc = leg.get("start_time_utc") or leg.get("event_start")
    start = parse_aware_time(start_utc)
    if not start:
        return None
    league = str(leg.get("league") or "").upper()
    tz_name = {"NPB": "Asia/Tokyo", "CPBL": "Asia/Taipei", "KBO": "Asia/Seoul"}.get(league)
    if tz_name:
        return start.astimezone(ZoneInfo(tz_name)).date().isoformat()
    return start.date().isoformat()


class TicketSettlementEngine:
    """Automated ticket settlement engine for user betting slips."""

    def __init__(
        self,
        settlement_engine: Optional[SettlementEngine] = None,
        ticket_recorder: Optional[TicketRecorder] = None,
        line_notifier: Optional[LineNotifier] = None,
    ):
        self.settlement_engine = settlement_engine or SettlementEngine()
        self.ticket_recorder = ticket_recorder or TicketRecorder()
        self.line_notifier = line_notifier or LineNotifier()
        self._games_cache: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}

    def clear_cache(self) -> None:
        """Clear cached game results."""
        self._games_cache.clear()

    def fetch_games_for_leg(self, leg: Dict[str, Any], date_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch games matching the leg's sport, league, and date window."""
        raw_sport = str(leg.get("sport") or "").lower()
        raw_league = str(leg.get("league") or "").upper()
        canonical_league, canonical_sport = normalize_league_and_sport(raw_league)
        sport = canonical_sport if canonical_sport else raw_sport
        league = canonical_league if canonical_league != "OTHER" else raw_league

        target_date = date_str or _extract_leg_date(leg)
        if not target_date:
            # Fallback to today UTC if no date can be parsed
            target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Query dates: target_date plus adjacent dates to handle timezone differences
        try:
            base_dt = datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            base_dt = datetime.now(timezone.utc)
            target_date = base_dt.strftime("%Y-%m-%d")

        date_window = [
            (base_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            target_date,
            (base_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
        ]

        all_games: List[Dict[str, Any]] = []
        for d in date_window:
            cache_key = (sport, league, d)
            if cache_key in self._games_cache:
                all_games.extend(self._games_cache[cache_key])
                continue

            fetched_for_date: List[Dict[str, Any]] = []
            try:
                if hasattr(self.settlement_engine, "fetch_results"):
                    fetched_for_date = self.settlement_engine.fetch_results(sport, league, d)
                elif sport == "baseball" and league == "MLB":
                    fetched_for_date = list(self.settlement_engine.fetch_mlb_completed_games(d).values())
            except Exception as exc:
                logger.warning("Auto-settle fetch failed for %s/%s on %s: %s", sport, league, d, exc)

            self._games_cache[cache_key] = fetched_for_date
            all_games.extend(fetched_for_date)

        return all_games

    def evaluate_leg(self, leg: Dict[str, Any], games: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Match and evaluate a single leg against official results."""
        if games is None:
            games = self.fetch_games_for_leg(leg)

        matched_game = None
        if games:
            if hasattr(self.settlement_engine, "match_result_game"):
                matched_game = self.settlement_engine.match_result_game(leg, games)
            if not matched_game and leg.get("sport") == "baseball" and "MLB" in str(leg.get("league", "")).upper():
                legacy_games = {str(g.get("game_pk") or i): g for i, g in enumerate(games)}
                if hasattr(self.settlement_engine, "match_mlb_game"):
                    matched_game = self.settlement_engine.match_mlb_game(leg, legacy_games)

        orig_odds = float(leg.get("odds") or leg.get("taiwan_odds") or 1.0)

        if not matched_game:
            # Check if kickoff time is in future
            start = parse_aware_time(leg.get("start_time_utc") or leg.get("event_start"))
            now_utc = datetime.now(timezone.utc)
            if start and start > now_utc:
                return {
                    "status": "NOT_STARTED",
                    "reason": f"尚未開賽 (預計 {leg.get('start_time') or start.strftime('%H:%M')})",
                    "matched_game": None,
                    "score": None,
                    "effective_odds": orig_odds,
                }
            return {
                "status": "PENDING",
                "reason": "尚未取得官方賽果 (進行中或等待資料發布)",
                "matched_game": None,
                "score": None,
                "effective_odds": orig_odds,
            }

        game_status = matched_game.get("status") or (
            "FINAL" if matched_game.get("game_status") in {"Final", "Completed", "Game Over"} else "PENDING"
        )
        provider_status = matched_game.get("provider_status") or matched_game.get("game_status") or game_status

        away_score = matched_game.get("away_score")
        home_score = matched_game.get("home_score")
        score_str = matched_game.get("final_score") or (
            f"{away_score}:{home_score}" if away_score is not None and home_score is not None else None
        )

        # Check for cancelled / postponed matches
        if game_status == "VOID" or "cancel" in str(provider_status).lower():
            return {
                "status": "VOID",
                "reason": f"賽事取消/延期無效 ({provider_status})，依台彩規定賠率計為 1.0",
                "matched_game": matched_game,
                "score": score_str,
                "effective_odds": 1.0,
            }

        if game_status != "FINAL":
            return {
                "status": "IN_PROGRESS",
                "reason": f"比賽進行中 ({provider_status})" if score_str else f"賽事狀態: {provider_status}",
                "matched_game": matched_game,
                "score": score_str,
                "effective_odds": orig_odds,
            }

        if away_score is None or home_score is None:
            return {
                "status": "UNRESOLVED",
                "reason": "賽事已結束但缺少官方正式比分",
                "matched_game": matched_game,
                "score": score_str,
                "effective_odds": orig_odds,
            }

        # Apply Taiwan Sports Lottery official rules
        sport = str(leg.get("sport") or matched_game.get("sport") or "baseball").lower()
        league = str(leg.get("league") or matched_game.get("league") or "MLB").upper()
        market = str(leg.get("market") or leg.get("market_type") or "")
        selection = str(leg.get("selection") or "")
        side = str(leg.get("side") or "")
        line = leg.get("line")

        rule_id = resolve_settlement_rule_id(sport, league, market)
        res: SettlementResult = self.settlement_engine.evaluate_leg_settlement(
            market=market,
            selection=selection,
            line=line,
            away_score=away_score,
            home_score=home_score,
            side=side,
            rule_id=rule_id,
            soccer_regulation_away=matched_game.get("soccer_regulation_away"),
            soccer_regulation_home=matched_game.get("soccer_regulation_home"),
            innings_completed=matched_game.get("innings_completed"),
            official_completion_status=matched_game.get("official_completion_status"),
            game_status="Final",
        )

        eff_odds = orig_odds if res.status == "WON" else (1.0 if res.status in ("VOID", "PUSH") else 0.0)

        return {
            "status": res.status,
            "reason": res.reason,
            "matched_game": matched_game,
            "score": score_str,
            "effective_odds": eff_odds,
            "is_called_game": getattr(res, "is_called_game", False),
        }

    def evaluate_ticket(self, ticket: Dict[str, Any]) -> Dict[str, Any]:
        """Audit and evaluate all legs of a user ticket."""
        legs = ticket.get("legs", [])
        if not legs:
            return {
                "ticket_id": ticket["id"],
                "can_settle": False,
                "final_status": ticket.get("status", "OPEN"),
                "payout": float(ticket.get("actual_payout", 0.0)),
                "recalculated_odds": float(ticket.get("total_odds", 1.0)),
                "legs_eval": [],
                "summary": "無關卡資料",
            }

        legs_eval = [self.evaluate_leg(leg) for leg in legs]

        stake = float(ticket.get("stake", 10.0))

        # Check for Round Robin (過關組合) ticket
        notes_str = str(ticket.get("notes") or "")
        rr_meta = None
        if "round_robin_spec" in notes_str or "ROUND_ROBIN" in notes_str:
            try:
                import json
                parsed = json.loads(notes_str)
                if isinstance(parsed, dict) and parsed.get("type") == "ROUND_ROBIN":
                    rr_meta = parsed
            except Exception:
                pass

        if rr_meta and "round_robin_spec" in rr_meta:
            from core.round_robin import RoundRobinEngine
            combo_key = rr_meta["round_robin_spec"]
            unit_stake = float(rr_meta.get("unit_stake", 10.0))
            rr_res = RoundRobinEngine.evaluate_round_robin_settlement(
                legs=legs,
                combo_key=combo_key,
                legs_eval=legs_eval,
                unit_stake=unit_stake,
                total_stake=stake,
            )
            return {
                "ticket_id": ticket["id"],
                "is_round_robin": True,
                "can_settle": rr_res["can_settle"],
                "final_status": rr_res["final_status"],
                "payout": rr_res["payout"],
                "recalculated_odds": round(rr_res["payout"] / stake, 2) if stake > 0 else 1.0,
                "legs_eval": legs_eval,
                "won_count": sum(1 for e in legs_eval if e["status"] == "WON"),
                "lost_count": sum(1 for e in legs_eval if e["status"] == "LOST"),
                "void_count": sum(1 for e in legs_eval if e["status"] in ("VOID", "PUSH")),
                "pending_count": sum(1 for e in legs_eval if e["status"] in ("PENDING", "IN_PROGRESS", "NOT_STARTED")),
                "round_robin_details": rr_res,
                "summary": rr_res["summary"],
            }

        has_lost = False
        all_resolved = True
        all_void = True
        recalculated_odds = 1.0

        won_count = 0
        lost_count = 0
        void_count = 0
        pending_count = 0

        for le in legs_eval:
            st = le["status"]
            if st == "LOST":
                has_lost = True
                all_void = False
                lost_count += 1
            elif st in ("VOID", "PUSH"):
                recalculated_odds *= 1.0
                void_count += 1
            elif st == "WON":
                all_void = False
                recalculated_odds *= le["effective_odds"]
                won_count += 1
            else:
                all_resolved = False
                pending_count += 1

        recalculated_odds = round(recalculated_odds, 4)

        if has_lost:
            # In sports lottery parlay, if any leg loses, the whole ticket loses
            can_settle = True
            final_status = "LOST"
            payout = 0.0
            summary = f"未過關 ({lost_count} 關失利，{won_count} 關過關)"
        elif all_resolved:
            if all_void:
                can_settle = True
                final_status = "VOID"
                payout = stake
                summary = "全數退盤 (賽事取消/無效，本金全退)"
            else:
                can_settle = True
                final_status = "WON"
                raw_payout = stake * recalculated_odds
                payout = round(raw_payout, 2)
                void_note = f" (含 {void_count} 關無效賠率1.0)" if void_count > 0 else ""
                summary = f"🎉 全數過關！{won_count}/{len(legs)} 關命中{void_note}"
        else:
            can_settle = False
            final_status = "OPEN"
            payout = float(ticket.get("potential_payout", stake * recalculated_odds))
            summary = f"進行中 ({won_count} 關已過，{pending_count} 關待定)"

        return {
            "ticket_id": ticket["id"],
            "can_settle": can_settle,
            "final_status": final_status,
            "payout": payout,
            "recalculated_odds": recalculated_odds,
            "legs_eval": legs_eval,
            "won_count": won_count,
            "lost_count": lost_count,
            "void_count": void_count,
            "pending_count": pending_count,
            "summary": summary,
        }

    def auto_settle_open_tickets(self, dry_run: bool = False) -> Dict[str, Any]:
        """Automatically fetch scores and settle all resolvable OPEN user tickets."""
        open_tickets = [t for t in self.ticket_recorder.list_tickets(limit=100) if t.get("status") == "OPEN"]
        
        settled_won = 0
        settled_lost = 0
        settled_void = 0
        still_open = 0
        total_payout_credited = 0.0
        results: List[Dict[str, Any]] = []

        for ticket in open_tickets:
            eval_res = self.evaluate_ticket(ticket)
            results.append(eval_res)

            if eval_res["can_settle"] and not dry_run:
                tid = ticket["id"]
                st = eval_res["final_status"]
                payout = eval_res["payout"]

                settle_note = f"🤖 自動對獎結算: {eval_res['summary']}"
                if st == "WON":
                    self.ticket_recorder.settle_ticket(tid, won=True, custom_payout=payout, notes=settle_note)
                    settled_won += 1
                    total_payout_credited += payout
                    if self.line_notifier and self.line_notifier.is_configured():
                        try:
                            wallet_status = self.ticket_recorder.wallet.get_status() if hasattr(self.ticket_recorder, "wallet") and self.ticket_recorder.wallet else {}
                            self.line_notifier.notify_ticket_settlement(
                                ticket=ticket,
                                won=True,
                                actual_payout=payout,
                                prize_pool=float(wallet_status.get("prize_pool", 0.0)),
                                weekly_balance=float(wallet_status.get("weekly_wallet_balance", 0.0)),
                            )
                        except Exception as n_exc:
                            logger.warning("Failed to send LINE notification for WON ticket: %s", n_exc)
                elif st == "LOST":
                    self.ticket_recorder.settle_ticket(tid, won=False, notes=settle_note)
                    settled_lost += 1
                elif st == "VOID":
                    self.ticket_recorder.settle_ticket(tid, won=False, is_void=True, notes=settle_note)
                    settled_void += 1
                    total_payout_credited += payout
            else:
                still_open += 1

        return {
            "total_open_checked": len(open_tickets),
            "settled_won": settled_won,
            "settled_lost": settled_lost,
            "settled_void": settled_void,
            "still_open": still_open,
            "total_payout_credited": round(total_payout_credited, 2),
            "ticket_results": results,
        }
