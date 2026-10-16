#!/usr/bin/env python3
"""Penaltyblog Dixon-Coles Soccer Prediction Model Adapter (External Open-Source Engine).

PROVENANCE & AUTHENTICITY GATE:
- Open-Source Repository: https://github.com/martineastwood/penaltyblog
- Engine: penaltyblog.models.DixonColesGoalModel (directly imported and fitted)
- Data Source: Real match results from Football-Data.co.uk via penaltyblog.scrapers.FootballData
- Point-in-Time Leakage Guard: Training dataset is strictly filtered to matches with date < prediction_date
- License: MIT
- Source Category: EXTERNAL_OPEN_SOURCE_ENGINE
- Independence Group: DIXON_COLES_MATCHES
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import json
import logging
import os
from collections import OrderedDict
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

import penaltyblog as pb

from core.identity import GLOBAL_TEAM_REGISTRY
from integrations.common.models import ModelQualityLabel, PredictionSignal, TaiwanLeg

logger = logging.getLogger(__name__)

CACHE_DIR = str(Path(__file__).resolve().parents[3] / "data" / "cache")
MIN_MATCHES_REQUIRED = 60
MIN_TEAM_APPEARANCES = 4
MODEL_CACHE_MAXSIZE = 8

LEAGUE_CODE_MAP = {
    "PREMIER": "eng.1",
    "CHAMPIONS": "uefa.champions",
    "LALIGA": "esp.1",
    "ENG.1": "eng.1",
    "ESP.1": "esp.1",
    "ITA.1": "ita.1",
    "GER.1": "ger.1",
    "FRA.1": "fra.1",
    "UEFA.CHAMPIONS": "uefa.champions",
    "英超": "eng.1",
    "西甲": "esp.1",
    "義甲": "ita.1",
    "德甲": "ger.1",
    "法甲": "fra.1",
    "歐冠": "uefa.champions",
    "英格蘭超級聯賽": "eng.1",
    "西班牙甲級聯賽": "esp.1",
    "義大利甲級聯賽": "ita.1",
    "德國甲級聯賽": "ger.1",
}

# Football-Data.co.uk uses abbreviated labels that are not all in the shared
# display registry (for example, "Tottenham"). Keep these exact source aliases
# explicit; never infer teams from substrings.
FOOTBALL_DATA_TEAM_ALIASES = {
    "tottenham": "Tottenham Hotspur",
}


def _canonical_model_team_name(source_name: Any) -> Tuple[str, Optional[Dict[str, str]]]:
    original = str(source_name or "").strip()
    if not original:
        return original, None
    lookup_name = FOOTBALL_DATA_TEAM_ALIASES.get(original.casefold(), original)
    team = GLOBAL_TEAM_REGISTRY.resolve(lookup_name, sport="soccer")
    if team is None:
        return original, None
    exact_names = {team.canonical_id, team.abbreviation, team.display_name_en,
                   team.display_name_zh, team.short_name_zh, *team.aliases}
    if lookup_name.casefold() not in {name.strip().casefold() for name in exact_names}:
        return original, None
    canonical = team.display_name_en or team.canonical_id
    if original.casefold() == canonical.casefold():
        return canonical, None
    return canonical, {"source_name": original, "canonical_name": canonical}


def _valid_nonnegative_score(value: Any) -> bool:
    """Accept only raw JSON integer scores; bool is an int subclass in Python."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass
class ModelInputProvenance:
    """Rigorous metadata documenting the exact training dataset and provenance."""
    dataset_source: str
    dataset_url: str
    dataset_version: str
    downloaded_at: Optional[str]
    training_start_date: Optional[str]
    training_end_date: Optional[str]
    match_count: int
    latest_match_date: str
    dataset_seasons: List[str] = field(default_factory=list)
    data_age_days: Optional[int] = None
    freshness_status: str = "UNKNOWN"      # 'FRESH', 'AGING', 'STALE', 'UNKNOWN'
    point_in_time_verified: bool = False
    cold_start_flag: Optional[str] = None # e.g. 'LOW_HISTORY_TEAM'
    training_file_sha256: Optional[str] = None
    future_records_excluded: int = 0
    unknown_date_records: int = 0
    invalid_score_records: int = 0
    source_team_name_aliases: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_source": self.dataset_source,
            "dataset_url": self.dataset_url,
            "dataset_version": self.dataset_version,
            "downloaded_at": self.downloaded_at,
            "training_start_date": self.training_start_date,
            "training_end_date": self.training_end_date,
            "match_count": self.match_count,
            "latest_match_date": self.latest_match_date,
            "dataset_seasons": self.dataset_seasons,
            "data_age_days": self.data_age_days,
            "freshness_status": self.freshness_status,
            "point_in_time_verified": self.point_in_time_verified,
            "cold_start_flag": self.cold_start_flag,
            "training_file_sha256": self.training_file_sha256,
            "future_records_excluded": self.future_records_excluded,
            "unknown_date_records": self.unknown_date_records,
            "invalid_score_records": self.invalid_score_records,
            "source_team_name_aliases": self.source_team_name_aliases,
        }


class PenaltyblogDixonColesAdapter:
    """Evaluates soccer TaiwanLeg betting options using genuine Dixon & Coles bivariate Poisson model."""

    SOURCE_CATEGORY = "EXTERNAL_OPEN_SOURCE_ENGINE"
    INDEPENDENCE_GROUP = "DIXON_COLES_MATCHES"
    ENGINE_NAME = "Penaltyblog Dixon-Coles Engine"
    REPO_URL = "https://github.com/martineastwood/penaltyblog"
    LICENSE = "MIT"
    MODEL_CACHE_MAXSIZE = MODEL_CACHE_MAXSIZE

    def __init__(self, cache_dir: str = CACHE_DIR):
        self.version = getattr(pb, "__version__", "1.12.2")
        self.cache_dir = cache_dir
        self.min_matches_required = MIN_MATCHES_REQUIRED
        self.min_team_appearances = MIN_TEAM_APPEARANCES
        self._cache_meta: Dict[str, Dict[str, Any]] = {}
        self._model_cache: OrderedDict[Tuple[str, str, str], Tuple[Any, ModelInputProvenance, Dict[str, int]]] = OrderedDict()
        self._fit_count = 0
        os.makedirs(self.cache_dir, exist_ok=True)

    def _resolve_league_code(self, league_name: str) -> Optional[str]:
        normalized = str(league_name or "").strip().lower()
        return LEAGUE_CODE_MAP.get(normalized.upper()) or LEAGUE_CODE_MAP.get(normalized)

    def _load_league_matches(self, league_code: str) -> List[Dict[str, Any]]:
        """Load authentic match results from cache file."""
        cache_file = os.path.join(self.cache_dir, f"real_matches_{league_code}.json")
        if not os.path.exists(cache_file):
            return []
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._cache_meta[league_code] = {
                "dataset_source": data.get("dataset_source", "Football-Data.co.uk via penaltyblog.scrapers.FootballData"),
                "dataset_url": data.get("dataset_url", "https://www.football-data.co.uk"),
                "dataset_version": data.get("dataset_version", self.version),
                "downloaded_at": data.get("downloaded_at", ""),
                "dataset_seasons": data.get("dataset_seasons", ["2023-2024", "2024-2025", "2025-2026", "2026-2027"]),
            }
            return data.get("matches", []) if isinstance(data, dict) else []
        except Exception as exc:
            logger.warning("Failed to load real match history for %s: %s", league_code, exc)
            return []

    def _filter_matches_point_in_time(self, league_code: str, pred_date: str) -> List[Dict[str, Any]]:
        """Return dated records strictly before cutoff, sorted by actual match date."""
        cutoff = date.fromisoformat(pred_date[:10])
        dated = []
        for match in self._load_league_matches(league_code):
            try:
                match_date = date.fromisoformat(str(match.get("date", ""))[:10])
            except (TypeError, ValueError):
                continue
            if match_date < cutoff:
                dated.append((match_date, match))
        dated.sort(key=lambda row: row[0])
        return [match for _, match in dated
                if _valid_nonnegative_score(match.get("home_goals"))
                and _valid_nonnegative_score(match.get("away_goals"))
                and match.get("home_team") and match.get("away_team")]

    def _get_or_fit_model(
        self,
        league_code: str,
        pred_date: Optional[str] = None,
        home_id: Optional[str] = None,
        away_id: Optional[str] = None,
    ) -> Tuple[Optional[pb.models.DixonColesGoalModel], Optional[ModelInputProvenance]]:
        """Fit once per league, cutoff and exact source file content hash."""
        cache_file = Path(self.cache_dir) / f"real_matches_{league_code}.json"
        if not cache_file.exists():
            return None, None
        try:
            file_hash = hashlib.sha256(cache_file.read_bytes()).hexdigest()
        except OSError:
            return None, None
        cutoff = None
        if pred_date:
            try:
                cutoff = date.fromisoformat(str(pred_date)[:10])
            except (TypeError, ValueError):
                cutoff = None
        cache_key = (league_code, cutoff.isoformat() if cutoff else "UNKNOWN", file_hash)
        cached = self._model_cache.get(cache_key)
        if cached:
            self._model_cache.move_to_end(cache_key)
            model, base_prov, appearances = cached
            cold = self._cold_start(home_id, away_id, appearances)
            if cold == "INSUFFICIENT_TEAM_HISTORY":
                return None, replace(base_prov, cold_start_flag=cold)
            return model, replace(base_prov, cold_start_flag=cold)

        all_matches = self._load_league_matches(league_code)
        dated: List[Tuple[date, Dict[str, Any]]] = []
        unknown_dates = 0
        invalid_score_records = 0
        for match in all_matches:
            try:
                match_date = date.fromisoformat(str(match.get("date", ""))[:10])
            except (TypeError, ValueError):
                unknown_dates += 1
                continue
            if cutoff is None or match_date < cutoff:
                if not (match.get("home_team") and match.get("away_team")):
                    continue
                home_goals, away_goals = match.get("home_goals"), match.get("away_goals")
                # Football-Data scores are source integers. Do not coerce floats,
                # booleans, strings, or negative values into apparently valid results.
                if not (_valid_nonnegative_score(home_goals) and _valid_nonnegative_score(away_goals)):
                    invalid_score_records += 1
                    continue
                dated.append((match_date, match))
        dated.sort(key=lambda row: row[0])
        source_training_matches = [match for _, match in dated]
        training_matches: List[Dict[str, Any]] = []
        alias_map: Dict[Tuple[str, str], Dict[str, str]] = {}
        for match in source_training_matches:
            normalized = dict(match)
            for field_name in ("home_team", "away_team"):
                canonical, alias = _canonical_model_team_name(match[field_name])
                normalized[field_name] = canonical
                if alias:
                    alias_map[(alias["source_name"], alias["canonical_name"])] = alias
            training_matches.append(normalized)
        future_records_excluded = sum(1 for match in all_matches
                                      if cutoff and str(match.get("date", ""))[:10] >= cutoff.isoformat())
        if len(training_matches) < self.min_matches_required:
            logger.info("Insufficient dated training matches for %s (%d < %d)",
                        league_code, len(training_matches), self.min_matches_required)
            return None, None

        goals_home = [int(m["home_goals"]) for m in training_matches]
        goals_away = [int(m["away_goals"]) for m in training_matches]
        teams_home = [str(m["home_team"]) for m in training_matches]
        teams_away = [str(m["away_team"]) for m in training_matches]
        dates_list = [d for d, _ in dated]
        latest_date = dates_list[-1]
        data_age_days = max(0, (cutoff - latest_date).days) if cutoff else None
        if data_age_days is None or unknown_dates or invalid_score_records:
            freshness_status = "UNKNOWN"
        elif data_age_days <= 14:
            freshness_status = "FRESH"
        elif data_age_days <= 45:
            freshness_status = "AGING"
        else:
            freshness_status = "STALE"

        appearances: Dict[str, int] = {}
        for match in training_matches:
            appearances[match["home_team"]] = appearances.get(match["home_team"], 0) + 1
            appearances[match["away_team"]] = appearances.get(match["away_team"], 0) + 1
        cold_start_flag = self._cold_start(home_id, away_id, appearances)

        try:
            # Official penaltyblog 1.12 API accepts base_date; anchor decay weights
            # to the prediction cutoff, never to execution date.
            base_date = cutoff or latest_date
            weights = pb.models.dixon_coles_weights(dates_list, xi=0.0018, base_date=base_date)
            model = pb.models.DixonColesGoalModel(goals_home, goals_away, teams_home, teams_away, weights=weights)
            model.fit()
            self._fit_count += 1
            meta = self._cache_meta.get(league_code, {})
            prov = ModelInputProvenance(
                dataset_source=meta.get("dataset_source", "Football-Data.co.uk via penaltyblog.scrapers.FootballData"),
                dataset_url=meta.get("dataset_url", "https://www.football-data.co.uk"),
                dataset_version=meta.get("dataset_version", self.version),
                downloaded_at=meta.get("downloaded_at"),
                training_start_date=dates_list[0].isoformat(),
                training_end_date=latest_date.isoformat(), match_count=len(goals_home),
                latest_match_date=latest_date.isoformat(), dataset_seasons=meta.get("dataset_seasons", []),
                data_age_days=data_age_days, freshness_status=freshness_status,
                point_in_time_verified=bool(cutoff is not None and unknown_dates == 0 and invalid_score_records == 0),
                cold_start_flag=cold_start_flag, training_file_sha256=file_hash,
                future_records_excluded=future_records_excluded, unknown_date_records=unknown_dates,
                invalid_score_records=invalid_score_records,
                source_team_name_aliases=[alias_map[key] for key in sorted(alias_map)],
            )
            # Extra audit data is kept outside the public dataclass for compatibility.
            self._model_cache[cache_key] = (model, prov, appearances)
            self._model_cache.move_to_end(cache_key)
            while len(self._model_cache) > max(1, int(self.MODEL_CACHE_MAXSIZE)):
                self._model_cache.popitem(last=False)
            self._cache_meta.setdefault(league_code, {})["future_records_excluded"] = future_records_excluded
            self._cache_meta[league_code]["unknown_date_records"] = unknown_dates
            if cold_start_flag == "INSUFFICIENT_TEAM_HISTORY":
                return None, prov
            return model, prov
        except Exception as exc:
            logger.warning("Fitting Dixon-Coles model failed for %s: %s", league_code, exc)
            return None, None

    def _cold_start(self, home_id: Optional[str], away_id: Optional[str], appearances: Dict[str, int]) -> Optional[str]:
        if not home_id or not away_id:
            return None
        h_apps, a_apps = appearances.get(home_id, 0), appearances.get(away_id, 0)
        if h_apps < self.min_team_appearances or a_apps < self.min_team_appearances:
            return "INSUFFICIENT_TEAM_HISTORY"
        if h_apps < 15 or a_apps < 15:
            return "LOW_HISTORY_TEAM"
        return None

    def evaluate_leg(self, leg: TaiwanLeg) -> Optional[PredictionSignal]:
        """Evaluate a soccer TaiwanLeg option using fitted Dixon-Coles model.

        Returns PredictionSignal with full ModelInputProvenance. Returns None if MODEL_NOT_READY.
        """
        if leg.sport != "soccer":
            return None

        league_code = self._resolve_league_code(leg.league)
        if not league_code:
            return None

        # Extract game prediction date to enforce Leakage Guard
        pred_date = None
        if leg.start_time_utc:
            pred_date = leg.start_time_utc[:10]
        elif leg.start_time and re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", leg.start_time):
            m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", leg.start_time)
            if m:
                pred_date = m.group(1).replace("/", "-")

        away_id, _ = _canonical_model_team_name(leg.away_team)
        home_id, _ = _canonical_model_team_name(leg.home_team)

        model, prov = self._get_or_fit_model(league_code, pred_date=pred_date, home_id=home_id, away_id=away_id)
        if model is None or prov is None:
            # Honest reality: data insufficient or model not fitted -> None (MODEL_NOT_READY)
            return None

        try:
            pred = model.predict(home_id, away_id)
        except Exception as exc:
            logger.info("Dixon-Coles predict failed for (%s vs %s): %s", home_id, away_id, exc)
            return None

        prob_home = float(pred.home_win)
        prob_draw = float(pred.draw)
        prob_away = float(pred.away_win)

        line_val = float(leg.line) if leg.line is not None else None
        try:
            if line_val is None:
                prob_over = prob_under = None
            else:
                prob_over = float(pred.total_goals("over", line_val))
                prob_under = float(pred.total_goals("under", line_val))
        except Exception:
            prob_over = prob_under = None

        taiwan_odds = leg.taiwan_odds
        market = leg.market
        side = leg.side
        market_implied = 1.0 / taiwan_odds if taiwan_odds > 1.0 else 0.50

        model_prob: Optional[float] = None
        side_code = {"主": "H", "H": "H", "HOME": "H",
                     "和": "D", "D": "D", "DRAW": "D", "和局": "D",
                     "客": "A", "A": "A", "AWAY": "A"}.get(str(side or "").strip().upper(),
                                                          {"主": "H", "和": "D", "和局": "D", "客": "A"}.get(str(side or "").strip()))
        if market in {"不讓分", "獨贏", "和局"}:
            if side_code == "H":
                model_prob = prob_home
            elif side_code == "D":
                model_prob = prob_draw
            elif side_code == "A":
                model_prob = prob_away
        elif market == "大小":
            if side == "大":
                model_prob = prob_over
            elif side == "小":
                model_prob = prob_under
        elif market == "讓分":
            # Dixon-Coles 1X2 probabilities are not a calibrated handicap model.
            return None

        if model_prob is None:
            return None

        model_prob = round(max(0.05, min(0.95, model_prob)), 3)
        edge = round((model_prob - market_implied) * 100.0, 1)

        # Freshness Gate & Cold Start Governance
        if prov.freshness_status == "STALE":
            source_category = "MODEL_STALE"
            confidence = "REFERENCE_ONLY"
            quality_label = ModelQualityLabel.MODEL_STALE
        elif prov.cold_start_flag in {"LOW_HISTORY_TEAM", "INSUFFICIENT_TEAM_HISTORY"}:
            source_category = self.SOURCE_CATEGORY
            confidence = "LOW"
            quality_label = ModelQualityLabel.MODEL_EXPERIMENTAL
        else:
            source_category = self.SOURCE_CATEGORY
            confidence = "MED" if edge >= 0.0 else "LOW"
            quality_label = ModelQualityLabel.MODEL_EXPERIMENTAL

        model_market_delta_pp = round((model_prob - market_implied) * 100.0, 1)

        return PredictionSignal(
            source_id="penaltyblog_dixon_coles",
            source_name="Penaltyblog Dixon-Coles (External Engine)",
            source_type="MODEL",
            event_id=leg.event_id,
            market=leg.market,
            selection=leg.selection,
            probability=model_prob,
            score=edge,
            confidence=confidence,
            pick=leg.selection,
            source_category=source_category,
            independence_group=self.INDEPENDENCE_GROUP,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data_as_of=prov.latest_match_date,
            data_age_hours=round(prov.data_age_days * 24.0, 1) if prov.data_age_days is not None else None,
            freshness_status=prov.freshness_status,
            market_implied_probability=round(market_implied, 3),
            model_probability=model_prob,
            model_market_delta_pp=model_market_delta_pp,
            quality_label=quality_label,
            metadata={
                "source_category": source_category,
                "independence_group": self.INDEPENDENCE_GROUP,
                "engine_name": self.ENGINE_NAME,
                "github_repo": self.REPO_URL,
                "license": self.LICENSE,
                "league": league_code,
                "home_win_prob": round(prob_home, 3),
                "draw_prob": round(prob_draw, 3),
                "away_win_prob": round(prob_away, 3),
                "over_goals_prob": round(prob_over, 3) if prob_over is not None else None,
                "under_goals_prob": round(prob_under, 3) if prob_under is not None else None,
                "market_implied_prob": round(market_implied, 3),
                "edge_pp": edge,
                "model_market_delta_pp": model_market_delta_pp,
                "quality_label": quality_label,
                "freshness_status": prov.freshness_status,
                "cold_start_flag": prov.cold_start_flag,
                "training_file_sha256": prov.training_file_sha256,
                "future_records_excluded": prov.future_records_excluded,
                "unknown_date_records": prov.unknown_date_records,
                "invalid_score_records": prov.invalid_score_records,
                "empirically_calibrated": False,
                "quality_note": "模型勝率為未校準估計；資料新鮮度不代表預測品質已驗證。",
                "provenance": prov.to_dict(),
            },
        )

