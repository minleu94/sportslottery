"""Shared state serialization and replay helpers for research workflows."""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.bet_validation import parse_aware_time
from core.contracts.common import PredictionSignal, TaiwanLeg


def _mlb_game_is_cancelled(game):
    status = game.get("status") or {}
    return (str(status.get("codedGameState") or "").upper() == "C"
            and str(status.get("detailedState") or "").casefold() in {"cancelled", "canceled"})

def _json_default(value: Any):
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, default=_json_default)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers can briefly hold a destination open. Retry only the
        # atomic replace operation; never truncate the old state or rewrite the
        # temporary payload between attempts.
        retry_delays = (0.05, 0.1, 0.15, 0.2)
        for attempt in range(len(retry_delays) + 1):
            try:
                os.replace(temp_name, path)
                break
            except PermissionError:
                if attempt >= len(retry_delays):
                    raise
                time.sleep(retry_delays[attempt])
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _mlb_game_date(game: dict[str, Any]) -> date | None:
    stamp = parse_aware_time(game.get("gameDate"))
    return stamp.date() if stamp else None


def _mlb_game_is_final(game: dict[str, Any]) -> bool:
    status = game.get("status") or {}
    detailed = str(status.get("detailedState") or "").casefold()
    coded = str(status.get("codedGameState") or "").upper()
    # Stats API can report abstractGameState=Final while the coded/detailed
    # state is still a postponement stub. That is not a completed result.
    if coded == "D" or "postpon" in detailed:
        return False
    if not (status.get("abstractGameState") == "Final" or status.get("codedGameState") == "F"):
        return False
    # A final label alone is not usable Elo evidence. Preserve/requery incomplete
    # finals as pending; do not invent scores or advance the rating watermark.
    from integrations.results.models import parse_score
    teams = game.get("teams") or {}
    linescore = (game.get("linescore") or {}).get("teams") or {}
    return all(parse_score((linescore.get(side) or {}).get("runs", (teams.get(side) or {}).get("score"))) is not None
               for side in ("home", "away"))


def _mlb_game_is_regular_or_postseason(game: dict[str, Any]) -> bool:
    # Stats API gameType: R regular season; F/D/L/W postseason rounds.
    # Spring training (S), exhibitions (E), all-star (A), and unknown types
    # are retained in the source ledger but excluded from this model protocol.
    game_type = str(game.get("gameType") or "").strip().upper()
    return game_type in {"R", "F", "D", "L", "W"}


def _mlb_reschedule_target_date(game: dict[str, Any]) -> date | None:
    """Read only an explicit MLB date field; never derive a new game date."""
    # Official calendar dates can differ from the UTC date of a night game.
    for key in ("rescheduleGameDate", "rescheduleDate", "officialDate"):
        value = game.get(key)
        if not value:
            continue
        parsed = parse_aware_time(value)
        if parsed:
            return parsed.date()
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            continue
    return None


def _mlb_needs_live_reconciliation(game: dict[str, Any], completed_through: date) -> bool:
    if not _mlb_game_is_regular_or_postseason(game) or _mlb_game_is_final(game) or _mlb_game_is_cancelled(game):
        return False
    scheduled = _mlb_game_date(game)
    target = _mlb_reschedule_target_date(game)
    return bool(scheduled and target and scheduled <= completed_through and target <= completed_through)


def _mlb_normalize_live_feed(
    payload: dict[str, Any], schedule_game: dict[str, Any], *, observed_at_utc: str,
) -> dict[str, Any]:
    """Normalize a verified MLB live feed to the Stats schedule-game shape.

    Reconciliation requires the same gamePk, same home/away team IDs, an
    explicit aware gameData.datetime.dateTime, a matching official reschedule
    date when supplied, and a completed final score.
    """
    game_data = payload.get("gameData") or {}
    live = payload.get("liveData") or {}
    game_meta = game_data.get("game") or {}
    game_pk = str(game_meta.get("pk") or payload.get("gamePk") or "")
    expected_pk = str(schedule_game.get("gamePk") or "")
    if not game_pk or game_pk != expected_pk:
        raise ValueError(f"live feed gamePk mismatch: expected {expected_pk}, received {game_pk or 'missing'}")

    schedule_teams = schedule_game.get("teams") or {}
    live_teams = game_data.get("teams") or {}
    normalized_teams = {}
    for side in ("home", "away"):
        schedule_team = (schedule_teams.get(side) or {}).get("team") or {}
        live_team = live_teams.get(side) or {}
        schedule_id, live_id = str(schedule_team.get("id") or ""), str(live_team.get("id") or "")
        if not schedule_id or schedule_id != live_id:
            raise ValueError(f"live feed {side} team ID mismatch for gamePk={expected_pk}: {schedule_id or 'missing'} != {live_id or 'missing'}")

    game_datetime = game_data.get("datetime") or {}
    start_time = str(game_datetime.get("dateTime") or "")
    start_aware = parse_aware_time(start_time)
    if not start_aware:
        raise ValueError(f"live feed gamePk={expected_pk} has no aware gameData.datetime.dateTime")
    official_date = str(game_datetime.get("officialDate") or "")
    target_date = _mlb_reschedule_target_date(schedule_game)
    if target_date:
        if not official_date:
            raise ValueError(f"live feed gamePk={expected_pk} has no officialDate for reschedule validation")
        try:
            live_official_date = date.fromisoformat(official_date[:10])
        except ValueError as exc:
            raise ValueError(f"live feed gamePk={expected_pk} has invalid officialDate {official_date!r}") from exc
        if live_official_date != target_date:
            raise ValueError(f"live feed officialDate {official_date} does not match schedule reschedule date {target_date}")

    schedule_game_type = str(schedule_game.get("gameType") or "").strip().upper()
    live_game_type = str(game_meta.get("type") or "").strip().upper()
    if schedule_game_type and live_game_type and schedule_game_type != live_game_type:
        raise ValueError(f"live feed gameType {live_game_type} does not match schedule gameType {schedule_game_type}")

    status = game_data.get("status") or {}
    detailed_state = str(status.get("detailedState") or "").casefold()
    coded_state = str(status.get("codedGameState") or "").upper()
    if coded_state == "D" or "postpon" in detailed_state:
        raise ValueError(f"live feed gamePk={expected_pk} still reports a postponement")
    if status.get("abstractGameState") != "Final" and coded_state != "F":
        raise ValueError(f"live feed gamePk={expected_pk} is not final")
    linescore = live.get("linescore") or {}
    line_teams = linescore.get("teams") or {}
    scores = {}
    for side in ("home", "away"):
        value = (line_teams.get(side) or {}).get("runs")
        from integrations.results.models import parse_score
        parsed = parse_score(value)
        if parsed is None:
            raise ValueError(f"live feed gamePk={expected_pk} missing final {side} runs")
        scores[side] = parsed
        source_team = live_teams[side]
        normalized_teams[side] = {
            "team": {"id": int(str(source_team["id"])), "name": str(source_team.get("name") or "")},
            "score": parsed,
        }

    return {
        "gamePk": int(game_pk),
        "gameType": str(game_meta.get("type") or schedule_game.get("gameType") or ""),
        "gameDate": start_time,
        "officialDate": official_date or start_aware.date().isoformat(),
        "status": dict(status),
        "teams": normalized_teams,
        "linescore": {"teams": {side: {"runs": score} for side, score in scores.items()}},
        "_reconciled_from_live_feed": True,
        "_live_feed_observed_at_utc": observed_at_utc,
        "_source_observation": {
            "provider": "MLB_STATS_API_LIVE_FEED",
            "official_game_pk": game_pk,
            "official_start_time_utc": start_time,
            "home_team_id": str(normalized_teams["home"]["team"]["id"]),
            "away_team_id": str(normalized_teams["away"]["team"]["id"]),
        },
    }


def _parse_football_data_date(value: Any) -> date | None:
    """Football-Data date columns use both two- and four-digit years."""
    text = str(value or "").strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _leg_payload(leg: TaiwanLeg) -> dict[str, Any]:
    return leg.to_dict()


def _leg_from_payload(row: dict[str, Any]) -> TaiwanLeg:
    known = {item.name for item in fields(TaiwanLeg)}
    payload = {key: value for key, value in row.items() if key in known}
    signal_fields = {item.name for item in fields(PredictionSignal)}
    payload["signals"] = [
        signal if isinstance(signal, PredictionSignal) else
        PredictionSignal(**{key: value for key, value in signal.items() if key in signal_fields})
        for signal in payload.get("signals", []) if isinstance(signal, (dict, PredictionSignal))
    ]
    return TaiwanLeg(**payload)\n