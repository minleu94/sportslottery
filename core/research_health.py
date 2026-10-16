"""Read-only operational evidence; never infer scheduler success from a lock file."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from core.bet_validation import parse_aware_time
from core.research_paths import research_paths


def _read(path, errors):
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("expected object")
        return value
    except (OSError, ValueError) as exc:
        errors.append({"path":str(path), "error":str(exc)})
        return None


def build_research_health(data_root=None, *, now=None, cadence_minutes=None):
    now = parse_aware_time(now) if now is not None else datetime.now(timezone.utc)
    if now is None:
        raise ValueError("Health observation time must be timezone aware")
    if cadence_minutes is None:
        import yaml
        import core.research_paths as research_config
        config = yaml.safe_load(research_config.DEFAULT_CONFIG.read_text(encoding="utf-8")) if research_config.DEFAULT_CONFIG.exists() else {}
        cadence_minutes = max(1, int((config or {}).get("cadence_minutes", 15)))
    paths = research_paths(data_root)
    root, errors = paths["root"], []
    runs = []
    for path in sorted((root / "runs").glob("*/run.json")):
        row = _read(path, errors)
        if row:
            started = parse_aware_time(row.get("started_at"))
            if started is None or started > now:
                errors.append({"path":str(path),"error":"Invalid or future run start time"})
                continue
            row["record_path"] = str(path)
            runs.append(row)
    latest = max(runs, key=lambda row:parse_aware_time(row.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc), default=None)
    successful = [r for r in runs if r.get("status") == "COMPLETE" and parse_aware_time(r.get("completed_at")) is not None and parse_aware_time(r["completed_at"]) <= now]
    last_success = max(successful, key=lambda r:parse_aware_time(r["completed_at"]), default=None)
    last_stamp = parse_aware_time((last_success or {}).get("completed_at"))
    age = (now-last_stamp).total_seconds()/60 if last_stamp else None
    pipeline = {"status":(latest or {}).get("status", "NO_OBSERVATION"), "last_started_at":(latest or {}).get("started_at"),
                "last_success_at":last_stamp.isoformat() if last_stamp else None, "minutes_since_success":age,
                "overdue":age is None or age > cadence_minutes * 2, "cadence_minutes":cadence_minutes,
                "latest_run_id":(latest or {}).get("run_id"), "stages":(latest or {}).get("stages", {}),
                "error":(latest or {}).get("error") if (latest or {}).get("status") == "FAILED" else None,
                "record_path":(latest or {}).get("record_path")}
    sources, malformed = {}, 0
    source_successes = {}
    if paths["source_health"].exists():
        try:
            source_lines = paths["source_health"].read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            errors.append({"path":str(paths["source_health"]),"error":str(exc)})
            source_lines = []
        for raw in source_lines:
            try:
                row = json.loads(raw)
                if not isinstance(row, dict) or not row.get("alliance_id"):
                    raise ValueError("missing alliance")
                stamp = parse_aware_time(row.get("recorded_at") or row.get("attempted_at") or row.get("observed_at"))
                if not stamp or stamp > now:
                    continue
                key = str(row["alliance_id"])
                observed = parse_aware_time(row.get("observed_at"))
                if row.get("source_status") in {"LIVE", "LIVE_NO_EVENTS", "CACHED", "TTL_CACHE", "TTL_NO_EVENTS"} and not row.get("failure_status") and observed and observed <= now:
                    if observed > source_successes.get(key, datetime.min.replace(tzinfo=timezone.utc)):
                        source_successes[key] = observed
                if key not in sources or stamp > sources[key]["_stamp"]:
                    sources[key] = {**row, "_stamp":stamp}
            except (ValueError, TypeError):
                malformed += 1
    for row in sources.values():
        stamp = row.pop("_stamp")
        observed = parse_aware_time(row.get("observed_at"))
        row["minutes_since_attempt"] = (now-stamp).total_seconds()/60
        row["minutes_since_observation"] = (now-observed).total_seconds()/60 if observed and observed <= now else None
        row["last_success_at"] = source_successes[str(row["alliance_id"])].isoformat() if str(row["alliance_id"]) in source_successes else None
        row["stale"] = observed is None or observed > now or (now-observed).total_seconds() > 15*60
    models = []
    elo = _read(root / "model_state/live_mlb_elo.json", errors)
    if elo:
        models.append({"model":"MLB Elo", "data_as_of":elo.get("data_as_of"), "source":elo.get("source"),
                       "processed_games":len(elo.get("processed_game_pks", [])),
                       "path":str(root / "model_state/live_mlb_elo.json")})
    if models:
        progress = _read(root / "model_state/live_mlb_elo_fetch_coverage.json", errors) or {}
        models[0]["official_schedule_queried_through"] = progress.get("official_schedule_queried_through")
        models[0]["pending_game_dates"] = progress.get("pending_game_dates", [])
        models[0]["held_final_count"] = len(progress.get("held_final_games", []))
        models[0]["official_ledger_complete"] = progress.get("bootstrap_complete") is True
    for league in ("eng.1", "esp.1"):
        path = root / f"cache/models/penaltyblog_dixon_coles/real_matches_{league}.json"
        value = _read(path, errors)
        if value:
            matches = value.get("matches", [])
            models.append({"model":f"Dixon–Coles {league}", "data_as_of":value.get("latest_match_date") or max((str(r.get("date", "")) for r in matches),default=None),
                           "source":value.get("dataset_source"), "match_count":len(matches), "path":str(path)})
    for model in models:
        stamp = parse_aware_time(model.get("data_as_of"))
        if stamp is None:
            try:
                stamp = datetime.fromisoformat(str(model.get("data_as_of"))).replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
        model["watermark_status"] = "FUTURE_INVALID" if stamp and stamp > now else "KNOWN" if stamp else "UNKNOWN"
        model["days_behind"] = (now.date()-stamp.date()).days if stamp and stamp <= now else None
    scheduler = _read(root / "operations/task_status.json", errors)
    notification = _read(root / "operations/notification_receipt.json", errors)
    if scheduler:
        observed = parse_aware_time(scheduler.get("observed_at_utc"))
        scheduler["observation_stale"] = not observed or observed > now or (now-observed).total_seconds() > cadence_minutes*120
    settlement = {}
    for run in reversed(runs):
        audit = _read(Path(run["record_path"]).parent / "data/settlement_audit.json", errors)
        if audit:
            settlement = {"run_id":run.get("run_id"), "coverage":audit.get("coverage", {})}
            break
    connections = []
    source_legs = []
    source_run = None
    for run in reversed(runs):
        path = Path(run["record_path"]).parent / "data/source_legs.json"
        if not path.exists():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
                raise ValueError("Expected source leg objects")
            source_legs, source_run = value, run
        except (OSError, ValueError) as exc:
            errors.append({"path":str(path),"error":str(exc)})
        break
    if source_legs:
        from collections import defaultdict
        import yaml
        from core.bet_validation import assess_leg
        from core.research_paths import PROJECT_ROOT
        from core.identity.league_mapping import normalize_league_and_sport
        from core.settlement_engine import SettlementEngine
        from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter
        from integrations.models.espn_poisson_soccer import ESPNPoissonSoccerFallback
        configured = yaml.safe_load((PROJECT_ROOT / "config/models.yaml").read_text(encoding="utf-8")).get("models",{})
        declared = SettlementEngine.supported_result_coverage()
        evidence_path = PROJECT_ROOT / "config/result_coverage_evidence.yaml"
        if evidence_path.exists():
            evidence_manifest = yaml.safe_load(evidence_path.read_text(encoding="utf-8")) or {}
            for entry in evidence_manifest.get("entries", []):
                key = f"{entry['sport']}/{entry['league']}"
                row = {**entry, "coverage":entry.get("status"),
                       "checked_reference":entry.get("checked_references", [])}
                if key not in declared:
                    declared[key] = row
        groups = defaultdict(list)
        for row in source_legs:
            raw = str(row.get("league") or "")
            normalized, _ = normalize_league_and_sport(raw)
            league = normalized if normalized != "OTHER" else raw
            groups[(row.get("sport"), league)].append(row)
        for (sport,league), legs in groups.items():
            models_for_scope = []
            if sport == "soccer":
                for model_id, adapter in (("penaltyblog_dixon_coles",PenaltyblogDixonColesAdapter),("espn_poisson_soccer",ESPNPoissonSoccerFallback)):
                    if configured.get(model_id,{}).get("enabled") and adapter._resolve_league_code(None,league):
                        models_for_scope.append(model_id)
            elif league == "MLB":
                models_for_scope = [model for model in ("live_mlb_elo","espn_pythagorean_mlb") if configured.get(model,{}).get("enabled")]
            coverage = declared.get(f"{sport}/{league}",{})
            label = str(coverage.get("coverage") or "")
            supported = label.startswith("available") or "game_jsonld" in label
            connections.append({"league":league,"option_count":len(legs),
                                "ready_option_count":sum(assess_leg(row,now=now)["is_ready"] for row in legs),
                                "configured_model_adapters":models_for_scope,
                                "result_source_supported":supported,"result_provider":coverage.get("provider"),
                                "result_coverage":coverage.get("coverage"),
                                "result_evidence_gap":coverage.get("evidence_gap"),
                                "result_checked_reference":coverage.get("checked_reference"),
                                "source_run_started_at":source_run.get("started_at")})
        connections.sort(key=lambda row:(-row["ready_option_count"],row["league"]))
    pairing_failures = sum((row.get("unmatched_reason_counts") or {}).get("NO_UNIQUE_RESULT_MATCH", 0)
                           for row in settlement.get("coverage", {}).values())
    unsupported = sum(row.get("unmatched_snapshots", 0) for row in settlement.get("coverage", {}).values()
                      if row.get("status") == "UNSUPPORTED")
    stale_models = [row["model"] for row in models if row.get("days_behind") is None or row["days_behind"] > 7
                    or row.get("official_ledger_complete") is False]
    source_problems = [row.get("alliance_id") for row in sources.values()
                       if row["stale"] or row.get("failure_status") not in {None, "", "UNKNOWN"}]
    latest_predictions = (latest or {}).get("stages", {}).get("pregame_snapshots", {}).get("result", {})
    candidate_count = latest_predictions.get("model_candidate_probability_count")
    quality = {"status":"NEEDS_ATTENTION" if pairing_failures or unsupported or stale_models or source_problems else "OBSERVED",
               "pairing_failed_snapshot_count":pairing_failures, "unsupported_snapshot_count":unsupported,
               "stale_or_unknown_models":stale_models, "source_problem_alliances":source_problems,
               "model_candidate_prediction_count_latest_run":candidate_count,
               "meaning":"Workflow COMPLETE is execution status, not data/model qualification."}
    alerts = []
    if pipeline["overdue"] or pipeline["status"] == "FAILED":
        alerts.append({"key":"pipeline","severity":"ERROR","message":"研究流程未按時完整成功或有失敗階段。"})
    if source_problems:
        alerts.append({"key":"sources","severity":"WARNING","message":"盤口來源有失敗或過期：" + ", ".join(source_problems)})
    if pairing_failures:
        alerts.append({"key":"pairing","severity":"WARNING","message":f"{pairing_failures} 筆快照無法唯一配對賽果，請查看逐場差異。"})
    if stale_models:
        alerts.append({"key":"models","severity":"WARNING","message":"模型資料過舊或未知：" + ", ".join(stale_models)})
    return {"notification":notification, "data_quality":quality, "alerts":alerts, "league_connections":connections, "observed_at_utc":now.isoformat(), "data_root":str(root), "pipeline":pipeline,
            "sources":list(sources.values()), "models":models, "scheduler":scheduler,
            "settlement":settlement, "read_errors":errors, "malformed_source_records":malformed}
