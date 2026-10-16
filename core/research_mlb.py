"""Official MLB warmup and reconciliation separated from orchestration."""
from __future__ import annotations
import hashlib
import json
import os
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Any
from core.bet_validation import parse_aware_time


def _mlb_game_is_cancelled(game):
    status = game.get("status") or {}
    return (str(status.get("codedGameState") or "").upper() == "C"
            and str(status.get("detailedState") or "").casefold() in {"cancelled", "canceled"})


def _contiguous_schedule_coverage(ledger, beginning, through):
    """Only actual successful query intervals can bridge the coverage cursor."""
    cursor = beginning - timedelta(days=1)
    intervals = []
    for row in ledger.get("query_ranges", []):
        try:
            first, last = date.fromisoformat(row['start_date']), date.fromisoformat(row['end_date'])
        except (KeyError, ValueError, TypeError):
            continue
        if first <= last:
            intervals.append((first,min(last,through)))
    for first, last in sorted(intervals):
        if first > cursor + timedelta(days=1):
            break
        cursor = max(cursor,last)
    return cursor


class MLBResearchMixin:
    def _stage_model_update(self, stage_data: Path) -> dict[str, Any]:
        from core.research_pipeline import (_read_json, _write_json_atomic, _mlb_game_date,
            _mlb_game_is_final, _mlb_game_is_regular_or_postseason, _mlb_needs_live_reconciliation,
            _mlb_normalize_live_feed, _mlb_reschedule_target_date)
        settings = self.config.get("model_update", {}) or {}
        state_path = self.data_root / "model_state" / "live_mlb_elo.json"
        progress_path = self.data_root / "model_state" / "live_mlb_elo_fetch_coverage.json"
        if not settings.get("enabled", False):
            result = {"status": "SKIPPED", "reason": "model_update.enabled is false"}
            _write_json_atomic(stage_data / "model_update.json", result)
            return {"_stage_status": "SKIPPED", **result}
        from integrations.models.external.live_mlb_elo import LiveMLBEloAdapter
        ledger_path = self.data_root / "model_state" / "mlb_official_schedule_ledger.json"
        ledger = _read_json(ledger_path, {}) if self._model_updater is None else {}
        if self._model_updater is None and not (
            isinstance(ledger, dict) and ledger.get("schema") == "mlb-official-ledger-v1"
            and isinstance(ledger.get("games"), dict)
        ):
            # Imported checkpoints do not carry the complete raw game ledger
            # needed for safe delayed-result replay. Preserve one read-only
            # backup, then rebuild the isolated state from an explicit neutral
            # prior while the official ledger is accumulated.
            if state_path.exists():
                backup_path = state_path.with_name("live_mlb_elo.pre_ledger_backup.json")
                if not backup_path.exists():
                    _write_json_atomic(backup_path, _read_json(state_path, {}))
            if settings.get("bootstrap_initialization") != "neutral_1500_official_warmup":
                result = {"status": "REBUILD_REQUIRED", "reason": "checkpoint lacks a complete official game ledger; neutral warmup is required before use"}
                _write_json_atomic(stage_data / "model_update.json", result)
                return {"_stage_status": "SKIPPED", **result}
            from integrations.models.external.live_mlb_elo import DEFAULT_MLB_ELO, STATE_SCHEMA_VERSION
            state_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(state_path, {
                "schema_version": STATE_SCHEMA_VERSION, "ratings": dict(DEFAULT_MLB_ELO),
                "history_count": 0, "history": [], "processed_game_pks": [],
                "last_update": None, "source": "Neutral 1500 initialization; official-ledger rebuild in progress",
                "data_as_of": None,
            })
            ledger = {"schema": "mlb-official-ledger-v1", "source": "MLB Stats API schedule endpoint",
                      "bootstrap_start_date": str(settings.get("bootstrap_start_date") or ""),
                      "games": {}, "queried_through": None, "created_at_utc": self._current_utc().isoformat()}
            _write_json_atomic(ledger_path, ledger)
            _write_json_atomic(progress_path, {"source": "MLB Stats API schedule endpoint",
                                               "official_schedule_queried_through": None,
                                               "pending_game_dates": [], "held_final_games": [],
                                               "late_final_games": [], "bootstrap_complete": False})
        if not state_path.exists():
            # Explicitly initialize a research prior, with no invented result or
            # model-data watermark. Official query coverage is tracked separately.
            if settings.get("bootstrap_initialization") != "neutral_1500_official_warmup":
                result = {"status": "UNAVAILABLE", "reason": "No initialized Elo checkpoint or configured neutral warmup."}
                _write_json_atomic(stage_data / "model_update.json", result)
                return {"_stage_status": "SKIPPED", **result}
            from integrations.models.external.live_mlb_elo import DEFAULT_MLB_ELO, STATE_SCHEMA_VERSION
            state_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(state_path, {
                "schema_version": STATE_SCHEMA_VERSION,
                "ratings": dict(DEFAULT_MLB_ELO),
                "history_count": 0,
                "history": [],
                "processed_game_pks": [],
                "last_update": None,
                "source": "Neutral 1500 initialization; awaiting official MLB Stats API warmup",
                "data_as_of": None,
            })
        adapter = LiveMLBEloAdapter(state_file=state_path)
        bootstrap = str(adapter.source or "").startswith("Neutral 1500 initialization")
        if adapter._load_error or not adapter._has_state or (not bootstrap and not adapter.data_as_of):
            raise RuntimeError("Isolated Elo state is invalid or missing data_as_of; refusing overwrite.")
        if bootstrap:
            bootstrap_date = settings.get("bootstrap_start_date")
            if not bootstrap_date or settings.get("bootstrap_initialization") != "neutral_1500_official_warmup":
                result = {"status": "UNAVAILABLE", "reason": "No initialized checkpoint and no explicit neutral warmup protocol."}
                _write_json_atomic(stage_data / "model_update.json", result)
                return {"_stage_status": "SKIPPED", **result}
            start_date = date.fromisoformat(str(bootstrap_date))
        else:
            watermark = parse_aware_time(adapter.data_as_of)
            if watermark is None:
                raise RuntimeError("Elo checkpoint data_as_of is not a timezone-aware timestamp.")
            start_date = watermark.date() + timedelta(days=1)
        # This cursor means only that the official schedule endpoint was queried
        # successfully through a date. It is deliberately separate from the Elo
        # result watermark, which advances only when an official final is applied.
        progress = _read_json(progress_path, {})
        if not isinstance(progress, dict):
            progress = {}
        coverage_cursor = progress.get("official_schedule_queried_through")
        if self._model_updater is None:
            coverage_beginning = date.fromisoformat(str(ledger.get("bootstrap_start_date") or settings["bootstrap_start_date"]))
            contiguous = _contiguous_schedule_coverage(ledger, coverage_beginning,
                self.clock().astimezone(timezone.utc).date() - timedelta(days=1))
            coverage_cursor = contiguous.isoformat() if contiguous >= coverage_beginning else None
            start_date = contiguous + timedelta(days=1)
        elif coverage_cursor:
            queried = date.fromisoformat(coverage_cursor)
            start_date = max(start_date, queried + timedelta(days=1))
        # Only request completed UTC dates and cap each run to a bounded range;
        # subsequent runs advance solely from the saved official data_as_of.
        completed_through = self.clock().astimezone(timezone.utc).date() - timedelta(days=1)
        regular_days = max(1, int(settings.get("max_days_per_update", 7)))
        catchup = not progress.get("bootstrap_complete", False) or (completed_through - start_date).days >= regular_days
        max_days = max(regular_days, min(90, int(settings.get("warmup_max_days_per_update", 90)))) if catchup else regular_days
        end_date = min(completed_through, start_date + timedelta(days=max_days - 1))
        pending_dates = {date.fromisoformat(value) for value in progress.get("pending_game_dates", [])
                         if isinstance(value, str)}
        held_final_games = progress.get("held_final_games", [])
        if not isinstance(held_final_games, list):
            held_final_games = []
        late_final_games = progress.get("late_final_games", [])
        if not isinstance(late_final_games, list):
            late_final_games = []
        result: dict[str, Any]
        result_reconciliation: dict[str, Any] = {"status": "NOT_RUN", "candidate_count": 0,
                                                  "request_limit": max(0, int(settings.get("max_reschedule_live_feed_fetches_per_run", 20))),
                                                  "attempted_count": 0, "reconciled_game_ids": [],
                                                  "deferred_game_ids": [], "errors": []}
        pending_date_diagnostics: list[dict[str, Any]] = []
        queried_through = coverage_cursor
        pending_after: set[date]
        held_after: list[dict[str, Any]]
        if self._model_updater is not None:
            # Test/host integrations may provide their own bounded official
            # update implementation. Cursor advances only when the call returns.
            result = dict(self._model_updater(data_root=self.data_root, state_path=state_path,
                                              start_date=start_date, end_date=end_date,
                                              pending_game_dates=sorted(pending_dates)) or {})
            pending_after = set()
            for value in result.get("pending_game_dates", []):
                try:
                    pending_after.add(date.fromisoformat(str(value)))
                except ValueError:
                    continue
            held_after = held_final_games
            if start_date <= end_date:
                queried_through = end_date.isoformat()
        elif start_date <= end_date or any(value <= completed_through for value in pending_dates):
            from scripts.update_mlb_elo import MLBStatsApiClient, SOURCE
            client = MLBStatsApiClient()
            fetched_by_date: dict[date, list[dict[str, Any]]] = {}
            request_audit: list[dict[str, Any]] = []
            if start_date <= end_date:
                for game in client.fetch_games(start_date, end_date):
                    game_date = _mlb_game_date(game)
                    if game_date:
                        fetched_by_date.setdefault(game_date, []).append(game)
                queried_through = max(date.fromisoformat(coverage_cursor), end_date).isoformat() if coverage_cursor else end_date.isoformat()
                request_audit.append({"start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
                                      "source_url": "https://statsapi.mlb.com/api/v1/schedule", "sport_id": 1,
                                      "hydrate": "linescore", "fetched_at_utc": self._current_utc().isoformat()})
            for pending_date in sorted(pending_dates):
                if pending_date > completed_through or start_date <= pending_date <= end_date:
                    continue
                for game in client.fetch_games(pending_date, pending_date):
                    game_date = _mlb_game_date(game)
                    if game_date:
                        fetched_by_date.setdefault(game_date, []).append(game)
                request_audit.append({"start_date": pending_date.isoformat(), "end_date": pending_date.isoformat(),
                                      "reason": "pending_game_recheck",
                                      "source_url": "https://statsapi.mlb.com/api/v1/schedule", "sport_id": 1,
                                      "hydrate": "linescore", "fetched_at_utc": self._current_utc().isoformat()})

            fetched = {}
            for day_games in fetched_by_date.values():
                for game in day_games:
                    game_id = str(game.get("gamePk") or "")
                    if game_id:
                        fetched[game_id] = game
            schedule_fetched = dict(fetched)
            # Persist every source observation (including pending and excluded
            # game types) before rating updates. A delayed final can therefore
            # be replayed from the real source record instead of being skipped.
            if self._model_updater is None and isinstance(ledger, dict):
                ledger_games = dict(ledger.get("games") or {})
                reconciliation_records = dict(ledger.get("reschedule_reconciliations") or {})
                # Recheck explicit reschedules through the per-game live feed.
                # Schedule responses can keep returning a postponed stub even
                # after the same gamePk has a completed official live record.
                candidates: dict[str, dict[str, Any]] = {}
                for game_id, game in {**ledger_games, **fetched}.items():
                    if _mlb_needs_live_reconciliation(game, completed_through):
                        candidates[game_id] = game
                per_run_limit = max(0, int(settings.get("max_reschedule_live_feed_fetches_per_run", 20)))
                reconciliation_errors: list[dict[str, str]] = []
                reconciled_game_ids: list[str] = []
                deferred_reconciliation_ids: list[str] = []
                attempted = 0
                fetch_live = getattr(client, "fetch_live_game", None)
                for game_id, schedule_game in sorted(
                    candidates.items(), key=lambda item: (_mlb_reschedule_target_date(item[1]) or date.max, item[0])
                ):
                    if attempted >= per_run_limit:
                        deferred_reconciliation_ids.append(game_id)
                        continue
                    attempted += 1
                    if not callable(fetch_live):
                        reconciliation_errors.append({"game_pk": game_id, "error": "MLB client does not expose fetch_live_game"})
                        continue
                    try:
                        live_observation = fetch_live(game_id)
                        if not isinstance(live_observation, dict) or not isinstance(live_observation.get("payload"), dict):
                            raise ValueError("live feed response wrapper/payload is invalid")
                        live_payload = live_observation["payload"]
                        observed_at = str(live_observation.get("fetched_at_utc") or self._current_utc().isoformat())
                        normalized = _mlb_normalize_live_feed(live_payload, schedule_game, observed_at_utc=observed_at)
                        schedule_start_date = _mlb_game_date(schedule_game)
                        schedule_audit = next((row for row in reversed(request_audit)
                                               if schedule_start_date and
                                               date.fromisoformat(row["start_date"]) <= schedule_start_date <= date.fromisoformat(row["end_date"])), None)
                        schedule_params = {
                            "sportId": 1,
                            "startDate": schedule_audit["start_date"] if schedule_audit else (schedule_start_date.isoformat() if schedule_start_date else ""),
                            "endDate": schedule_audit["end_date"] if schedule_audit else (schedule_start_date.isoformat() if schedule_start_date else ""),
                            "hydrate": "linescore",
                        }
                        from urllib.parse import urlencode
                        schedule_source_url = "https://statsapi.mlb.com/api/v1/schedule?" + urlencode(schedule_params)
                        schedule_observed_at = str((schedule_audit or {}).get("fetched_at_utc") or self._current_utc().isoformat())
                        schedule_record_sha256 = hashlib.sha256(json.dumps(
                            schedule_game, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                        ).encode("utf-8")).hexdigest()
                        live_payload_sha256 = str(live_observation.get("sha256") or hashlib.sha256(json.dumps(
                            live_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                        ).encode("utf-8")).hexdigest())
                        live_source_url = str(live_observation.get("source_url") or
                                              f"https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live")
                        normalized["_source_observation"].update({
                            "schedule_record_sha256": schedule_record_sha256,
                            "schedule_source_url": schedule_source_url,
                            "schedule_observed_at_utc": schedule_observed_at,
                            "live_feed_sha256": live_payload_sha256,
                            "live_feed_source_url": live_source_url,
                            "live_feed_observed_at_utc": observed_at,
                        })
                        fetched[game_id] = normalized
                        reconciliation_records[game_id] = {
                            "schedule_game_record": schedule_game,
                            "schedule_record_sha256": schedule_record_sha256,
                            "schedule_source_url": schedule_source_url,
                            "schedule_observed_at_utc": schedule_observed_at,
                            "live_feed_source_url": live_source_url,
                            "live_feed_observed_at_utc": observed_at,
                            "live_feed_sha256": live_payload_sha256,
                            "normalized_game_date": normalized["gameDate"],
                            "normalized_away_team_id": normalized["teams"]["away"]["team"]["id"],
                            "normalized_home_team_id": normalized["teams"]["home"]["team"]["id"],
                            "final_score": f"{normalized['teams']['home']['score']}:{normalized['teams']['away']['score']}",
                            "final_score_order": "home:away",
                        }
                        reconciled_game_ids.append(game_id)
                    except Exception as exc:
                        # Keep the official schedule stub unresolved and retry
                        # next run; a live-feed fault must not stop other model
                        # or source stages.
                        reconciliation_errors.append({"game_pk": game_id, "error": str(exc)})

                pending_event_ids: dict[date, set[str]] = {}
                for game_id, old_game in ledger_games.items():
                    old_date = _mlb_game_date(old_game)
                    if (old_date in pending_dates and _mlb_game_is_regular_or_postseason(old_game)
                            and not _mlb_game_is_final(old_game)):
                        pending_event_ids.setdefault(old_date, set()).add(str(game_id))
                ledger_games.update(fetched)
                range_audit = list(ledger.get("query_ranges") or []) + request_audit
                if request_audit:
                    range_audit[-1]["returned_event_count"] = len(schedule_fetched)
                    range_audit[-1]["returned_events_sha256"] = hashlib.sha256(json.dumps(
                        schedule_fetched, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")).hexdigest()
                ledger = {**ledger, "games": ledger_games,
                          "reschedule_reconciliations": reconciliation_records,
                          "query_ranges": range_audit,
                          "queried_through": queried_through or ledger.get("queried_through"),
                          "last_fetched_at_utc": self._current_utc().isoformat(),
                          "ledger_sha256": hashlib.sha256(json.dumps(
                              ledger_games, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                          ).encode("utf-8")).hexdigest()}
                contiguous = _contiguous_schedule_coverage(ledger, coverage_beginning, completed_through)
                queried_through = contiguous.isoformat() if contiguous >= coverage_beginning else None
                ledger["queried_through"] = queried_through
                _write_json_atomic(ledger_path, ledger)
                result_reconciliation = {
                    "status": "PARTIAL" if reconciliation_errors else "UPDATED" if reconciled_game_ids else "NO_CANDIDATES",
                    "candidate_count": len(candidates),
                    "request_limit": per_run_limit,
                    "attempted_count": attempted,
                    "reconciled_game_ids": reconciled_game_ids,
                    "deferred_game_ids": deferred_reconciliation_ids,
                    "errors": reconciliation_errors,
                }
            else:
                result_reconciliation = {"status": "SKIPPED", "reason": "custom model updater owns reconciliation"}
            # Recompute pending dates from the merged, gamePk-keyed ledger. The
            # raw schedule response can be empty or retain an old postponed
            # stub even after a per-game live feed has verified the final.
            # Empty dates remain unknown unless every previously unresolved
            # gamePk on that date was reconciled to a final moved event.
            pending_after = set()
            for pending_date in pending_dates:
                ledger_day_games = [
                    game for game in ledger_games.values()
                    if _mlb_game_date(game) == pending_date
                    and _mlb_game_is_regular_or_postseason(game)
                ]
                if ledger_day_games:
                    nonfinal_ids = sorted(str(game.get("gamePk") or "") for game in ledger_day_games
                                          if (not _mlb_game_is_final(game) and not _mlb_game_is_cancelled(game)))
                    if nonfinal_ids:
                        pending_after.add(pending_date)
                        pending_date_diagnostics.append({"date": pending_date.isoformat(),
                            "status": "PENDING_UNFINISHED_GAMES", "game_count": len(ledger_day_games),
                            "unresolved_game_pks": nonfinal_ids})
                    else:
                        pending_date_diagnostics.append({"date": pending_date.isoformat(),
                            "status": "CLEARED_ALL_GAMEPks_FINAL", "game_count": len(ledger_day_games),
                            "game_pks": sorted(str(game.get("gamePk") or "") for game in ledger_day_games)})
                    continue

                unresolved_ids = pending_event_ids.get(pending_date, set())
                moved_and_verified = bool(unresolved_ids) and all(
                    (game := ledger_games.get(game_id)) is not None
                    and _mlb_game_is_regular_or_postseason(game)
                    and _mlb_game_is_final(game)
                    and _mlb_game_date(game) != pending_date
                    and bool((reconciliation_records.get(game_id) or {}).get("live_feed_sha256"))
                    for game_id in unresolved_ids
                )
                if not moved_and_verified:
                    # No ledger row is not evidence that the schedule day had
                    # no games; retain the unresolved date for a later source
                    # recheck.
                    pending_after.add(pending_date)
                    pending_date_diagnostics.append({"date": pending_date.isoformat(),
                        "status": "PENDING_EMPTY_OR_UNVERIFIED_SOURCE", "game_count": 0,
                        "unresolved_game_pks": sorted(unresolved_ids)})
                else:
                    pending_date_diagnostics.append({"date": pending_date.isoformat(),
                        "status": "CLEARED_ALL_GAMEPks_LIVE_RECONCILED_MOVED_FINAL", "game_count": 0,
                        "game_pks": sorted(unresolved_ids)})
            # Every unresolved explicit reschedule remains in the warmup
            # watermark, including older ledger rows that were absent from a
            # recent schedule response or deferred by this run's fetch budget.
            reconciled_ids = set(reconciled_game_ids)
            for game_id, schedule_game in candidates.items():
                if game_id in reconciled_ids:
                    continue
                unresolved_date = _mlb_game_date(schedule_game)
                if unresolved_date is not None:
                    pending_after.add(unresolved_date)
            for day, day_games in fetched_by_date.items():
                for observed_game in day_games:
                    # A schedule stub must not undo a final verified above.
                    game = ledger_games.get(str(observed_game.get("gamePk") or ""), observed_game)
                    if _mlb_game_is_regular_or_postseason(game) and (not _mlb_game_is_final(game) and not _mlb_game_is_cancelled(game)):
                        effective_date = _mlb_game_date(game)
                        if effective_date is not None and effective_date <= completed_through:
                            pending_after.add(effective_date)
            finals = {game_id: game for game_id, game in fetched.items()
                      if _mlb_game_is_final(game) and _mlb_game_is_regular_or_postseason(game)}
            for game in held_final_games:
                game_id = str(game.get("gamePk") or "")
                if game_id and _mlb_game_is_regular_or_postseason(game):
                    finals.setdefault(game_id, game)
            earliest_pending = min(pending_after) if pending_after else None
            ordered_finals = sorted(finals.values(), key=lambda game: (game.get("gameDate", ""), str(game.get("gamePk", ""))))
            if earliest_pending:
                eligible = [game for game in ordered_finals
                            if (_mlb_game_date(game) or date.max) < earliest_pending]
                held_after = [game for game in ordered_finals
                              if (_mlb_game_date(game) or date.max) >= earliest_pending]
            else:
                eligible, held_after = ordered_finals, []

            watermark = parse_aware_time(adapter.data_as_of)
            late = ([game for game in eligible if (_mlb_game_date(game) or date.min) <= watermark.date()]
                    if watermark else [])
            if late and self._model_updater is None:
                # Rebuild into a sibling file from the complete queried source
                # ledger; only switch the live isolated state after replay and
                # validation succeed. No date mutation or processed-ID bypass.
                from integrations.models.external.live_mlb_elo import DEFAULT_MLB_ELO, STATE_SCHEMA_VERSION
                rebuild_path = state_path.with_name("live_mlb_elo.rebuild.tmp.json")
                _write_json_atomic(rebuild_path, {
                    "schema_version": STATE_SCHEMA_VERSION, "ratings": dict(DEFAULT_MLB_ELO),
                    "history_count": 0, "history": [], "processed_game_pks": [],
                    "last_update": None, "source": "Neutral 1500 initialization; official ledger replay",
                    "data_as_of": None,
                })
                rebuild = LiveMLBEloAdapter(state_file=rebuild_path)
                replay_games = [game for game in ledger.get("games", {}).values()
                                if _mlb_game_is_final(game) and _mlb_game_is_regular_or_postseason(game)
                                and (earliest_pending is None or (_mlb_game_date(game) or date.max) < earliest_pending)]
                replayed = rebuild.apply_official_games(replay_games, source=SOURCE)
                os.replace(rebuild_path, state_path)
                adapter = LiveMLBEloAdapter(state_file=state_path)
                late_final_games = []
                result = {**replayed, "replayed_from_complete_source_ledger": True,
                          "late_final_replayed_count": len(late), "held_final_count": len(held_after),
                          "excluded_non_regular_games": sum(1 for game in ledger.get("games", {}).values()
                              if _mlb_game_is_final(game) and not _mlb_game_is_regular_or_postseason(game))}
            else:
                applied = adapter.apply_official_games(eligible, source=SOURCE)
                result = {**applied, "held_final_count": len(held_after),
                          "late_final_requires_rebuild_count": 0,
                          "excluded_non_regular_games": sum(1 for game in fetched.values()
                              if _mlb_game_is_final(game) and not _mlb_game_is_regular_or_postseason(game))}
        else:
            result = {"updated_games": 0, "data_as_of": adapter.data_as_of,
                      "reason": "Checkpoint already covers through current UTC date."}
            pending_after, held_after = pending_dates, held_final_games

        result = dict(result or {})
        if self._model_updater is None:
            result["reschedule_reconciliation"] = result_reconciliation
            result["pending_date_diagnostics"] = pending_date_diagnostics
        if queried_through or pending_after or held_after or late_final_games:
            _write_json_atomic(progress_path, {
                "source": "MLB Stats API schedule endpoint",
                "official_schedule_queried_through": queried_through,
                "pending_game_dates": [value.isoformat() for value in sorted(pending_after)],
                "pending_game_ids": sorted(
                    str(game_id) for game_id, game in (ledger.get("games") or {}).items()
                    if _mlb_game_is_regular_or_postseason(game)
                    and (not _mlb_game_is_final(game) and not _mlb_game_is_cancelled(game))
                    and _mlb_game_date(game) in pending_after
                ) if isinstance(ledger, dict) else [],
                "held_final_games": held_after,
                "late_final_games": late_final_games[-100:],
                "updated_at_utc": self.clock().astimezone(timezone.utc).isoformat(),
                "bootstrap_complete": bool(queried_through and date.fromisoformat(queried_through) >= completed_through
                                           and not pending_after),
                "ledger_path": str(ledger_path) if self._model_updater is None else None,
                "ledger_sha256": ledger.get("ledger_sha256") if isinstance(ledger, dict) else None,
            })
        warmup_complete = bool(queried_through and date.fromisoformat(queried_through) >= completed_through
                               and not pending_after)
        result["status"] = ("LATE_FINAL_REQUIRES_REBUILD" if result.get("late_final_requires_rebuild_count")
                            else "WARMUP_IN_PROGRESS" if bootstrap and not warmup_complete
                            else "UPDATED" if result.get("updated_games", 0) else "NO_NEW_FINALS")
        result["official_ledger_complete_through_yesterday"] = warmup_complete
        result["cancelled_game_ids_excluded_from_elo"] = [str(key) for key, game in ledger.get("games", {}).items()
                                                          if _mlb_game_is_cancelled(game)]
        if state_path.exists() and self._model_updater is None:
            published_state = _read_json(state_path, {})
            published_state["official_schedule_coverage"] = {
                "complete_through_yesterday":warmup_complete, "queried_through":queried_through,
                "pending_game_dates":[day.isoformat() for day in sorted(pending_after)],
                "observed_at_utc":self._current_utc().isoformat()}
            _write_json_atomic(state_path, published_state)
        result["initialization_mode"] = "neutral_1500_official_warmup" if bootstrap else "incremental_official_results"
        result["official_schedule_queried_through"] = queried_through
        result["pending_game_dates"] = [value.isoformat() for value in sorted(pending_after)]
        result["incomplete_final_game_ids"] = [str(game.get("gamePk")) for game in ledger.get("games", {}).values()
            if _mlb_game_is_regular_or_postseason(game)
            and (game.get("status", {}).get("abstractGameState") == "Final" or game.get("status", {}).get("codedGameState") == "F")
            and (not _mlb_game_is_final(game) and not _mlb_game_is_cancelled(game))]
        result["start_date"] = start_date.isoformat()
        result["end_date"] = end_date.isoformat()
        _write_json_atomic(stage_data / "model_update.json", result)
        registry = getattr(self._signal_hub, "model_registry", None)
        if hasattr(registry, "refresh"):
            registry.refresh()
        return result
