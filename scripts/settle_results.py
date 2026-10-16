#!/usr/bin/env python3
"""Run Result Settlement for Shadow Evaluation.

Scans for unsettled historical predictions, fetches completed match results,
settles Brier / Log Loss / CLV, and resolves candidate parlays and shadow portfolio bets.

Usage:
  python scripts/settle_results.py [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Fix console encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.settlement_engine import SettlementEngine
from core.shadow_portfolio import ShadowPortfolioManager
from core.snapshot_logger import PredictionSnapshotLogger
from core.bet_validation import parse_aware_time
from core.identity.league_mapping import normalize_league_and_sport


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
MAX_UNMATCHED_AUDIT_SAMPLES = 100


def _snapshot_local_date(snapshot):
    start = parse_aware_time(snapshot.get("event_start") or snapshot.get("start_time_utc"))
    if not start:
        return None
    league = str(snapshot.get("league") or "").upper()
    tz_name = {"NPB": "Asia/Tokyo", "CPBL": "Asia/Taipei", "KBO": "Asia/Seoul"}.get(league)
    return start.astimezone(ZoneInfo(tz_name)).date().isoformat() if tz_name else start.date().isoformat()


def settle_snapshot_results(engine, snapshots, date_filter=None, *, now=None):
    """Fetch each covered sport/league by historical date and fail closed on identity gaps."""
    unsettled = [s for s in snapshots if not s.get("is_settled")]
    current = parse_aware_time(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        raise ValueError("Settlement observation time must be timezone aware.")
    if date_filter:
        scoped = []
        for snap in unsettled:
            if (_snapshot_local_date(snap) == date_filter) or (not _snapshot_local_date(snap) and (snap.get("source_game_id") or snap.get("game_pk"))):
                scoped.append(snap)
        unsettled = scoped
    by_league = {}
    coverage_status = {}
    unmatched_observations = []
    unmatched_reason_counts = {}
    deferred_counts = {}
    deferred_observations = []
    unresolved = 0
    for snap in unsettled:
        sport, league = str(snap.get("sport") or "").lower(), str(snap.get("league") or "").upper()
        # Exact source aliases may have been stored before a competition had
        # canonical result coverage. Normalize only recognized names so those
        # existing snapshots can use the newly verified provider feed.
        canonical_league, canonical_sport = normalize_league_and_sport(league)
        if canonical_sport == sport and canonical_league != "OTHER":
            league = canonical_league
        if not sport or not league:
            key = f"{sport or 'unknown'}/{league or 'unknown'}"
            coverage_status.setdefault(key, {"provider": None, "status": "MISSING_SPORT_OR_LEAGUE_METADATA",
                                              "fetch_status": "NOT_ATTEMPTED",
                                              "games": 0, "snapshots": 0, "matched_snapshots": 0, "unique_matches": 0,
                                              "settled_snapshots": 0, "unmatched_snapshots": 0, "errors": []})
            coverage_status[key].setdefault("settlement_status_counts", {})
            coverage_status[key]["snapshots"] += 1
            coverage_status[key]["unmatched_snapshots"] += 1
            unresolved += 1
            _record_unmatched(unmatched_observations, snap, sport or None, league or None,
                              "MISSING_SPORT_OR_LEAGUE_METADATA", None, [], unmatched_reason_counts)
            continue
        start = parse_aware_time(snap.get("event_start") or snap.get("start_time_utc"))
        if start is not None and start > current:
            key = f"{sport}/{league}"
            deferred_counts[key] = deferred_counts.get(key, 0) + 1
            if len(deferred_observations) < MAX_UNMATCHED_AUDIT_SAMPLES:
                deferred_observations.append({"snapshot_id": snap.get("snapshot_id"),
                                              "event_start": start.isoformat(), "reason": "EVENT_NOT_STARTED"})
            continue
        by_league.setdefault((sport, league), []).append(snap)

    settled = 0
    game_count = 0
    for (sport, league), league_snaps in sorted(by_league.items()):
        declared_coverage = None
        coverage_reader = getattr(engine, "supported_result_coverage", None)
        if callable(coverage_reader):
            try:
                declared_coverage = coverage_reader().get(f"{sport}/{league}")
            except Exception as exc:
                # Without readable coverage metadata we cannot safely infer
                # that an arbitrary league is unsupported. Fail explicitly so
                # the pipeline retries instead of silently skipping it.
                raise RuntimeError(
                    f"Result coverage metadata failed for {sport}/{league}: {exc}"
                ) from exc
        coverage_label = str((declared_coverage or {}).get("coverage") or "").strip().lower()
        explicitly_supported = (
            coverage_label.startswith("available")
            or "game_jsonld" in coverage_label
        )
        if callable(coverage_reader) and not explicitly_supported:
            # A known-but-unverified feed (for example NHL schedule-only) and
            # an unknown league are both not attempted. They remain unresolved
            # in the audit, while only an attempted supported feed can fail a
            # pipeline run and trigger its retry policy.
            reason = "RESULT_SOURCE_UNSUPPORTED"
            coverage_status[f"{sport}/{league}"] = {
                "provider": None,
                "status": "UNSUPPORTED",
                "fetch_status": "NOT_ATTEMPTED",
                "coverage": declared_coverage,
                "coverage_reason": (coverage_label or "No declared result source coverage"),
                "games": 0,
                "snapshots": len(league_snaps),
                "matched_snapshots": 0,
                "unique_matches": 0,
                "settled_snapshots": 0,
                "unmatched_snapshots": len(league_snaps),
                "errors": [],
                "settlement_status_counts": {},
                "unmatched_reason_counts": {reason: len(league_snaps)},
            }
            unresolved += len(league_snaps)
            for snap in league_snaps:
                _record_unmatched(unmatched_observations, snap, sport, league, reason,
                                  None, [], unmatched_reason_counts)
            continue

        target_dates = ({(datetime.strptime(date_filter, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d") for n in (-1, 0, 1)}
                        if date_filter else set())
        if not date_filter:
            for snap in league_snaps:
                start = parse_aware_time(snap.get("event_start") or snap.get("start_time_utc"))
                if start:
                    # Adjacent UTC dates cover local-league schedules crossing UTC midnight.
                    target_dates.update((start + timedelta(days=n)).strftime("%Y-%m-%d") for n in (-1, 0, 1))
        fetched = []
        fetch_errors = []
        for target_date in sorted(d for d in target_dates if d):
            try:
                if hasattr(engine, "fetch_results"):
                    source_ids = [str(s.get("source_game_id") or s.get("source_event_id") or s.get("provider_event_id"))
                                  for s in league_snaps
                                  if _snapshot_local_date(s) == target_date
                                  and (s.get("source_game_id") or s.get("source_event_id") or s.get("provider_event_id"))]
                    if sport == "baseball" and league == "CPBL" and source_ids:
                        fetched.extend(engine.fetch_results(sport, league, target_date, source_ids=source_ids))
                    elif sport == "baseball" and league == "CPBL" and any(
                        s.get("source_game_id") or s.get("source_event_id") or s.get("provider_event_id") for s in league_snaps
                    ):
                        continue
                    else:
                        fetched.extend(engine.fetch_results(sport, league, target_date))
                elif sport == "baseball" and league == "MLB":
                    fetched.extend(engine.fetch_mlb_completed_games(target_date).values())
                else:
                    fetch_errors.append("provider unavailable")
            except Exception as exc:
                fetch_errors.append(str(exc))
                logger.warning("Result fetch failed for %s/%s %s: %s", sport, league, target_date, exc)
        game_count += len(fetched)
        unique_result_event_keys = set()
        coverage_status[f"{sport}/{league}"] = {
            "provider": (fetched[0].get("provider") if fetched else None),
            "status": "FETCH_ERROR" if fetch_errors else "AVAILABLE" if fetched else "NO_RESULTS_AVAILABLE",
            "fetch_status": "FETCH_ERROR" if fetch_errors else "RESULTS_AVAILABLE" if fetched else "NO_RESULTS_AVAILABLE",
            "games": len(fetched),
            "snapshots": len(league_snaps), "matched_snapshots": 0, "unique_matches": 0, "settled_snapshots": 0,
            "unmatched_snapshots": 0,
            "errors": fetch_errors, "settlement_status_counts": {},
        }
        for snap in league_snaps:
            reason = None
            matched_game = None
            if not fetched:
                unresolved += 1
                reason = "NO_RESULTS_AVAILABLE" if not fetch_errors else "RESULT_FETCH_FAILED"
                coverage_status[f"{sport}/{league}"]["unmatched_snapshots"] += 1
                _record_unmatched(unmatched_observations, snap, sport, league, reason, None, fetch_errors, unmatched_reason_counts)
                continue
            game = engine.match_result_game(snap, fetched) if hasattr(engine, "match_result_game") else None
            if not game and sport == "baseball" and league == "MLB" and hasattr(engine, "match_mlb_game"):
                legacy_games = {str(g.get("game_pk") or i): g for i, g in enumerate(fetched)}
                game = engine.match_mlb_game(snap, legacy_games)
            if not game:
                unresolved += 1
                coverage_status[f"{sport}/{league}"]["unmatched_snapshots"] += 1
                _record_unmatched(unmatched_observations, snap, sport, league, "NO_UNIQUE_RESULT_MATCH", None, [], unmatched_reason_counts,
                                  candidate_games=fetched)
                continue
            matched_game = game
            league_coverage = coverage_status[f"{sport}/{league}"]
            league_coverage["matched_snapshots"] += 1
            result_event_key = str(game.get("provider_event_id") or game.get("event_id") or game.get("game_pk")
                                   or (game.get("start_time_utc"), game.get("away_team"), game.get("home_team"),
                                       game.get("away_score"), game.get("home_score")))
            if result_event_key not in unique_result_event_keys:
                unique_result_event_keys.add(result_event_key)
                league_coverage["unique_matches"] += 1
            if "status" not in game:
                # The legacy MLB feed/test double uses game_status; normalize
                # it through the same final gate as all newer result adapters.
                game = dict(game)
                game["status"] = "FINAL" if game.get("game_status") in {"Final", "Completed", "Game Over"} else "PENDING"
                game.setdefault("provider", "MLB_STATS_API")
                game.setdefault("sport", sport)
                game.setdefault("league", league)
                if not game.get("final_score") and game.get("away_score") is not None and game.get("home_score") is not None:
                    game["final_score"] = f"{game['away_score']}:{game['home_score']}"

            provider = str(game.get("provider") or game.get("source") or "UNKNOWN_RESULT_SOURCE")
            source_url = game.get("source_url")
            if game.get("status") in {"PENDING", "VOID", "UNRESOLVED"}:
                status = game["status"]
                coverage_status[f"{sport}/{league}"]["settlement_status_counts"][status] = coverage_status[f"{sport}/{league}"]["settlement_status_counts"].get(status, 0) + 1
                reason = game.get("unresolved_reason") or status
                if game.get("provider_status"):
                    reason = f"{reason}; provider_status={game['provider_status']}"
                if game.get("source_url"):
                    reason = f"{reason}; source={game['source_url']}"
                engine.settle_single_prediction_direct(
                    snapshot_id=snap.get("snapshot_id"), actual_outcome=None,
                    settlement_status=status, settlement_reason=reason,
                    final_score=game.get("final_score"), result_source=provider,
                )
                unresolved += status in {"PENDING", "UNRESOLVED"}
                settled += status == "VOID"
                if status in {"PENDING", "UNRESOLVED"}:
                    coverage_status[f"{sport}/{league}"]["unmatched_snapshots"] += 1
                    _record_unmatched(unmatched_observations, snap, sport, league, f"RESULT_{status}", game, [], unmatched_reason_counts)
                else:
                    coverage_status[f"{sport}/{league}"]["settled_snapshots"] += 1
                continue
            if game.get("status") != "FINAL" or game.get("away_score") is None or game.get("home_score") is None:
                unresolved += 1
                coverage_status[f"{sport}/{league}"]["unmatched_snapshots"] += 1
                _record_unmatched(unmatched_observations, snap, sport, league, "RESULT_NOT_FINAL_OR_SCORE_MISSING", game, [], unmatched_reason_counts)
                continue

            # A rule is selected from the snapshot's explicit sport/league.
            # Unknown leagues must never fall through to the old MLB default.
            from core.settlement.taiwan_rules import resolve_settlement_rule_id
            rule_id = resolve_settlement_rule_id(sport, league, str(snap.get("market") or ""))
            legacy_league_mismatch = (
                (sport == "baseball" and league in {"NPB", "CPBL", "KBO"} and rule_id.startswith("MLB_"))
                or (sport == "basketball" and league == "WNBA" and rule_id.startswith("NBA_"))
            )
            if legacy_league_mismatch:
                unresolved += 1
                coverage_status[f"{sport}/{league}"]["status"] = "RESULTS_AVAILABLE_RULE_MAPPING_REQUIRED"
                coverage_status[f"{sport}/{league}"]["unmatched_snapshots"] += 1
                _record_unmatched(unmatched_observations, snap, sport, league, "RULE_MAPPING_REQUIRED", game, [], unmatched_reason_counts)
                continue
            if rule_id in {"GENERIC_FULLGAME", "BASEBALL_FULLGAME_OTHER", "BASKETBALL_FULLGAME_OTHER", "NFL_FULLGAME_OTHER", "SOCCER_90MIN_OTHER"}:
                unresolved += 1
                coverage_status[f"{sport}/{league}"]["unmatched_snapshots"] += 1
                _record_unmatched(unmatched_observations, snap, sport, league, "SETTLEMENT_RULE_UNSUPPORTED", game, [], unmatched_reason_counts)
                continue

            event_start = snap.get("event_start") or snap.get("start_time_utc")
            closing_odds = None
            if snap.get("event_id") and event_start:
                closing_odds, _ = engine.odds_watcher.get_closing_odds(
                    event_id=str(snap["event_id"]), market=str(snap.get("market") or ""),
                    selection=str(snap.get("selection") or ""), event_start_iso=event_start,
                    line=snap.get("line"), canonical_event_id=snap.get("canonical_event_id"),
                    sport=snap.get("sport"), league=snap.get("league"),
                )
            close_source = "ODDS_WATCHER_LAST_PRESTART_OBSERVATION" if closing_odds is not None else None
            result = engine.evaluate_leg_settlement(
                market=snap.get("market", ""), selection=snap.get("selection", ""),
                line=snap.get("line"), away_score=game["away_score"], home_score=game["home_score"],
                side=snap.get("side", ""), game_status="Final", rule_id=rule_id,
                official_completion_status=game.get("official_completion_status"),
                innings_completed=game.get("innings_completed"),
                soccer_regulation_away=game.get("soccer_regulation_away"),
                soccer_regulation_home=game.get("soccer_regulation_home"),
            )
            status = result.status
            coverage_status[f"{sport}/{league}"]["settlement_status_counts"][status] = coverage_status[f"{sport}/{league}"]["settlement_status_counts"].get(status, 0) + 1
            settlement_reason = result.reason
            if game.get("provider_status"):
                settlement_reason = f"{settlement_reason}; provider_status={game['provider_status']}"
            if game.get("source_url"):
                settlement_reason = f"{settlement_reason}; source={game['source_url']}"
            engine.settle_single_prediction_direct(
                snapshot_id=snap.get("snapshot_id"), actual_outcome=True if status == "WON" else False if status == "LOST" else None,
                settlement_status=status, settlement_reason=settlement_reason,
                final_score=game.get("final_score"), result_source=provider,
                closing_odds=closing_odds, closing_odds_source=close_source,
            )
            settled += status in {"WON", "LOST", "PUSH", "VOID"}
            unresolved += status in {"PENDING", "UNRESOLVED", "SETTLEMENT_NOT_SUPPORTED"}
            if status in {"WON", "LOST", "PUSH", "VOID"}:
                coverage_status[f"{sport}/{league}"]["settled_snapshots"] += 1
            else:
                coverage_status[f"{sport}/{league}"]["unmatched_snapshots"] += 1
                _record_unmatched(unmatched_observations, snap, sport, league,
                                  status or "SETTLEMENT_UNRESOLVED", matched_game, [], unmatched_reason_counts)
    for key, count in deferred_counts.items():
        coverage = coverage_status.setdefault(key, {"provider": None, "status": "NOT_DUE",
            "fetch_status": "NOT_ATTEMPTED", "games": 0, "snapshots": 0, "matched_snapshots": 0,
            "unique_matches": 0, "settled_snapshots": 0, "unmatched_snapshots": 0,
            "errors": [], "settlement_status_counts": {}})
        coverage["snapshots"] += count
        coverage["deferred_snapshots"] = count
    for key, coverage in coverage_status.items():
        coverage["unmatched_reason_counts"] = dict(unmatched_reason_counts.get(key, {}))
    return {"settled": settled, "unresolved": unresolved, "games": game_count,
            "coverage": coverage_status, "unmatched_observations": unmatched_observations,
            "deferred_snapshots": sum(deferred_counts.values()), "deferred_observations": deferred_observations,
            "unmatched_observations_sampled": len(unmatched_observations),
            "unmatched_observations_truncated": sum(unmatched_reason_counts.get(k, {}).get(reason, 0)
                                                       for k in unmatched_reason_counts
                                                       for reason in unmatched_reason_counts[k]) > len(unmatched_observations),
            "unmatched_observation_sample_limit": MAX_UNMATCHED_AUDIT_SAMPLES}


def _exact_team_canonical_id(name, sport, league):
    """Resolve an audit identity only from an exact registered key, never a substring."""
    cleaned = str(name or "").strip().casefold()
    if not cleaned:
        return None
    from core.identity.team_alias import GLOBAL_TEAM_REGISTRY
    matches = set()
    for team in GLOBAL_TEAM_REGISTRY._teams.values():
        if sport and team.sport != sport:
            continue
        if sport != "soccer" and league and team.league != league:
            continue
        keys = {
            str(team.canonical_id).casefold(), str(team.abbreviation).casefold(),
            str(team.display_name_en).casefold(), str(team.display_name_zh).casefold(),
            str(team.short_name_zh).casefold(), *(str(value).casefold() for value in team.aliases),
        }
        if cleaned in keys:
            matches.add(team.canonical_id)
    return next(iter(matches)) if len(matches) == 1 else None


def _candidate_result_diagnostics(snapshot, games, *, limit=3):
    """Return a bounded, diagnostic-only comparison; never participates in matching."""
    start = parse_aware_time(snapshot.get("event_start") or snapshot.get("start_time_utc"))
    source_id = str(snapshot.get("source_game_id") or snapshot.get("source_event_id")
                    or snapshot.get("provider_event_id") or snapshot.get("game_pk") or "")
    away, home = str(snapshot.get("away_team") or ""), str(snapshot.get("home_team") or "")
    sport, league = str(snapshot.get("sport") or ""), str(snapshot.get("league") or "")
    source_away_id = _exact_team_canonical_id(away, sport, league)
    source_home_id = _exact_team_canonical_id(home, sport, league)
    candidates = []
    for candidate in games:
        candidate_start = parse_aware_time(candidate.get("start_time_utc"))
        signed_delta = (candidate_start - start).total_seconds() if start and candidate_start else None
        delta = abs(signed_delta) if signed_delta is not None else None
        away_result_identity = str(candidate.get("away_team") or "")
        home_result_identity = str(candidate.get("home_team") or "")
        away_result = str(candidate.get("away_team_source_name") or away_result_identity)
        home_result = str(candidate.get("home_team_source_name") or home_result_identity)
        away_exact = bool(away and away_result and away.casefold() == away_result.casefold())
        home_exact = bool(home and home_result and home.casefold() == home_result.casefold())
        provider_id = str(candidate.get("provider_event_id") or candidate.get("event_id")
                           or candidate.get("game_pk") or "")
        provider_away_id = (_exact_team_canonical_id(away_result_identity, sport, league)
                            or _exact_team_canonical_id(away_result, sport, league))
        provider_home_id = (_exact_team_canonical_id(home_result_identity, sport, league)
                            or _exact_team_canonical_id(home_result, sport, league))
        away_canonical_match = bool(source_away_id and source_away_id == provider_away_id)
        home_canonical_match = bool(source_home_id and source_home_id == provider_home_id)
        candidates.append((
            (delta is None, delta if delta is not None else float("inf"),
             -(away_canonical_match + home_canonical_match), -(away_exact + home_exact), provider_id),
            {
                "provider_event_id": provider_id or None,
                "provider_away_team_id": candidate.get("away_provider_team_id"),
                "provider_home_team_id": candidate.get("home_provider_team_id"),
                "provider_away_team_canonical_id": provider_away_id,
                "provider_home_team_canonical_id": provider_home_id,
                "provider_away_team": away_result or None,
                "provider_home_team": home_result or None,
                "provider_start_time_utc": candidate.get("start_time_utc"),
                "provider_start_delta_seconds": signed_delta,
                "absolute_start_delta_seconds": delta,
                "provider_status": candidate.get("provider_status") or candidate.get("status"),
                "provider_away_score": candidate.get("away_score"),
                "provider_home_score": candidate.get("home_score"),
                "source_event_id_equal": bool(source_id and source_id == provider_id),
                "away_raw_name_exact": away_exact,
                "home_raw_name_exact": home_exact,
                "away_canonical_id_equal": away_canonical_match,
                "home_canonical_id_equal": home_canonical_match,
                "diagnostic_only": True,
            },
        ))
    candidates.sort(key=lambda row: row[0])
    return [row[1] for row in candidates[:max(0, int(limit))]]


def _record_unmatched(rows, snapshot, sport, league, reason, game, fetch_errors, reason_counts,
                      *, candidate_games=None):
    key = f"{sport or 'unknown'}/{league or 'unknown'}"
    bucket = reason_counts.setdefault(key, {})
    bucket[reason] = bucket.get(reason, 0) + 1
    if len(rows) >= MAX_UNMATCHED_AUDIT_SAMPLES:
        return
    row = {
        "snapshot_id": snapshot.get("snapshot_id"), "sport": sport, "league": league,
        "source_game_id": snapshot.get("source_game_id") or snapshot.get("source_event_id") or snapshot.get("provider_event_id"),
        "canonical_event_id": snapshot.get("canonical_event_id"),
        "event_start": snapshot.get("event_start") or snapshot.get("start_time_utc"),
        "away_team": snapshot.get("away_team"), "home_team": snapshot.get("home_team"),
        "away_team_canonical_id": _exact_team_canonical_id(snapshot.get("away_team"), sport, league),
        "home_team_canonical_id": _exact_team_canonical_id(snapshot.get("home_team"), sport, league),
        "reason": reason, "provider": (game or {}).get("provider") if game else None,
        "provider_event_id": (game or {}).get("provider_event_id") or (game or {}).get("event_id") if game else None,
        "source_url": (game or {}).get("source_url") if game else None,
        "fetch_errors": list(fetch_errors or []),
    }
    if candidate_games:
        row["candidate_result_comparisons"] = _candidate_result_diagnostics(snapshot, candidate_games)
        row["candidate_comparison_scope"] = "nearest provider starts and exact raw team/event-id comparisons; diagnostic only"
    rows.append(row)


def write_settlement_audit_report(result, output_path: Path) -> Path:
    """Write an additive audit artifact without rewriting snapshot or settlement data."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), **result}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_settlement(date_filter: str | None = None):
    print("=" * 65)
    print("⚖️ 執行影子評估結果結算 (SHADOW RESULT SETTLEMENT)")
    print("=" * 65)

    engine = SettlementEngine()
    snap_logger = PredictionSnapshotLogger()
    portfolio = ShadowPortfolioManager()

    print("賽果來源覆蓋 (來源 availability 不代表玩法結算規則可用):")
    for league, info in engine.supported_result_coverage().items():
        print(f"  • {league}: {info['coverage']} [{info['provider']}]")

    snapshots = snap_logger.get_all_snapshots()
    unsettled = [s for s in snapshots if not s.get("is_settled")]
    print(f"歷史快照總數: {len(snapshots)} 筆 | 待結算快照: {len(unsettled)} 筆")

    print(f"結算目標日期: {date_filter or '依各賽事歷史日期'}")
    outcome_counts = settle_snapshot_results(engine, snapshots, date_filter)
    settled_snaps = outcome_counts["settled"]
    print(f"已取得結果來源場次: {outcome_counts['games']} 場 | 待處理/無法唯一匹配: {outcome_counts['unresolved']} 筆")
    for league, info in outcome_counts.get("coverage", {}).items():
        print(f"  • {league}: 抓取={info.get('fetch_status', info['status'])}，provider={info.get('provider') or '未涵蓋'}，賽果場次={info['games']}，匹配快照={info.get('matched_snapshots', 0)}，唯一賽事={info['unique_matches']}，已結算={info['settled_snapshots']}，未配對/待處理={info['unmatched_snapshots']}，結算狀態={info.get('settlement_status_counts', {})}，未配對原因={info.get('unmatched_reason_counts', {})}")
    audit_path = write_settlement_audit_report(
        outcome_counts,
        PROJECT_ROOT / "reports" / "settlement_audits" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json",
    )
    print(f"結算配對稽核：{audit_path}")

    # Settle parlays and shadow tickets
    parlay_res = engine.settle_parlays_against_snapshots()

    print("\n-------------------------------------------------------")
    print("結算成果統計:")
    print(f"  • 單場預測快照已結算: {settled_snaps} 筆")
    print(f"  • 候選串關單已結算:   {parlay_res['settled_parlay_candidates']} 組")
    print(f"  • 影子錢包注單已結算: {parlay_res['settled_shadow_tickets']} 張")
    print("-------------------------------------------------------")

    summary = portfolio.get_portfolio_summary()
    print(f"影子錢包最新狀態:")
    print(f"  總下注額: NT$ {summary['total_virtual_staked']:.2f}")
    print(f"  總獲賠額: NT$ {summary['total_virtual_payout']:.2f}")
    print(f"  淨獲利:   NT$ {summary['net_pl']:+.2f} (ROI: {summary['roi_pct']:+.2f}%, N = {summary['settled_tickets']})")
    if summary["is_insufficient_sample"]:
        print("  ⚠️ 警告: 樣本數 N < 30 (INSUFFICIENT_SAMPLE)，不得據此調參！")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Settle shadow predictions")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD")
    args = parser.parse_args()
    run_settlement(args.date)
