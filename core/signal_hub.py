#!/usr/bin/env python3
"""Signal Hub (情報中心 - Intelligence Layer Reform).

Aggregates multi-source evidence for a specific TaiwanLeg:
1. Taiwan Market Odds & Implied Baseline (TAIWAN_MARKET: Baseline only, NEVER votes for itself)
2. Verified Playsport Experts (PLAYSPORT_EXPERT: Verified on member prediction pages)
3. Playsport Crowd Consensus (PLAYSPORT_CROWD: Community voting percentage >= 55%)
4. Open-Source Prediction Engines (DIXON_COLES_MATCHES, FIVETHIRTYEIGHT_ELO)
5. Local Fallback Models (ESPN_SEASON_STATS)

Strictly enforces independence groups: multiple models sharing the same data source
(e.g., ESPN_SEASON_STATS) only count as 1 independent supporting group.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from core.edge_engine import EdgeEngine
from core.line_movement import LineMovementTracker
from core.model_registry import ModelRegistry
from core.model_acceptance import acceptance_matches_signal
from integrations.common.models import PredictionSignal, TaiwanLeg
from integrations.experts.playsport_crowd import PlaysportCrowdAdapter
from integrations.experts.playsport_expert import PlaysportExpertAdapter
from integrations.odds.betting_splits_client import BettingSplitsClient
from integrations.odds.sharp_benchmark_odds import SharpBenchmarkOddsAdapter

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "evidence_weights.yaml"

FAMILY_MARKET = "MARKET"
FAMILY_HUMAN = "HUMAN"
FAMILY_STATISTICAL_MODEL = "STATISTICAL_MODEL"
FAMILY_FUNDAMENTAL = "FUNDAMENTAL_DATA"


class SignalHub:
    """Aggregates multi-source evidence for TaiwanLeg betting selections."""

    def __init__(
        self,
        expert_adapter: Optional[PlaysportExpertAdapter] = None,
        crowd_adapter: Optional[PlaysportCrowdAdapter] = None,
        model_registry: Optional[ModelRegistry] = None,
        edge_engine: Optional[EdgeEngine] = None,
        sharp_adapter: Optional[SharpBenchmarkOddsAdapter] = None,
        line_movement_tracker: Optional[LineMovementTracker] = None,
        splits_client: Optional[BettingSplitsClient] = None,
        config_path: Optional[Path] = None,
    ):
        self.expert_adapter = expert_adapter or PlaysportExpertAdapter()
        self.crowd_adapter = crowd_adapter or PlaysportCrowdAdapter()
        self.model_registry = model_registry or ModelRegistry()
        self.sharp_adapter = sharp_adapter or SharpBenchmarkOddsAdapter()
        self.line_movement_tracker = line_movement_tracker or LineMovementTracker()
        self.splits_client = splits_client or BettingSplitsClient()
        self.config_path = config_path or CONFIG_PATH
        self.weights_config = self._load_weights_config()
        self.edge_engine = edge_engine or EdgeEngine(source_weights=self.weights_config.get("source_weights", {}))
        self._leg_eval_cache: Dict[tuple, TaiwanLeg] = {}

    def refresh(self) -> None:
        """Clear evaluation caches and refresh underlying adapters."""
        self._leg_eval_cache.clear()
        if hasattr(self.model_registry, "refresh"):
            self.model_registry.refresh()
        if hasattr(self.expert_adapter, "refresh"):
            self.expert_adapter.refresh()
        if hasattr(self.line_movement_tracker, "refresh"):
            self.line_movement_tracker.refresh()

    def _load_weights_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            content = self.config_path.read_text(encoding="utf-8")
            return yaml.safe_load(content) or {}
        except Exception as exc:
            logger.warning("Failed to load evidence weights config: %s", exc)
            return {}

    def evaluate_taiwan_leg(self, leg: TaiwanLeg) -> TaiwanLeg:
        """Gather all external evidence for a TaiwanLeg and calculate agreement level."""
        cache_key = (
            leg.event_id, leg.sport, leg.league, leg.market,
            leg.selection, getattr(leg, "side", None), getattr(leg, "line", None),
            float(leg.taiwan_odds or 0.0), getattr(leg, "odds_scraped_at", "")
        )
        if hasattr(self, "_leg_eval_cache") and cache_key in self._leg_eval_cache:
            return self._leg_eval_cache[cache_key]

        signals: List[PredictionSignal] = []

        # 1. Market Signal (Taiwan Odds implied) - BASELINE ONLY, NEVER VOTES
        odds = leg.taiwan_odds
        market_implied = 1.0 / odds if odds > 1.0 else 0.5

        signals.append(
            PredictionSignal(
                source_id="taiwan_market_odds",
                source_name="台灣運彩盤口",
                source_type="BETTING_MARKET",
                event_id=leg.event_id,
                market=leg.market,
                selection=leg.selection,
                probability=round(market_implied, 3),
                score=odds,
                confidence="HIGH" if odds <= 1.55 else "MED" if odds <= 1.90 else "LOW",
                pick=leg.selection,
                source_category="BETTING_MARKET",
                independence_group="TAIWAN_MARKET",
                metadata={"odds": odds, "implied_pct": round(market_implied * 100.0, 1)},
            )
        )

        # 2. Expert Signal (Real billboard ranker)
        expert_sig = self.expert_adapter.get_expert_signal(leg)
        if expert_sig:
            signals.append(expert_sig)

        # 3. Crowd Signal (Community voting scale)
        crowd_sig = self.crowd_adapter.get_crowd_signal(leg)
        if crowd_sig:
            signals.append(crowd_sig)

        # 4. Registered Models (Open-Source Engines & Local Fallbacks)
        model_signals = self.model_registry.evaluate_leg_across_models(leg)
        signals.extend(model_signals)

        # 5. Sharp Market Benchmark (+EV Quantitative Value Engine)
        try:
            sharp_sig = self.sharp_adapter.evaluate_leg(leg)
            if sharp_sig:
                signals.append(sharp_sig)
        except Exception as exc:
            logger.debug("Sharp benchmark evaluation skipped: %s", exc)

        # 6. Public Betting Splits (Tickets % vs Money Handle %)
        try:
            if hasattr(self, "splits_client") and self.splits_client:
                splits = self.splits_client.get_betting_splits(leg.league)
                for sp in splits:
                    is_side_match = False
                    if leg.market in {"讓分", "讓球"} and sp.market_type == "SPREAD":
                        if leg.side == "主" and sp.selection == "home":
                            is_side_match = True
                        elif leg.side == "客" and sp.selection == "away":
                            is_side_match = True
                    elif leg.market in {"大小", "大小分"} and sp.market_type == "TOTAL":
                        if leg.side in {"大", "大分"} and sp.selection == "over":
                            is_side_match = True
                        elif leg.side in {"小", "小分"} and sp.selection == "under":
                            is_side_match = True
                    elif leg.market in {"不讓分", "獨贏"} and sp.market_type == "MONEYLINE":
                        if leg.side == "主" and sp.selection == "home":
                            is_side_match = True
                        elif leg.side == "客" and sp.selection == "away":
                            is_side_match = True

                    if is_side_match:
                        meta = {
                            "bet_percentage": sp.bet_percentage,
                            "money_percentage": sp.money_percentage,
                            "sample_size": sp.sample_size,
                            "reporting_bookmaker": sp.reporting_bookmaker,
                            "reporting_scope": sp.reporting_scope,
                            "is_synthetic": sp.is_synthetic,
                        }
                        splits_sig = PredictionSignal(
                            source_id=sp.source_id,
                            source_name=f"Public Betting Splits ({sp.reporting_bookmaker})",
                            source_type="BETTING_SPLITS",
                            source_category="MONEY_VOLUME_SPLITS",
                            independence_group="PUBLIC_BETTING_SPLITS",
                            event_id=leg.event_id,
                            market=leg.market,
                            selection=leg.selection,
                            probability=None,
                            score=sp.money_percentage,
                            confidence="MED" if (sp.sample_size or 0) >= 1000 else "LOW",
                            data_as_of=sp.observed_at_utc,
                            freshness_status=sp.freshness_status,
                            metadata=meta,
                        )
                        signals.append(splits_sig)
                        break
        except Exception as exc:
            logger.debug("Betting splits retrieval skipped: %s", exc)

        result = self.synthesize_signals_for_leg(leg, signals)
        if hasattr(self, "_leg_eval_cache"):
            self._leg_eval_cache[cache_key] = result
        return result

    def synthesize_signals_for_leg(self, leg: TaiwanLeg, signals: List[PredictionSignal]) -> TaiwanLeg:
        """Synthesize a collection of signals for a TaiwanLeg with source-family independence rules."""
        original_evidence = dict(leg.signal_evidence or {})
        odds = leg.taiwan_odds
        market_implied = 1.0 / odds if odds > 1.0 else 0.5

        # Evaluate supporting groups and Source Families
        supporting_groups: Dict[str, List[PredictionSignal]] = {}
        supporting_families: Dict[str, List[PredictionSignal]] = {}
        all_evaluated_groups: set = set()

        expert_desc = "無驗證大神主推"
        crowd_desc = "無大眾選票數據"
        models_desc: List[str] = []

        for s in signals:
            grp = s.independence_group or "UNKNOWN_GROUP"
            cat = s.source_category or s.source_type
            group_rule = self.weights_config.get("independence_groups", {}).get(grp, {})

            # Market odds is baseline only, NEVER counts as a supporting vote!
            if grp == "TAIWAN_MARKET" or cat == "BETTING_MARKET" or group_rule.get("is_baseline") or group_rule.get("max_votes") == 0:
                continue

            all_evaluated_groups.add(grp)

            # Expert Evaluation (HUMAN family)
            if cat in ["VERIFIED_EXPERT", "EXPERT"] or grp == "PLAYSPORT_EXPERT":
                expert_desc = f"{s.source_name}: 榜單歷史勝率 {s.score}%（非本場勝率）"
                rule = self.weights_config.get("source_weights", {}).get("VERIFIED_EXPERT", {})
                samples = (s.metadata or {}).get("sample_size", 0)
                confidence_rank = {"LOW": 1, "MED": 2, "HIGH": 3}
                if (s.freshness_status in {"LIVE", "FRESH"}
                        and confidence_rank.get(s.confidence, 0) >= confidence_rank.get(rule.get("min_confidence", "MED"), 2)
                        and samples >= rule.get("min_sample_size", 10)):
                    supporting_groups.setdefault("PLAYSPORT_EXPERT", []).append(s)
                    supporting_families.setdefault("HUMAN", []).append(s)

            # Crowd Evaluation (HUMAN family)
            elif cat in ["CROWD_CONSENSUS", "CROWD"] or grp == "PLAYSPORT_CROWD":
                crowd_pct = s.score if s.score is not None else 0.0
                crowd_desc = f"彩迷選票: {crowd_pct}%"
                rule = self.weights_config.get("source_weights", {}).get("CROWD_CONSENSUS", {})
                votes = (s.metadata or {}).get("vote_count")
                if s.freshness_status in {"LIVE", "FRESH"} and crowd_pct >= rule.get("min_support_pct", 55.0) and votes is not None and votes >= rule.get("min_sample_size", 20):
                    supporting_groups.setdefault("PLAYSPORT_CROWD", []).append(s)
                    supporting_families.setdefault("HUMAN", []).append(s)

            # Model Evaluation (STATISTICAL_MODEL family)
            elif cat in [
                "EXTERNAL_OPEN_SOURCE_ENGINE",
                "LOCAL_REIMPLEMENTATION",
                "OPEN_SOURCE_ENGINE",
                "LOCAL_FALLBACK_MODEL",
                "MODEL",
                "MODEL_STALE",
                "PUBLIC_MODEL",
            ]:
                mod_prob = s.probability
                edge = s.score or 0.0
                is_stale = (s.freshness_status not in {"LIVE", "FRESH"} or cat == "MODEL_STALE" or s.confidence == "REFERENCE_ONLY" or (s.metadata or {}).get("initialized") is False)
                
                if is_stale:
                    quality_tag = " [過期參考/STALE]"
                elif cat == "EXTERNAL_OPEN_SOURCE_ENGINE":
                    quality_tag = " [外部開源]"
                elif cat == "LOCAL_REIMPLEMENTATION":
                    quality_tag = " [本機重現]"
                else:
                    quality_tag = ""

                acceptance = (s.metadata or {}).get("model_acceptance") or {}
                if acceptance.get("accepted") is not True:
                    quality_tag += f" [未通過前向驗證:{acceptance.get('status', 'NOT_EVALUATED')}]"

                probability_text = f"{mod_prob * 100:.1f}%" if isinstance(mod_prob, (int, float)) and math.isfinite(mod_prob) and 0 <= mod_prob <= 1 else "未知"
                models_desc.append(f"{s.source_name}{quality_tag}: 未校準估計 {probability_text} (差值 {edge:+.1f}pp)")
                
                # Freshness Gate: Stale models CANNOT count as high-quality independent support!
                rule = self.weights_config.get("source_weights", {}).get(cat, {})
                configured_weight = (s.metadata or {}).get("configured_weight", rule.get("base_weight", 1.0))
                try:
                    weight_is_active = math.isfinite(float(configured_weight)) and float(configured_weight) > 0
                except (TypeError, ValueError):
                    weight_is_active = False
                if (acceptance_matches_signal(s, leg) and not is_stale and weight_is_active
                        and probability_text != "未知" and math.isfinite(edge)
                        and edge >= rule.get("min_edge_pp", 0.0)):
                    supporting_groups.setdefault(grp, []).append(s)
                    supporting_families.setdefault("STATISTICAL_MODEL", []).append(s)

            # Sharp Market Benchmark (+EV Quantitative Value Bet Signal)
            elif cat in ["SHARP_MARKET_BENCHMARK", "SHARP_BENCHMARK", "MARKET_BENCHMARK"] or grp == "SHARP_CONSENSUS":
                is_val = (s.metadata or {}).get("is_value_bet", False)
                if s.freshness_status in {"LIVE", "FRESH"} and is_val:
                    supporting_groups.setdefault("SHARP_CONSENSUS", []).append(s)
                    supporting_families.setdefault("SHARP_BENCHMARK", []).append(s)

            # Public Betting Splits (Participation & Capital Tendency)
            elif cat in ["BET_COUNT_SPLITS", "MONEY_VOLUME_SPLITS", "PUBLIC_BETTING_SPLITS"] or grp == "PUBLIC_BETTING_SPLITS":
                rule = self.weights_config.get("source_weights", {}).get("MONEY_VOLUME_SPLITS", {})
                min_samp = rule.get("min_sample_size", 1000)
                meta = s.metadata or {}
                sample = meta.get("sample_size") or 0
                money_pct = meta.get("money_percentage")
                if s.freshness_status in {"LIVE", "FRESH"} and money_pct is not None and money_pct >= 60.0 and sample >= min_samp:
                    supporting_groups.setdefault("PUBLIC_BETTING_SPLITS", []).append(s)
                    supporting_families.setdefault("BETTING_SPLITS", []).append(s)

        # Fundamental data support (e.g. verified pitchers)
        has_pitchers = bool(leg.away_pitcher and leg.home_pitcher)
        # Pitcher names alone contain no directional prediction and cannot
        # manufacture a second independent supporting family.

        independent_support_count = len(supporting_groups)
        has_verified_expert = "PLAYSPORT_EXPERT" in supporting_groups
        has_engine_support = any(g in supporting_groups for g in ["DIXON_COLES_MATCHES", "LIVE_MLB_ELO", "FIVETHIRTYEIGHT_ELO"])
        has_crowd_support = "PLAYSPORT_CROWD" in supporting_groups
        has_fallback_support = "ESPN_SEASON_STATS" in supporting_groups
        num_families = len(supporting_families)

        # Determine Agreement Level based on Source-Family Independence:
        # HIGH requires at least 2 independent families (e.g. Model + Human, or Model + Fundamental).
        # Expert + Crowd within HUMAN family alone yields MED, preventing single-platform vote inflation.
        high_rules = self.weights_config.get("agreement_rules", {}).get("HIGH", {})
        med_rules = self.weights_config.get("agreement_rules", {}).get("MED", {})
        high_minimum = high_rules.get("min_independent_groups", 2)
        if (num_families >= high_rules.get("min_source_families", 2) and independent_support_count >= high_minimum
                and (not high_rules.get("requires_expert_or_engine", True) or has_engine_support or has_verified_expert)):
            agreement = "HIGH"
            agreement_badge = "🟢 HIGH"
            agreement_emoji = "🟢"
        elif independent_support_count >= med_rules.get("min_independent_groups", 2):
            agreement = "MED"
            agreement_badge = "🟡 MED"
            agreement_emoji = "🟡"
        elif num_families == 1:
            if "HUMAN" in supporting_families:
                if has_verified_expert and med_rules.get("fallback_single_expert", True):
                    agreement = "MED"
                    agreement_badge = "🟡 MED"
                    agreement_emoji = "🟡"
                else:
                    # Crowd only is LOW
                    agreement = "LOW"
                    agreement_badge = "⚪ LOW"
                    agreement_emoji = "⚪"
            elif "STATISTICAL_MODEL" in supporting_families:
                if has_engine_support and med_rules.get("fallback_single_engine", True):
                    agreement = "MED"
                    agreement_badge = "🟡 MED"
                    agreement_emoji = "🟡"
                else:
                    agreement = "LOW"
                    agreement_badge = "⚪ LOW"
                    agreement_emoji = "⚪"
            else:
                agreement = "LOW"
                agreement_badge = "⚪ LOW"
                agreement_emoji = "⚪"
        else:
            agreement = "INSUFFICIENT_SIGNAL"
            agreement_badge = "⚪ INSUFFICIENT"
            agreement_emoji = "⚪"

        # Calculate continuous Quality Score (0-100)
        quality_score = sum(
            35.0 * self.weights_config.get("source_weights", {}).get(group_signals[0].source_category, {}).get("base_weight", 0.0)
            for group_signals in supporting_groups.values()
        )
        quality_score = round(max(0.0, min(100.0, quality_score)), 1)

        model_provenances = []
        primary_model_prob = None
        primary_delta_pp = None
        for s in signals:
            if s.metadata and "provenance" in s.metadata:
                model_provenances.append(s.metadata["provenance"])
            if s.source_type == "MODEL" and primary_model_prob is None and s.probability is not None:
                primary_model_prob = s.probability
                primary_delta_pp = s.model_market_delta_pp if s.model_market_delta_pp is not None else round((s.probability - market_implied) * 100.0, 1)

        # Keep candidate fusion for research, but only accepted, exact-scope model
        # evidence can affect the deployed recommendation probability.
        model_signal_categories = {
            "EXTERNAL_OPEN_SOURCE_ENGINE", "LOCAL_REIMPLEMENTATION", "OPEN_SOURCE_ENGINE",
            "LOCAL_FALLBACK_MODEL", "MODEL", "MODEL_STALE", "PUBLIC_MODEL",
        }
        model_signals = [s for s in signals if (s.source_category or s.source_type) in model_signal_categories]
        accepted_model_signals = [s for s in model_signals if acceptance_matches_signal(s, leg)]
        # The gate certifies one model's calibrated probability, not a later
        # average of several accepted models. Select a stable champion for the
        # deployed point estimate; retain every candidate in research evidence.
        champion = min(
            accepted_model_signals,
            key=lambda s: (str((s.metadata or {}).get("model_id", s.source_id)), str(s.source_id)),
            default=None,
        )
        candidate_eval = self.edge_engine.evaluate_leg(leg, signals=model_signals, research_candidate=True)
        edge_eval = self.edge_engine.evaluate_leg(leg, signals=[
            s for s in signals if s not in model_signals
        ] + ([champion] if champion is not None else []),
            direct_accepted_model=champion is not None)
        candidate_provenances = []
        for signal in model_signals:
            metadata = signal.metadata or {}
            candidate_provenances.append({
                "source_id": signal.source_id,
                "model_id": metadata.get("model_id", signal.source_id),
                "model_version": metadata.get("model_version"),
                "artifact_hash": metadata.get("model_artifact_hash"),
                "protocol_id": metadata.get("model_protocol_id"),
                "protocol_hash": metadata.get("model_protocol_hash"),
                "source_scope": metadata.get("prediction_source_scope", "unknown"),
                "raw_probability": metadata.get("model_candidate_probability", signal.probability),
                "data_as_of": signal.data_as_of,
                "freshness_status": signal.freshness_status,
                "acceptance_status": (metadata.get("model_acceptance") or {}).get("status", "NOT_EVALUATED"),
            })

        # Preserve observed source fields; missing crowd data stays unknown.
        crowd_signal = next((s for s in signals if s.source_type == "CROWD" or s.source_category in ["CROWD_CONSENSUS", "CROWD_SENTIMENT"]), None)
        expert_signal = next((s for s in signals if s.source_type == "EXPERT" or s.source_category in ["VERIFIED_EXPERT", "EXPERT_PICKS"]), None)
        sharp_signal = next((s for s in signals if s.source_type == "SHARP_BENCHMARK" or s.source_category in ["SHARP_MARKET_BENCHMARK", "MARKET_BENCHMARK"]), None)
        splits_signal = next((s for s in signals if s.source_type == "BETTING_SPLITS" or s.source_category in ["BET_COUNT_SPLITS", "MONEY_VOLUME_SPLITS", "PUBLIC_BETTING_SPLITS"]), None)
        crowd_metadata = crowd_signal.metadata if crowd_signal else {}
        expert_metadata = expert_signal.metadata if expert_signal else {}
        sharp_metadata = sharp_signal.metadata if sharp_signal else {}
        splits_metadata = splits_signal.metadata if splits_signal else {}
        crowd_ratio = crowd_metadata.get("ratio", original_evidence.get("crowd_ratio", original_evidence.get("consensus_ratio")))
        if crowd_ratio is None and crowd_signal and crowd_signal.score is not None:
            crowd_ratio = crowd_signal.score / 100.0

        bet_pct = splits_metadata.get("bet_percentage")
        money_pct = splits_metadata.get("money_percentage")
        splits_divergence = round(money_pct - bet_pct, 1) if (money_pct is not None and bet_pct is not None) else None

        # Line Movement & Steam/Trap Tracking
        line_movement = None
        if hasattr(self, "line_movement_tracker") and self.line_movement_tracker:
            try:
                line_movement = self.line_movement_tracker.analyze_leg_movement(leg, current_odds=odds)
            except Exception as exc:
                logger.debug("Line movement analysis skipped: %s", exc)

        evidence_summary: Dict[str, Any] = {
            **original_evidence,
            "taiwan_odds": odds,
            "line_movement": line_movement,
            "bet_percentage": bet_pct,
            "money_percentage": money_pct,
            "splits_divergence_pp": splits_divergence,
            "splits_sample_size": splits_metadata.get("sample_size"),
            "splits_reporting_book": splits_metadata.get("reporting_bookmaker"),
            "is_sharp_money_divergence": bool(splits_divergence and splits_divergence >= 15.0),
            "signal_classification_breakdown": {
                "crowd_sentiment": {
                    "source": "Playsport 社群選票",
                    "ratio_pct": round(crowd_ratio * 100.0, 1) if crowd_ratio is not None else None,
                    "vote_count": crowd_metadata.get("vote_count"),
                    "classification": "CROWD_SENTIMENT",
                    "role": "社群情緒指標（非真實勝率）",
                },
                "expert_picks": {
                    "source": "Playsport 認證達人",
                    "agreeing_count": expert_metadata.get("agreeing_count", 0),
                    "classification": "EXPERT_PICKS",
                    "role": "達人主推意見（歷史勝率非本場勝率）",
                },
                "betting_splits": {
                    "bet_percentage": bet_pct,
                    "money_percentage": money_pct,
                    "sample_size": splits_metadata.get("sample_size"),
                    "reporting_book": splits_metadata.get("reporting_bookmaker"),
                    "classification": "BETTING_SPLITS",
                    "role": "國際投注傾向（籌碼分佈非勝率）",
                },
                "market_benchmark": {
                    "fair_probability": sharp_metadata.get("sharp_fair_probability"),
                    "expected_value_pct": sharp_metadata.get("expected_value_pct"),
                    "sharp_book": sharp_metadata.get("sharp_book"),
                    "is_value_bet": sharp_metadata.get("is_value_bet", False),
                    "classification": "MARKET_BENCHMARK",
                    "role": "國際市場公允定價（去水公允機率）",
                },
                "statistical_models": {
                    "candidate_count": len(model_signals),
                    "accepted_champion": ((champion.metadata or {}).get("model_id", champion.source_id) if champion else None),
                    "classification": "STATISTICAL_MODEL",
                    "role": "獨立統計數據模型預測",
                },
            },
            "market_implied_pct": round(market_implied * 100.0, 1),
            "market_implied_probability": round(market_implied, 3),
            "market_fair_probability": edge_eval.market_fair_probability,
            "sharp_fair_probability": sharp_metadata.get("sharp_fair_probability"),
            "sharp_expected_value_pct": sharp_metadata.get("expected_value_pct"),
            "is_sharp_value_bet": sharp_metadata.get("is_value_bet", False),
            "sharp_value_grade": sharp_metadata.get("value_grade", "NONE"),
            "sharp_edge_pp": sharp_metadata.get("edge_pp"),
            "sharp_book": sharp_metadata.get("sharp_book"),
            "model_probability": edge_eval.consensus_probability if edge_eval.model_probability_raw is not None else None,
            "model_probability_raw": edge_eval.model_probability_raw,
            "model_probability_calibrated": edge_eval.model_probability_calibrated,
            "model_candidate_probability_raw": candidate_eval.model_probability_raw,
            "model_candidate_probability_fused": candidate_eval.consensus_probability if candidate_eval.model_probability_raw is not None else None,
            "model_candidate_provenances": candidate_provenances,
            "model_acceptance_statuses": [{"model_id": p["model_id"], "status": p["acceptance_status"]}
                                           for p in candidate_provenances],
            "model_accepted_ids": [p["model_id"] for p in candidate_provenances
                                   if p["acceptance_status"] == "ACCEPTED"],
            "active_model_champion_id": ((champion.metadata or {}).get("model_id", champion.source_id)
                                          if champion is not None else None),
            "consensus_probability": edge_eval.consensus_probability,
            "edge_vs_breakeven_pp": edge_eval.edge_vs_breakeven_pp,
            "edge_vs_fair_pp": edge_eval.edge_vs_fair_pp,
            "expected_value": edge_eval.expected_value,
            "expected_value_pct": round(edge_eval.expected_value * 100.0, 1),
            "conservative_ev": edge_eval.conservative_ev,
            "is_positive_ev": edge_eval.is_positive_ev,
            "ev_grade": edge_eval.ev_grade,
            "confidence_interval": list(edge_eval.confidence_interval) if edge_eval.confidence_interval is not None else None,
            "probability_status": edge_eval.details["probability_status"],
            "calibration_status": edge_eval.details["calibration_status"],
            "market_fair_method": edge_eval.details["market_fair_method"],
            "model_fusion_groups": edge_eval.details["model_groups"],
            "excluded_model_ids": edge_eval.details["excluded_models"],
            "uncertainty_level": edge_eval.uncertainty_level,
            "source_families": list(supporting_families.keys()),
            "supporting_families_count": len(supporting_families),
            "model_market_delta_pp": edge_eval.edge_vs_breakeven_pp if edge_eval.model_probability_raw is not None else None,
            "odds_status": leg.odds_status,
            "odds_age_minutes": leg.odds_age_minutes,
            "odds_scraped_at": leg.odds_scraped_at,
            "market_desc": f"台彩賠率 {odds:.2f} (隱含機率 {int(market_implied*100)}%)",
            "expert_desc": expert_desc,
            "crowd_desc": crowd_desc,
            "models_desc": models_desc,
            "source_url": original_evidence.get("source_url"),
            "consensus_ratio": crowd_ratio,
            "crowd_ratio": crowd_ratio,
            "vote_count": crowd_metadata.get("vote_count", original_evidence.get("vote_count")),
            "crowd_age_minutes": crowd_metadata.get("data_age_minutes", original_evidence.get("crowd_age_minutes")),
            "crowd_snapshot_timestamp": crowd_metadata.get("snapshot_timestamp", original_evidence.get("crowd_snapshot_timestamp")),
            "verified_experts": expert_metadata.get("expert_details", []),
            "expert_source_status": expert_metadata.get("source_status", "UNKNOWN"),
            "expert_source_urls": expert_metadata.get("source_urls", []),
            "expert_observed_at": expert_metadata.get("observed_at"),
            "expert_cache_age_minutes": expert_metadata.get("cache_age_minutes"),
            "expert_board_kinds": expert_metadata.get("board_kinds", []),
            "publication_time_precision": expert_metadata.get("publication_time_precision", "UNKNOWN") if expert_signal else "NOT_APPLICABLE",
            "expert_count": expert_metadata.get("agreeing_count", 0),
            "expert_consensus": expert_metadata.get("agreeing_count", 0),
            "expert_consensus_ratio": expert_metadata.get("consensus_ratio"),
            "model_provenances": model_provenances,
            "agreement": agreement,
            "agreement_badge": agreement_badge,
            "agreement_emoji": agreement_emoji,
            "evidence_quality": agreement,
            "quality_score": quality_score,
            "support_count": independent_support_count,
            "independent_support_count": independent_support_count,
            "non_market_supports": independent_support_count,
            "supporting_groups": list(supporting_groups.keys()),
            "all_evaluated_groups": list(all_evaluated_groups),
            "total_sources": len({s.independence_group or s.source_id for s in signals}),
            "raw_signal_count": len(signals),
            "has_verified_expert": has_verified_expert,
            "has_engine_support": has_engine_support,
            "has_model_support": has_engine_support or has_fallback_support,
            "has_crowd_support": has_crowd_support,
            "has_fallback_support": has_fallback_support,
        }

        leg.signals = signals
        leg.signal_evidence = evidence_summary
        leg.evidence_quality = agreement
        leg.market_probability = edge_eval.market_probability
        leg.model_probability_raw = edge_eval.model_probability_raw
        leg.model_probability_calibrated = edge_eval.model_probability_calibrated
        leg.consensus_probability = edge_eval.consensus_probability
        leg.edge = edge_eval.edge_vs_breakeven_pp
        leg.expected_value = edge_eval.expected_value
        leg.conservative_ev = edge_eval.conservative_ev
        leg.confidence_interval = edge_eval.confidence_interval
        leg.uncertainty_level = edge_eval.uncertainty_level
        leg.source_families = list(supporting_families.keys())
        return leg

    def evaluate_option(self, option: Dict[str, Any]) -> Dict[str, Any]:
        """Backward-compatible evaluation for raw option dictionaries."""
        odds = float(option.get("odds", 1.0))
        observed_consensus = option.get("consensus_ratio")
        consensus = float(observed_consensus) if observed_consensus is not None else None
        observed_votes = option.get("vote_count")
        vote_count = int(observed_votes) if observed_votes is not None else None

        leg = TaiwanLeg(
            event_id=str(option.get("match_id", "test")),
            sport="baseball",
            league="MLB",
            market=str(option.get("market_type", "不讓分")),
            selection=str(option.get("selection", "客勝")),
            taiwan_odds=odds,
            start_time="00:00",
            away_team="客隊",
            home_team="主隊",
            side=str(option.get("side", "客")),
            signal_evidence={"consensus_ratio": consensus, "vote_count": vote_count},
        )
        self.evaluate_taiwan_leg(leg)

        res = dict(option)
        res["signals"] = {
            "consistency_level": leg.evidence_quality,
            "consistency_badge": leg.signal_evidence.get("agreement_badge", ""),
            "agreement": leg.evidence_quality,
            "support_count": leg.signal_evidence.get("independent_support_count", 0),
            "independent_support_count": leg.signal_evidence.get("independent_support_count", 0),
            "quality_score": leg.signal_evidence.get("quality_score", 0.0),
            "market": {"desc": leg.signal_evidence.get("market_desc", "")},
            "expert": {"desc": leg.signal_evidence.get("expert_desc", "")},
            "crowd": {"desc": leg.signal_evidence.get("crowd_desc", "")},
            "model": {"desc": "; ".join(leg.signal_evidence.get("models_desc", []))},
        }
        return res
