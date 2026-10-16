#!/usr/bin/env python3
"""Experimental MLB Elo model with explicit official-results provenance.

The neutral 1500 ratings are only an initialization convention. They are not
historical team strength estimates and are never reported as live data.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.identity import GLOBAL_TEAM_REGISTRY
from integrations.common.models import ModelQualityLabel, PredictionSignal, TaiwanLeg

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
STATE_FILE = DATA_DIR / "live_mlb_elo_state.json"
HOME_FIELD_ADVANTAGE = 24.0
DEFAULT_K_FACTOR = 16.0
STATE_SCHEMA_VERSION = 2
FRESH_DAYS = 14
AGING_DAYS = 45

# Neutral initialization only; never presented as data-backed ratings.
DEFAULT_MLB_ELO: Dict[str, float] = {
    f"MLB_{team.abbreviation}": 1500.0
    for team in GLOBAL_TEAM_REGISTRY._teams.values()
    if team.sport == "baseball" and team.league == "MLB"
}


def _parse_aware(value: Any) -> Optional[datetime]:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _game_pk_sort_key(value: Any) -> Tuple[int, Any]:
    """Stable order for numeric and nonnumeric official/game legacy IDs."""
    text = str(value)
    return (0, int(text)) if text.isdigit() else (1, text)


def _strict_score(value: Any, *, game_pk: Any = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        label = f"gamePk={game_pk} " if game_pk is not None else ""
        raise ValueError(f"{label}比分必須是原始非負整數。")
    return value


def _data_as_of_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    parsed = _parse_aware(value)
    if parsed is not None:
        return parsed
    # Old states sometimes kept date-only freshness. That is not precise enough
    # to safely order another game on the same date.
    try:
        parsed_date = date.fromisoformat(str(value))
        return datetime.combine(parsed_date, datetime.min.time(), timezone.utc)
    except (TypeError, ValueError):
        raise ValueError("MLB Elo state 的 data_as_of 格式無效，需先備份並人工修復。")


def _game_not_after_data_as_of(game_dt: datetime, value: Optional[str]) -> bool:
    if not value:
        return False
    parsed = _parse_aware(value)
    if parsed is not None:
        return game_dt <= parsed
    try:
        # Date-only legacy metadata cannot order games within that date.
        return game_dt.date() <= date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("MLB Elo state 的 data_as_of 格式無效，需先備份並人工修復。")


def _resolve_official_team(name: str):
    """Resolve only exact registry names/aliases; reject substring guesses."""
    team = GLOBAL_TEAM_REGISTRY.resolve(name, sport="baseball", league="MLB")
    if team is None:
        return None
    allowed = {team.canonical_id, team.abbreviation, team.display_name_en, *team.aliases}
    if name.strip().casefold() not in {value.strip().casefold() for value in allowed}:
        return None
    return team


class LiveMLBEloAdapter:
    SOURCE_CATEGORY = "OPEN_SOURCE_ENGINE"
    INDEPENDENCE_GROUP = "LIVE_MLB_ELO"
    ENGINE_NAME = "MLB Elo (未校準研究模型)"
    LICENSE = "MIT"

    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = Path(state_file or STATE_FILE)
        self._ratings = dict(DEFAULT_MLB_ELO)
        self._history: List[Dict[str, Any]] = []
        self._history_count = 0
        self._processed_game_pks: set[str] = set()
        self._has_state = False
        self._load_error: Optional[str] = None
        self.last_update: Optional[str] = None
        self.source: Optional[str] = None
        self.data_as_of: Optional[str] = None
        self._legacy_metadata: Dict[str, Any] = {}
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            content = json.loads(self.state_file.read_text(encoding="utf-8"))
            if not isinstance(content, dict):
                raise ValueError("state must be a JSON object")
            known_fields = {"schema_version", "ratings", "history_count", "history", "processed_game_pks",
                            "last_update", "source", "data_as_of"}
            legacy_metadata = {k: v for k, v in content.items() if k not in known_fields}
            legacy_ids = {"MLB_AZ": "MLB_ARI", "MLB_WAS": "MLB_WSH"}
            ratings = content.get("ratings", {})
            history = content.get("history", [])
            processed = content.get("processed_game_pks", [])
            if not isinstance(ratings, dict) or not isinstance(history, list) or not isinstance(processed, list):
                raise ValueError("ratings/history/processed_game_pks 必須分別是 object/list/list")
            loaded_ratings = dict(DEFAULT_MLB_ELO)
            for key, value in ratings.items():
                if isinstance(value, bool):
                    raise ValueError(f"rating {key} 不是有限數值")
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError(f"rating {key} 不是有限數值")
                canonical_key = legacy_ids.get(str(key), str(key))
                if canonical_key in DEFAULT_MLB_ELO:
                    loaded_ratings[canonical_key] = value
            loaded_history = list(history)
            loaded_count = max(len(loaded_history), int(content.get("history_count", len(loaded_history))))
            loaded_processed = {str(pk) for pk in processed}
            data_as_of = content.get("data_as_of")
            _data_as_of_datetime(data_as_of)
            self._legacy_metadata = legacy_metadata
            self._ratings = loaded_ratings
            self._history = loaded_history
            self._history_count = loaded_count
            self._processed_game_pks = loaded_processed
            self.last_update = content.get("last_update")
            self.source = content.get("source")
            self.data_as_of = data_as_of
            self._has_state = True
        except Exception as exc:
            # Never retain a partially-read state. Keep the corrupt file intact;
            # callers must not turn a neutral fallback into an overwrite.
            self._ratings = dict(DEFAULT_MLB_ELO)
            self._history = []
            self._history_count = 0
            self._processed_game_pks = set()
            self._legacy_metadata = {}
            self.last_update = None
            self.source = None
            self.data_as_of = None
            self._has_state = False
            self._load_error = str(exc)
            logger.warning("Failed loading MLB Elo state; neutral experimental baseline used: %s", exc)

    def _clear_loaded_state(self) -> None:
        self._ratings = dict(DEFAULT_MLB_ELO)
        self._history = []
        self._history_count = 0
        self._processed_game_pks = set()
        self._legacy_metadata = {}
        self.last_update = None
        self.source = None
        self.data_as_of = None
        self._has_state = False

    def reload_state(self) -> None:
        """Discard cached state and read the current atomic state file fail-closed."""
        self._clear_loaded_state()
        self._load_error = None
        self._load_state()

    def invalidate_state(self, reason: str = "state file unavailable") -> None:
        """Drop stale ratings when the external state cannot be inspected."""
        self._clear_loaded_state()
        self._load_error = str(reason)

    def _serialize_state(self) -> Dict[str, Any]:
        return {**self._legacy_metadata,
            "schema_version": STATE_SCHEMA_VERSION,
            "ratings": self._ratings,
            "history_count": self._history_count,
            "history": self._history[-50:],
            "processed_game_pks": sorted(self._processed_game_pks, key=_game_pk_sort_key),
            "last_update": self.last_update,
            "source": self.source,
            "data_as_of": self.data_as_of,
        }

    def _save_state(self) -> None:
        """Atomically replace state and raise on any persistence failure."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.state_file.parent,
                                             prefix=self.state_file.name + ".", suffix=".tmp", delete=False) as handle:
                temp_path = handle.name
                json.dump(self._serialize_state(), handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.state_file)
            self._has_state = True
        except Exception:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def get_rating(self, team_canonical_id: str) -> float:
        # Unknown teams are never silently assigned a synthetic 1500 rating.
        if team_canonical_id not in DEFAULT_MLB_ELO:
            raise ValueError(f"未知 MLB canonical team: {team_canonical_id}")
        return self._ratings.get(team_canonical_id, 1500.0)

    def predict_match(self, home_canonical_id: str, away_canonical_id: str,
                      home_pitcher_adj: float = 0.0, away_pitcher_adj: float = 0.0,
                      home_rest_adj: float = 0.0, away_rest_adj: float = 0.0) -> Tuple[float, float]:
        r_home = self.get_rating(home_canonical_id) + HOME_FIELD_ADVANTAGE + home_pitcher_adj + home_rest_adj
        r_away = self.get_rating(away_canonical_id) + away_pitcher_adj + away_rest_adj
        prob_home = 1.0 / (1.0 + math.pow(10.0, -(r_home - r_away) / 400.0))
        return prob_home, 1.0 - prob_home

    def update_game_result(self, home_canonical_id: str, away_canonical_id: str,
                           home_score: int, away_score: int, match_date: str = "",
                           game_pk: Optional[str | int] = None,
                           _allow_ordered_batch: bool = False) -> Tuple[float, float]:
        """Apply one final result; updater supplies gamePk for durable deduplication."""
        if home_canonical_id not in DEFAULT_MLB_ELO or away_canonical_id not in DEFAULT_MLB_ELO:
            raise ValueError("拒絕更新：MLB canonical team 未知。")
        if home_canonical_id == away_canonical_id:
            raise ValueError("主客隊 canonical identity 相同。")
        home_score = _strict_score(home_score)
        away_score = _strict_score(away_score)
        if game_pk is not None and str(game_pk) in self._processed_game_pks:
            return self.get_rating(home_canonical_id), self.get_rating(away_canonical_id)
        current_game_dt = _parse_aware(match_date) if match_date else None
        if current_game_dt and not _allow_ordered_batch and _game_not_after_data_as_of(current_game_dt, self.data_as_of):
            raise ValueError("收到早於或無法排序於既有 data_as_of 的未處理賽果；需完整重播賽季後才能安全增量更新。")
        old_h, old_a = self.get_rating(home_canonical_id), self.get_rating(away_canonical_id)
        p_home, _ = self.predict_match(home_canonical_id, away_canonical_id)
        w_home = 1.0 if home_score > away_score else 0.0 if away_score > home_score else 0.5
        mov = abs(int(home_score) - int(away_score))
        elo_diff = (old_h + HOME_FIELD_ADVANTAGE) - old_a if w_home >= 0.5 else old_a - (old_h + HOME_FIELD_ADVANTAGE)
        mov_mult = (math.log(max(1, mov) + 1.0) * 2.2) / ((max(0.0, elo_diff) * 0.001) + 2.2)
        delta = DEFAULT_K_FACTOR * mov_mult * (w_home - p_home)
        new_home, new_away = round(old_h + delta, 1), round(old_a - delta, 1)
        self._ratings[home_canonical_id], self._ratings[away_canonical_id] = new_home, new_away
        self._history.append({"game_pk": str(game_pk) if game_pk is not None else None,
                              "date": match_date, "home": home_canonical_id, "away": away_canonical_id,
                              "score": f"{home_score}:{away_score}", "delta": round(delta, 1),
                              "new_home_r": new_home, "new_away_r": new_away})
        self._history_count += 1
        if game_pk is not None:
            self._processed_game_pks.add(str(game_pk))
        if match_date and (not self.data_as_of or match_date > self.data_as_of):
            self.data_as_of = match_date
        return new_home, new_away

    def apply_official_games(self, games: Iterable[Dict[str, Any]], source: str = "MLB Stats API") -> Dict[str, Any]:
        """Validate, sort, dedupe and atomically persist a batch of official final games."""
        if self._load_error:
            raise ValueError("既有 MLB Elo state 無法讀取，為保護原帳本拒絕覆寫；請先備份並人工修復。") from ValueError(self._load_error)
        games = list(games)
        normalized = []
        seen = set()
        for game in games:
            pk = str(game["gamePk"])
            if pk in self._processed_game_pks or pk in seen:
                continue
            status = game.get("status", {})
            if status.get("abstractGameState") != "Final" and status.get("codedGameState") != "F":
                continue
            game_type = str(game.get("gameType") or "").strip().upper()
            if game_type and game_type not in {"R", "F", "D", "L", "W"}:
                continue
            game_dt = _parse_aware(game.get("gameDate"))
            if game_dt is None:
                raise ValueError(f"Final gamePk={pk} 沒有有效時區 gameDate。")
            home_obj, away_obj = game["teams"]["home"], game["teams"]["away"]
            home_name, away_name = home_obj["team"]["name"], away_obj["team"]["name"]
            home = _resolve_official_team(home_name)
            away = _resolve_official_team(away_name)
            if not home or not away:
                raise ValueError(f"gamePk={pk} 的官方隊名無法映射：{away_name} @ {home_name}；停止更新避免猜隊。")
            linescore = game.get("linescore", {})
            home_score = linescore.get("teams", {}).get("home", {}).get("runs", home_obj.get("score"))
            away_score = linescore.get("teams", {}).get("away", {}).get("runs", away_obj.get("score"))
            if home_score is None or away_score is None:
                raise ValueError(f"Final gamePk={pk} 缺少比分。")
            home_score = _strict_score(home_score, game_pk=pk)
            away_score = _strict_score(away_score, game_pk=pk)
            normalized.append((game_dt, pk, home.canonical_id, away.canonical_id, home_score, away_score))
            seen.add(pk)
        normalized.sort(key=lambda row: (row[0], _game_pk_sort_key(row[1])))
        if any(_game_not_after_data_as_of(game_dt, self.data_as_of) for game_dt, *_ in normalized):
            raise ValueError("收到早於或無法排序於既有 data_as_of 的未處理賽果；需完整重播賽季後才能安全增量更新。")
        snapshot = (dict(self._ratings), list(self._history), self._history_count, set(self._processed_game_pks),
                    self.data_as_of, self.last_update, self.source, self._has_state)
        try:
            for game_dt, pk, home_id, away_id, home_score, away_score in normalized:
                self.update_game_result(home_id, away_id, home_score, away_score,
                                        game_dt.isoformat(), game_pk=pk, _allow_ordered_batch=True)
            if normalized:
                self.last_update = datetime.now(timezone.utc).isoformat()
                self.source = source
                self._save_state()
        except Exception:
            (self._ratings, self._history, self._history_count, self._processed_game_pks, self.data_as_of,
             self.last_update, self.source, self._has_state) = snapshot
            raise
        return {"updated_games": len(normalized), "skipped_games": sum(
                    1 for game in games if str(game.get("gamePk")) in snapshot[3]),
                "data_as_of": self.data_as_of, "last_update": self.last_update,
                "source": self.source}

    def _freshness_for_leg(self, leg: TaiwanLeg) -> str:
        coverage = self._legacy_metadata.get("official_schedule_coverage")
        if isinstance(coverage, dict) and coverage.get("complete_through_yesterday") is not True:
            return "UNKNOWN"
        if not self._has_state or not self.data_as_of:
            return "UNKNOWN"
        pred = _parse_aware(getattr(leg, "start_time_utc", None))
        data = _parse_aware(self.data_as_of)
        if data is None or pred is None:
            return "UNKNOWN"
        # Schedule gameDate is game start, not final whistle. Same-day use cannot
        # prove the result existed before this prediction, so fail closed.
        if data.date() >= pred.date():
            return "UNKNOWN"
        age = (pred.date() - data.date()).days
        return "FRESH" if age <= FRESH_DAYS else "AGING" if age <= AGING_DAYS else "STALE"

    def evaluate_leg(self, leg: TaiwanLeg) -> Optional[PredictionSignal]:
        if leg.sport != "baseball" or "MLB" not in leg.league.upper():
            return None
        away = GLOBAL_TEAM_REGISTRY.resolve(leg.away_team, sport="baseball", league="MLB")
        home = GLOBAL_TEAM_REGISTRY.resolve(leg.home_team, sport="baseball", league="MLB")
        if not away or not home:
            logger.debug("LiveMLBEloAdapter: Cannot resolve canonical teams for %s vs %s", leg.away_team, leg.home_team)
            return None
        freshness = self._freshness_for_leg(leg)
        if freshness == "UNKNOWN":
            data_dt, pred_dt = _parse_aware(self.data_as_of), _parse_aware(getattr(leg, "start_time_utc", None))
            if self._has_state and data_dt and pred_dt and data_dt.date() >= pred_dt.date():
                return None  # same-day completion time is unknown, so never risk lookahead
        prob_home, prob_away = self.predict_match(home.canonical_id, away.canonical_id)
        market_implied = 1.0 / leg.taiwan_odds if leg.taiwan_odds > 1.0 else 0.50
        if "不讓分" not in leg.market and leg.market != "獨贏":
            # No validated run-line mapping; do not return a hand-built estimate.
            return None
        is_home = "主" in leg.selection or leg.side == "主" or home.display_name_en in leg.selection
        probability = prob_home if is_home else prob_away
        edge = (probability - market_implied) * 100.0
        confidence = "MED" if edge >= 0 else "LOW"
        meta = {"home_elo": self.get_rating(home.canonical_id), "away_elo": self.get_rating(away.canonical_id),
                "hfa": HOME_FIELD_ADVANTAGE, "engine": self.ENGINE_NAME,
                "rating_initialization": "neutral_1500" if not self.data_as_of else "official_results_elo",
                "data_as_of": self.data_as_of, "last_update": self.last_update, "source": self.source,
                "processed_game_count": len(self._processed_game_pks), "starting_pitcher_adjustment_used": False,
                "rest_adjustment_used": False, "empirically_calibrated": False,
                "quality_note": "模型勝率為未校準估計；資料新鮮度不代表預測品質已驗證。"}
        return PredictionSignal(source_id="live_mlb_elo", source_name=self.ENGINE_NAME,
            source_type="MODEL", event_id=leg.event_id, market=leg.market, selection=leg.selection,
            probability=round(probability, 3), score=round(edge, 1), confidence=confidence,
            pick="主" if is_home else "客", source_category=self.SOURCE_CATEGORY,
            independence_group=self.INDEPENDENCE_GROUP, data_as_of=self.data_as_of,
            freshness_status=freshness, market_implied_probability=round(market_implied, 3),
            model_probability=round(probability, 3), model_market_delta_pp=round(edge, 1),
            quality_label=ModelQualityLabel.MODEL_EXPERIMENTAL,
            metadata=meta)
