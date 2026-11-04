from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import Future
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from core.scraper import ALLIANCE_MAP
from core.signal_hub import SignalHub
from core.contracts.common import TaiwanLeg
from server import service_registry
from server.auth import verify_no_pending_password_change
from server.formatters import clean_league_name
from server.responses import ParlaySearchResponse
from server.schemas import ParlaySearchRequest

logger = logging.getLogger("server.api")
_parlay_search_lock = threading.Lock()
_parlay_search_inflight: Dict[str, Future] = {}
_parlay_search_capacity = threading.BoundedSemaphore(6)  # 2 active + up to 4 waiting
_parlay_search_slots = threading.BoundedSemaphore(2)
_parlay_prepared_lock = threading.Lock()
_parlay_prepared_cache: Optional[Dict[str, Any]] = None
_PARLAY_PREPARED_CACHE_TTL_SECONDS = 15 * 60
_PARLAY_PREPARED_CACHE_MAX_LEGS = 5000

router = APIRouter()



@router.post("/api/parlays/search", response_model=ParlaySearchResponse)
def search_parlays(
    req: ParlaySearchRequest,
    _session: Optional[Dict[str, Any]] = Depends(verify_no_pending_password_change),
):
    if (req.min_odds is None) != (req.max_odds is None):
        raise HTTPException(status_code=422, detail="min_odds 與 max_odds 必須同時提供。")
    request_key = hashlib.sha256(
        json.dumps(req.model_dump(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    with _parlay_search_lock:
        shared_result = _parlay_search_inflight.get(request_key)
        if shared_result is None:
            if not _parlay_search_capacity.acquire(blocking=False):
                raise HTTPException(
                    status_code=429,
                    detail="串關搜尋目前繁忙，請稍後再試。",
                    headers={"Retry-After": "5"},
                )
            shared_result = Future()
            _parlay_search_inflight[request_key] = shared_result
            is_owner = True
        else:
            is_owner = False

    if not is_owner:
        # Identical simultaneous searches use the same live data snapshot and
        # result. Completed results are removed immediately; later manual clicks
        # always start a fresh search.
        return shared_result.result()

    slot_acquired = False
    try:
        if not _parlay_search_slots.acquire(timeout=20):
            raise HTTPException(
                status_code=429,
                detail="串關搜尋佇列已滿，請稍後再試。",
                headers={"Retry-After": "5"},
            )
        slot_acquired = True
        try:
            result = _execute_parlay_search(req)
        finally:
            if slot_acquired:
                _parlay_search_slots.release()
                slot_acquired = False
    except BaseException as exc:
        with _parlay_search_lock:
            if _parlay_search_inflight.get(request_key) is shared_result:
                del _parlay_search_inflight[request_key]
        shared_result.set_exception(exc)
        raise
    else:
        # Remove before completing the Future so later manual requests cannot
        # receive a just-completed result as if it were a fresh search.
        with _parlay_search_lock:
            if _parlay_search_inflight.get(request_key) is shared_result:
                del _parlay_search_inflight[request_key]
        shared_result.set_result(result)
        return result
    finally:
        _parlay_search_capacity.release()


def _execute_parlay_search(req: ParlaySearchRequest):
    request_started = time.perf_counter()
    stage_started = request_started
    odds_adapter, signal_hub, parlay_engine, _, _, _, _, _ = service_registry.get_services()
    service_setup_ms = (time.perf_counter() - stage_started) * 1000

    selected_alliances = req.alliances if req.alliances else list(ALLIANCE_MAP.keys())
    stage_started = time.perf_counter()
    raw_legs = odds_adapter.get_taiwan_legs(selected_alliances, force_refresh=req.force_refresh)
    taiwan_fetch_ms = (time.perf_counter() - stage_started) * 1000

    # Enrich legs once per unchanged Taiwan snapshot. The combination search
    # still runs on every manual click; the cache only reuses signal work.
    enriched_legs, prep_cache_hit, signal_enrichment_ms = _get_prepared_parlay_legs(
        raw_legs, selected_alliances, signal_hub, bypass_cache=req.force_refresh
    )

    has_explicit_range = req.min_odds is not None and req.max_odds is not None
    if has_explicit_range:
        min_o = max(1.5, float(req.min_odds))
        max_o = float(req.max_odds)
        if max_o < min_o:
            raise HTTPException(status_code=422, detail="max_odds 必須大於或等於 min_odds。")
        engine_target_odds = None
        response_target_odds = req.target_odds or round((min_o + max_o) / 2.0, 2)
    else:
        engine_target_odds = req.target_odds or 20.0
        min_o = round(engine_target_odds * (1 - req.tolerance), 2)
        max_o = round(engine_target_odds * (1 + req.tolerance), 2)
        response_target_odds = engine_target_odds

    diagnostics: Dict[str, Any] = {}
    stage_started = time.perf_counter()
    parlay_results = parlay_engine.search_parlays(
        legs=enriched_legs,
        min_odds=max(1.5, min_o),
        max_odds=max_o,
        target_odds=engine_target_odds,
        tolerance=req.tolerance,
        signal_filter=req.signal_filter,
        exclude_traps=req.exclude_traps,
        prefer_steam=req.prefer_steam,
        min_legs=req.min_legs,
        max_legs=req.max_legs,
        diagnostics=diagnostics,
        search_budget=req.search_budget,
        ranking_mode=req.ranking_mode,
    )
    parlay_search_ms = (time.perf_counter() - stage_started) * 1000

    # Clean tier items
    def format_parlays(items: List[Dict[str, Any]], tier: str):
        formatted = []
        for p in items:
            p_copy = dict(p)
            p_copy["parlay_id"] = p.get("candidate_id") or p.get("parlay_id", "")
            p_copy["tier"] = tier
            # Search internals retain live objects for ranking/checkpointing;
            # clients only need the already-normalized `legs` response field.
            p_copy.pop("raw_legs", None)
            p_copy["expected_value"] = p.get("parlay_expected_value")
            p_copy["parlay_ev_pct"] = p.get("parlay_ev_pct")
            p_copy["sharp_parlay_ev_pct"] = p.get("sharp_parlay_ev_pct")
            p_copy["joint_probability"] = p.get("joint_probability")
            p_copy["sharp_badge"] = p.get("sharp_badge", "")
            p_copy["is_positive_ev"] = p.get("is_positive_ev", False)
            p_copy["parlay_expected_value_source"] = p.get("parlay_expected_value_source", "UNVALIDATED_ESTIMATE")
            p_copy["credible_value_basis"] = p.get("credible_value_basis", False)
            p_copy["credible_value_status"] = p.get("credible_value_status", "UNVERIFIED")
            p_copy["joint_probability_sources"] = p.get("joint_probability_sources", [])

            # Ensure legs in parlay are dicts and have display_league & signal fields
            clean_legs = []
            for l in p.get("legs", []):
                ld = l.to_dict() if hasattr(l, "to_dict") else dict(l.__dict__ if hasattr(l, "__dict__") else l)
                ld["display_league"] = clean_league_name(ld.get("league"))
                sig = ld.get("signal_evidence") or {}
                t_odds = float(ld.get("taiwan_odds") or ld.get("odds") or 1.0)
                is_synth = bool(sig.get("is_market_synthetic") or sig.get("is_synthetic"))
                prob = sig.get("consensus_probability")
                leg_ev = sig.get("expected_value_pct")

                ld["is_market_synthetic"] = is_synth
                # Keep the value paired with the same probability displayed on
                # the leg. Sharp EV remains in signal_evidence and is labeled
                # separately in the evidence drawer.
                ld["expected_value_pct"] = None if is_synth else leg_ev
                ld["consensus_probability"] = prob
                ld["market_implied_pct"] = sig.get("market_implied_pct", round((1.0 / t_odds) * 100.0, 1) if t_odds > 0 else 0.0)
                ld["agreement_badge"] = sig.get("agreement_badge", "")
                ld["is_positive_ev"] = bool(not is_synth and sig.get("is_positive_ev", False))
                ld["is_sharp_value_bet"] = bool(
                    not is_synth
                    and sig.get("market_source_qualification") == "SHARP_QUALIFIED"
                    and sig.get("is_sharp_value_bet", False)
                )
                ld["crowd_desc"] = sig.get("crowd_desc", "")
                ld["line_movement_label"] = (sig.get("line_movement") or {}).get("text_label", "")
                clean_legs.append(ld)
            p_copy["legs"] = clean_legs
            if any(l.get("is_market_synthetic") for l in clean_legs):
                p_copy["is_positive_ev"] = False
            formatted.append(p_copy)
        return formatted

    stage_started = time.perf_counter()
    response = {
        "target_odds": response_target_odds,
        "min_odds": min_o,
        "max_odds": max_o,
        "tolerance": req.tolerance,
        "tiers": {
            "high_consensus": format_parlays(parlay_results.get("high_consensus", []), "high_consensus"),
            "aggressive": format_parlays(parlay_results.get("aggressive", []), "aggressive"),
            "moonshot": format_parlays(parlay_results.get("moonshot", []), "moonshot"),
        },
        "diagnostics": diagnostics,
        "search_complete": diagnostics.get("search_complete", True),
        "total_combinations_searched": diagnostics.get("evaluated_combinations", 0),
        "enriched_legs_count": len(enriched_legs),
    }
    response_format_ms = (time.perf_counter() - stage_started) * 1000
    performance = {
        "service_setup_ms": round(service_setup_ms, 2),
        "taiwan_fetch_ms": round(taiwan_fetch_ms, 2),
        "signal_enrichment_ms": round(signal_enrichment_ms, 2),
        "parlay_search_ms": round(parlay_search_ms, 2),
        "response_format_ms": round(response_format_ms, 2),
        "total_ms": round((time.perf_counter() - request_started) * 1000, 2),
        "raw_legs_count": len(raw_legs),
        "prepared_legs_cache_hit": prep_cache_hit,
    }
    response["performance"] = performance
    logger.info("parlay_search_timing %s", json.dumps(performance, ensure_ascii=False, sort_keys=True))
    return response


def _get_prepared_parlay_legs(
    raw_legs: List[TaiwanLeg],
    selected_alliances: List[str],
    signal_hub: SignalHub,
    *,
    bypass_cache: bool = False,
) -> tuple[List[TaiwanLeg], bool, float]:
    """Reuse signal-enriched legs for the same fresh input snapshot.

    Keep a single bounded snapshot in memory. Source timestamps, freshness,
    eligibility, odds, and SignalHub configuration all participate in the key.
    """
    global _parlay_prepared_cache
    started = time.perf_counter()
    if len(raw_legs) > _PARLAY_PREPARED_CACHE_MAX_LEGS:
        return [signal_hub.evaluate_taiwan_leg(leg) for leg in raw_legs], False, (time.perf_counter() - started) * 1000

    weights_signature = hashlib.sha256(
        json.dumps(getattr(signal_hub, "weights_config", {}), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    leg_signature = tuple(
        (
            getattr(leg, "event_id", ""), getattr(leg, "sport", ""), getattr(leg, "league", ""),
            getattr(leg, "market", ""), getattr(leg, "selection", ""), getattr(leg, "side", None),
            getattr(leg, "line", None), float(getattr(leg, "taiwan_odds", 0.0) or 0.0),
            getattr(leg, "odds_scraped_at", None), getattr(leg, "odds_status", None),
            bool(getattr(leg, "eligible_for_parlay", True)), getattr(leg, "start_time_utc", None),
            getattr(leg, "canonical_event_id", None), getattr(leg, "away_team", None), getattr(leg, "home_team", None),
            getattr(leg, "away_pitcher", None), getattr(leg, "home_pitcher", None),
        )
        for leg in raw_legs
    )
    cache_key = (tuple(selected_alliances), id(signal_hub), getattr(signal_hub, "_cache_epoch", 0), weights_signature, leg_signature)

    with _parlay_prepared_lock:
        cache = _parlay_prepared_cache
        if (
            not bypass_cache
            and cache is not None
            and cache["key"] == cache_key
            and (time.monotonic() - cache["created_at"]) < _PARLAY_PREPARED_CACHE_TTL_SECONDS
        ):
            # Signal evidence is reused, while time-sensitive source fields are
            # copied from the just-fetched legs so displayed freshness stays current.
            prepared = []
            for raw, enriched in zip(raw_legs, cache["legs"]):
                leg = copy.copy(enriched)
                leg.odds_age_minutes = raw.odds_age_minutes
                leg.odds_status = raw.odds_status
                leg.eligible_for_parlay = raw.eligible_for_parlay
                evidence = dict(enriched.signal_evidence or {})
                for field in ("odds_age_minutes", "crowd_age_minutes", "odds_status", "source_status", "source_cache_status"):
                    if field in (raw.signal_evidence or {}):
                        evidence[field] = raw.signal_evidence[field]
                leg.signal_evidence = evidence
                prepared.append(leg)
            return prepared, True, (time.perf_counter() - started) * 1000

        prepared = [signal_hub.evaluate_taiwan_leg(leg) for leg in raw_legs]
        if not bypass_cache:
            _parlay_prepared_cache = {
                "key": cache_key,
                "legs": prepared,
                "created_at": time.monotonic(),
            }
        else:
            _parlay_prepared_cache = None
        return prepared, False, (time.perf_counter() - started) * 1000
