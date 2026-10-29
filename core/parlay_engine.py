#!/usr/bin/env python3
"""Fair, resumable search over eligible Taiwan parlay options.

Partial search results are useful candidates only; they are never described as
the global top set until every exact branch has been visited or admissibly
pruned against the requested odds bounds.
"""
from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
import hashlib
import json
import math
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from core.correlation_guard import CorrelationGuard
from core.sharp_edge_engine import SharpEdgeEngine
from core.signal_hub import SignalHub
from core.bet_validation import assess_leg, event_key
from integrations.common.models import PredictionSignal, TaiwanLeg

SEARCH_STATE_SCHEMA = "parlay-search-state-v1"
SEARCH_VERSION = "fair-frontier-v1"


class ParlaySearchResult(dict):
    """Tier mapping compatible with older callers plus serializable progress."""
    def __init__(self, tiers: Dict[str, List[Dict[str, Any]]], *,
                 search_state: Dict[str, Any], diagnostics: Dict[str, Any]):
        super().__init__(tiers)
        self.search_state = search_state
        self.diagnostics = diagnostics


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=lambda item: item.isoformat() if hasattr(item, "isoformat") else str(item))


def _stable_id(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class ParlayEngine:
    """Searches legal combinations with fair per-event and per-length budgets."""

    def __init__(self, signal_hub: Optional[SignalHub] = None,
                 correlation_guard: Optional[CorrelationGuard] = None,
                 sharp_edge_engine: Optional[SharpEdgeEngine] = None):
        self.signal_hub = signal_hub or SignalHub()
        self.correlation_guard = correlation_guard or CorrelationGuard()
        self.sharp_edge_engine = sharp_edge_engine or SharpEdgeEngine()

    @staticmethod
    def _team_name(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("name") or value.get("name_zh") or value.get("display_name_zh")
                       or value.get("name_en") or value.get("display_name_en") or value.get("abbr") or "")
        return str(value) if value is not None else ""

    @classmethod
    def _normalize_option(cls, option: Dict[str, Any], match: Optional[Dict[str, Any]] = None) -> TaiwanLeg:
        merged = dict(match or {})
        merged.update(option)
        aliases = {
            "event_id": merged.get("event_id") or merged.get("match_id") or "",
            "sport": merged.get("sport") or "", "league": merged.get("league") or "",
            "market": merged.get("market") or merged.get("market_type") or "",
            "selection": merged.get("selection") or "",
            "taiwan_odds": merged.get("taiwan_odds", merged.get("odds")),
            "start_time": merged.get("start_time", merged.get("game_time", "")),
            "away_team": cls._team_name(merged.get("away_team")),
            "home_team": cls._team_name(merged.get("home_team")),
        }
        evidence = {}
        for source in (match or {}, option):
            for name in ("signal_evidence", "market_evidence"):
                nested = source.get(name)
                if isinstance(nested, dict):
                    evidence.update(nested)
            for key in ("consensus_ratio", "crowd_ratio", "vote_count", "crowd_votes", "crowd_age_minutes",
                        "crowd_snapshot_timestamp", "publication_time_precision", "verified_experts",
                        "expert_count", "expert_consensus", "expert_consensus_ratio", "expert_observed_at",
                        "expert_publication_timestamp", "model_provenances", "model_probability",
                        "model_probability_raw", "model_probability_calibrated", "consensus_probability",
                        "probability_status", "market_outcome_odds", "market_complete", "source_url",
                        "independent_support_count", "supporting_groups", "agreement", "evidence_quality"):
                if key in source:
                    evidence[key] = source[key]
        aliases["signal_evidence"] = evidence
        aliases["event_id"] = str(aliases["event_id"] or "")
        try:
            aliases["taiwan_odds"] = float(aliases["taiwan_odds"])
        except (TypeError, ValueError, OverflowError):
            aliases["taiwan_odds"] = 0.0
        field_names = {item.name for item in fields(TaiwanLeg)}
        values = {key: value for key, value in merged.items() if key in field_names}
        values.update({key: value for key, value in aliases.items() if key in field_names})
        raw_signals = values.get("signals") or []
        signal_fields = {item.name for item in fields(PredictionSignal)}
        required_signal_fields = {"source_id", "source_name", "source_type", "event_id", "market", "selection"}
        values["signals"] = [
            signal if isinstance(signal, PredictionSignal) else PredictionSignal(**{k: v for k, v in signal.items() if k in signal_fields})
            for signal in raw_signals
            if isinstance(signal, PredictionSignal) or (isinstance(signal, dict) and required_signal_fields.issubset(signal))
        ]
        for key, default in (("event_id", ""), ("sport", ""), ("league", ""), ("market", ""),
                             ("selection", ""), ("taiwan_odds", 0.0)):
            values.setdefault(key, default)
        return TaiwanLeg(**values)

    @staticmethod
    def _independent_valid_support_count(leg: TaiwanLeg) -> int:
        evidence = leg.signal_evidence or {}
        groups = evidence.get("supporting_groups")
        if groups is not None:
            return len({str(group) for group in groups if group and str(group) != "TAIWAN_MARKET"})
        valid_groups = set()
        for signal in leg.signals or []:
            data = signal.to_dict() if hasattr(signal, "to_dict") else signal
            if not isinstance(data, dict):
                continue
            category = data.get("source_category") or data.get("source_type")
            if category in {"BETTING_MARKET", "MARKET", "TAIWAN_MARKET"}:
                continue
            if data.get("freshness_status") not in {"LIVE", "FRESH"}:
                continue
            if data.get("independence_group"):
                valid_groups.add(str(data["independence_group"]))
        if valid_groups:
            return len(valid_groups)
        try:
            return max(0, int(evidence.get("independent_support_count", 0)))
        except (TypeError, ValueError):
            return 0

    def search_parlays(
        self,
        legs: Optional[Union[List[TaiwanLeg], List[Dict[str, Any]]]] = None,
        min_odds: float = 10.0,
        max_odds: float = 500.0,
        target_odds: Optional[float] = None,
        tolerance: float = 0.20,
        min_legs: int = 2,
        max_legs: int = 6,
        max_matches_pool: int = 16,
        matches: Optional[List[Dict[str, Any]]] = None,
        signal_filter: str = "normal",
        exclude_traps: bool = False,
        prefer_steam: bool = False,
        diagnostics: Optional[Dict[str, Any]] = None,
        search_budget: int = 250_000,
        resume_state: Optional[Dict[str, Any]] = None,
        deadline_monotonic: Optional[float] = None,
        scope_as_of: Any = None,
    ) -> Dict[str, Any]:
        """Search exact legal combinations with a resumable fair frontier.

        Budget is shared round-robin across (first event, legs count) tasks.
        ``search_budget`` applies to this call; pass the returned
        ``search_state`` to continue. Checkpoints are reusable only for an
        identical evaluated pool, odds/config and point-in-time scope.
        """
        if target_odds is not None and target_odds > 1.0:
            min_odds = max(1.05, target_odds * (1.0 - tolerance))
            max_odds = max(min_odds, target_odds * (1.0 + tolerance))
        else:
            min_odds = max(1.05, min_odds)
            max_odds = max(min_odds, max_odds)
        min_legs = max(1, int(min_legs))
        max_legs = max(min_legs, int(max_legs))
        budget = max(1, int(search_budget))
        if scope_as_of is None:
            scope_as_of = datetime.now(timezone.utc).isoformat()
        elif hasattr(scope_as_of, "isoformat"):
            scope_as_of = scope_as_of.isoformat()

        raw_items = matches if matches is not None else (legs or [])
        normalized_legs: List[TaiwanLeg] = []
        for item in raw_items:
            if isinstance(item, TaiwanLeg):
                normalized_legs.append(item)
            elif isinstance(item, dict):
                if "options" in item:
                    normalized_legs.extend(self._normalize_option(opt, item) for opt in item.get("options", []))
                else:
                    normalized_legs.append(self._normalize_option(item))

        ready, rejection_counts = [], {}
        for leg in normalized_legs:
            if not leg.eligible_for_parlay or leg.taiwan_odds <= 1.0:
                rejection_counts["INELIGIBLE_OR_INVALID_ODDS"] = rejection_counts.get("INELIGIBLE_OR_INVALID_ODDS", 0) + 1
                continue
            if leg.signals and (not leg.signal_evidence or "agreement" not in leg.signal_evidence):
                leg = self.signal_hub.synthesize_signals_for_leg(leg, leg.signals)
            elif not leg.signal_evidence or ("agreement" not in leg.signal_evidence and "evidence_quality" not in leg.signal_evidence):
                leg = self.signal_hub.evaluate_taiwan_leg(leg)
            check = assess_leg(leg.to_dict(), now=scope_as_of)
            if not check["is_ready"]:
                for reason in check["reasons"] or ["NOT_READY"]:
                    rejection_counts[str(reason)] = rejection_counts.get(str(reason), 0) + 1
                continue
            ready.append(leg)

        if signal_filter == "strict":
            active = [leg for leg in ready if leg.evidence_quality in {"HIGH", "MED"}
                      and self._independent_valid_support_count(leg) >= 2]
        elif signal_filter == "value_only":
            active = [leg for leg in ready if (getattr(leg, "is_positive_ev", False)
                      or (leg.signal_evidence or {}).get("is_positive_ev")
                      or (leg.signal_evidence or {}).get("is_sharp_value_bet")
                      or (leg.signal_evidence or {}).get("expected_value", 0) > 0
                      or ((leg.signal_evidence or {}).get("consensus_probability", 0) >= 0.55 and leg.taiwan_odds <= 2.0))]
        elif signal_filter == "normal":
            active = [leg for leg in ready if leg.evidence_quality != "INSUFFICIENT_SIGNAL"]
        else:
            active = ready
        if resume_state is not None and any(not assess_leg(leg.to_dict())["is_ready"] for leg in active):
            raise ValueError("搜尋進度的盤口已過期或賽事已開始；必須重新取得資料並開始新搜尋。")

        quality_score = {"HIGH": 3, "MED": 2, "LOW": 1, "INSUFFICIENT_SIGNAL": 0}
        legs_by_event: Dict[str, List[TaiwanLeg]] = {}
        for leg in active:
            legs_by_event.setdefault(event_key(leg), []).append(leg)
        events = []
        duplicate_option_records_collapsed = 0
        for eid, options in legs_by_event.items():
            options.sort(key=lambda leg: (quality_score.get(leg.evidence_quality, 0),
                                          float((leg.signal_evidence or {}).get("non_market_supports", 0)),
                                          str(getattr(leg, "odds_scraped_at", "")),
                                          1.0 / leg.taiwan_odds,
                                          _stable_id(leg.to_dict())), reverse=True)
            # Same event/market/side/line/selection at the same exact price is
            # one candidate even if it was repeated in the input pool. Keep the
            # strongest deterministic evidence version and expose the collapse
            # count; differing prices remain separate legal options.
            unique: Dict[str, TaiwanLeg] = {}
            for option in options:
                semantic_id = _stable_id({"event_id": eid, "sport": option.sport, "league": option.league,
                                          "market": option.market, "selection": option.selection,
                                          "side": getattr(option, "side", None),
                                          "line": getattr(option, "line", None),
                                          "odds": option.taiwan_odds})
                if semantic_id in unique:
                    duplicate_option_records_collapsed += 1
                    continue
                unique[semantic_id] = option
            options = list(unique.values())
            events.append((max(quality_score.get(l.evidence_quality, 0) for l in options), eid, options))
        events.sort(key=lambda row: (-row[0], row[1]))
        event_ids = [row[1] for row in events]
        event_options = {row[1]: row[2] for row in events}
        option_ids = {eid: [_stable_id(leg.to_dict()) for leg in event_options[eid]] for eid in event_ids}
        legs_by_id = {option_ids[eid][idx]: leg for eid in event_ids for idx, leg in enumerate(event_options[eid])}
        event_index_by_id = {eid: idx for idx, eid in enumerate(event_ids)}

        config_scope = {"min_odds": min_odds, "max_odds": max_odds, "target_odds": target_odds,
                        "tolerance": tolerance, "min_legs": min_legs, "max_legs": max_legs,
                        "signal_filter": signal_filter, "exclude_traps": exclude_traps,
                        "prefer_steam": prefer_steam, "scope_as_of": scope_as_of,
                        "search_version": SEARCH_VERSION,
                        "normalized_input_pool": sorted((leg.to_dict() for leg in normalized_legs),
                                                         key=_stable_id),
                        "pool": [{"event_id": eid, "options": [leg.to_dict() for leg in event_options[eid]]}
                                 for eid in event_ids]}
        fingerprint = _stable_id(config_scope)

        max_length = min(max_legs, len(event_ids))
        if resume_state is not None:
            if not isinstance(resume_state, dict) or resume_state.get("schema") != SEARCH_STATE_SCHEMA:
                raise ValueError("Unsupported parlay search checkpoint")
            if resume_state.get("pool_config_fingerprint") != fingerprint:
                raise ValueError("Checkpoint scope changed: pool, prices, evidence, freshness or search config differs")
            state = json.loads(_canonical_json(resume_state))
        else:
            tasks = []
            for first_index in range(len(event_ids)):
                for length in range(min_legs, max_length + 1):
                    if len(event_ids) - first_index < length:
                        continue
                    tasks.append({"first_event_index": first_index, "legs_count": length,
                                  "stack": [{"start": first_index, "need": length, "chosen": [],
                                             "odds": 1.0, "root": True,
                                             "next_event": first_index, "next_option": 0}]})
            state = {"schema": SEARCH_STATE_SCHEMA, "search_version": SEARCH_VERSION,
                     "pool_config_fingerprint": fingerprint, "event_ids": event_ids,
                     "option_ids": option_ids, "tasks": tasks, "next_task_cursor": 0,
                     "visited_nodes_total": 0, "checked_combinations": 0,
                     "odds_matching_combinations": 0, "odds_pruned_nodes": 0,
                     "event_branch_visits": {eid: 0 for eid in event_ids},
                     "length_progress": {str(k): {"complete_candidates_checked": 0,
                                                   "task_count": sum(1 for t in tasks if t["legs_count"] == k)}
                                         for k in range(min_legs, max_length + 1)},
                     "top_candidates": {"high_consensus": [], "aggressive": [], "moonshot": []}}

        # Reconstruct saved top entries from stable IDs; no TaiwanLeg object is
        # serialized in the checkpoint.
        high_consensus: List[Dict[str, Any]] = []
        aggressive: List[Dict[str, Any]] = []
        moonshot: List[Dict[str, Any]] = []
        buckets = {"high_consensus": high_consensus, "aggressive": aggressive, "moonshot": moonshot}
        rank_key = lambda x: (
            x["min_evidence_score"],
            x["parlay_expected_value"] + (0.15 * x.get("steam_count", 0)) - (0.25 * x.get("trap_count", 0)),
            x["avg_evidence_score"],
            x["total_independent_sources"],
            -x["odds_distance"],
            x["total_odds"],
        )
        def keep_top(items, combo):
            if any(row["candidate_id"] == combo["candidate_id"] for row in items):
                return
            items.append(combo)
            items.sort(key=rank_key, reverse=True)
            del items[12:]

        def evaluate_combo(leg_tuple: Tuple[TaiwanLeg, ...], total_odds: float, *, count: bool) -> Dict[str, Any]:
            num_legs = len(leg_tuple)
            if count:
                state["checked_combinations"] += 1
            epsilon = 1e-12 * max(1.0, abs(min_odds), abs(max_odds), abs(total_odds))
            if total_odds < min_odds - epsilon or total_odds > max_odds + epsilon:
                return {}
            if count:
                state["odds_matching_combinations"] += 1

            steam_count = sum(1 for leg in leg_tuple if (leg.signal_evidence or {}).get("line_movement", {}).get("is_steam"))
            trap_count = sum(1 for leg in leg_tuple if (leg.signal_evidence or {}).get("line_movement", {}).get("is_trap_warning"))
            if exclude_traps and trap_count > 0:
                return {}

            scores = [quality_score.get(leg.evidence_quality, 0) for leg in leg_tuple]
            min_score, avg_score = min(scores), sum(scores) / num_legs
            supports = sum((leg.signal_evidence or {}).get("non_market_supports", 0) for leg in leg_tuple)
            emojis = "".join((leg.signal_evidence or {}).get("agreement_emoji", "⚪") for leg in leg_tuple)
            corr = self.correlation_guard.evaluate_parlay(list(leg_tuple), total_odds=total_odds)
            sharp_eval = self.sharp_edge_engine.evaluate_parlay_sharp_ev(
                list(leg_tuple), total_odds=total_odds, correlation_penalty=corr.correlation_penalty
            )
            target_mid = target_odds if target_odds is not None else (min_odds + max_odds) / 2.0
            checks = [assess_leg(leg.to_dict(), now=scope_as_of) for leg in leg_tuple]
            reasons = list(dict.fromkeys(reason for check in checks for reason in check["reasons"]))
            ready_combo = all(check["is_ready"] for check in checks)
            has_stale = any(reason in {"ODDS_STALE", "ODDS_TIME_UNKNOWN", "ODDS_TIME_FUTURE"} for reason in reasons)
            ids = [option_ids[event_key(leg)][event_options[event_key(leg)].index(leg)] for leg in leg_tuple]
            semantic_ids = [_stable_id({"event_id": event_key(leg), "sport": leg.sport, "league": leg.league,
                                        "market": leg.market, "selection": leg.selection,
                                        "side": getattr(leg, "side", None), "line": getattr(leg, "line", None),
                                        "odds": leg.taiwan_odds}) for leg in leg_tuple]
            candidate_id = _stable_id(semantic_ids)
            return {"candidate_id": candidate_id, "legs_count": num_legs, "parlay_name": f"{num_legs} 串 1",
                    "total_odds": round(total_odds, 2), "min_evidence_score": min_score,
                    "avg_evidence_score": round(avg_score, 2), "avg_support": round(avg_score, 2),
                    "total_independent_sources": supports, "joint_probability": round(corr.joint_probability, 6),
                    "naive_joint_probability": round(corr.naive_joint_probability, 6),
                    "parlay_expected_value": round(corr.parlay_expected_value, 4),
                    "parlay_ev_pct": round(corr.parlay_ev_pct, 1),
                    "sharp_parlay_ev": sharp_eval.get("sharp_parlay_ev", 0.0),
                    "sharp_parlay_ev_pct": sharp_eval.get("sharp_parlay_ev_pct", 0.0),
                    "sharp_joint_probability": sharp_eval.get("sharp_joint_probability", 0.0),
                    "is_positive_ev": sharp_eval.get("is_positive_ev", False) or corr.parlay_expected_value > 0,
                    "value_legs_count": sharp_eval.get("value_legs_count", 0),
                    "sharp_badge": sharp_eval.get("summary_badge", ""),
                    "correlation_penalty": round(corr.correlation_penalty, 4),
                    "correlation_risk_grade": corr.risk_grade, "correlation_risk_factors": corr.risk_factors,
                    "odds_distance": round(abs(total_odds - target_mid), 2), "signal_summary": emojis,
                    "steam_count": steam_count, "trap_count": trap_count,
                    "has_steam": steam_count > 0, "has_trap": trap_count > 0,
                    "bet_status": "READY" if ready_combo else (reasons[0] if reasons else "NOT_READY"),
                    "is_ready": ready_combo, "readiness_reasons": reasons, "has_stale_odds": has_stale,
                    "legs": [leg.to_dict() for leg in leg_tuple], "raw_legs": list(leg_tuple)}

        # Restore top candidates and preserve their original bucket placement.
        for tier, refs in state.get("top_candidates", {}).items():
            for ref in refs:
                try:
                    selected = tuple(legs_by_id[key] for key in ref["leg_ids"])
                except (KeyError, TypeError):
                    raise ValueError("Checkpoint top candidate references an option outside its fingerprinted pool")
                combo = evaluate_combo(selected, math.prod(leg.taiwan_odds for leg in selected), count=False)
                if combo:
                    buckets[tier].append(combo)
        for bucket in buckets.values():
            bucket.sort(key=rank_key, reverse=True)

        # Per-event min/max products provide exact admissible bounds for all
        # remaining choices; same-event options remain mutually exclusive.
        suffix_min, suffix_max = [], []
        for index in range(len(event_ids) + 1):
            lows = sorted(min(leg.taiwan_odds for leg in event_options[eid]) for eid in event_ids[index:])
            highs = sorted((max(leg.taiwan_odds for leg in event_options[eid]) for eid in event_ids[index:]), reverse=True)
            lo, hi = [1.0], [1.0]
            for value in lows:
                lo.append(lo[-1] * value)
            for value in highs:
                hi.append(hi[-1] * value)
            suffix_min.append(lo)
            suffix_max.append(hi)

        total_possible_by_length = {}
        dp = [1] + [0] * max_length
        for eid in event_ids:
            options_n = len(event_options[eid])
            for k in range(max_length, 0, -1):
                dp[k] += dp[k - 1] * options_n
        for k in range(min_legs, max_length + 1):
            total_possible_by_length[str(k)] = dp[k]

        visited_this_call = 0
        tasks = state["tasks"]
        cursor = int(state.get("next_task_cursor", 0)) % max(1, len(tasks)) if tasks else 0
        idle_rounds = 0
        while tasks and visited_this_call < budget and (deadline_monotonic is None or time.monotonic() < deadline_monotonic):
            task_index = cursor
            cursor = (cursor + 1) % len(tasks)
            task = tasks[task_index]
            stack = task["stack"]
            if not stack:
                idle_rounds += 1
                if idle_rounds >= len(tasks):
                    break
                continue
            idle_rounds = 0
            frame = stack[-1]
            visited_this_call += 1
            state["visited_nodes_total"] += 1
            length = int(task["legs_count"])
            if frame.get("root"):
                first_index = int(task["first_event_index"])
                options = event_options[event_ids[first_index]]
                option_index = int(frame.get("next_option", 0))
                if option_index >= len(options):
                    stack.pop()
                    continue
                frame["next_option"] = option_index + 1
                first_leg = options[option_index]
                state["event_branch_visits"][event_ids[first_index]] += 1
                if length == 1:
                    combo = evaluate_combo((first_leg,), first_leg.taiwan_odds, count=True)
                    state["length_progress"][str(length)]["complete_candidates_checked"] += 1
                    if combo:
                        tiers = []
                        if combo["total_odds"] >= 40.0 or length >= 4: tiers.append("moonshot")
                        if combo["min_evidence_score"] >= 2 and combo["total_odds"] <= 100.0: tiers.append("high_consensus")
                        else: tiers.append("aggressive")
                        for tier in tiers: keep_top(buckets[tier], combo)
                else:
                    stack.append({"start": first_index + 1, "need": length - 1,
                                  "chosen": [option_ids[event_ids[first_index]][option_index]],
                                  "odds": first_leg.taiwan_odds, "root": False,
                                  "next_event": first_index + 1, "next_option": 0})
                continue

            start, need = int(frame["start"]), int(frame["need"])
            odds = float(frame["odds"])
            if need == 0:
                selected = tuple(legs_by_id[key] for key in frame["chosen"])
                combo = evaluate_combo(selected, odds, count=True)
                state["length_progress"][str(length)]["complete_candidates_checked"] += 1
                if combo:
                    tier_names = []
                    if combo["total_odds"] >= 40.0 or length >= 4: tier_names.append("moonshot")
                    if combo["min_evidence_score"] >= 2 and combo["total_odds"] <= 100.0: tier_names.append("high_consensus")
                    else: tier_names.append("aggressive")
                    for tier in tier_names: keep_top(buckets[tier], combo)
                stack.pop()
                continue
            if len(event_ids) - start < need:
                stack.pop()
                continue
            min_possible = odds * suffix_min[start][need]
            max_possible = odds * suffix_max[start][need]
            eps = 1e-12 * max(1.0, abs(min_odds), abs(max_odds), abs(min_possible), abs(max_possible))
            if min_possible > max_odds + eps or max_possible < min_odds - eps:
                state["odds_pruned_nodes"] += 1
                stack.pop()
                continue
            final_start = len(event_ids) - need
            next_event = int(frame.get("next_event", start))
            next_option = int(frame.get("next_option", 0))
            while next_event <= final_start and next_option >= len(event_options[event_ids[next_event]]):
                next_event += 1
                next_option = 0
            if next_event > final_start:
                stack.pop()
                continue
            frame["next_event"], frame["next_option"] = next_event, next_option + 1
            eid = event_ids[next_event]
            option_id = option_ids[eid][next_option]
            leg = legs_by_id[option_id]
            next_odds = odds * leg.taiwan_odds
            state["event_branch_visits"][eid] += 1
            if next_odds > max_odds + 1e-12 * max(1.0, abs(max_odds), abs(next_odds)):
                state["odds_pruned_nodes"] += 1
                continue
            stack.append({"start": next_event + 1, "need": need - 1,
                          "chosen": list(frame["chosen"]) + [option_id], "odds": next_odds,
                          "root": False, "next_event": next_event + 1, "next_option": 0})

        state["next_task_cursor"] = cursor
        completed_by_length = {str(k): 0 for k in range(min_legs, max_length + 1)}
        for task in tasks:
            if not task["stack"]:
                completed_by_length[str(task["legs_count"])] += 1
        complete = all(not task["stack"] for task in tasks)
        top_refs = {}
        for tier, bucket in buckets.items():
            top_refs[tier] = [{"candidate_id": combo["candidate_id"],
                               "leg_ids": [option_ids[event_key(leg)][event_options[event_key(leg)].index(leg)]
                                           for leg in combo["raw_legs"]]} for combo in bucket]
        state["top_candidates"] = top_refs
        state["status"] = "COMPLETE" if complete else ("BUDGET_EXHAUSTED" if visited_this_call >= budget else "PARTIAL_NO_GLOBAL_TOP_GUARANTEE")
        progress = {str(k): {"complete_candidates_checked": int(state["length_progress"][str(k)]["complete_candidates_checked"]),
                             "theoretical_combinations": total_possible_by_length.get(str(k), 0),
                             "tasks_completed": completed_by_length[str(k)],
                             "task_count": int(state["length_progress"][str(k)]["task_count"]),
                             "status": "COMPLETE" if completed_by_length[str(k)] == int(state["length_progress"][str(k)]["task_count"]) else "PARTIAL"}
                    for k in range(min_legs, max_length + 1)}
        covered_events = sum(count > 0 for count in state["event_branch_visits"].values())
        diag = {
            "normalized_option_count": len(normalized_legs), "ready_option_count": len(ready),
            "quality_option_count": len(active), "quality_event_count": len(event_ids),
            "quality_filtered_out_option_count": len(ready) - len(active), "signal_filter": signal_filter,
            "search_event_count": len(event_ids), "search_option_count": sum(len(event_options[eid]) for eid in event_ids),
            "max_options_per_event": max((len(event_options[eid]) for eid in event_ids), default=0),
            "excluded_option_reasons": rejection_counts,
            "duplicate_option_records_collapsed": duplicate_option_records_collapsed,
            "max_matches_pool": max_matches_pool, "max_matches_pool_applied": False,
            "search_budget": budget, "search_budget_unit": "frontier_nodes_per_call",
            "visited_nodes_this_call": visited_this_call, "visited_nodes_total": state["visited_nodes_total"],
            "visited_nodes": state["visited_nodes_total"],
            "odds_pruned_nodes": state["odds_pruned_nodes"], "checked_combinations": state["checked_combinations"],
            "odds_matching_combinations": state["odds_matching_combinations"],
            "search_complete": complete, "budget_exhausted": not complete and visited_this_call >= budget,
            "deadline_reached": not complete and deadline_monotonic is not None and time.monotonic() >= deadline_monotonic,
            "search_status": "BUDGET_EXHAUSTED" if (not complete and visited_this_call >= budget) else state["status"], "global_top_guarantee": complete,
            "ranking_objective": "max evidence score, then expected value, average evidence, independent supports, target-odds proximity, total odds; top 12 per tier",
            "partial_result_interpretation": "Partial frontiers produce useful candidates but do not guarantee the global top candidates.",
            "min_legs": min_legs, "max_legs": max_legs, "effective_max_legs": max_length,
            "event_coverage": {"visited_events": covered_events, "total_events": len(event_ids),
                               "visited_fraction": covered_events / len(event_ids) if event_ids else 0.0,
                               "branch_visits_by_event": dict(state["event_branch_visits"])},
            "legs_count_progress": progress, "pool_config_fingerprint": fingerprint,
            "scope_as_of": scope_as_of,
        }
        if diagnostics is not None:
            diagnostics.clear()
            diagnostics.update(diag)
            diagnostics["resume_state"] = state
        return ParlaySearchResult({"high_consensus": high_consensus, "aggressive": aggressive,
                                   "moonshot": moonshot}, search_state=state, diagnostics=diag)
