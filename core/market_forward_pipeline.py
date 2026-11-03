#!/usr/bin/env python3
"""Market Intelligence & Continuous Forward Validation Pipeline.

Phase 4.5: Global Market Intelligence & Continuous Forward Validation.

Executes the complete verified data lifecycle:
1. Retrieval: Fetch live Taiwan legs and international market quotes (The Odds API)
2. Alignment: Bi-directional team normalization, temporal window, line equivalence
3. Devigging & Valuation: 2-way / 3-way de-vigging to calculate true fair prob and EV
4. Pre-Match Snapshots: Immutable SHA-256 sealed prediction snapshots with pre-game cutoff
5. Match Settlement: Verification of original payload hashes, outcome settlement, Brier/LogLoss/CLV
6. Comparative Forward Evaluation: 3-way benchmark report (Taiwan Base vs Sharp Benchmark vs Model)
7. Sample Size Guard: Strictly enforces Shadow Mode when N < 30.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from core.forward_evaluation_engine import (
    ForwardEvaluationEngine,
    MIN_FORWARD_EVALUATION_SAMPLE,
    StrategyComparisonReport,
    _validated_market_probabilities,
)
from core.market_aligner import MarketAligner
from core.market_candidate_policy import candidate_rejection_reason, canonical_league_query_key
from core.market_fair_odds import BookmakerQuote, MarketFairOddsEngine
from core.market_provider_factory import (
    DEFAULT_MARKET_PROVIDER_CAPABILITIES,
    MarketProviderCapabilities,
    build_default_market_providers,
)
from core.persistence import iter_jsonl
from core.settlement_engine import SettlementEngine
from core.signal_hub import SignalHub
from core.snapshot_logger import PredictionSnapshotLogger, compute_prediction_payload_hash
from core.bet_validation import parse_aware_time
from core.contracts.common import TaiwanLeg
from core.contracts.market import (
    MarketAlignmentStatus,
    MarketBenchmarkEvidence,
    MarketOddsSnapshot,
    MarketSelectionIdentity,
    TAIWAN_MARKET_TO_ODDS_API,
    canonical_market_event_id,
)
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter
from integrations.odds.the_odds_api import TheOddsApiClient

logger = logging.getLogger(__name__)

SUMMARY_PATH = Path(__file__).resolve().parents[1] / "data" / "research" / "forward_evaluation_summary.json"

_summary_cache_payload: Optional[Dict[str, Any]] = None
_summary_cache_mtime: int = 0
_summary_cache_time: float = 0
_summary_cache_lock = threading.Lock()


def _alignment_summary_from_scheduler_status(scheduler_status: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Expose quote alignment separately from Odds API source availability."""
    latest_cycle = (scheduler_status or {}).get("last_cycle_summary") or {}
    if not latest_cycle:
        return {"status": "NO_RECORDED_CYCLE"}
    matched = int(latest_cycle.get("real_matched_count", 0) or 0)
    return {
        "status": "REAL_QUOTES_MATCHED" if matched else "NO_REAL_QUOTES_MATCHED",
        "real_matched_count": matched,
        "taiwan_snapshots_logged": latest_cycle.get("taiwan_snapshots_logged", 0),
        "valid_candidate_count": latest_cycle.get("valid_candidate_count", 0),
        "unique_candidate_event_count": latest_cycle.get("unique_candidate_event_count", 0),
        "real_market_quote_count": latest_cycle.get("real_market_quote_count", 0),
        "complete_market_benchmark_count": latest_cycle.get("complete_market_benchmark_count", 0),
        "sharp_qualified_count": latest_cycle.get("sharp_qualified_count", 0),
        "ev_count": latest_cycle.get("ev_count", 0),
        "candidate_rejection_counts": latest_cycle.get("candidate_rejection_counts", {}),
        "rejection_counts": latest_cycle.get("alignment_rejection_counts", {}),
        "rejection_examples": latest_cycle.get("alignment_rejection_examples", {}),
        "query_diagnostics": latest_cycle.get("query_diagnostics", {}),
        "official_credits_consumed": latest_cycle.get("official_credits_consumed"),
        "estimated_credits": latest_cycle.get("estimated_credits", 0),
        "credit_accounting_source": latest_cycle.get("credit_accounting_source", "UNKNOWN"),
        "cycle_timestamp_utc": latest_cycle.get("timestamp_utc"),
    }


class MarketForwardPipeline:
    """End-to-end continuous market intelligence and prospective validation engine."""

    _MARKET_TO_API = TAIWAN_MARKET_TO_ODDS_API

    def __init__(
        self,
        odds_adapter: Optional[PlaysportOddsAdapter] = None,
        odds_client: Optional[TheOddsApiClient] = None,
        signal_hub: Optional[SignalHub] = None,
        aligner: Optional[MarketAligner] = None,
        fair_engine: Optional[MarketFairOddsEngine] = None,
        snapshot_logger: Optional[PredictionSnapshotLogger] = None,
        settlement_engine: Optional[SettlementEngine] = None,
        evaluation_engine: Optional[ForwardEvaluationEngine] = None,
        summary_path: Optional[Path] = None,
        provider_capabilities: Optional[MarketProviderCapabilities] = None,
        scheduler_status_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        if odds_adapter is None or odds_client is None:
            default_adapter, default_client = build_default_market_providers(
                taiwan=odds_adapter is None,
                international=odds_client is None,
            )
        else:
            default_adapter, default_client = None, None
        self.odds_adapter = odds_adapter if odds_adapter is not None else default_adapter
        self.odds_client = odds_client if odds_client is not None else default_client
        self.provider_capabilities = provider_capabilities or DEFAULT_MARKET_PROVIDER_CAPABILITIES
        self.signal_hub = signal_hub or SignalHub()
        self.aligner = aligner or MarketAligner()
        self.fair_engine = fair_engine or MarketFairOddsEngine()
        self.snapshot_logger = snapshot_logger or PredictionSnapshotLogger()
        self.settlement_engine = settlement_engine or SettlementEngine(
            snapshot_logger=self.snapshot_logger
        )
        if (isinstance(self.settlement_engine, SettlementEngine)
                and self.settlement_engine.snapshot_logger is not self.snapshot_logger):
            self.settlement_engine.snapshot_logger = self.snapshot_logger
        self.evaluation_engine = evaluation_engine or ForwardEvaluationEngine()
        self.summary_path = summary_path or SUMMARY_PATH
        self.scheduler_status_provider = scheduler_status_provider
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)

    def resolve_target_leagues(self, leagues: Optional[List[str]] = None) -> List[str]:
        """Resolve one cycle's league list so costing and fetching use the same targets."""
        if leagues:
            return list(leagues)
        try:
            active = self.odds_adapter.get_active_leagues_with_games()
            return list(active) if active else ["NBA", "SOCCER"]
        except Exception:
            return ["MLB", "NBA", "NFL", "SOCCER"]

    def _candidate_query_key(self, league: str) -> Optional[str]:
        """Resolve only leagues the configured Odds API client can query."""
        return canonical_league_query_key(league, self.provider_capabilities.sport_key_map)

    def _api_query_league(self, league: str) -> Optional[str]:
        """Return a concrete client-supported league label for a sport key."""
        key = self._candidate_query_key(league)
        if not key:
            return None
        return self.provider_capabilities.preferred_league_labels.get(key)

    @staticmethod
    def _split_markets(value: Any) -> set[str]:
        if isinstance(value, str):
            return {part.strip().casefold() for part in value.split(",") if part.strip()}
        if isinstance(value, (list, tuple, set)):
            return {str(part).strip().casefold() for part in value if str(part).strip()}
        return set()

    def _allowed_scheduled_markets(self) -> set[str]:
        """Return markets both enabled by the client cap and schedule policy."""
        cap = self._split_markets(getattr(self.odds_client, "markets", "h2h"))
        if not cap:
            cap = {"h2h"}
        scheduled = getattr(self.odds_client, "scheduled_markets", "auto")
        if not isinstance(scheduled, str) or scheduled.strip().casefold() in {"", "auto", "candidate", "candidate_driven"}:
            return cap
        return self._split_markets(scheduled) & cap

    def _candidate_rejection_reason(
        self,
        leg: TaiwanLeg,
        query_league: str,
        target_markets: str,
    ) -> Optional[str]:
        """Compatibility wrapper around the separately testable candidate policy."""
        return candidate_rejection_reason(
            leg,
            query_league,
            target_markets,
            market_to_api=self._MARKET_TO_API,
            query_key_resolver=self._candidate_query_key,
        )

    @staticmethod
    def _quote_freshness(observed_times: List[Optional[str]]) -> str:
        parsed = [parse_aware_time(value) for value in observed_times]
        if not parsed or any(value is None for value in parsed):
            return "UNKNOWN"
        now = datetime.now(timezone.utc)
        ages = [(now - value).total_seconds() for value in parsed if value is not None]
        if any(age < -300 or age > 900 for age in ages):
            return "STALE"
        if any(age > 300 for age in ages):
            return "AGING"
        if any(age > 120 for age in ages):
            return "FRESH"
        return "LIVE"

    def _build_market_benchmark_evidence(
        self,
        leg: TaiwanLeg,
        primary: MarketOddsSnapshot,
        market_quotes: List[MarketOddsSnapshot],
        *,
        taiwan_odds: float,
    ) -> Optional[MarketBenchmarkEvidence]:
        """Build a same-event, complete-market benchmark from verified API books."""
        provider_quotes = [
            quote for quote in market_quotes
            if quote.event_id == primary.event_id
            and quote.market_type == primary.market_type
            and not quote.is_synthetic
            and quote.source_type.upper() in {"BOOKMAKER", "EXCHANGE"}
            and quote.source_id.startswith("the_odds_api:")
            and quote.decimal_odds > 1.0
        ]
        matching_primaries = [
            quote for quote in provider_quotes
            if MarketSelectionIdentity(primary.market_type, primary.selection, primary.line).same_outcome(
                MarketSelectionIdentity(quote.market_type, quote.selection, quote.line)
            )
        ]

        bookmaker_quotes: List[BookmakerQuote] = []
        bookmaker_rows: List[Dict[str, Any]] = []
        sharp_quotes: List[BookmakerQuote] = []
        sharp_sources: List[str] = []
        raw_outcome_odds: Dict[str, Dict[str, float]] = {}
        observation_times: Dict[str, Dict[str, Optional[str]]] = {}
        retrieval_times: List[datetime] = []
        all_observed: List[Optional[str]] = []
        sharp_book_ids = {
            str(book).strip().casefold()
            for book in getattr(self.odds_client, "sharp_qualified_books", ["pinnacle"])
            if str(book).strip()
        }

        for candidate in matching_primaries:
            same_book = [quote for quote in provider_quotes if quote.source_id == candidate.source_id]
            is_three_way = (
                candidate.market_type == "MONEYLINE"
                and any(quote.event_id == candidate.event_id
                        and quote.market_type == candidate.market_type
                        and quote.selection == "draw" for quote in same_book)
            )
            quote = self._build_fair_odds_quote(candidate, same_book, is_three_way)
            if quote is None:
                continue
            if candidate.market_type == "MONEYLINE":
                quote_times = list(same_book)
            elif candidate.market_type == "SPREAD" and candidate.line is not None:
                identity = MarketSelectionIdentity(candidate.market_type, candidate.selection, candidate.line)
                quote_times = [
                    item for item in same_book
                    if identity.same_outcome(MarketSelectionIdentity(item.market_type, item.selection, item.line))
                    or identity.opposite_outcome(MarketSelectionIdentity(item.market_type, item.selection, item.line))
                ]
            elif candidate.market_type == "TOTAL" and candidate.line is not None:
                identity = MarketSelectionIdentity(candidate.market_type, candidate.selection, candidate.line)
                quote_times = [
                    item for item in same_book
                    if identity.same_outcome(MarketSelectionIdentity(item.market_type, item.selection, item.line))
                    or identity.opposite_outcome(MarketSelectionIdentity(item.market_type, item.selection, item.line))
                ]
            else:
                quote_times = []
            times = [item.observed_at_utc for item in quote_times]
            freshness = self._quote_freshness(times)
            if freshness in {"UNKNOWN", "STALE"}:
                continue
            result = self.fair_engine.calculate_fair_odds(
                taiwan_odds=taiwan_odds,
                benchmark_quotes=[quote],
                observed_at=candidate.observed_at_utc,
            )
            if result is None:
                continue

            bookmaker_id = candidate.source_id.split(":", 1)[-1].casefold()
            sharp_qualified = bookmaker_id in sharp_book_ids
            bookmaker_quotes.append(quote)
            bookmaker_rows.append({
                "source_id": candidate.source_id,
                "bookmaker_id": bookmaker_id,
                "source_type": candidate.source_type,
                "outcome_odds": {item.selection: item.decimal_odds for item in quote_times},
                "observed_at_utc": {item.selection: item.observed_at_utc for item in quote_times},
                "retrieved_at_utc": max((item.retrieved_at_utc for item in quote_times), default=None),
                "fair_probability": result.market_fair_prob,
                "devig_method": result.devig_method,
                "freshness_status": freshness,
                "sharp_qualified": sharp_qualified,
            })
            raw_outcome_odds[candidate.source_id] = {
                item.selection: item.decimal_odds for item in quote_times
            }
            observation_times[candidate.source_id] = {
                item.selection: item.observed_at_utc for item in quote_times
            }
            all_observed.extend(times)
            for item in quote_times:
                retrieved = parse_aware_time(item.retrieved_at_utc)
                if retrieved:
                    retrieval_times.append(retrieved)
            if sharp_qualified:
                sharp_quotes.append(quote)
                sharp_sources.append(candidate.source_id)

        if not bookmaker_quotes:
            return None
        fair_result = self.fair_engine.calculate_fair_odds(
            taiwan_odds=taiwan_odds,
            benchmark_quotes=bookmaker_quotes,
            observed_at=primary.observed_at_utc,
        )
        if fair_result is None:
            return None
        sharp_result = self.fair_engine.calculate_fair_odds(
            taiwan_odds=taiwan_odds,
            benchmark_quotes=sharp_quotes,
            observed_at=primary.observed_at_utc,
        ) if sharp_quotes else None
        kickoff = parse_aware_time(primary.start_time_utc)
        canonical_event_id = canonical_market_event_id(
            leg.sport, leg.league, primary.event_id, kickoff.isoformat() if kickoff else None,
        )
        return MarketBenchmarkEvidence(
            taiwan_event_id=str(leg.event_id),
            taiwan_selection=str(leg.selection),
            canonical_event_id=canonical_event_id,
            sport=leg.sport,
            league=leg.league,
            market_type=primary.market_type,
            selection=primary.selection,
            line=primary.line,
            source_id="the_odds_api:consensus",
            bookmaker_ids=sorted({row["bookmaker_id"] for row in bookmaker_rows}),
            raw_outcome_odds=raw_outcome_odds,
            market_observation_times=observation_times,
            retrieved_at_utc=max(retrieval_times).isoformat() if retrieval_times else datetime.now(timezone.utc).isoformat(),
            is_synthetic=False,
            devig_method=fair_result.devig_method,
            fair_probability=fair_result.market_fair_prob,
            sharp_fair_probability=sharp_result.market_fair_prob if sharp_result else None,
            source_qualification="SHARP_QUALIFIED" if sharp_result else "INTERNATIONAL_MARKET",
            complete=True,
            freshness_status=self._quote_freshness(all_observed),
            eligible=True,
            eligibility_reason=None,
            sharp_qualified_source_ids=sorted(set(sharp_sources)),
            bookmaker_evidence=bookmaker_rows,
        )

    @staticmethod
    def _build_fair_odds_quote(
        primary: MarketOddsSnapshot,
        market_quotes: List[MarketOddsSnapshot],
        is_three_way: bool,
    ) -> Optional[BookmakerQuote]:
        """Build a complete same-event, same-book quote for the fair-odds engine."""
        same_market = [
            quote for quote in market_quotes
            if quote.event_id == primary.event_id
            and quote.source_id == primary.source_id
            and quote.market_type == primary.market_type
            and quote.decimal_odds > 1.0
        ]

        def timestamps_are_consistent(quotes: List[MarketOddsSnapshot]) -> bool:
            observed = [parse_aware_time(quote.observed_at_utc) for quote in quotes]
            if not observed or any(value is None for value in observed):
                return False
            quote_times = [value for value in observed if value is not None]
            current = datetime.now(timezone.utc)
            if any((current - value).total_seconds() > 900 or (value - current).total_seconds() > 300
                   for value in quote_times):
                return False
            return (max(quote_times) - min(quote_times)).total_seconds() <= 120

        if is_three_way:
            by_selection = {quote.selection: quote for quote in same_market}
            if not {"home", "away", "draw"}.issubset(by_selection):
                return None
            other_selections = [selection for selection in ("home", "away", "draw") if selection != primary.selection]
            if primary.selection not in by_selection or len(other_selections) != 2:
                return None
            complete_quote = [by_selection[selection] for selection in ("home", "away", "draw")]
            if not timestamps_are_consistent(complete_quote):
                return None
            return BookmakerQuote(
                book_name=primary.source_id,
                odds=primary.decimal_odds,
                opposing_odds=by_selection[other_selections[0]].decimal_odds,
                draw_odds=by_selection[other_selections[1]].decimal_odds,
                is_three_way=True,
            )

        if primary.market_type == "SPREAD":
            if primary.selection not in {"home", "away"} or primary.line is None:
                return None
            opposing = next((
                quote for quote in same_market
                if MarketSelectionIdentity(primary.market_type, primary.selection, primary.line).opposite_outcome(
                    MarketSelectionIdentity(quote.market_type, quote.selection, quote.line)
                )
            ), None)
        elif primary.market_type == "TOTAL":
            if primary.selection not in {"over", "under"} or primary.line is None:
                return None
            opposing = next((
                quote for quote in same_market
                if MarketSelectionIdentity(primary.market_type, primary.selection, primary.line).opposite_outcome(
                    MarketSelectionIdentity(quote.market_type, quote.selection, quote.line)
                )
            ), None)
        elif primary.market_type == "MONEYLINE":
            if primary.selection not in {"home", "away"}:
                return None
            opposing = next((
                quote for quote in same_market
                if MarketSelectionIdentity(primary.market_type, primary.selection, primary.line).opposite_outcome(
                    MarketSelectionIdentity(quote.market_type, quote.selection, quote.line)
                )
            ), None)
        else:
            return None

        if opposing is None:
            return None
        if not timestamps_are_consistent([primary, opposing]):
            return None
        return BookmakerQuote(
            book_name=primary.source_id,
            odds=primary.decimal_odds,
            opposing_odds=opposing.decimal_odds,
        )

    def run_market_snapshot_cycle(
        self,
        leagues: Optional[List[str]] = None,
        force_refresh: bool = False,
        automated: bool = False,
    ) -> Dict[str, Any]:
        """Fetch only candidate-required markets, align evidence, and log sealed snapshots."""
        target_leagues = self.resolve_target_leagues(leagues)
        initial_status = self.odds_client.get_source_status()
        usage_before = initial_status.get("requests_used_this_month", 0)
        metrics_before = initial_status.get("request_metrics", {}) or {}
        allowed_markets = self._allowed_scheduled_markets()
        market_order = ("h2h", "spreads", "totals")
        region_count = len(self._split_markets(getattr(self.odds_client, "regions", "us"))) or 1

        raw_by_league: Dict[str, List[TaiwanLeg]] = {}
        candidate_records: List[tuple[str, TaiwanLeg, str, str]] = []
        seen_candidate_legs: set[tuple[str, str, str, str, str, str]] = set()
        query_groups: Dict[str, Dict[str, Any]] = {}
        league_query_diagnostics: Dict[str, Dict[str, Any]] = {}
        for league in target_leagues:
            try:
                raw_legs = list(self.odds_adapter.get_taiwan_legs([league], force_refresh=force_refresh) or [])
            except Exception as exc:
                logger.warning("Taiwan candidate retrieval failed for %s: %s", league, exc)
                raw_legs = []
                league_query_diagnostics[league] = {
                    "raw_leg_count": 0, "valid_candidate_count": 0, "valid_event_count": 0,
                    "rejected_leg_count": 0, "skip_reason_counts": {"TAIWAN_SOURCE_ERROR": 1},
                    "query_called": False, "client_call_count": 0, "network_request_count": 0,
                    "cache_hit_count": 0, "estimated_credits": 0, "actual_credits": 0,
                }
            raw_by_league[league] = raw_legs
            rejection_counts: Counter[str] = Counter()
            valid_count = 0
            valid_events: set[str] = set()
            for leg in raw_legs:
                reason = self._candidate_rejection_reason(leg, league, ",".join(sorted(allowed_markets)))
                if reason:
                    rejection_counts[reason] += 1
                    continue
                api_market = self._MARKET_TO_API.get(str(leg.market or "").strip().casefold())
                query_key = self._candidate_query_key(leg.league)
                client_league = self._api_query_league(leg.league)
                if not api_market or not query_key or not client_league:
                    rejection_counts["UNSUPPORTED_OR_MISMATCHED_LEAGUE"] += 1
                    continue
                try:
                    normalized_line = str(float(leg.line)) if leg.line is not None else ""
                except (TypeError, ValueError, OverflowError):
                    normalized_line = str(leg.line or "").strip()
                candidate_fingerprint = (
                    str(leg.sport).casefold(), query_key, str(leg.event_id), api_market,
                    str(leg.side).strip().casefold(), normalized_line,
                )
                if candidate_fingerprint in seen_candidate_legs:
                    rejection_counts["DUPLICATE_CANDIDATE_LEG"] += 1
                    continue
                seen_candidate_legs.add(candidate_fingerprint)
                valid_count += 1
                valid_events.add(str(leg.event_id))
                candidate_records.append((league, leg, query_key, api_market))
                group = query_groups.setdefault(query_key, {
                    "client_league": client_league,
                    "markets": set(),
                    "records": [],
                })
                group["markets"].add(api_market)
                group["records"].append((league, leg))
            if league not in league_query_diagnostics:
                league_query_diagnostics[league] = {
                    "raw_leg_count": len(raw_legs), "valid_candidate_count": valid_count,
                    "valid_event_count": len(valid_events), "rejected_leg_count": len(raw_legs) - valid_count,
                    "skip_reason_counts": dict(rejection_counts), "query_called": False,
                    "client_call_count": 0, "network_request_count": 0, "cache_hit_count": 0,
                    "estimated_credits": 0, "actual_credits": 0,
                }
            if not valid_count:
                if not raw_legs:
                    league_query_diagnostics[league]["skip_reason_counts"] = {"NO_TAIWAN_CANDIDATES": 1}
                logger.info("Skipping Odds API odds query for %s: no valid Taiwan candidates; 0 estimated credits", league)

        query_diagnostics: Dict[str, Dict[str, Any]] = {}
        quotes_by_sport_key: Dict[str, List[MarketOddsSnapshot]] = {}
        requested_market_union: set[str] = set()
        client_invocation_count = 0
        network_request_count = 0
        cache_hit_count = 0
        estimated_credits = 0
        official_credits_consumed = 0
        official_credit_accounting_complete = True
        for query_key, group in query_groups.items():
            markets = [market for market in market_order if market in group["markets"]]
            market_string = ",".join(markets)
            requested_market_union.update(markets)
            estimated_cost = len(markets) * region_count
            estimated_credits += estimated_cost
            client_invocation_count += 1
            before = self.odds_client.get_source_status()
            before_metrics = before.get("request_metrics", {}) or {}
            before_usage = before.get("requests_used_this_month", 0)
            try:
                quotes = list(self.odds_client.fetch_market_odds(
                    group["client_league"], markets=market_string,
                    force_refresh=force_refresh, automated=automated,
                ) or [])
                query_error = None
            except Exception as exc:
                logger.warning("Odds API market query failed for %s: %s", query_key, exc)
                quotes = []
                query_error = str(exc)
            after = self.odds_client.get_source_status()
            after_metrics = after.get("request_metrics", {}) or {}
            try:
                query_network_requests = max(0, int(after_metrics.get("api_requests", 0) or 0) - int(before_metrics.get("api_requests", 0) or 0))
                query_cache_hits = max(0, int(after_metrics.get("cache_hits", 0) or 0) - int(before_metrics.get("cache_hits", 0) or 0))
                query_cache_hits += max(0, int(after_metrics.get("coalesced_requests", 0) or 0) - int(before_metrics.get("coalesced_requests", 0) or 0))
                query_actual_credits = max(0, int(after.get("requests_used_this_month", before_usage) or 0) - int(before_usage or 0))
            except (TypeError, ValueError):
                query_network_requests = query_cache_hits = query_actual_credits = 0
            network_request_count += query_network_requests
            cache_hit_count += query_cache_hits
            query_accounting_source = after.get("requests_last_accounting_source", "UNKNOWN")
            if query_network_requests == 0:
                query_official_credits: Optional[int] = 0
            elif query_accounting_source == "OFFICIAL_HEADERS":
                query_official_credits = query_actual_credits
            else:
                query_official_credits = None
                official_credit_accounting_complete = False
            if query_official_credits is not None:
                official_credits_consumed += query_official_credits
            quotes_by_sport_key[query_key] = quotes
            synthetic_count = sum(1 for quote in quotes if quote.is_synthetic)
            query_diagnostics[query_key] = {
                "query_league": group["client_league"], "markets": markets,
                "regions": getattr(self.odds_client, "regions", ""),
                "candidate_count": len(group["records"]),
                "event_count": len({str(leg.event_id) for _, leg in group["records"]}),
                "client_invocation_count": 1, "network_request_count": query_network_requests,
                "cache_hit_count": query_cache_hits, "estimated_credits": estimated_cost,
                "accounted_credits_consumed": query_actual_credits,
                "official_credits_consumed": query_official_credits,
                "credit_accounting_source": query_accounting_source,
                "snapshot_count": len(quotes),
                "real_snapshot_count": len(quotes) - synthetic_count,
                "synthetic_snapshot_count": synthetic_count, "error": query_error,
            }
            for requested_league, _ in group["records"]:
                diag = league_query_diagnostics[requested_league]
                diag["query_called"] = True
                diag["query_sport_keys"] = sorted(set(diag.get("query_sport_keys", []) + [query_key]))
                diag["client_call_count"] += 1
                diag["network_request_count"] += query_network_requests
                diag["cache_hit_count"] += query_cache_hits
                diag["estimated_credits"] += estimated_cost
                diag["actual_credits"] += query_actual_credits

        total_legs_processed = sum(len(rows) for rows in raw_by_league.values())
        total_matched = total_snapshots_logged = 0
        total_unmatched = max(0, total_legs_processed - len(candidate_records))
        real_market_quote_count = synthetic_market_quote_count = 0
        real_matched_count = synthetic_matched_count = 0
        complete_market_benchmark_count = sharp_qualified_count = ev_count = 0
        qualified_pending_candidate_count = 0
        candidate_rejection_counts: Counter[str] = Counter()
        for diagnostics in league_query_diagnostics.values():
            candidate_rejection_counts.update(diagnostics.get("skip_reason_counts", {}))
        alignment_rejection_counts: Counter[str] = Counter()
        alignment_rejection_examples: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for query_key, quotes in quotes_by_sport_key.items():
            synthetic_market_quote_count += sum(1 for quote in quotes if quote.is_synthetic)
            real_market_quote_count += sum(1 for quote in quotes if not quote.is_synthetic)

        for _, leg, query_key, _api_market in candidate_records:
            int_odds = quotes_by_sport_key.get(query_key, [])
            cand, record = self.aligner.align_leg_with_candidates(leg, int_odds)
            benchmark: Optional[MarketBenchmarkEvidence] = None
            if cand and record.status == MarketAlignmentStatus.MATCHED:
                total_matched += 1
                if cand.is_synthetic:
                    synthetic_matched_count += 1
                else:
                    real_matched_count += 1
                    try:
                        benchmark = self._build_market_benchmark_evidence(
                            leg, cand, int_odds, taiwan_odds=float(leg.taiwan_odds),
                        )
                    except Exception as exc:
                        logger.warning("Market benchmark qualification failed for event %s: %s", leg.event_id, exc)
                if benchmark and benchmark.eligible:
                    complete_market_benchmark_count += 1
                    sharp_qualified_count += bool(benchmark.sharp_qualified_source_ids)
            else:
                total_unmatched += 1
                rejection_code = record.rejection_code or record.status.value
                alignment_rejection_counts[rejection_code] += 1
                if len(alignment_rejection_examples[rejection_code]) < 2:
                    alignment_rejection_examples[rejection_code].append({
                        "taiwan_event_id": record.taiwan_event_id,
                        "taiwan_league": record.taiwan_league,
                        "taiwan_market": record.taiwan_market,
                        "taiwan_selection": record.taiwan_selection,
                        "taiwan_line": record.taiwan_line,
                        "international_event_id": record.international_event_id,
                        "international_league": next((q.league for q in int_odds if q.event_id == record.international_event_id), None),
                        "international_market_type": record.international_market_type,
                        "international_line": record.international_line,
                        "time_delta_seconds": record.time_delta_seconds,
                        "reason": record.reason,
                    })

            if benchmark and benchmark.eligible:
                enriched = self.signal_hub.evaluate_taiwan_leg(leg, market_benchmark=benchmark)
            else:
                enriched = self.signal_hub.evaluate_taiwan_leg(leg)
            if not enriched.odds_scraped_at:
                enriched.odds_scraped_at = (cand.observed_at_utc if cand else None) or datetime.now(timezone.utc).isoformat()
            if enriched.expected_value is not None:
                ev_count += 1
            try:
                snapshot = self.snapshot_logger.log_snapshot(enriched)
                total_snapshots_logged += 1
                if (
                    benchmark and cand and record.status == MarketAlignmentStatus.MATCHED
                    and not cand.is_synthetic and snapshot.get("forward_validation_eligible") is True
                    and snapshot.get("settlement_status") == "PENDING"
                ):
                    qualified_pending_candidate_count += 1
            except Exception as exc:
                logger.debug("Snapshot logging skipped for leg %s: %s", enriched.event_id, exc)

        final_status = self.odds_client.get_source_status()
        try:
            credits_consumed = max(0, int(final_status.get("requests_used_this_month", usage_before) or 0) - int(usage_before or 0))
        except (TypeError, ValueError):
            credits_consumed = 0
        final_metrics = final_status.get("request_metrics", {}) or {}
        qualified_per_credit = round(complete_market_benchmark_count / credits_consumed, 4) if credits_consumed else None
        credit_accounting_source = (
            "NO_NETWORK_REQUESTS" if network_request_count == 0 else
            "OFFICIAL_HEADERS" if official_credit_accounting_complete else
            "MIXED_OR_ESTIMATED"
        )
        official_credit_result = (
            0 if network_request_count == 0 else
            official_credits_consumed if official_credit_accounting_complete else
            None
        )
        return {
            "target_leagues": target_leagues,
            "target_markets": ",".join(market for market in market_order if market in requested_market_union) or "NONE",
            "target_regions": getattr(self.odds_client, "regions", ""),
            "total_legs_processed": total_legs_processed,
            "valid_candidate_count": sum(int(d.get("valid_candidate_count", 0) or 0) for d in league_query_diagnostics.values()),
            "unique_candidate_event_count": len({(leg.sport, leg.league, str(leg.event_id)) for _, leg, _, _ in candidate_records}),
            "total_matched": total_matched,
            "real_matched_count": real_matched_count,
            "synthetic_matched_count": synthetic_matched_count,
            "total_unmatched": total_unmatched,
            "complete_market_benchmark_count": complete_market_benchmark_count,
            "sharp_qualified_count": sharp_qualified_count,
            "ev_count": ev_count,
            "candidate_rejection_counts": dict(candidate_rejection_counts),
            "alignment_rejection_counts": dict(alignment_rejection_counts),
            "alignment_rejection_examples": dict(alignment_rejection_examples),
            "league_query_diagnostics": league_query_diagnostics,
            "query_diagnostics": query_diagnostics,
            "client_invocation_count": client_invocation_count,
            "network_request_count": network_request_count,
            "cache_hit_count": cache_hit_count,
            "estimated_credits": estimated_credits,
            "accounted_credits_consumed": credits_consumed,
            "official_credits_consumed": official_credit_result,
            "credit_accounting_source": credit_accounting_source,
            "qualified_market_matches_per_credit": qualified_per_credit,
            "api_request_count_total": int(final_metrics.get("api_requests", 0) or 0),
            "snapshots_logged": total_snapshots_logged,
            "taiwan_snapshots_logged": total_snapshots_logged,
            "real_market_quote_count": real_market_quote_count,
            "synthetic_market_quote_count": synthetic_market_quote_count,
            "qualified_pending_candidate_count": qualified_pending_candidate_count,
            "credits_consumed": credits_consumed,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    def run_settlement_cycle(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Fetch verified results and settle due prediction snapshots idempotently."""
        current_time = parse_aware_time(now) if now is not None else datetime.now(timezone.utc)
        if current_time is None:
            raise ValueError("Settlement observation time must be timezone aware.")

        unsettled_checked = 0
        deferred_count = 0
        missing_start_count = 0
        due_snapshots: List[Dict[str, Any]] = []
        result_grace = 3 * 60 * 60

        for snap in iter_jsonl(self.snapshot_logger.log_path):
            if snap.get("is_settled"):
                continue
            unsettled_checked += 1
            event_start = parse_aware_time(snap.get("event_start") or snap.get("start_time_utc"))
            if event_start is None:
                missing_start_count += 1
                continue
            if (current_time - event_start).total_seconds() <= result_grace:
                deferred_count += 1
                continue
            due_snapshots.append(snap)

        # Reuse the same provider coverage, identity matching, Taiwan settlement
        # rules, payload integrity check, and idempotent writes used by the full
        # research settlement workflow.
        if due_snapshots:
            from scripts.settle_results import settle_snapshot_results

            result = settle_snapshot_results(
                self.settlement_engine,
                due_snapshots,
                now=current_time,
            )
        else:
            result = {
                "settled": 0,
                "unresolved": 0,
                "games": 0,
                "coverage": {},
                "unmatched_observations": [],
                "deferred_snapshots": 0,
                "deferred_observations": [],
            }

        parlay_result = self.settlement_engine.settle_parlays_against_snapshots()
        fetch_errors = {
            league: list(info.get("errors") or [])
            for league, info in result.get("coverage", {}).items()
            if info.get("fetch_status") == "FETCH_ERROR"
        }
        return {
            "unsettled_checked": unsettled_checked,
            "due_count": len(due_snapshots),
            "settled_count": int(result.get("settled", 0)),
            "unresolved_count": int(result.get("unresolved", 0)) + missing_start_count,
            "deferred_count": deferred_count + int(result.get("deferred_snapshots", 0)),
            "missing_start_count": missing_start_count,
            "result_games": int(result.get("games", 0)),
            "coverage": result.get("coverage", {}),
            "unmatched_observations": result.get("unmatched_observations", []),
            "result_fetch_errors": fetch_errors,
            "settled_parlay_candidates": int(parlay_result.get("settled_parlay_candidates", 0)),
            "settled_shadow_tickets": int(parlay_result.get("settled_shadow_tickets", 0)),
            "timestamp_utc": current_time.isoformat(),
        }

    def audit_snapshots(
        self,
        snapshots: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Perform non-destructive classification and integrity audit of historical snapshots.

        Classifies records into:
        - total_count
        - settled_count
        - unsettled_pending_count
        - pre_match_verified_count
        - post_match_leak_count
        - missing_timestamp_count
        - legacy_unverified_count (Phase 1-3 baseline records lacking independent model predictions or international sharp quotes)
        - synthetic_fixture_count
        - eligible_forward_samples_count
        - excluded_breakdown: summary of exclusions
        - eligible_samples: list of records passed to forward evaluation engine
        """
        records = snapshots if snapshots is not None else iter_jsonl(self.snapshot_logger.log_path)

        total = 0
        settled_count = 0
        unsettled_count = 0
        pre_match_verified_count = 0
        post_match_leak_count = 0
        missing_timestamp_count = 0
        legacy_unverified_count = 0
        synthetic_fixture_count = 0
        invalid_odds_or_outcome_count = 0
        ineligible_flag_count = 0
        missing_hash_count = 0
        invalid_hash_count = 0
        valid_hash_count = 0
        market_benchmark_count = 0
        sharp_benchmark_count = 0

        eligible_samples: List[Dict[str, Any]] = []

        for r in records:
            total += 1
            # 1. Settlement status
            is_settled = (
                bool(r.get("is_settled"))
                or r.get("settlement_status") in ("WON", "LOST", "PUSH")
                or r.get("outcome") in (0, 1)
                or r.get("actual_outcome") is not None
            )
            if is_settled:
                settled_count += 1
            else:
                unsettled_count += 1

            # 2. Timing check (pre-match vs post-match leak)
            pred_time = r.get("prediction_timestamp") or r.get("snapshot_timestamp") or r.get("logged_at_utc")
            event_start = r.get("event_start") or r.get("start_time_utc")
            is_pre_match = False

            pred_dt = None
            event_dt = None
            if pred_time and event_start:
                try:
                    pt_dt = datetime.fromisoformat(str(pred_time).replace("Z", "+00:00"))
                    es_dt = datetime.fromisoformat(str(event_start).replace("Z", "+00:00"))
                    if pt_dt.tzinfo is None or es_dt.tzinfo is None:
                        missing_timestamp_count += 1
                    elif pt_dt < es_dt:
                        is_pre_match = True
                        pre_match_verified_count += 1
                    else:
                        post_match_leak_count += 1
                    pred_dt = pt_dt.astimezone(timezone.utc) if pt_dt.tzinfo is not None else None
                    event_dt = es_dt.astimezone(timezone.utc) if es_dt.tzinfo is not None else None
                except Exception:
                    missing_timestamp_count += 1
            else:
                missing_timestamp_count += 1

            # 3. Synthetic check
            ev = r.get("signal_evidence") or {}
            is_syn = bool(
                r.get("is_synthetic")
                or r.get("is_market_synthetic")
                or ev.get("is_market_synthetic")
                or r.get("market_source") == "SYNTHETIC"
            )
            if is_syn:
                synthetic_fixture_count += 1

            # 4. Legacy baseline check (Phase 1-3 baseline only, no model & no sharp quote)
            has_model = (
                r.get("model_probability") is not None or r.get("model_prob") is not None
            ) and r.get("probability_status") != "MARKET_BASELINE_ONLY"

            mkt_prob, sharp_prob, _ = (
                _validated_market_probabilities(r, pred_dt)
                if pred_dt is not None else (None, None, None)
            )
            has_market = mkt_prob is not None
            has_sharp = sharp_prob is not None
            market_benchmark_count += int(has_market)
            sharp_benchmark_count += int(has_sharp)

            if not has_model and not has_market:
                legacy_unverified_count += 1

            # 5. Outcome & odds check
            outcome = r.get("outcome")
            if outcome is None:
                if r.get("actual_outcome") is True or r.get("settlement_status") == "WON":
                    outcome = 1
                elif r.get("actual_outcome") is False or r.get("settlement_status") == "LOST":
                    outcome = 0

            odds = r.get("taiwan_odds") or r.get("decimal_odds")
            try:
                odds_val = float(odds) if odds is not None else None
            except (ValueError, TypeError):
                odds_val = None

            if is_settled and (outcome not in (0, 1) or not odds_val or odds_val <= 1.0):
                invalid_odds_or_outcome_count += 1

            explicitly_eligible = r.get("forward_validation_eligible") is True
            if not explicitly_eligible:
                ineligible_flag_count += 1

            hash_valid = False
            try:
                hash_schema = int(r.get("prediction_hash_schema", 0) or 0)
                saved_hash = r.get("prediction_payload_hash")
                if not saved_hash:
                    missing_hash_count += 1
                elif hash_schema >= 3 and compute_prediction_payload_hash(r) == saved_hash:
                    hash_valid = True
                    valid_hash_count += 1
                else:
                    invalid_hash_count += 1
            except (TypeError, ValueError, OverflowError):
                invalid_hash_count += 1

            # Eligibility for Forward Evaluation:
            # Must be: settled, valid outcome/odds, strictly pre-match, non-synthetic, and have model or sharp benchmark
            if (
                is_settled
                and explicitly_eligible
                and outcome in (0, 1)
                and odds_val and odds_val > 1.0
                and not is_syn
                and is_pre_match
                and hash_valid
                and (has_model or has_market)
            ):
                eligible_samples.append(r)

        return {
            "total_count": total,
            "settled_count": settled_count,
            "unsettled_pending_count": unsettled_count,
            "pre_match_verified_count": pre_match_verified_count,
            "post_match_leak_count": post_match_leak_count,
            "missing_timestamp_count": missing_timestamp_count,
            "legacy_unverified_count": legacy_unverified_count,
            "synthetic_fixture_count": synthetic_fixture_count,
            "eligible_forward_samples_count": len(eligible_samples),
            "valid_prediction_hash_count": valid_hash_count,
            "market_benchmark_count": market_benchmark_count,
            "sharp_qualified_benchmark_count": sharp_benchmark_count,
            "excluded_breakdown": {
                "legacy_unverified": legacy_unverified_count,
                "unsettled_pending": unsettled_count,
                "post_match_leak": post_match_leak_count,
                "synthetic_fixture": synthetic_fixture_count,
                "invalid_odds_or_outcome": invalid_odds_or_outcome_count,
                "missing_timestamp": missing_timestamp_count,
                "forward_validation_ineligible_or_missing": ineligible_flag_count,
                "missing_prediction_hash": missing_hash_count,
                "invalid_prediction_hash": invalid_hash_count,
            },
            "eligible_samples": eligible_samples,
        }

    def generate_forward_evaluation_report(
        self,
        scope: str = "GLOBAL",
    ) -> StrategyComparisonReport:
        """Run 3-way evaluation on all verified eligible forward snapshots and persist summary."""
        audit = self.audit_snapshots(iter_jsonl(self.snapshot_logger.log_path))
        report = self.evaluation_engine.evaluate_cohort(audit["eligible_samples"], scope_name=scope)

        # Persist summary JSON
        try:
            self.summary_path.write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save evaluation summary: %s", exc)

        return report

    def run_full_cycle(
        self,
        leagues: Optional[List[str]] = None,
        force_refresh: bool = False,
        automated: bool = False,
    ) -> Dict[str, Any]:
        """Execute full closed loop: Snapshot -> Settle -> Evaluate."""
        cycle_started = time.perf_counter()
        stage_started = cycle_started
        snap_res = self.run_market_snapshot_cycle(leagues=leagues, force_refresh=force_refresh, automated=automated)
        snapshot_duration_ms = round((time.perf_counter() - stage_started) * 1000)
        stage_started = time.perf_counter()
        settle_res = self.run_settlement_cycle()
        settlement_duration_ms = round((time.perf_counter() - stage_started) * 1000)
        stage_started = time.perf_counter()
        eval_report = self.generate_forward_evaluation_report()
        evaluation_duration_ms = round((time.perf_counter() - stage_started) * 1000)

        snapshot_cycle_status = (
            "QUALIFIED_REAL_MARKET_DATA"
            if snap_res.get("qualified_pending_candidate_count", 0) > 0
            else "NO_QUALIFIED_REAL_MARKET_DATA"
        )
        operation_status = "PARTIAL" if settle_res.get("result_fetch_errors") else "SUCCESS"

        return {
            # The operation may complete successfully even when no real aligned
            # candidates were available. Keep that distinction explicit.
            "cycle_status": snapshot_cycle_status,
            "operation_status": operation_status,
            "snapshot_cycle": snap_res,
            "settlement_cycle": settle_res,
            "evaluation_summary": eval_report.to_dict(),
            "durations_ms": {
                "snapshot_and_fetch": snapshot_duration_ms,
                "settlement_scan": settlement_duration_ms,
                "forward_evaluation": evaluation_duration_ms,
                "total": round((time.perf_counter() - cycle_started) * 1000),
            },
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    def get_research_status_summary(self) -> Dict[str, Any]:
        """Retrieve aggregated research metrics for the UI."""
        global _summary_cache_payload, _summary_cache_mtime, _summary_cache_time

        mtime_ns = 0
        try:
            if self.snapshot_logger.log_path.exists():
                mtime_ns = self.snapshot_logger.log_path.stat().st_mtime_ns
        except Exception:
            pass

        now_ts = time.time()
        cached_blocks = None
        with _summary_cache_lock:
            if (
                _summary_cache_payload is not None
                and _summary_cache_mtime == mtime_ns
                and (now_ts - _summary_cache_time) < 120.0
            ):
                cached_blocks = _summary_cache_payload

        if cached_blocks is None:
            all_snaps = iter_jsonl(self.snapshot_logger.log_path)
            audit = self.audit_snapshots(all_snaps)
            report = self.evaluation_engine.evaluate_cohort(audit["eligible_samples"])
            cached_blocks = {
                "snapshots": {
                    "total_count": audit["total_count"],
                    "settled_count": audit["settled_count"],
                    "pending_count": audit["unsettled_pending_count"],
                    "pre_match_verified_count": audit["pre_match_verified_count"],
                    "post_match_leak_count": audit["post_match_leak_count"],
                    "legacy_unverified_count": audit["legacy_unverified_count"],
                    "forward_eligible_count": audit["eligible_forward_samples_count"],
                    "valid_prediction_hash_count": audit["valid_prediction_hash_count"],
                    "market_benchmark_count": audit["market_benchmark_count"],
                    "sharp_qualified_benchmark_count": audit["sharp_qualified_benchmark_count"],
                    "excluded_breakdown": audit["excluded_breakdown"],
                },
                "forward_evaluation": {
                    "sample_size": report.sample_size,
                    "paired_sample_size": report.paired_sample_size,
                    "market_paired_sample_size": report.market_paired_sample_size,
                    "sharp_paired_sample_size": report.sharp_paired_sample_size,
                    "minimum_sample_size": MIN_FORWARD_EVALUATION_SAMPLE,
                    "status": report.status,
                    "data_quality_status": report.data_quality_status,
                    "evaluation_protocol_status": report.evaluation_protocol_status,
                    "statistical_evidence_status": report.statistical_evidence_status,
                    "champion_source": report.champion_source,
                    "acceptance_gate_qualified": report.acceptance_gate_qualified,
                    "shadow_mode_recommendation": report.shadow_mode_recommendation,
                    "delta_brier_ci_95": list(report.delta_brier_ci_95) if report.delta_brier_ci_95 else None,
                    "delta_brier_market_ci_95": list(report.delta_brier_market_ci_95) if report.delta_brier_market_ci_95 else None,
                    "taiwan_baseline": report.taiwan_market_baseline.to_dict(),
                    "international_market": report.international_market_benchmark.to_dict()
                    if report.international_market_benchmark else None,
                    "international_sharp": report.international_sharp_benchmark.to_dict(),
                    "active_model": report.active_model_strategy.to_dict(),
                },
            }
            with _summary_cache_lock:
                _summary_cache_payload = cached_blocks
                _summary_cache_mtime = mtime_ns
                _summary_cache_time = now_ts

        odds_status = self.odds_client.get_source_status()
        scheduler_status = None
        if callable(self.scheduler_status_provider):
            try:
                scheduler_status = self.scheduler_status_provider()
            except Exception:
                logger.debug("Scheduler status provider is unavailable", exc_info=True)

        alignment_summary = _alignment_summary_from_scheduler_status(scheduler_status)

        return {
            "live_status": odds_status.get("operating_mode", "SYNTHETIC_FIXTURE"),
            "live_status_scope": "ODDS_API_SOURCE_STATUS_ONLY",
            "the_odds_api": odds_status,
            "alignment": alignment_summary,
            "scheduler": scheduler_status,
            "snapshots": cached_blocks["snapshots"],
            "forward_evaluation": cached_blocks["forward_evaluation"],
            "as_of_utc": datetime.now(timezone.utc).isoformat(),
        }
