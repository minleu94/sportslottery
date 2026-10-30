#!/usr/bin/env python3
"""Automatic Result Settlement Engine (Taiwan Integrity Protocol).

Fetches official match outcomes from MLB Stats API, ESPN, and Football-Data feeds,
applies official Taiwan Sports Lottery settlement rules, resolves true closing prices,
and settles:
1. PredictionSnapshots (Cryptographic Payload Hash Audit, Brier, Log Loss, CLV)
2. Parlay candidate snapshots (Taiwan VOID rule: void leg = 1.0 odds)
3. Shadow Portfolio tickets (Unified deduplication & VOID refund handling)

Integrity Rules Enforced:
- Multi-provider conflict resolution (disagreeing scores -> UNRESOLVED)
- Comprehensive statuses: WON, LOST, PUSH, VOID, PENDING, UNRESOLVED
- Strict immutability verification: Mismatch raises AuditFailureError.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

from core.odds_watcher import OddsWatcher
from core.settlement.taiwan_rules import SettlementResult, TaiwanSettlementRules, resolve_settlement_rule_id
from core.shadow_parlay_logger import ShadowParlayLogger
from core.shadow_portfolio import ShadowPortfolioManager
from core.snapshot_logger import AuditFailureError, PredictionSnapshotLogger
from core.identity.team_alias import GLOBAL_TEAM_REGISTRY
from core.bet_validation import parse_aware_time
from integrations.results import CPBLResultProvider, ESPNResultProvider, OfficialAsianBaseballProvider

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"


class SettlementEngine:
    """Official Taiwan Lottery result settlement engine with audit verification."""

    def __init__(
        self,
        snapshot_logger: Optional[PredictionSnapshotLogger] = None,
        parlay_logger: Optional[ShadowParlayLogger] = None,
        shadow_portfolio: Optional[ShadowPortfolioManager] = None,
        odds_watcher: Optional[OddsWatcher] = None,
        session: Optional[requests.Session] = None,
        espn_result_provider: Optional[ESPNResultProvider] = None,
        asian_baseball_result_provider: Optional[OfficialAsianBaseballProvider] = None,
        cpbl_result_provider: Optional[CPBLResultProvider] = None,
    ):
        self.snapshot_logger = snapshot_logger or PredictionSnapshotLogger()
        self.parlay_logger = parlay_logger or ShadowParlayLogger()
        self.shadow_portfolio = shadow_portfolio or ShadowPortfolioManager()
        self.odds_watcher = odds_watcher or OddsWatcher()
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        self.espn_result_provider = espn_result_provider or ESPNResultProvider(session=self.session)
        self.asian_baseball_result_provider = asian_baseball_result_provider or OfficialAsianBaseballProvider(session=self.session)
        self.cpbl_result_provider = cpbl_result_provider or CPBLResultProvider(session=self.session)

    @staticmethod
    def supported_result_coverage() -> Dict[str, Dict[str, str]]:
        """Visible provider coverage; this describes source availability, not rule support."""
        return {
            "baseball/MLB": {"provider": "MLB_STATS_API", "coverage": "available"},
            "soccer/PREMIER": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party"},
            "soccer/LALIGA": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party"},
            "soccer/MLS": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party"},
            "soccer/UNKNOWN_美國足球大聯盟": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party_legacy_exact_alias"},
              "soccer/COLOMBIA_PRIMERA_A": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party"},
              "soccer/COSTA_RICA_PRIMERA": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party"},
            "soccer/AFC_CHAMPIONS_LEAGUE_TWO": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party_verified_observed_slate"},
            "soccer/SAUDI_PRO_LEAGUE": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party_verified_observed_slate"},
            "soccer/CONMEBOL_LIBERTADORES": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party_verified_observed_slate"},
            "soccer/CHAMPIONS": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party"},
            "basketball/NBA": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party"},
            "basketball/WNBA": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party"},
            "football/NFL": {"provider": "ESPN_PUBLIC_SCOREBOARD", "coverage": "available_third_party"},
            "baseball/NPB": {"provider": "NPB_OFFICIAL", "coverage": "available_official"},
            "baseball/CPBL": {"provider": "CPBL_STATS_OFFICIAL", "coverage": "game_jsonld; historical_lookup_requires_source_id"},
            "baseball/KBO": {"provider": "KBO_OFFICIAL", "coverage": "available_official"},
            "hockey/NHL": {"provider": "ESPN_SCOREBOARD", "coverage": "schedule_only_result_feed_unverified"},
        }

    def fetch_results(self, sport: str, league: str, date_str: str, source_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Fetch a date-scoped provider result feed and preserve provider status."""
        if sport == "baseball" and league.upper() == "MLB":
            return list(self.fetch_mlb_completed_games(date_str).values())
        if sport == "baseball" and league.upper() in {"NPB", "KBO"}:
            return [game.to_dict() for game in self.asian_baseball_result_provider.fetch(league, date_str)]
        if sport == "baseball" and league.upper() == "CPBL":
            return [game.to_dict() for game in self.cpbl_result_provider.fetch(date_str, source_ids or [])]
        parsed = self.espn_result_provider.fetch(sport, league.upper(), date_str.replace("-", ""))
        return [game.to_dict() for game in parsed]

    @staticmethod
    def match_result_game(snapshot: Dict[str, Any], games: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Match by exact source ID, or full canonical matchup plus aware UTC start.

        A source ID that is present but missing from the fetched provider set is
        an explicit miss; the routine never falls through to a weaker identity.
        """
        source_id = snapshot.get("source_game_id") or snapshot.get("source_event_id") or snapshot.get("provider_event_id") or snapshot.get("game_pk")
        provider = snapshot.get("result_provider")
        if source_id is not None:
            matches = [g for g in games if str(g.get("provider_event_id") or g.get("game_pk") or "") == str(source_id)
                       and (not provider or not g.get("provider") or provider == g.get("provider"))]
            if len(matches) != 1:
                return None
            candidate = matches[0]
            # An ID is authoritative only within the expected sport/league and
            # cannot override known conflicting teams or a known start time.
            for key in ("sport", "league"):
                expected = snapshot.get(key)
                actual = candidate.get(key)
                if expected and actual and str(expected).upper() != str(actual).upper():
                    return None
            sport = str(snapshot.get("sport") or candidate.get("sport") or "")
            league = str(snapshot.get("league") or candidate.get("league") or "")
            for side in ("away", "home"):
                snap_name = snapshot.get(f"{side}_team")
                result_name = candidate.get(f"{side}_team")
                if not snap_name or not result_name:
                    continue
                resolve_league = None if sport == "soccer" else league
                snap_team = GLOBAL_TEAM_REGISTRY.resolve(str(snap_name), sport=sport, league=resolve_league)
                result_team = GLOBAL_TEAM_REGISTRY.resolve(str(result_name), sport=sport, league=resolve_league)
                if snap_team and result_team and snap_team.canonical_id != result_team.canonical_id:
                    return None
            snap_start = parse_aware_time(snapshot.get("event_start") or snapshot.get("start_time_utc"))
            game_start = parse_aware_time(candidate.get("start_time_utc"))
            if snap_start and game_start and abs((snap_start - game_start).total_seconds()) > 900:
                return None
            return candidate

        start = parse_aware_time(snapshot.get("event_start") or snapshot.get("start_time_utc"))
        away_name, home_name = snapshot.get("away_team"), snapshot.get("home_team")
        if not start or not away_name or not home_name:
            return None
        sport, league = str(snapshot.get("sport") or ""), str(snapshot.get("league") or "")
        resolve_league = None if sport == "soccer" else league
        away = GLOBAL_TEAM_REGISTRY.resolve(str(away_name), sport=sport, league=resolve_league)
        home = GLOBAL_TEAM_REGISTRY.resolve(str(home_name), sport=sport, league=resolve_league)
        if not away or not home:
            return None
        matches = []
        league_tz = {"NPB": "Asia/Tokyo", "CPBL": "Asia/Taipei", "KBO": "Asia/Seoul"}.get(league.upper())
        if league_tz:
            local_date = start.astimezone(ZoneInfo(league_tz)).date().isoformat()
            for game in games:
                ga = GLOBAL_TEAM_REGISTRY.resolve(str(game.get("away_team") or ""), sport=sport, league=resolve_league)
                gh = GLOBAL_TEAM_REGISTRY.resolve(str(game.get("home_team") or ""), sport=sport, league=resolve_league)
                game_start = parse_aware_time(game.get("start_time_utc"))
                exact_teams = bool(ga and gh and ga.canonical_id == away.canonical_id and gh.canonical_id == home.canonical_id)
                if not exact_teams:
                    continue
                if game_start is not None:
                    if abs((game_start - start).total_seconds()) <= 900:
                        matches.append(game)
                elif game.get("event_date_local") == local_date:
                    matches.append(game)
            return matches[0] if len(matches) == 1 else None
        for game in games:
            ga = GLOBAL_TEAM_REGISTRY.resolve(str(game.get("away_team") or ""), sport=sport, league=resolve_league)
            gh = GLOBAL_TEAM_REGISTRY.resolve(str(game.get("home_team") or ""), sport=sport, league=resolve_league)
            game_start = parse_aware_time(game.get("start_time_utc"))
            if (ga and gh and game_start and ga.canonical_id == away.canonical_id
                    and gh.canonical_id == home.canonical_id
                    and abs((game_start - start).total_seconds()) <= 900):
                matches.append(game)
        return matches[0] if len(matches) == 1 else None

    def fetch_mlb_completed_games(self, date_str: str) -> Dict[str, Dict[str, Any]]:
        """Fetch completed MLB games for date YYYY-MM-DD from statsapi.mlb.com."""
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
        games = {}
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for date_info in data.get("dates", []):
                    for g in date_info.get("games", []):
                        status_obj = g.get("status", {})
                        abstract = str(status_obj.get("abstractGameState") or "").lower()
                        detailed = str(status_obj.get("detailedState") or status_obj.get("codedGameState") or abstract)
                        away_team = g.get("teams", {}).get("away", {}).get("team", {}).get("name", "")
                        home_team = g.get("teams", {}).get("home", {}).get("team", {}).get("name", "")
                        away_score = g.get("teams", {}).get("away", {}).get("score")
                        home_score = g.get("teams", {}).get("home", {}).get("score")
                        def _official_score(value):
                            if isinstance(value, bool) or not isinstance(value, (int, float)):
                                return None
                            if not math.isfinite(float(value)) or int(value) != value or value < 0:
                                return None
                            return int(value)
                        if abstract == "final":
                            away_score, home_score = _official_score(away_score), _official_score(home_score)
                            if away_score is None or home_score is None:
                                result_status = "UNRESOLVED"
                                completion = None
                                logger.warning("MLB final game has invalid score (gamePk=%s)", g.get("gamePk"))
                            else:
                                result_status = "FINAL"
                                completion = "REGULATION_COMPLETED"
                        elif "cancel" in detailed.lower():
                            result_status, completion = "VOID", "CANCELLED"
                            away_score = _official_score(away_score)
                            home_score = _official_score(home_score)
                        else:
                            result_status, completion = "PENDING", None
                            away_score = _official_score(away_score)
                            home_score = _official_score(home_score)
                        if away_score is None or home_score is None:
                            final_score = None
                            total_score = None
                        else:
                            final_score = f"{away_score}:{home_score}"
                            total_score = int(away_score + home_score)
                        game_pk = g.get("gamePk")
                        # gamePk is the stable identity; never key by matchup alone
                        # because doubleheaders have two independent results.
                        key = str(game_pk) if game_pk is not None else f"{date_info.get('date')}:{g.get('gameDate')}:{away_team}@{home_team}"
                        games[key] = {
                            "provider": "MLB_STATS_API",
                            "provider_event_id": str(game_pk) if game_pk is not None else None,
                            "sport": "baseball",
                            "league": "MLB",
                            "game_pk": str(game_pk) if game_pk is not None else None,
                            "game_date": date_info.get("date"),
                            "event_date_local": date_info.get("date"),
                            "start_time_utc": g.get("gameDate"),
                            "away_team": away_team,
                            "home_team": home_team,
                            "away_score": away_score,
                            "home_score": home_score,
                            "final_score": final_score,
                            "total_score": total_score,
                            "completed": result_status == "FINAL",
                            "status": result_status,
                            "game_status": detailed,
                            "provider_status": detailed,
                            "official_completion_status": completion,
                            "innings_completed": g.get("linescore", {}).get("currentInning") if g.get("linescore") else None,
                            "source": "MLB_STATS_API",
                        }
        except Exception as exc:
            logger.warning("Failed to fetch MLB schedule for date %s: %s", date_str, exc)

        return games

    @staticmethod
    def match_mlb_game(snapshot: Dict[str, Any], games: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Match only by stable source id or exact ordered teams and UTC start."""
        source_id = snapshot.get("source_game_id") or snapshot.get("game_pk")
        if source_id is not None:
            exact = [g for g in games.values() if str(g.get("game_pk")) == str(source_id)]
            if len(exact) != 1:
                return None
            candidate = exact[0]
            start = parse_aware_time(snapshot.get("event_start") or snapshot.get("start_time_utc"))
            if start is not None:
                game_start = parse_aware_time(candidate.get("start_time_utc"))
                if game_start is not None and abs((game_start - start).total_seconds()) > 900:
                    return None
            away_name, home_name = snapshot.get("away_team"), snapshot.get("home_team")
            if away_name and home_name:
                sport, league = snapshot.get("sport") or "baseball", snapshot.get("league") or "MLB"
                away = GLOBAL_TEAM_REGISTRY.resolve(str(away_name), sport=sport, league=league)
                home = GLOBAL_TEAM_REGISTRY.resolve(str(home_name), sport=sport, league=league)
                candidate_away = GLOBAL_TEAM_REGISTRY.resolve(str(candidate.get("away_team", "")), sport=sport, league=league)
                candidate_home = GLOBAL_TEAM_REGISTRY.resolve(str(candidate.get("home_team", "")), sport=sport, league=league)
                if away and home and candidate_away and candidate_home and (
                    away.canonical_id != candidate_away.canonical_id or home.canonical_id != candidate_home.canonical_id
                ):
                    return None
            return candidate

        start = parse_aware_time(snapshot.get("event_start") or snapshot.get("start_time_utc"))
        away_name, home_name = snapshot.get("away_team"), snapshot.get("home_team")
        if start is None or not away_name or not home_name:
            return None
        sport = snapshot.get("sport") or "baseball"
        league = snapshot.get("league") or "MLB"
        away = GLOBAL_TEAM_REGISTRY.resolve(str(away_name), sport=sport, league=league)
        home = GLOBAL_TEAM_REGISTRY.resolve(str(home_name), sport=sport, league=league)
        if not away or not home:
            return None
        matches = []
        for game in games.values():
            game_away = GLOBAL_TEAM_REGISTRY.resolve(str(game.get("away_team", "")), sport=sport, league=league)
            game_home = GLOBAL_TEAM_REGISTRY.resolve(str(game.get("home_team", "")), sport=sport, league=league)
            game_start = parse_aware_time(game.get("start_time_utc"))
            if not game_away or not game_home or game_start is None:
                continue
            if (game_away.canonical_id == away.canonical_id and game_home.canonical_id == home.canonical_id
                    and abs((game_start - start).total_seconds()) <= 900):
                matches.append(game)
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def find_leg_snapshot(leg: Dict[str, Any], snapshots: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Resolve a stored parlay leg to one prediction snapshot without local-id guessing."""
        sid = leg.get("snapshot_id")
        if sid:
            found = [s for s in snapshots if s.get("snapshot_id") == sid]
            return found[0] if len(found) == 1 else None
        source_id = leg.get("source_game_id") or leg.get("game_pk")
        canonical = leg.get("canonical_event_id")
        start = parse_aware_time(leg.get("start_time_utc") or leg.get("event_start"))
        event_id = leg.get("event_id") or leg.get("match_id")
        market, selection = leg.get("market"), leg.get("selection")
        line = str(leg.get("line") or "")
        matches = []
        for snap in snapshots:
            if snap.get("market") != market or snap.get("selection") != selection or str(snap.get("line") or "") != line:
                continue
            if source_id is not None:
                if str(snap.get("source_game_id") or snap.get("game_pk")) == str(source_id):
                    matches.append(snap)
                continue
            if canonical:
                if snap.get("canonical_event_id") == canonical:
                    matches.append(snap)
                continue
            snap_start = parse_aware_time(snap.get("event_start") or snap.get("start_time_utc"))
            if event_id and str(snap.get("event_id")) == str(event_id) and start and snap_start == start:
                matches.append(snap)
        return matches[0] if len(matches) == 1 else None

    def evaluate_leg_outcome(
        self,
        market: str,
        selection: str,
        line: Optional[float],
        away_score: int,
        home_score: int,
        side: str = "",
        rule_id: Optional[str] = None,
        is_postponed: bool = False,
        postponed_beyond_window: bool = False,
        soccer_regulation_away: Optional[int] = None,
        soccer_regulation_home: Optional[int] = None,
        innings_completed: Optional[float] = None,
        official_completion_status: Optional[str] = None,
    ) -> bool:
        """Evaluate whether a selection won based on Taiwan Lottery rules (backward compatibility helper)."""
        result = self.evaluate_leg_settlement(
            market, selection, line, away_score, home_score, side,
            rule_id or resolve_settlement_rule_id("baseball", "MLB", market),
            is_postponed, postponed_beyond_window, soccer_regulation_away,
            soccer_regulation_home, innings_completed, official_completion_status,
        )
        return result.status == "WON"

    def evaluate_leg_settlement(
        self,
        market: str,
        selection: str,
        line: Optional[float],
        away_score: int,
        home_score: int,
        side: str = "",
        rule_id: Optional[str] = None,
        is_postponed: bool = False,
        postponed_beyond_window: bool = False,
        soccer_regulation_away: Optional[int] = None,
        soccer_regulation_home: Optional[int] = None,
        innings_completed: Optional[float] = None,
        official_completion_status: Optional[str] = None,
        game_status: str = "Final",
    ):
        """Return the full rule-engine result without collapsing non-binary states."""
        if line is not None:
            try:
                line = float(line)
            except (TypeError, ValueError):
                return SettlementResult(status="UNRESOLVED", reason="盤口門檻格式無效，無法安全結算")
        elif ("讓分" in market and market != "不讓分") or any(token in market for token in ("大小", "總分")):
            embedded = re.search(r"([+-]?\d+(?:\.\d+)?)", str(selection))
            if not embedded:
                return SettlementResult(status="UNRESOLVED", reason="缺少讓分/大小盤門檻，無法安全結算")
            line = float(embedded.group(1))
        if not rule_id:
            return SettlementResult(status="UNRESOLVED", reason="缺少明確運動與聯盟結算規則，拒絕套用預設規則")
        actual_rule = rule_id
        return TaiwanSettlementRules.evaluate_taiwan_market(
            rule_id=actual_rule,
            market=market,
            selection=selection,
            line=line,
            away_score=away_score,
            home_score=home_score,
            side=side,
            is_postponed=is_postponed,
            postponed_beyond_window=postponed_beyond_window,
            soccer_regulation_away=soccer_regulation_away,
            soccer_regulation_home=soccer_regulation_home,
            innings_completed=innings_completed,
            official_completion_status=official_completion_status,
            game_status=game_status,
        )

    def settle_single_prediction_direct(
        self,
        snapshot_id: str,
        actual_outcome: Optional[bool],
        settlement_status: Optional[str] = None,
        settlement_reason: Optional[str] = None,
        closing_odds: Optional[float] = None,
        reference_closing_odds: Optional[float] = None,
        closing_odds_source: Optional[str] = None,
        final_score: Optional[str] = None,
        result_source: str = "STATS_API",
    ) -> Optional[Dict[str, Any]]:
        """Settle a snapshot with strict payload hash check."""
        return self.snapshot_logger.settle_prediction(
            snapshot_id=snapshot_id,
            actual_outcome=actual_outcome,
            settlement_status=settlement_status,
            settlement_reason=settlement_reason,
            final_score=final_score,
            result_source=result_source,
            closing_odds=closing_odds,
            reference_closing_odds=reference_closing_odds,
            closing_odds_source=closing_odds_source,
        )

    @staticmethod
    def check_provider_conflict(
        provider_a_result: Tuple[int, int],
        provider_b_result: Optional[Tuple[int, int]],
    ) -> bool:
        """Return True if multiple result providers report conflicting scores."""
        if provider_b_result is None:
            return False
        return bool(provider_a_result != provider_b_result)

    def settle_parlays_against_snapshots(self) -> Dict[str, int]:
        """Settle parlay candidates and shadow tickets using official Taiwan VOID logic."""
        all_snaps = self.snapshot_logger.get_all_snapshots()

        settled_candidates_count = 0
        all_parlays = self.parlay_logger.get_all_parlay_snapshots()

        for p_snap in all_parlays:
            for cand in p_snap.get("candidates", []):
                if cand.get("settled"):
                    continue

                legs = cand.get("legs", [])
                if not legs:
                    continue

                # Check status of every leg
                leg_eval_list: List[Tuple[str, float]] = []
                leg_result_snapshots = []
                all_resolved = True

                for leg in legs:
                    target_snap = self.find_leg_snapshot(leg, all_snaps)

                    if not target_snap or not target_snap.get("is_settled"):
                        all_resolved = False
                        break

                    status = target_snap.get("settlement_status")
                    if not status:
                        outcome = target_snap.get("actual_outcome")
                        status = "WON" if outcome is True else "LOST" if outcome is False else "UNRESOLVED"
                    if status not in {"WON", "LOST", "PUSH", "VOID"}:
                        all_resolved = False
                        break

                    orig_odds = float(leg.get("taiwan_odds", target_snap.get("taiwan_odds", 1.0)))
                    leg_eval_list.append((status, orig_odds))
                    leg_result_snapshots.append(target_snap)

                if all_resolved:
                    cid = cand.get("candidate_id")
                    self.parlay_logger.settle_parlay_candidate_with_taiwan_rules(
                        candidate_id=cid,
                        leg_statuses=leg_eval_list,
                        virtual_stake=10.0,
                        leg_result_snapshots=leg_result_snapshots,
                    )
                    settled_candidates_count += 1

        # Settle shadow tickets using identical Taiwan VOID rules
        settled_shadow_count = 0
        open_tickets = [t for t in self.shadow_portfolio.get_recent_tickets(200) if t["status"] == "OPEN"]

        for t in open_tickets:
            try:
                legs = json.loads(t["legs_json"]) if isinstance(t["legs_json"], str) else t["legs_json"]
            except Exception:
                legs = []

            if not legs:
                continue

            leg_eval_list = []
            all_resolved = True

            for leg in legs:
                ms = self.find_leg_snapshot(leg, all_snaps)
                if ms and ms.get("is_settled"):
                    status = ms.get("settlement_status")
                    if not status:
                        outcome = ms.get("actual_outcome")
                        status = "WON" if outcome is True else "LOST" if outcome is False else "UNRESOLVED"
                    if status not in {"WON", "LOST", "PUSH", "VOID"}:
                        all_resolved = False
                        break
                    orig_odds = float(leg.get("taiwan_odds", ms.get("taiwan_odds", 1.0)))
                    leg_eval_list.append((status, orig_odds))
                else:
                    all_resolved = False
                    break

            if all_resolved:
                # Recalculate multiplier with VOID legs = 1.0
                recalc_odds = 1.0
                any_lost = False
                all_void = True
                has_win = False

                for status, orig_odds in leg_eval_list:
                    if status == "LOST":
                        any_lost = True
                        all_void = False
                    elif status in ["VOID", "PUSH"]:
                        recalc_odds *= 1.0
                    elif status == "WON":
                        recalc_odds *= orig_odds
                        all_void = False
                        has_win = True

                recalc_odds = round(recalc_odds, 4)

                if any_lost:
                    final_status = "LOST"
                elif all_void:
                    final_status = "VOID"
                elif has_win:
                    final_status = "WON"
                else:
                    final_status = "PENDING"

                if final_status != "PENDING":
                    self.shadow_portfolio.settle_ticket(
                        ticket_id=t["id"],
                        settlement_status=final_status,
                        recalculated_odds=recalc_odds,
                    )
                    settled_shadow_count += 1

        return {
            "settled_parlay_candidates": settled_candidates_count,
            "settled_shadow_tickets": settled_shadow_count,
        }
