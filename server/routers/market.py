from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.app_meta import APP_BUILD
from core.forward_evaluation_engine import ForwardEvaluationEngine
from core.market_aligner import MarketAligner
from core.market_candidate_policy import (
    allowed_scheduled_markets,
    candidate_rejection_reason,
    canonical_league_query_key,
)
from core.market_fair_odds import MarketFairOddsEngine
from core.market_scheduler import get_market_scheduler
from core.scraper import ALLIANCE_MAP
from core.snapshot_logger import PredictionSnapshotLogger
from core.strategy_version import get_strategy_metadata
from core.contracts.market import TAIWAN_MARKET_TO_ODDS_API
from integrations.odds.betting_splits_client import BettingSplitsClient
from integrations.odds.the_odds_api import SPORT_KEY_MAP, TheOddsApiClient
from server import service_registry
from server.auth import require_active_admin_session, verify_no_pending_password_change
from server.formatters import clean_league_name
from server.responses import (
    ForwardEvaluationResponse,
    LegsResponse,
    MarketResearchSummaryResponse,
    RadarResponse,
)
from server.schemas import MarketKeyConfigRequest, MarketSchedulerConfigRequest, TheOddsTestConnectionRequest

logger = logging.getLogger("server.api")

router = APIRouter()



@router.get("/api/health")
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


@router.get("/api/radar", response_model=RadarResponse)
def get_radar(
    force_refresh: bool = False,
    _session: Optional[Dict[str, Any]] = Depends(verify_no_pending_password_change),
):
    odds_adapter, _, _, season_radar, _, _, _, _ = service_registry.get_services()
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


@router.get("/api/market/status")
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


@router.get("/api/market/research-summary", response_model=MarketResearchSummaryResponse)
def get_market_research_summary():
    """Retrieve unified Phase 4.5 operational and prospective verification summary."""
    from core.market_forward_pipeline import MarketForwardPipeline
    pipeline = MarketForwardPipeline()
    summary = pipeline.get_research_status_summary()
    summary["scheduler"] = get_market_scheduler().get_status()
    return summary


@router.get("/api/market/scheduler/status")
def get_market_scheduler_status():
    """Retrieve background scheduler runtime metrics, next run time, and cadence."""
    scheduler = get_market_scheduler()
    return scheduler.get_status()


@router.post("/api/market/scheduler/config")
def update_market_scheduler_config(
    req: MarketSchedulerConfigRequest,
    _session: Dict[str, Any] = Depends(require_active_admin_session),
):
    """Update background scheduler settings (enable/disable or interval)."""
    scheduler = get_market_scheduler()
    return scheduler.update_config(enabled=req.enabled, interval_seconds=req.interval_seconds)


@router.post("/api/market/config")
def update_market_api_key(
    req: MarketKeyConfigRequest,
    _session: Dict[str, Any] = Depends(require_active_admin_session),
):
    """Save The Odds API key securely into gitignored config/odds_api.local.yaml without modifying Git."""
    key = req.the_odds_api_key.strip()
    if not re.match(r"^[a-zA-Z0-9_-]+$", key):
        raise HTTPException(status_code=400, detail="Invalid API key format. Alphanumeric characters only.")

    odds_client = TheOddsApiClient()
    success = odds_client.save_api_key(key)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save local API key.")

    # The scheduler owns a long-lived client created at service startup. Refresh
    # that instance too so the next live cycle does not keep serving synthetic data.
    try:
        get_market_scheduler().pipeline.odds_client.reload_api_key()
    except Exception as exc:
        logger.warning("Saved The Odds API key, but the active scheduler client did not reload it: %s", exc)

    return {
        "status": "SUCCESS",
        "message": "The Odds API key saved securely into local configuration.",
        "the_odds_api": odds_client.get_source_status(),
    }


@router.post("/api/market/the-odds/test-connection")
def test_the_odds_api_connection(
    req: Optional[TheOddsTestConnectionRequest] = None,
    _session: Dict[str, Any] = Depends(require_active_admin_session),
):
    """Zero-credit connection test verifying API key validity and fetching official quota headers."""
    odds_client = TheOddsApiClient()
    fetch_sample = req.fetch_sample if req else False
    sport = req.sport_league if req else None
    res = odds_client.test_connection(fetch_sample=fetch_sample, sport_league=sport)
    return res


@router.get("/api/market/pipeline/estimate-cost")
def estimate_pipeline_cost(
    leagues: Optional[str] = Query(None, description="Comma-separated leagues (e.g. MLB,NBA)"),
    markets: Optional[str] = Query(None, description="Comma-separated markets (e.g. h2h,spreads)"),
):
    """Estimate credits by supported API sports, markets, and regions."""
    odds_client = TheOddsApiClient()
    target_leagues = [l.strip().upper() for l in leagues.split(",")] if leagues else ["NBA", "SOCCER"]
    market_str = markets or odds_client.scheduled_markets or "h2h"
    league_count = len(target_leagues)
    market_count = len([m for m in market_str.split(",") if m.strip()])
    api_sports = {
        SPORT_KEY_MAP.get(league.upper())
        for league in target_leagues
    }
    api_sport_count = len({sport for sport in api_sports if sport})
    regions = odds_client.regions or "us"
    region_count = len([region for region in regions.split(",") if region.strip()])
    estimated_credits = api_sport_count * market_count * region_count
    return {
        "target_leagues": target_leagues,
        "markets": market_str,
        "regions": regions,
        "league_count": league_count,
        "api_sport_count": api_sport_count,
        "market_count": market_count,
        "region_count": region_count,
        "estimated_credits": estimated_credits,
    }


@router.post("/api/market/pipeline/cycle")
def trigger_market_pipeline_cycle(
    leagues: Optional[str] = Query(None, description="Comma-separated leagues (e.g. MLB,NBA)"),
    force_refresh: bool = False,
    _session: Dict[str, Any] = Depends(require_active_admin_session),
):
    """Run an automated prospective validation cycle across live odds and snapshots."""
    scheduler = get_market_scheduler()
    league_list = [l.strip().upper() for l in leagues.split(",")] if leagues else None
    return scheduler.run_cycle_now(leagues=league_list, force_refresh=force_refresh)


@router.get("/api/market/benchmark")
def get_market_benchmark_comparison(
    league: str = Query("MLB", description="League identifier (e.g. MLB, NBA, SOCCER)"),
    force_refresh: bool = False,
    _session: Dict[str, Any] = Depends(require_active_admin_session),
):
    """Retrieve precision aligned international market benchmark odds, de-vigged fair probabilities, and theoretical EV."""
    odds_client = TheOddsApiClient()
    odds_adapter, signal_hub, _, _, _, _, _, _ = service_registry.get_services()
    raw_legs = odds_adapter.get_taiwan_legs([league], force_refresh=force_refresh)
    allowed_markets = allowed_scheduled_markets(
        getattr(odds_client, "markets", "h2h"),
        getattr(odds_client, "scheduled_markets", "auto"),
    )
    allowed_market_csv = ",".join(sorted(allowed_markets))
    rejection_counts: Counter[str] = Counter()
    rejection_examples: Dict[str, List[Dict[str, Any]]] = {}
    eligible_legs = []
    for leg in raw_legs:
        reason = candidate_rejection_reason(
            leg,
            league,
            allowed_market_csv,
            market_to_api=TAIWAN_MARKET_TO_ODDS_API,
            query_key_resolver=lambda value: canonical_league_query_key(value, SPORT_KEY_MAP),
        )
        if reason:
            rejection_counts[reason] += 1
            examples = rejection_examples.setdefault(reason, [])
            if len(examples) < 3:
                examples.append({
                    "event_id": str(getattr(leg, "event_id", "") or ""),
                    "league": str(getattr(leg, "league", "") or ""),
                })
            continue
        eligible_legs.append(leg)

    if not eligible_legs:
        return {
            "league": league,
            "status": "SKIPPED_NO_VALID_CANDIDATES",
            "total_taiwan_legs": len(raw_legs),
            "valid_candidate_count": 0,
            "rejected_candidate_count": len(raw_legs),
            "candidate_rejection_counts": dict(rejection_counts),
            "candidate_rejection_examples": rejection_examples,
            "matched_count": 0,
            "unmatched_count": 0,
            "stale_count": 0,
            "benchmarks": [],
            "as_of_utc": datetime.now(timezone.utc).isoformat(),
        }

    requested_markets = sorted({
        TAIWAN_MARKET_TO_ODDS_API[str(leg.market or "").strip().casefold()]
        for leg in eligible_legs
    })
    int_odds = odds_client.fetch_market_odds(
        league,
        markets=",".join(requested_markets),
        force_refresh=force_refresh,
    )
    aligner = MarketAligner()

    matched_results = []
    unmatched_count = 0
    stale_count = 0

    for leg in eligible_legs:
        leg_enriched = signal_hub.evaluate_taiwan_leg(leg)
        matched_cand, record = aligner.align_leg_with_candidates(leg_enriched, int_odds)
        if matched_cand and record.status.value == "MATCHED":
            # Strict devigging using MarketFairOddsEngine:
            # 1. NBA, MLB, NFL 2-way markets require complete both sides.
            # 2. Soccer 1X2 3-way markets require home, away, AND draw. Never treat 2 outcomes as a 2-way market!
            # 3. Missing counterparts, mismatched lines, or stale data Fail-Closed (EV = None).
            fair_prob = None
            ev = None
            ev_pct = None
            is_pos_ev = False
            ev_status = "NO_COUNTERPART_ODDS"
            counterpart_odds = None
            draw_odds = None
            can_devig = False

            is_three_way = (
                leg.sport == "soccer"
                or leg.league in {"EPL", "SOCCER", "LALIGA", "西甲", "英超", "CHAMPS_LEAGUE", "MLS", "WORLD_CUP"}
                or any(
                    o.event_id == matched_cand.event_id
                    and o.source_id == matched_cand.source_id
                    and o.market_type == "MONEYLINE"
                    and o.selection == "draw"
                    for o in int_odds
                )
            ) and matched_cand.market_type == "MONEYLINE"

            same_market_quotes = [
                o for o in int_odds
                if (
                    o.event_id == matched_cand.event_id
                    and o.source_id == matched_cand.source_id
                    and o.market_type == matched_cand.market_type
                    and o.freshness_status not in {"STALE", "EXPIRED"}
                )
            ]

            if is_three_way:
                # 3-way 1X2 market (e.g. Soccer):
                # Must find home, away, AND draw from the exact same bookmaker and event!
                # NEVER treat 2 outcomes of a 3-way market as a 2-way market!
                home_q = next((o for o in same_market_quotes if o.selection == "home" and o.decimal_odds > 1.0), None)
                away_q = next((o for o in same_market_quotes if o.selection == "away" and o.decimal_odds > 1.0), None)
                draw_q = next((o for o in same_market_quotes if o.selection == "draw" and o.decimal_odds > 1.0), None)

                if home_q and away_q and draw_q:
                    can_devig = True
                    draw_odds = draw_q.decimal_odds
                    if matched_cand.selection == "home":
                        counterpart_odds = away_q.decimal_odds
                    elif matched_cand.selection == "away":
                        counterpart_odds = home_q.decimal_odds
                    else:  # draw
                        counterpart_odds = home_q.decimal_odds
                        draw_odds = away_q.decimal_odds
                else:
                    can_devig = False
                    ev_status = "INCOMPLETE_THREE_WAY_MARKET"
            elif matched_cand.market_type == "SPREAD":
                # 2-way handicap: opposite handicap line required
                for other in same_market_quotes:
                    if (
                        other.selection != matched_cand.selection
                        and other.line is not None
                        and matched_cand.line is not None
                        and other.decimal_odds > 1.0
                        and math.isclose(other.line, -matched_cand.line, abs_tol=0.01)
                    ):
                        counterpart_odds = other.decimal_odds
                        can_devig = True
                        break
            elif matched_cand.market_type == "TOTAL":
                # 2-way total: identical threshold line required
                for other in same_market_quotes:
                    if (
                        other.selection != matched_cand.selection
                        and other.line is not None
                        and matched_cand.line is not None
                        and other.decimal_odds > 1.0
                        and math.isclose(other.line, matched_cand.line, abs_tol=0.01)
                    ):
                        counterpart_odds = other.decimal_odds
                        can_devig = True
                        break
            else:
                # 2-way MONEYLINE (MLB, NBA, NFL):
                for other in same_market_quotes:
                    if (
                        other.selection != matched_cand.selection
                        and other.selection in {"home", "away"}
                        and other.decimal_odds > 1.0
                    ):
                        counterpart_odds = other.decimal_odds
                        can_devig = True
                        break

            # De-vig using MarketFairOddsEngine
            if can_devig and counterpart_odds is not None and matched_cand.decimal_odds > 1.0:
                fair_engine = MarketFairOddsEngine()
                bq = BookmakerQuote(
                    book_name=matched_cand.source_id,
                    odds=matched_cand.decimal_odds,
                    opposing_odds=counterpart_odds,
                    draw_odds=draw_odds,
                    is_three_way=is_three_way,
                )
                fair_res = fair_engine.calculate_fair_odds(leg.taiwan_odds, [bq])
                if fair_res is not None:
                    fair_prob = round(fair_res.market_fair_prob, 4)
                    ev = round(fair_res.theoretical_ev, 4)
                    ev_pct = round(fair_res.theoretical_ev_pct, 1)
                    if matched_cand.is_synthetic:
                        is_pos_ev = False
                        ev_status = "SYNTHETIC_DATA_DISPLAY_ONLY"
                    else:
                        is_pos_ev = fair_res.is_value_bet
                        ev_status = "VERIFIED_DEVIGGED"
            else:
                # Task 3: Check fallback evidence from signal hub with strict completeness & provenance gates
                evidence = leg_enriched.signal_evidence or {}
                evidence_fair_p = evidence.get("market_fair_probability")
                fair_method = evidence.get("market_fair_method")
                is_complete = bool(evidence.get("market_complete"))
                is_evidence_synth = bool(
                    evidence.get("is_market_synthetic") or evidence.get("is_synthetic") or matched_cand.is_synthetic
                )

                # Strict provenance gate: Must come from COMPLETE_MARKET_PROPORTIONAL or verified 2-way
                # Never use BREAKEVEN_BASELINE_NOT_DEVIGGED as fair probability!
                can_use_evidence = (
                    evidence_fair_p is not None
                    and 0.0 < evidence_fair_p < 1.0
                    and is_complete
                    and (
                        (is_three_way and fair_method == "COMPLETE_MARKET_PROPORTIONAL")
                        or (not is_three_way and fair_method in {"COMPLETE_MARKET_PROPORTIONAL", "TWO_WAY_PROPORTIONAL"})
                    )
                )

                if can_use_evidence:
                    fair_prob = round(evidence_fair_p, 4)
                    ev_calc = (fair_prob * leg.taiwan_odds) - 1.0
                    ev = round(ev_calc, 4)
                    ev_pct = round(ev_calc * 100.0, 1)
                    if is_evidence_synth:
                        is_pos_ev = False
                        ev_status = "SYNTHETIC_DATA_DISPLAY_ONLY"
                    else:
                        is_pos_ev = ev_calc >= 0.02
                        ev_status = "VERIFIED_FROM_COMPLETE_MARKET"
                else:
                    # Fail-Closed: No verified counterpart odds or complete market
                    fair_prob = None
                    ev = None
                    ev_pct = None
                    is_pos_ev = False
                    if not is_three_way and ev_status != "INCOMPLETE_THREE_WAY_MARKET":
                        ev_status = "NO_COUNTERPART_ODDS"

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
                "counterpart_odds": counterpart_odds,
                "draw_odds": draw_odds if is_three_way else None,
                "is_three_way": is_three_way,
                "fair_probability": fair_prob,
                "theoretical_ev": ev,
                "theoretical_ev_pct": ev_pct,
                "is_positive_ev": is_pos_ev,
                "ev_status": ev_status,
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
        "status": "COMPLETED",
        "total_taiwan_legs": len(raw_legs),
        "valid_candidate_count": len(eligible_legs),
        "rejected_candidate_count": len(raw_legs) - len(eligible_legs),
        "candidate_rejection_counts": dict(rejection_counts),
        "candidate_rejection_examples": rejection_examples,
        "matched_count": len(matched_results),
        "unmatched_count": unmatched_count,
        "stale_count": stale_count,
        "benchmarks": matched_results,
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/market/splits")
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


@router.get("/api/market/evaluation", response_model=ForwardEvaluationResponse)
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


@router.get("/api/legs", response_model=LegsResponse)
def get_legs(
    alliances: Optional[str] = Query(None, description="Comma-separated alliance IDs"),
    force_refresh: bool = False,
    limit: int = Query(1000, ge=1, le=5000),
    _session: Optional[Dict[str, Any]] = Depends(verify_no_pending_password_change),
):
    odds_adapter, signal_hub, _, _, _, _, _, _ = service_registry.get_services()
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
