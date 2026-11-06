"""Bounded official/public final-result updates for the isolated Elo research models."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from core.bet_validation import parse_aware_time
from core.research_helpers import _read_json, _write_json_atomic


RESULT_PROVIDERS = {
    "NBA": "ESPN_PUBLIC_SCOREBOARD",
    "NFL": "ESPN_PUBLIC_SCOREBOARD",
    "CPBL": "CPBL_STATS_OFFICIAL",
    "NPB": "NPB_OFFICIAL",
    "KBO": "KBO_OFFICIAL",
}
MODEL_LEAGUES = {
    "nba_elo_engine": ("NBA",),
    "nfl_elo_model": ("NFL",),
    "asian_baseball_model": ("CPBL", "NPB", "KBO"),
}
MODEL_CLASSES = {
    "nba_elo_engine": "integrations.models.external.nba_elo_engine.NBAEloEngine",
    "nfl_elo_model": "integrations.models.external.nfl_elo_model.NFLEloModel",
    "asian_baseball_model": "integrations.models.external.asian_baseball_model.AsianBaseballModel",
}
LEAGUE_TIMEZONES = {
    "NBA": "America/New_York", "NFL": "America/New_York",
    "CPBL": "Asia/Taipei", "NPB": "Asia/Tokyo", "KBO": "Asia/Seoul",
}


def _class_for(model_id: str):
    module_name, class_name = MODEL_CLASSES[model_id].rsplit(".", 1)
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)


def _result_value(game: Any, name: str, default=None):
    if isinstance(game, dict):
        return game.get(name, default)
    return getattr(game, name, default)


def _team_key(model_id: str, league: str, name: str) -> str | None:
    if model_id == "nba_elo_engine":
        from integrations.models.external.nba_elo_engine import BASE_NBA_ELO, _resolve_nba_team
        team = _resolve_nba_team(name)
        return team.canonical_id if team and team.canonical_id in BASE_NBA_ELO else None
    if model_id == "nfl_elo_model":
        from integrations.models.external.nfl_elo_model import BASE_NFL_ELO, _resolve_nfl_team_code
        code = _resolve_nfl_team_code(name)
        return code if code in BASE_NFL_ELO else None
    from integrations.models.external.asian_baseball_model import _resolve_asian_team_key
    return _resolve_asian_team_key(name, league)


def _normalized_final(model_id: str, league: str, game: Any, fetched_at: datetime) -> tuple[dict[str, Any] | None, str | None]:
    provider = str(_result_value(game, "provider", "") or "").upper()
    if provider != RESULT_PROVIDERS[league]:
        return None, "RESULT_PROVIDER_UNTRUSTED"
    if str(_result_value(game, "league", "") or "").upper() != league:
        return None, "LEAGUE_MISMATCH"
    if str(_result_value(game, "status", "") or "").upper() != "FINAL":
        return None, "NOT_FINAL"
    if _result_value(game, "official_completion_status") not in {"REGULATION_COMPLETED", "FINAL"}:
        return None, "FINAL_COMPLETION_UNPROVEN"
    away_score, home_score = _result_value(game, "away_score"), _result_value(game, "home_score")
    if (type(away_score) is not int or type(home_score) is not int
            or away_score < 0 or home_score < 0):
        return None, "INVALID_FINAL_SCORE"
    away_raw, home_raw = str(_result_value(game, "away_team", "") or "").strip(), str(_result_value(game, "home_team", "") or "").strip()
    away, home = _team_key(model_id, league, away_raw), _team_key(model_id, league, home_raw)
    if not away or not home:
        return None, "TEAM_IDENTITY_UNSUPPORTED"
    if away == home:
        return None, "TEAM_IDENTITY_COLLISION"
    event_time = parse_aware_time(_result_value(game, "start_time_utc"))
    local_date = str(_result_value(game, "event_date_local", "") or "")[:10]
    if event_time is None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", local_date):
        return None, "EVENT_DATE_OR_TIME_MISSING"
    observed = parse_aware_time(_result_value(game, "observed_at_utc")) or fetched_at
    if observed > fetched_at + timedelta(minutes=5):
        return None, "SOURCE_OBSERVATION_IN_FUTURE"
    if event_time is not None:
        if event_time > fetched_at or observed < event_time:
            return None, "EVENT_SOURCE_ORDER_INVALID"
        order_date = event_time.date().isoformat()
        event_order = event_time.isoformat()
    else:
        try:
            day = datetime.fromisoformat(local_date).date()
        except ValueError:
            return None, "EVENT_DATE_INVALID"
        if day > observed.astimezone(ZoneInfo(LEAGUE_TIMEZONES[league])).date():
            return None, "EVENT_SOURCE_ORDER_INVALID"
        order_date = day.isoformat()
        event_order = order_date  # NPB exposes day order only; do not invent a game time.
    source_url = str(_result_value(game, "source_url", "") or "").strip()
    if not source_url:
        return None, "SOURCE_URL_MISSING"
    provider_event_id = str(_result_value(game, "provider_event_id", "") or "").strip()
    stable_identity = provider_event_id or f"{league}|{order_date}|{away}|{home}"
    event_id = f"{provider}|{league}|{stable_identity}"
    result_body = {"league": league, "event_order": event_order, "home_team": home,
                   "away_team": away, "home_score": home_score, "away_score": away_score,
                   "provider": provider}
    result_hash = hashlib.sha256(json.dumps(result_body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ({**result_body, "event_id": event_id, "event_date": order_date,
             "observed_at_utc": observed.isoformat(), "source_url": source_url,
             "provider_event_id": provider_event_id or None, "result_sha256": result_hash}, None)


def _finite_ratings(value: Any, allowed: set[str]) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("research Elo state has no ratings object")
    result = {}
    for key, rating in value.items():
        if key not in allowed or isinstance(rating, bool):
            raise ValueError(f"research Elo state contains unsupported rating key: {key}")
        numeric = float(rating)
        if not math.isfinite(numeric):
            raise ValueError(f"research Elo state contains non-finite rating: {key}")
        result[key] = numeric
    return result


def _replay(model_id: str, base_ratings: dict[str, float], events: dict[str, dict[str, Any]]) -> dict[str, float]:
    from integrations.models.external.nba_elo_engine import HOME_COURT_ADVANTAGE as NBA_HCA
    from integrations.models.external.nfl_elo_model import HOME_FIELD_ADVANTAGE as NFL_HFA
    from integrations.models.external.asian_baseball_model import HOME_FIELD_ADVANTAGE as ASIAN_HFA
    hfa = {"nba_elo_engine": NBA_HCA, "nfl_elo_model": NFL_HFA, "asian_baseball_model": ASIAN_HFA}[model_id]
    grouped = defaultdict(list)
    for row in events.values():
        if not isinstance(row, dict):
            raise ValueError("research Elo event ledger has a non-object row")
        grouped[(row["league"], row["event_date"])].append(row)
    ratings = dict(base_ratings)
    for group_key in sorted(grouped):
        deltas: dict[str, float] = defaultdict(float)
        for row in sorted(grouped[group_key], key=lambda item: item["event_id"]):
            home, away = row["home_team"], row["away_team"]
            if home not in ratings or away not in ratings:
                raise ValueError("research Elo event ledger contains an unsupported team")
            difference = ratings[home] + hfa - ratings[away]
            expected_home = 1.0 / (1.0 + 10.0 ** (-difference / 400.0))
            home_score = row["home_score"]
            away_score = row["away_score"]
            actual_home = 0.5 if home_score == away_score else 1.0 if home_score > away_score else 0.0
            delta = 20.0 * (actual_home - expected_home)
            deltas[home] += delta
            deltas[away] -= delta
        for team, delta in deltas.items():
            ratings[team] = round(ratings[team] + delta, 1)
    return ratings


def _update_model(data_root: Path, model_id: str, finals_by_league: dict[str, list[tuple[Any, datetime]]]) -> dict[str, Any]:
    cls = _class_for(model_id)
    state_path = data_root / "model_state" / f"{model_id}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    old: dict[str, Any] = {}
    if state_path.exists():
        old = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(old, dict):
            raise ValueError("existing model state is not an object; refusing to overwrite")
    model = cls(state_file=state_path)
    allowed = set(model.elo_ratings)
    loaded_ratings = _finite_ratings(old.get("ratings", model.elo_ratings), allowed)
    stored_events = old.get("research_events", {})
    if not isinstance(stored_events, dict):
        raise ValueError("existing research event ledger is invalid; refusing to overwrite")
    base = _finite_ratings(old.get("research_base_ratings", loaded_ratings), allowed)
    base_count = int(old.get("research_base_processed_games", old.get("processed_games", 0)) or 0)
    events = dict(stored_events)
    added = corrected = excluded = 0
    exclusions: dict[str, int] = defaultdict(int)
    for league, batches in finals_by_league.items():
        if not batches:
            continue
        successful_batch = True
        normalized_rows = []
        for game, fetched_at in batches:
            row, reason = _normalized_final(model_id, league, game, fetched_at)
            if reason:
                exclusions[reason] += 1
                if reason in {"RESULT_PROVIDER_UNTRUSTED", "LEAGUE_MISMATCH"}:
                    successful_batch = False
                continue
            normalized_rows.append(row)
        if not successful_batch:
            exclusions["LEAGUE_UPDATE_SKIPPED_UNTRUSTED_BATCH"] += len(normalized_rows)
            continue
        for row in normalized_rows:
            previous = events.get(row["event_id"])
            if previous and previous.get("result_sha256") == row["result_sha256"]:
                continue
            if previous:
                corrected += 1
            else:
                added += 1
            events[row["event_id"]] = row
    changed = added + corrected
    if not changed:
        return {"status": "NO_NEW_FINALS", "updated_games": 0, "corrected_results": 0,
                "processed_games": len(events), "exclusion_counts": dict(exclusions)}
    ratings = _replay(model_id, base, events)
    observation_by_league: dict[str, datetime] = {}
    provider_by_league: dict[str, str] = {}
    for row in events.values():
        observed = parse_aware_time(row.get("observed_at_utc"))
        if observed is None:
            raise ValueError("research Elo event ledger contains an invalid observation timestamp")
        league = row["league"]
        if league not in observation_by_league or observed > observation_by_league[league]:
            observation_by_league[league] = observed
            provider_by_league[league] = row["provider"]
    previous_as_of = old.get("data_as_of_by_league", {})
    previous_source = old.get("source_by_league", {})
    if not isinstance(previous_as_of, dict) or not isinstance(previous_source, dict):
        raise ValueError("existing per-league research provenance is invalid")
    data_as_of_by_league = dict(previous_as_of)
    source_by_league = dict(previous_source)
    for league, observed in observation_by_league.items():
        data_as_of_by_league[league] = observed.isoformat()
        source_by_league[league] = provider_by_league[league]
    last_updated = max(observation_by_league.values()).isoformat()
    payload = {**old, "research_update_schema": 1,
               "research_base_ratings": base, "research_base_processed_games": base_count,
               "ratings": ratings, "processed_games": base_count + len(events),
               "research_events": events, "data_as_of_by_league": data_as_of_by_league,
               "source_by_league": source_by_league, "last_updated_at": last_updated,
               "source": ",".join(sorted(set(provider_by_league.values()))), "version": model.version}
    _write_json_atomic(state_path, payload)
    return {"status": "UPDATED", "updated_games": added, "corrected_results": corrected,
            "processed_games": len(events), "data_as_of_by_league": data_as_of_by_league,
            "exclusion_counts": dict(exclusions)}


class ResearchRatingUpdater:
    """Update NBA/NFL/Asian model Elo states from bounded public result feeds."""
    def __init__(self, data_root: Path, clock: Callable[[], datetime] | None = None,
                 *, espn_provider=None, asian_provider=None, cpbl_provider=None):
        self.data_root = Path(data_root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._espn = espn_provider
        self._asian = asian_provider
        self._cpbl = cpbl_provider

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("research rating update clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    def run(self, settings: dict[str, Any], stage_data: Path) -> dict[str, Any]:
        now = self._now()
        progress_path = self.data_root / "model_state" / "research_rating_update_progress.json"
        progress = _read_json(progress_path, {})
        if not isinstance(progress, dict):
            raise ValueError("research rating update progress file is invalid")
        interval_hours = max(1, int(settings.get("refresh_interval_hours", 12)))
        retry_minutes = max(15, int(settings.get("retry_interval_minutes", 60)))
        last_success = parse_aware_time(progress.get("last_success_utc"))
        last_attempt = parse_aware_time(progress.get("last_attempt_utc"))
        if last_success and now - last_success < timedelta(hours=interval_hours):
            return {"status": "FRESH_CACHE", "last_success_utc": last_success.isoformat(), "models": {}}
        if (progress.get("last_attempt_status") == "PARTIAL" and last_attempt
                and now - last_attempt < timedelta(minutes=retry_minutes)):
            return {"status": "RETRY_BACKOFF", "last_attempt_utc": last_attempt.isoformat(), "models": {}}
        days = min(7, max(1, int(settings.get("lookback_days", 3))))
        try:
            from integrations.results import CPBLResultProvider, ESPNResultProvider, OfficialAsianBaseballProvider
            self._espn = self._espn or ESPNResultProvider()
            self._asian = self._asian or OfficialAsianBaseballProvider()
            self._cpbl = self._cpbl or CPBLResultProvider()
            query_plan: dict[str, list[tuple[str, str]]] = {}
            for league in MODEL_LEAGUES["nba_elo_engine"] + MODEL_LEAGUES["nfl_elo_model"]:
                local_today = now.astimezone(ZoneInfo(LEAGUE_TIMEZONES[league])).date()
                query_plan[league] = [(local_today - timedelta(days=offset)).strftime("%Y%m%d")
                                      for offset in reversed(range(days))]
            for league in MODEL_LEAGUES["asian_baseball_model"]:
                local_today = now.astimezone(ZoneInfo(LEAGUE_TIMEZONES[league])).date()
                query_plan[league] = [(local_today - timedelta(days=offset)).isoformat()
                                      for offset in reversed(range(days))]
            fetched_by_league: dict[str, list[tuple[Any, datetime]]] = defaultdict(list)
            errors: dict[str, list[str]] = defaultdict(list)
            for league, dates in query_plan.items():
                for date_text in dates:
                    try:
                        if league in {"NBA", "NFL"}:
                            raw_games = self._espn.fetch("basketball" if league == "NBA" else "football",
                                                         league, date_text)
                        elif league == "CPBL":
                            raw_games = self._cpbl.fetch(date_text)
                        else:
                            raw_games = self._asian.fetch(league, date_text)
                        fetched_at = self._now()
                        fetched_by_league[league].extend((game, fetched_at) for game in raw_games)
                    except Exception as exc:
                        errors[league].append(f"{date_text}: {type(exc).__name__}: {exc}")
            model_reports = {}
            for model_id, leagues in MODEL_LEAGUES.items():
                report = {}
                for league in leagues:
                    if errors.get(league):
                        report[league] = {"status": "FETCH_FAILED_STATE_PRESERVED", "errors": errors[league]}
                        continue
                    update = _update_model(self.data_root, model_id,
                                           {league: fetched_by_league.get(league, [])})
                    report[league] = update
                model_reports[model_id] = report
            partial = bool(errors)
            result = {"status": "PARTIAL" if partial else "UPDATED_OR_NO_NEW_FINALS",
                      "models": model_reports, "fetch_errors": dict(errors),
                      "query_dates": query_plan,
                      "provider_note": "ESPN_PUBLIC_SCOREBOARD is a public third-party scoreboard; Asian feeds are official league sources."}
            progress.update(last_attempt_utc=now.isoformat(), last_attempt_status="PARTIAL" if partial else "SUCCEEDED")
            if not partial:
                progress["last_success_utc"] = now.isoformat()
            _write_json_atomic(progress_path, progress)
            _write_json_atomic(Path(stage_data) / "research_rating_update.json", result)
            return result
        except Exception as exc:
            progress.update(last_attempt_utc=now.isoformat(), last_attempt_status="PARTIAL",
                            last_error=f"{type(exc).__name__}: {exc}")
            _write_json_atomic(progress_path, progress)
            result = {"status": "FAILED_STATE_PRESERVED", "error": progress["last_error"], "models": {}}
            _write_json_atomic(Path(stage_data) / "research_rating_update.json", result)
            return result
