"""Read-only research scores and report files; no forecast or eligibility logic."""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.bet_validation import parse_aware_time
from core.experiment_identity import get_current_experiment_identity
from core.research_helpers import _read_json, _write_json_atomic


class ResearchReportMixin:
    @staticmethod
    def _shadow_research_coverage(snapshots, now: datetime, experiment_id: str,
                                  latest_run_path: Path | None = None) -> dict[str, Any]:
        current_rows = []
        for row in snapshots:
            identity = row.get("experiment_identity") or {}
            if identity.get("experiment_id") != experiment_id:
                continue
            stamp = parse_aware_time(row.get("snapshot_timestamp") or row.get("timestamp"))
            if stamp is not None and stamp <= now:
                current_rows.append(row)

        def event_id(row):
            return str(row.get("canonical_event_id") or row.get("event_id") or "")

        qualification_exclusions = Counter()
        def valid_model_predictions(row):
            stamp = parse_aware_time(row.get("snapshot_timestamp") or row.get("timestamp"))
            start = parse_aware_time(row.get("event_start"))
            valid = []
            for candidate in row.get("model_candidate_predictions") or []:
                if not isinstance(candidate, dict):
                    continue
                try:
                    probability = float(candidate.get("raw_probability"))
                except (TypeError, ValueError, OverflowError):
                    continue
                if not math.isfinite(probability) or not 0 < probability < 1:
                    continue
                as_of = parse_aware_time(candidate.get("data_as_of"))
                point_in_time_verified = (
                    candidate.get("point_in_time_status") == "VALID"
                    or candidate.get("point_in_time_verified") is True
                    or candidate.get("pre_event_source_order_valid") is True
                )
                freshness = str(candidate.get("freshness_status") or "UNKNOWN").upper()
                reason = None
                if freshness not in {"LIVE", "FRESH", "AGING"}:
                    reason = "DATA_STALE_OR_UNKNOWN"
                elif as_of is None:
                    reason = "DATA_AS_OF_MISSING_OR_UNAWARE"
                elif stamp is None or start is None:
                    reason = "SNAPSHOT_OR_EVENT_START_MISSING"
                elif as_of > stamp:
                    reason = "DATA_AS_OF_AFTER_OBSERVATION"
                elif as_of >= start:
                    reason = "DATA_AS_OF_NOT_PRE_EVENT"
                elif not point_in_time_verified:
                    reason = "POINT_IN_TIME_UNPROVEN"
                if reason:
                    qualification_exclusions[reason] += 1
                else:
                    valid.append(candidate)
            return valid

        eligible_events = set()
        model_events = set()
        model_pairs = set()
        data_valid_events = set()
        settled_model_events = set()
        international_events = set()
        sharp_events = set()
        model_sharp_events = set()
        model_freshness = Counter()
        all_event_keys = set()

        for row in current_rows:
            key = event_id(row)
            if not key:
                continue
            all_event_keys.add(key)
            stamp = parse_aware_time(row.get("snapshot_timestamp") or row.get("timestamp"))
            start = parse_aware_time(row.get("event_start"))
            if (row.get("forward_validation_eligible") is True and stamp is not None
                    and start is not None and stamp < start):
                eligible_events.add(key)

            predictions = [candidate for candidate in row.get("model_candidate_predictions") or []
                           if isinstance(candidate, dict)]
            raw_predictions = []
            for candidate in predictions:
                try:
                    probability = float(candidate.get("raw_probability"))
                except (TypeError, ValueError, OverflowError):
                    continue
                if math.isfinite(probability) and 0 < probability < 1:
                    raw_predictions.append(candidate)
                    model_freshness[str(candidate.get("freshness_status") or "UNKNOWN").upper()] += 1
                    model_pairs.add((key, str(candidate.get("model_id") or "UNKNOWN")))
            if raw_predictions:
                model_events.add(key)
                result_source = str(row.get("result_source") or "").strip().upper()
                settled_at = parse_aware_time(row.get("settled_at"))
                if (row.get("is_settled") is True and row.get("settlement_status") in {"WON", "LOST"}
                        and row.get("forward_validation_eligible") is True
                        and settled_at is not None and settled_at <= now
                        and result_source not in {"", "UNKNOWN", "MANUAL", "TEST", "FIXTURE"}):
                    settled_model_events.add(key)

            valid_predictions = valid_model_predictions(row)
            if valid_predictions:
                data_valid_events.add(key)

            evidence = row.get("signal_evidence") or {}
            if (evidence.get("international_market_complete") is True
                    and not evidence.get("is_market_synthetic")):
                international_events.add(key)
            if (evidence.get("market_source_qualification") == "SHARP_QUALIFIED"
                    and not evidence.get("is_market_synthetic")):
                sharp_events.add(key)
                if valid_predictions:
                    model_sharp_events.add(key)

        latest_run = _read_json(latest_run_path, {}) if latest_run_path is not None else {}
        latest_result = ((latest_run.get("stages") or {}).get("pregame_snapshots") or {}).get("result") or {}

        return {
            "experiment_id": experiment_id,
            "current_experiment_snapshot_count": len(current_rows),
            "other_experiment_snapshot_count_excluded": max(0, len(snapshots) - len(current_rows)),
            "current_experiment_unique_event_count": len(all_event_keys),
            "valid_pregame_candidate_event_count": len(eligible_events),
            "raw_shadow_model_prediction_event_count": len(model_events),
            "unique_model_event_pair_count": len(model_pairs),
            "data_valid_model_prediction_event_count": len(data_valid_events),
            "settled_model_prediction_event_count": len(settled_model_events),
            "international_market_complete_event_count": len(international_events),
            "sharp_market_complete_event_count": len(sharp_events),
            "model_and_sharp_complete_event_count": len(model_sharp_events),
            "model_prediction_freshness_status_counts": dict(model_freshness),
            "model_prediction_qualification_exclusion_counts": dict(qualification_exclusions),
            "latest_run_observation": latest_result.get("shadow_coverage", {}),
        }

    def _stage_report(self, stage_data: Path) -> dict[str, Any]:
        now = self.clock().astimezone(timezone.utc)
        since = now - timedelta(days=7)
        snapshots = self.snapshot_logger.get_all_snapshots()
        recent = []
        for row in snapshots:
            stamp = parse_aware_time(row.get("recorded_at") or row.get("timestamp"))
            if stamp and since <= stamp <= now:
                recent.append(row)
        known_rows = [row for row in recent if not row.get("is_settled") or (
            parse_aware_time(row.get("settled_at")) is not None
            and parse_aware_time(row.get("settled_at")) <= now)]
        settled = [row for row in known_rows if row.get("is_settled") and row.get("settlement_status") in {"WON", "LOST", "PUSH", "VOID"}]
        from core.performance_metrics import PerformanceMetricsEngine
        current_experiment_id = get_current_experiment_identity()["experiment_id"]
        forward_cohort = PerformanceMetricsEngine.forward_cohort(known_rows, current_experiment_id)
        scoped = forward_cohort["observations"]
        audit = forward_cohort["audit"]
        # Candidate calibration is a separate cohort: include settled shadow
        # rows as well as formal rows, deduped to the latest valid forecast.
        shadow_cohort = PerformanceMetricsEngine.forward_cohort(
            known_rows, current_experiment_id, observation_purpose="SHADOW_CALIBRATION"
        )
        shadow_scoped = shadow_cohort["observations"]
        audit["report_outcomes_unknown_at_cutoff_excluded"] = len(recent) - len(known_rows)
        def valid_probability(value):
            try:
                number = float(value)
                return math.isfinite(number) and 0 < number < 1
            except (TypeError, ValueError, OverflowError):
                return False
        # Paired model-vs-market scores require both probabilities on precisely
        # the same integrity-checked, current-experiment binary outcomes.
        paired_rows = [row for row in scoped
                       if row.get("probability_status") in {
                           "UNVALIDATED_MODEL_ESTIMATE", "MODEL_ESTIMATE", "CALIBRATED_MODEL_ESTIMATE"
                       }
                       and valid_probability(row.get("model_probability"))
                       and valid_probability(row.get("market_fair_probability"))]
        # Gate-rejected research candidates remain a separate diagnostic cohort:
        # they are never substituted into the deployed-model metric above.
        candidate_rows = [row for row in shadow_scoped
                          if valid_probability(row.get("model_candidate_probability_fused"))
                          and valid_probability(row.get("market_fair_probability"))
                          and bool(row.get("model_candidate_provenances"))]
        model_metrics = PerformanceMetricsEngine.evaluate_model_overall_metrics(
            paired_rows, current_experiment_id
        )
        market_metrics = self._binary_metrics(paired_rows, "market_fair_probability")
        paired_ci = self._paired_cluster_ci(paired_rows)
        candidate_metrics = self._binary_metrics(candidate_rows, "model_candidate_probability_fused")
        candidate_market_metrics = self._binary_metrics(candidate_rows, "market_fair_probability")
        candidate_ci = self._paired_cluster_ci(candidate_rows, model_probability_field="model_candidate_probability_fused")
        parlay_records = []
        for record in self.parlay_logger.get_all_parlay_snapshots():
            stamp = parse_aware_time(record.get("timestamp") or record.get("date"))
            if stamp and since <= stamp <= now:
                parlay_records.append(record)
        parlay_rows = [row for record in parlay_records for row in record.get("candidates", [])
                       if row.get("settled") and parse_aware_time(row.get("settled_at")) is not None
                       and parse_aware_time(row.get("settled_at")) <= now]
        parlay_statuses = Counter(str(row.get("settlement_status", "UNKNOWN")) for row in parlay_rows)
        won_parlays = [row for row in parlay_rows if row.get("settlement_status") == "WON"]
        losses_parlays = sum(row.get("settlement_status") == "LOST" for row in parlay_rows)
        stakes = len(parlay_rows) * 10.0
        payouts = sum(float(row.get("actual_payout") or 0) for row in parlay_rows)
        source_counts = Counter()
        health_path = self.data_root / "source_health" / "playsport.jsonl"
        if health_path.exists():
            for raw in health_path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(raw)
                    stamp = parse_aware_time(row.get("observed_at") or row.get("recorded_at") or row.get("attempted_at"))
                    if stamp and since <= stamp <= now:
                        source_counts[str(row.get("source_status", "UNKNOWN"))] += 1
                except (ValueError, TypeError):
                    continue
        from core.parlay_validation import evaluate_parlay_forward
        parlay_eval = evaluate_parlay_forward(parlay_records, current_experiment_id, as_of=now)
        # Descriptive error dependence uses the same integrity-checked forward
        # cohort as the single-leg scores. Raw model candidates stay labeled as
        # research estimates; these correlations do not certify calibration.
        error_correlation = self._empirical_error_correlation(scoped)
        joint_correlation = self._empirical_joint_hit_diagnostic(
            parlay_records, current_experiment_id, now,
        )
        payload = {
            "generated_at_utc": now.isoformat(), "period_start_utc": since.isoformat(),
            "period_end_utc": now.isoformat(), "data_root": str(self.data_root),
            "experiment_identity": get_current_experiment_identity(),
            "shadow_research_coverage": self._shadow_research_coverage(
                snapshots, now, current_experiment_id, stage_data.parent / "run.json",
            ),
            "wallet_data_used": False,
            "single_leg": {"recorded_snapshots": len(recent), "settled_count": len(settled),
                           "valid_current_experiment_unique_observations": audit,
                           "formal_strategy_observation_scope": "FORMAL_QUALIFICATION_WINDOW_OR_LEGACY_PREMATCH_WITHIN_60_MINUTES",
                           "paired_probability_cohort_n": len(paired_rows), "model": model_metrics,
                           "market_baseline": market_metrics,
                           "paired_cluster_bootstrap_ci95": paired_ci,
                           "realized_returns_same_selections": {
                               "n": len(paired_rows),
                               "hit_rate": model_metrics.get("hit_rate"),
                               "roi_pct": model_metrics.get("roi_pct"),
                               "interpretation": "Model and market score the same selected outcomes at the same Taiwan odds; realized hit rate and ROI are shared returns, not strategy differences.",
                           },
                           "research_candidate": {
                               "status": "UNVALIDATED_DIAGNOSTIC_ONLY",
                               "observation_scope": "FORMAL_PLUS_SHADOW_UP_TO_240_MINUTES_LATEST_VALID_OBSERVATION",
                               "cohort_audit": shadow_cohort["audit"],
                               "paired_probability_cohort_n": len(candidate_rows),
                               "model_candidate": candidate_metrics,
                               "market_baseline_same_cohort": candidate_market_metrics,
                               "paired_cluster_bootstrap_ci95": candidate_ci,
                               "realized_returns_same_selections": {
                                   "n": len(candidate_rows),
                                   "hit_rate": candidate_metrics.get("hit_rate"),
                                   "roi_pct": candidate_metrics.get("roi_pct"),
                                   "interpretation": "Candidate and market score the same selected outcomes at the same Taiwan odds; realized hit rate and ROI are shared returns, not strategy differences.",
                               },
                           }},
            "whole_ticket": {"operational_reference_only": True,
                             "settled_ticket_count": len(parlay_rows), "status_counts": dict(parlay_statuses),
                             "wager_units": stakes, "payout_units": payouts,
                             "roi_pct": (100 * (payouts - stakes) / stakes) if stakes else None,
                             "won_count": len(won_parlays), "lost_count": losses_parlays,
                             "forward_validation": parlay_eval,
                             "empirical_joint_hit_diagnostic": joint_correlation},
            "empirical_model_error_correlation": error_correlation,
            "source_health_observation_counts": dict(source_counts),
            "model_update": _read_json(stage_data / "model_update.json", {
                "status": "NOT_RUN", "reason": "No explicit initialized Elo checkpoint/update adapter configured."}),
            "soccer_model_update": _read_json(stage_data / "soccer_model_update.json", {"status": "NOT_RUN"}),
            "interpretation": "Research operations summary; estimates with N=0 are unavailable and this report alone does not establish model reliability.",
        }
        reports = self.data_root / "reports"
        json_path = reports / f"weekly_{now:%Y-%m-%d}.json"
        md_path = reports / f"weekly_{now:%Y-%m-%d}.md"
        _write_json_atomic(json_path, payload)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(self._render_report(payload), encoding="utf-8")
        return {"report_json": str(json_path), "report_markdown": str(md_path),
                "single_settled_n": len(settled), "model_cohort_n": len(paired_rows),
                "parlay_settled_n": len(parlay_rows), "source_health_observations": sum(source_counts.values())}


    @staticmethod
    def _empirical_error_correlation(rows: list[dict[str, Any]]) -> dict[str, Any]:
        from core.correlation_guard import empirical_error_correlation

        scopes: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            event = row.get("canonical_event_id") or row.get("source_game_id") or row.get("event_id")
            actual = row.get("actual_outcome")
            if not event or not isinstance(actual, bool):
                continue
            probabilities = {}
            for item in row.get("model_candidate_predictions") or []:
                if not isinstance(item, dict) or item.get("source_scope") != "taiwan_forward":
                    continue
                model_id = item.get("model_id")
                probability = item.get("raw_probability")
                if (not model_id or isinstance(probability, bool)
                        or not isinstance(probability, (int, float))
                        or not math.isfinite(probability) or not 0 <= probability <= 1):
                    continue
                name = "|".join(str(item.get(key) or "") for key in
                                ("model_id", "model_version", "artifact_hash", "protocol_hash"))
                probabilities[name] = float(probability)
            if not probabilities:
                continue
            line = row.get("line")
            scope = (str(row.get("league") or ""), str(row.get("market") or ""),
                     str(row.get("side") or ""), "" if line is None else str(line))
            scopes.setdefault(scope, []).append({
                "event_id": f"{event}|{scope!r}", "actual_outcome": actual,
                "probabilities": probabilities,
            })
        results = []
        for scope, scoped_rows in sorted(scopes.items()):
            diagnostic = empirical_error_correlation(scoped_rows)
            results.append({"league": scope[0], "market": scope[1], "side": scope[2],
                            "line": scope[3], **diagnostic})
        pair_count = sum(len(item.get("pairs", {})) for item in results)
        ready_count = sum(pair.get("status") == "DESCRIPTIVE_PAIRED_ERROR_CORRELATION"
                          for item in results for pair in item.get("pairs", {}).values())
        return {"status": "DESCRIPTIVE_ONLY" if ready_count else "INSUFFICIENT_PAIRED_EVENTS",
                "scope_count": len(results), "paired_model_pairs": pair_count,
                "estimated_pair_count": ready_count,
                "sample_source": "integrity-checked current-experiment forward snapshots; raw model candidate predictions",
                "calibration_claim": False, "scopes": results}


    @staticmethod
    def _empirical_joint_hit_diagnostic(records: list[dict[str, Any]], experiment_id: str,
                                        as_of: datetime) -> dict[str, Any]:
        from core.correlation_guard import empirical_joint_hit_diagnostic
        from core.parlay_validation import evaluate_parlay_forward, event_identity

        signatures: dict[tuple, dict[str, Any]] = {}
        conflicts: set[tuple] = set()
        for record in records:
            for candidate in record.get("candidates", []):
                # Reuse the full forward evaluator as the qualification source:
                # it verifies frozen leg hashes, exact identity, actual result
                # provenance, point-in-time ordering and outcome consistency.
                one = evaluate_parlay_forward([{"candidates": [candidate]}], experiment_id,
                                              replicates=0, as_of=as_of)
                if not any(tier.get("n") == 1 for tier in one["tiers"].values()):
                    continue
                key = tuple(sorted(event_identity(leg) + json.dumps([
                    leg.get("market"), leg.get("side") or leg.get("selection"),
                    str(leg.get("line")) if leg.get("line") is not None else None,
                ], sort_keys=True, separators=(",", ":")) for leg in candidate["legs"]))
                previous = signatures.get(key)
                if previous and previous.get("settlement_status") != candidate.get("settlement_status"):
                    conflicts.add(key)
                if previous is None or str(candidate.get("recorded_at", "")) < str(previous.get("recorded_at", "")):
                    signatures[key] = candidate
        qualified = [row for key, row in signatures.items() if key not in conflicts]
        # Group tickets by shared events and UTC event slate before applying the
        # diagnostic's minimum-cluster threshold.
        parent = list(range(len(qualified)))
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        owners: dict[str, int] = {}
        for i, row in enumerate(qualified):
            keys = {"event:" + event_identity(leg) for leg in row["legs"]}
            keys.update("slate:" + (parse_aware_time(leg.get("start_time_utc") or leg.get("event_start")).date().isoformat())
                        for leg in row["legs"])
            for key in keys:
                if key in owners:
                    parent[find(i)] = find(owners[key])
                owners[key] = i
        cluster_ids = {find(i): f"cluster:{find(i)}" for i in range(len(qualified))}
        diagnostic_rows = []
        for i, row in enumerate(qualified):
            statuses = [item[0] for item in row.get("leg_settlement_statuses", [])]
            result = row.get("settlement_status")
            diagnostic_rows.append({
                "ticket_id": row.get("prediction_payload_hash"),
                "event_id": cluster_ids[find(i)],
                "leg_outcomes": [status == "WON" for status in statuses],
                "predicted_joint_probability": row.get("joint_probability"),
            })
        diagnostic = empirical_joint_hit_diagnostic(diagnostic_rows)
        diagnostic.update({"experiment_id": experiment_id,
                           "duplicate_conflict_tickets_excluded": len(conflicts),
                           "sample_source": "frozen tickets passing evaluate_parlay_forward qualification",
                           "probability_status": "UNVALIDATED_HEURISTIC_JOINT_ESTIMATE",
                           "calibration_claim": False})
        return diagnostic


    @staticmethod
    def _binary_metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
        outcomes, probs, returns = [], [], []
        for row in rows:
            try:
                p = float(row[field])
                if not math.isfinite(p) or not 0 < p < 1:
                    continue
                win = row.get("settlement_status") == "WON"
                odds = float(row.get("taiwan_odds"))
                if not math.isfinite(odds) or odds <= 1:
                    continue
            except (TypeError, ValueError):
                continue
            outcomes.append(float(win)); probs.append(p); returns.append(odds - 1 if win else -1)
        n = len(probs)
        if not n:
            return {"n": 0, "brier": None, "log_loss": None, "hit_rate": None, "roi_pct": None}
        brier = sum((p-y)**2 for p, y in zip(probs, outcomes)) / n
        logloss = -sum(y*math.log(max(1e-12, p)) + (1-y)*math.log(max(1e-12, 1-p))
                       for p, y in zip(probs, outcomes)) / n
        return {"n": n, "brier": brier, "log_loss": logloss,
                "hit_rate": sum(outcomes)/n, "roi_pct": 100*sum(returns)/n}


    @classmethod
    def _paired_cluster_ci(cls, rows: list[dict[str, Any]], replicates: int = 1000,
                           model_probability_field: str = "model_probability") -> dict[str, Any]:
        import random
        clusters: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            start = parse_aware_time(row.get("event_start"))
            if start is None:
                continue
            key = str(row.get("event_cluster") or start.date().isoformat())
            clusters.setdefault(key, []).append(row)
        if len(clusters) < 5 or not rows:
            return {"status": "INSUFFICIENT_CLUSTERS", "cluster_count": len(clusters),
                    "replicates": 0, "intervals": None}
        rng = random.Random(20261013)
        blocks = list(clusters.values())
        values = {key: [] for key in ("brier_delta_model_minus_market", "log_loss_delta_model_minus_market")}
        for _ in range(replicates):
            sample = [row for _ in blocks for row in rng.choice(blocks)]
            model = cls._binary_metrics(sample, model_probability_field)
            market = cls._binary_metrics(sample, "market_fair_probability")
            for key, model_key, market_key in (
                ("brier_delta_model_minus_market", "brier", "brier"),
                ("log_loss_delta_model_minus_market", "log_loss", "log_loss"),
            ):
                if model[model_key] is not None and market[market_key] is not None:
                    values[key].append(model[model_key] - market[market_key])
        intervals = {}
        for key, sample in values.items():
            sample.sort()
            intervals[key] = ([sample[int(.025*(len(sample)-1))], sample[int(.975*(len(sample)-1))]]
                              if sample else None)
        return {"status": "COMPLETED", "compared_metrics": ["brier", "log_loss"],
                "cluster_count": len(clusters), "replicates": replicates,
                "cluster_unit": "UTC event start date", "intervals": intervals}


    @staticmethod
    def _render_report(payload: dict[str, Any]) -> str:
        single, tickets = payload["single_leg"], payload["whole_ticket"]
        model = single["model"]
        tickets = payload["whole_ticket"]
        forward_tiers = tickets.get("forward_validation", {}).get("tiers", {})
        error_corr = payload.get("empirical_model_error_correlation", {})
        corr_lines = [f"Status: **{error_corr.get('status', 'UNAVAILABLE')}** · "
                      f"eligible scopes: {error_corr.get('scope_count', 0)} · "
                      f"estimable pairs: {error_corr.get('estimated_pair_count', 0)}"]
        for scope in error_corr.get("scopes", []):
            label = " / ".join(str(scope.get(key) or "—") for key in ("league", "market", "side", "line"))
            corr_lines.append(f"- {label}: N={scope.get('unique_valid_events', 0)} unique events")
            for pair, values in scope.get("pairs", {}).items():
                estimate = values.get("error_correlation")
                shown = "未知" if estimate is None else f"{estimate:.4f}"
                corr_lines.append(f"  - `{pair}`: {values.get('status')} · paired N={values.get('paired_event_count', 0)} · r={shown}")
        joint = tickets.get("empirical_joint_hit_diagnostic", {})
        return (f"# Wallet-free Research Weekly Report\n\n"
                f"Period: {payload['period_start_utc']} — {payload['period_end_utc']}\n\n"
                f"Wallet data used: **No**\n\n"
                f"## Single-leg results\n\n"
                f"Recorded: {single['recorded_snapshots']} · Settled: {single['settled_count']} · "
                f"Paired model/market cohort N={single['paired_probability_cohort_n']} · "
                f"Model Brier={model.get('brier_score')} · Log loss={model.get('log_loss')} · "
                f"Hit rate={model.get('hit_rate')} · ROI={model.get('roi_pct')}%\n\n"
                f"Unvalidated research candidate only: N={single['research_candidate']['paired_probability_cohort_n']} · "
                f"Brier={single['research_candidate']['model_candidate']['brier']} · "
                f"Log loss={single['research_candidate']['model_candidate']['log_loss']} · "
                f"Hit rate={single['research_candidate']['model_candidate']['hit_rate']} · "
                f"ROI={single['research_candidate']['model_candidate']['roi_pct']}%\n\n"
                f"Market fair baseline: Brier={single['market_baseline']['brier']} · "
                f"Log loss={single['market_baseline']['log_loss']} · "
                f"Hit rate={single['market_baseline']['hit_rate']} · ROI={single['market_baseline']['roi_pct']}%\n\n"
                f"## Whole-ticket results\n\n"
                f"Experiment-qualified forward validation: `{json.dumps(forward_tiers, ensure_ascii=False)}`\n\n"
                f"Operational reference only (not experiment-qualified): settled tickets {tickets['settled_ticket_count']} · "
                f"ROI {tickets['roi_pct']}% · status counts `{json.dumps(tickets['status_counts'], ensure_ascii=False)}`\n\n"
                f"## Empirical dependence diagnostics\n\n"
                f"### Model forecast-error correlations\n\n"
                f"{chr(10).join(corr_lines)}\n\n"
                f"Descriptive only; raw candidate estimates are not calibrated probabilities.\n\n"
                f"### Frozen whole-ticket joint hit diagnostic\n\n"
                f"Status: **{joint.get('status', 'UNAVAILABLE')}** · tickets N={joint.get('ticket_count', 0)} · "
                f"event/slate clusters={joint.get('event_cluster_count', 0)} · "
                f"mean predicted p={joint.get('mean_predicted_joint_probability')} · "
                f"observed hit rate={joint.get('observed_joint_hit_rate')} · "
                f"mean p-error={joint.get('mean_probability_error')}\n\n"
                f"{joint.get('diagnostic_scope', 'No qualified frozen tickets available.')} Descriptive only; not a calibration claim.\n\n"
                f"## Data limits\n\n{payload['interpretation']}\n")
