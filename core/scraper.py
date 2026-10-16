#!/usr/bin/env python3
"""Playsport & Taiwan Sports Lottery Odds Scraper.

Fetches live odds, market options (讓分、不讓分、大小、和局),
and crowd consensus from playsport.cc.
Includes local disk caching and graceful offline fallback to stale cache.
NO FAKE FIXTURES IN PRODUCTION PATH.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from core.identity import (
    GLOBAL_EVENT_MATCHER,
    GLOBAL_TEAM_REGISTRY,
    normalize_league_and_sport,
    parse_playsport_time_to_utc,
)
from core.source_health import append_source_health_observation, build_identity_health

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"
CACHE_TTL_SECONDS = 900  # 15 minutes

ALLIANCE_MAP = {
    "1": "MLB (美棒)",
    "4": "足球 (各大聯賽)",
    "3": "NBA",
    "7": "WNBA",
    "2": "NPB (日棒)",
    "6": "CPBL (中職)",
    "9": "KBO (韓棒)",
    "93": "NFL (美足)",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class PlaysportScraper:
    def __init__(self, session: Optional[requests.Session] = None, cache_dir: Optional[Union[str, Path]] = None,
                 snapshot_dir: Optional[Union[str, Path]] = None,
                 source_health_history_path: Optional[Union[str, Path]] = None):
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        # Isolated cache dirs (used in tests/offline tools) must not write production snapshots.
        self.snapshot_dir = (Path(snapshot_dir) if snapshot_dir is not None else
                             None if cache_dir is not None else Path(__file__).resolve().parents[1] / "data" / "snapshots")
        self.source_health_history_path = (
            Path(source_health_history_path) if source_health_history_path is not None else
            None if cache_dir is not None else Path(__file__).resolve().parents[1] / "data" / "source_health" / "playsport.jsonl"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._scale_source_status: Dict[str, Dict[str, Any]] = {}

    def get_scale_source_status(self) -> Dict[str, Dict[str, Any]]:
        """Return observed source/cache diagnostics from the most recent scale fetches."""
        return {key: dict(value) for key, value in self._scale_source_status.items()}

    @staticmethod
    def _cache_age_minutes(cached_at: Any) -> Optional[float]:
        try:
            return max(0.0, (time.time() - float(cached_at)) / 60.0)
        except (TypeError, ValueError, OverflowError):
            return None

    def _store_scale_source_status(self, alliance_id: str, status: Dict[str, Any],
                                   matches: List[Dict[str, Any]]) -> None:
        """Attach privacy-safe identity completeness diagnostics and append source history."""
        health = build_identity_health(matches)
        status.update(health)
        self._scale_source_status[str(alliance_id)] = status
        try:
            append_source_health_observation(self.source_health_history_path, alliance_id, status, health)
        except OSError as exc:
            logger.warning("Could not append source health history: %s", exc)

    def get_cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def read_cache(self, key: str, ignore_ttl: bool = False) -> Optional[Dict[str, Any]]:
        path = self.get_cache_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached_time = data.get("cached_at", 0)
            if ignore_ttl or (time.time() - cached_time < CACHE_TTL_SECONDS):
                return data
        except Exception as exc:
            logger.warning("Failed to read cache %s: %s", key, exc)
        return None

    def write_cache(self, key: str, data: Dict[str, Any]) -> None:
        try:
            path = self.get_cache_path(key)
            now_dt = datetime.now(timezone.utc)
            data["cached_at"] = time.time()
            data["cached_iso"] = now_dt.isoformat()
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

            # Also save immutable snapshot in production mode.
            if self.snapshot_dir is not None:
                self.snapshot_dir.mkdir(parents=True, exist_ok=True)
                snap_name = f"{now_dt.strftime('%Y%m%d_%H%M%S')}_{key}.json"
                (self.snapshot_dir / snap_name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to write cache %s: %s", key, exc)

    def _write_no_event_cache(self, key: str, source_url: str, observed_at: str) -> Optional[str]:
        """Atomically replace prior odds with a short-lived, empty no-events record."""
        path = self.get_cache_path(key)
        payload = {
            "matches": [], "source_url": source_url,
            "source_status": "LIVE_NO_EVENTS", "no_events_observed_at": observed_at,
            "cached_at": time.time(), "cached_iso": observed_at,
        }
        temp_path = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            return None
        except OSError as exc:
            # If the atomic replacement fails, removing the old odds is still
            # safer than allowing them to survive a confirmed no-games page.
            try:
                path.unlink(missing_ok=True)
                logger.warning("Atomic no-events cache replacement failed for %s; removed prior cache: %s", key, exc)
                return None
            except OSError as clear_exc:
                return f"could not clear stale cache: {type(clear_exc).__name__}: {clear_exc}"
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove temporary no-events cache file %s", temp_path)

    @staticmethod
    def _is_explicit_no_events_page(table: BeautifulSoup, parsed_matches: List[Dict[str, Any]]) -> bool:
        """Accept only the source's explicit empty marker with no event rows."""
        if parsed_matches:
            return False
        table_text = table.get_text(" ", strip=True)
        if "此日無比賽" not in table_text:
            return False
        if table.select("tr.game-set"):
            return False
        # Guard against DOM variants whose event rows are not marked game-set.
        return not table.select("tr td.td-gameinfo")

    def fetch_expert_leaderboard(self, alliance_id: str = "1", force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Compatibility wrapper returning rankers from both public leaderboards."""
        return self.fetch_expert_leaderboards(alliance_id, force_refresh).get("rankers", [])

    @staticmethod
    def _extract_vue_data(html: str) -> Optional[Dict[str, Any]]:
        """Read the public Vue JSON object without evaluating any page scripts."""
        match = re.search(r"var\s+vueData\s*=\s*(\{.*?\});", html, re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(1))
            return value if isinstance(value, dict) else None
        except (ValueError, TypeError):
            return None

    def _fetch_public_board(self, alliance_id: str, board_kind: str, force_refresh: bool) -> Dict[str, Any]:
        path = "mainPrediction" if board_kind == "main_prediction" else "winRate"
        url = f"https://www.playsport.cc/billboard/{path}?allianceid={alliance_id}"
        cache_key = f"experts_{board_kind}_{alliance_id}"
        cached = None if force_refresh else self.read_cache(cache_key)
        if cached:
            fetched_at = float(cached.get("cached_at", 0) or 0)
            return {
                "rankers": cached.get("rankers", []), "source_status": "CACHED",
                "source_url": url, "observed_at": cached.get("cached_iso"),
                "cache_age_minutes": max(0.0, (time.time() - fetched_at) / 60.0),
            }

        try:
            response = self.session.get(url, timeout=10)
            observed_at = datetime.now(timezone.utc).isoformat()
            if response.status_code != 200:
                status = f"HTTP_{response.status_code}"
                raise requests.HTTPError(status)
            data = self._extract_vue_data(response.text)
            if not data or not isinstance(data.get("rankers"), dict):
                status = "PARSE_EMPTY"
                raise ValueError("Public board HTML has no parseable rankers")

            rows: List[Dict[str, Any]] = []
            rankers = data.get("rankers", {})
            labels = data.get("modeList" if board_kind == "main_prediction" else "gametypeList", {})
            for group_key, group_rows in rankers.items():
                label = labels.get(str(group_key), str(group_key)) if isinstance(labels, dict) else str(group_key)
                for row in group_rows if isinstance(group_rows, list) else []:
                    if not isinstance(row, dict) or not row.get("userid"):
                        continue
                    rows.append({
                        "rank": row.get("rank"), "nickname": row.get("nickname"),
                        "userid": str(row["userid"]), "winpercentage": row.get("winpercentage"),
                        "wingame": row.get("wingame"), "losegame": row.get("losegame"),
                        "total_game": row.get("total_game"), "winearn": row.get("winearn"),
                        "process_time": row.get("process_time"), "alliance_id": str(alliance_id),
                        "board_kind": board_kind, "board_group": str(label),
                        "link_url": urljoin("https://www.playsport.cc", row.get("linkUrl") or f"/member/{row['userid']}/prediction?allianceid={alliance_id}"),
                    })
            self.write_cache(cache_key, {"rankers": rows, "source_url": url, "observed_at": observed_at})
            return {"rankers": rows, "source_status": "LIVE", "source_url": url,
                    "observed_at": observed_at, "cache_age_minutes": 0.0}
        except Exception as exc:
            logger.warning("Failed to read Playsport %s board %s: %s", board_kind, alliance_id, exc)
            stale = self.read_cache(cache_key, ignore_ttl=True)
            if stale:
                fetched_at = float(stale.get("cached_at", 0) or 0)
                return {"rankers": stale.get("rankers", []), "source_status": "STALE_CACHE",
                        "source_url": url, "observed_at": stale.get("cached_iso"),
                        "cache_age_minutes": max(0.0, (time.time() - fetched_at) / 60.0),
                        "failure_status": locals().get("status", "FETCH_ERROR")}
            return {"rankers": [], "source_status": locals().get("status", "FETCH_ERROR"),
                    "source_url": url, "observed_at": None, "cache_age_minutes": None}

    def fetch_expert_leaderboards(self, alliance_id: str = "1", force_refresh: bool = False) -> Dict[str, Any]:
        """Fetch public main-pick and win-rate leaderboards; they are one source family."""
        boards = {
            kind: self._fetch_public_board(alliance_id, kind, force_refresh)
            for kind in ("main_prediction", "win_rate")
        }
        merged: Dict[str, Dict[str, Any]] = {}
        for kind, board in boards.items():
            for row in board["rankers"]:
                userid = row["userid"]
                merged_row = merged.setdefault(userid, {**row, "board_kinds": [], "board_entries": []})
                if kind not in merged_row["board_kinds"]:
                    merged_row["board_kinds"].append(kind)
                merged_row["board_entries"].append({
                    "board_kind": kind, "board_group": row.get("board_group"),
                    "rank": row.get("rank"), "historical_win_rate": row.get("winpercentage"),
                    "wins": row.get("wingame"), "losses": row.get("losegame"),
                    "total_game": row.get("total_game"), "winearn": row.get("winearn"),
                    "process_time": row.get("process_time"),
                })
        rankers = list(merged.values())
        rankers.sort(key=lambda row: (min((e.get("rank") or 10**9) for e in row["board_entries"]), row["userid"]))
        statuses = [b["source_status"] for b in boards.values()]
        source_status = ("LIVE" if all(status == "LIVE" for status in statuses) else
                         "CACHED" if all(status in ("LIVE", "CACHED") for status in statuses) else
                         "STALE_CACHE" if any(status == "STALE_CACHE" for status in statuses) else
                         "PARTIAL" if any(b["rankers"] for b in boards.values()) else "UNAVAILABLE")
        return {"rankers": rankers, "boards": boards, "source_status": source_status,
                "source_urls": [b["source_url"] for b in boards.values()],
                "observed_at": max((b.get("observed_at") for b in boards.values() if b.get("observed_at")), default=None),
                "cache_age_minutes": max((b.get("cache_age_minutes") or 0 for b in boards.values()), default=None)}

    def fetch_member_prediction_page(self, userid: str, alliance_id: str = "1") -> Optional[str]:
        """Fetch raw HTML of individual expert's prediction page."""
        return self.fetch_member_prediction_page_result(userid, alliance_id).get("html")

    def fetch_member_prediction_page_result(self, userid: str, alliance_id: str = "1", force_refresh: bool = False) -> Dict[str, Any]:
        """Fetch a public member page with explicit freshness and failure evidence."""
        cache_key = f"member_pred_{alliance_id}_{userid}"
        cached = None if force_refresh else self.read_cache(cache_key)
        if cached and "html" in cached:
            fetched_at = float(cached.get("cached_at", 0) or 0)
            return {"html": cached["html"], "source_url": cached.get("source_url"),
                    "source_status": "CACHED", "observed_at": cached.get("cached_iso"),
                    "cache_age_minutes": max(0.0, (time.time() - fetched_at) / 60.0)}

        url = f"https://www.playsport.cc/member/{userid}/prediction?allianceid={alliance_id}"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                observed_at = datetime.now(timezone.utc).isoformat()
                self.write_cache(cache_key, {"html": resp.text, "source_url": url, "observed_at": observed_at})
                return {"html": resp.text, "source_url": url, "source_status": "LIVE",
                        "observed_at": observed_at, "cache_age_minutes": 0.0}
            status = f"HTTP_{resp.status_code}"
        except Exception as exc:
            logger.warning("Failed to fetch member prediction page for %s: %s", userid, exc)
            status = "FETCH_ERROR"

        stale = self.read_cache(cache_key, ignore_ttl=True)
        if stale and stale.get("html") is not None:
            fetched_at = float(stale.get("cached_at", 0) or 0)
            return {"html": stale["html"], "source_url": stale.get("source_url", url),
                    "source_status": "STALE_CACHE", "failure_status": status,
                    "observed_at": stale.get("cached_iso"),
                    "cache_age_minutes": max(0.0, (time.time() - fetched_at) / 60.0)}
        return {"html": None, "source_url": url, "source_status": status,
                "observed_at": None, "cache_age_minutes": None}

    def fetch_scale_matches(self, alliance_id: str = "1", force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch live matches and options with odds & consensus scale."""
        cache_key = f"scale_{alliance_id}"
        url = f"https://www.playsport.cc/predict/scale?allianceid={alliance_id}"
        if not force_refresh:
            cached = self.read_cache(cache_key)
            if cached:
                cached_at = cached.get("cached_at")
                cached_iso = cached.get("cached_iso")
                cache_status = "CACHED" if cached_at is not None and cached_iso else "UNKNOWN"
                is_no_events_cache = cached.get("source_status") == "LIVE_NO_EVENTS"
                source_status = "LIVE_NO_EVENTS" if is_no_events_cache else cache_status
                matches = cached.get("matches", [])
                for m in matches:
                    m["_cached_at"] = cached_at
                    m["_cached_iso"] = cached_iso
                    m["_is_stale_cache"] = False
                    m["_cache_status"] = cache_status
                    m.setdefault("_source_url", cached.get("source_url", url))
                    self._mark_identity_integrity(m)
                self._store_scale_source_status(alliance_id, {
                    "source_status": source_status,
                    "cache_provenance": cache_status if is_no_events_cache else None,
                    "source_url": url,
                    "observed_at": cached.get("no_events_observed_at", cached_iso),
                    "cache_age_minutes": self._cache_age_minutes(cached_at),
                    "attempted_at": None, "failure_status": None, "error": None,
                    "no_events_confirmed": is_no_events_cache,
                    "match_count": len(matches), "market_match_count": sum(bool(m.get("options")) for m in matches),
                    "option_count": sum(len(m.get("options") or []) for m in matches),
                    "placeholder_identity_count": sum(bool(m.get("_identity_incomplete")) for m in matches),
                    "placeholder_identity_option_count": sum(len(m.get("options") or []) for m in matches if m.get("_identity_incomplete")),
                }, matches)
                return matches

        league_name = ALLIANCE_MAP.get(str(alliance_id), f"聯盟_{alliance_id}")
        attempted_at = datetime.now(timezone.utc).isoformat()
        failure_status: Optional[str] = None
        error: Optional[str] = None
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                table = soup.find("table", class_="predictgame-table")
                if table:
                    matches = self._parse_predict_table(table, league_name, alliance_id)
                    if matches:
                        now_t = time.time()
                        now_iso = datetime.now(timezone.utc).isoformat()
                        for m in matches:
                            m["_cached_at"] = now_t
                            m["_cached_iso"] = now_iso
                            m["_is_stale_cache"] = False
                            m["_cache_status"] = "LIVE"
                            m["_source_url"] = url
                            self._mark_identity_integrity(m)
                        self.write_cache(cache_key, {"matches": matches})
                        self._store_scale_source_status(alliance_id, {
                            "source_status": "LIVE", "source_url": url, "observed_at": now_iso,
                            "cache_age_minutes": 0.0,
                            "attempted_at": attempted_at, "failure_status": None, "error": None,
                            "match_count": len(matches),
                            "market_match_count": sum(bool(m.get("options")) for m in matches),
                            "option_count": sum(len(m.get("options") or []) for m in matches),
                            "placeholder_identity_count": sum(bool(m.get("_identity_incomplete")) for m in matches),
                            "placeholder_identity_option_count": sum(len(m.get("options") or []) for m in matches if m.get("_identity_incomplete")),
                        }, matches)
                        return matches
                    failure_status, error = "PARSE_EMPTY", "Expected table found but no matches were parsed"
                    if self._is_explicit_no_events_page(table, matches):
                        now_iso = datetime.now(timezone.utc).isoformat()
                        cache_error = self._write_no_event_cache(cache_key, url, now_iso)
                        self._store_scale_source_status(alliance_id, {
                            "source_status": "LIVE_NO_EVENTS", "source_url": url,
                            "observed_at": now_iso, "cache_age_minutes": 0.0,
                            "attempted_at": attempted_at, "failure_status": None,
                            "error": cache_error, "no_events_confirmed": True,
                            "empty_marker": "此日無比賽",
                            "match_count": 0, "market_match_count": 0,
                            "option_count": 0, "placeholder_identity_count": 0,
                            "placeholder_identity_option_count": 0,
                        }, [])
                        return []
                else:
                    failure_status, error = "PARSE_EMPTY", "Expected predictgame-table was absent"
            else:
                failure_status = f"HTTP_{resp.status_code}"
                error = f"HTTP status {resp.status_code}"
                logger.warning("HTTP %s from %s", resp.status_code, url)
        except Exception as exc:
            failure_status, error = "FETCH_ERROR", f"{type(exc).__name__}: {exc}"
            logger.warning("Failed to scrape alliance %s: %s", alliance_id, exc)

        # Fallback to stale cache (Never invent fake matches in production!)
        stale = self.read_cache(cache_key, ignore_ttl=True)
        if stale:
            logger.info("Using stale cache for alliance %s", alliance_id)
            cached_at = stale.get("cached_at")
            cached_iso = stale.get("cached_iso")
            cache_status = "STALE_CACHE" if cached_at is not None and cached_iso else "UNKNOWN"
            matches = stale.get("matches", [])
            for m in matches:
                m["_cached_at"] = cached_at
                m["_cached_iso"] = cached_iso
                m["_is_stale_cache"] = cache_status == "STALE_CACHE"
                m["_cache_status"] = cache_status
                m["_source_url"] = stale.get("source_url", url)
                m["_failure_status"] = failure_status
                m["_source_error"] = error
                self._mark_identity_integrity(m)
            self._store_scale_source_status(alliance_id, {
                "source_status": cache_status, "source_url": stale.get("source_url", url),
                "observed_at": stale.get("cached_iso"),
                "cache_age_minutes": self._cache_age_minutes(cached_at),
                "attempted_at": attempted_at,
                "failure_status": failure_status, "error": error, "match_count": len(matches),
                "market_match_count": sum(bool(m.get("options")) for m in matches),
                "option_count": sum(len(m.get("options") or []) for m in matches),
                "placeholder_identity_count": sum(bool(m.get("_identity_incomplete")) for m in matches),
                "placeholder_identity_option_count": sum(len(m.get("options") or []) for m in matches if m.get("_identity_incomplete")),
            }, matches)
            return matches

        # Real production behavior: return empty list, UI displays UNAVAILABLE
        self._store_scale_source_status(alliance_id, {
            "source_status": failure_status or "UNAVAILABLE", "source_url": url,
            "observed_at": None, "cache_age_minutes": None, "attempted_at": attempted_at,
            "failure_status": failure_status or "UNAVAILABLE", "error": error,
            "match_count": 0, "market_match_count": 0, "placeholder_identity_count": 0,
            "option_count": 0, "placeholder_identity_option_count": 0,
        }, [])
        logger.error("No live or stale data available for alliance %s", alliance_id)
        return []

    @staticmethod
    def _mark_identity_integrity(match: Dict[str, Any]) -> None:
        placeholders = {"", "客隊", "主隊", "未知", "unknown", "away", "home", "tbd"}
        away = str(match.get("away_team") or "").strip().casefold()
        home = str(match.get("home_team") or "").strip().casefold()
        incomplete = away in placeholders or home in placeholders or away == home
        match["_identity_incomplete"] = incomplete
        if incomplete:
            match.setdefault("_identity_diagnostic", "placeholder_or_duplicate_team")

    def _parse_predict_table(
        self, table: BeautifulSoup, league_name: str, alliance_id: str
    ) -> List[Dict[str, Any]]:
        """High-precision DOM parser separating teams, pitchers, and betting markets."""
        # Restrict parsing to the event table's own rows. Football embeds a
        # nested scoreboard table inside td-teaminfo; its participant rows must
        # never be treated as independent event rows.
        rows = []
        for tbody in table.find_all("tbody", recursive=False):
            rows.extend(tbody.find_all("tr", recursive=False))
        if not rows:
            rows = table.find_all("tr", recursive=False)
        matches: List[Dict[str, Any]] = []

        default_league, default_sport = normalize_league_and_sport(league_name, alliance_id)

        i = 0
        while i < len(rows):
            r1 = rows[i]
            td_game = r1.find("td", class_="td-gameinfo")
            if not td_game:
                i += 1
                continue

            # Found game header row!
            game_txt = td_game.get_text(strip=True)
            m_id_match = re.search(r"(\d{3,4})", game_txt)
            match_id = m_id_match.group(1) if m_id_match else f"{alliance_id}_{len(matches)+1}"
            time_match = re.search(r"(?:AM|PM)?\s*\d{1,2}:\d{2}", game_txt)
            game_time = time_match.group(0) if time_match else "即將開賽"
            competition_node = td_game.select_one(".football__nameWorld")
            source_competition = (_clean_text(competition_node.get_text(" ", strip=True))
                                  if competition_node else "")
            event_league, event_sport = normalize_league_and_sport(
                source_competition or league_name, alliance_id
            )
            # Playsport game IDs have YYYYMMDD as their leading eight digits.
            # Validate the calendar date before using it; never infer a year for
            # these IDs or silently stamp archived events with today's date.
            event_date = None
            game_id = str(r1.get("gameid") or "")
            if re.match(r"^\d{8}", game_id):
                try:
                    event_date = datetime.strptime(game_id[:8], "%Y%m%d").date()
                except ValueError:
                    event_date = None

            # Playsport football pages contain one event header followed by three
            # market rows. The first and second participant cells in the nested
            # td-teaminfo scoreboard align with the explicit 客 and 主 market rows;
            # winnerteam/secondteam are score-result classes and are not sides.
            td_team1 = r1.find("td", class_="td-teaminfo")
            away_team_raw = "客隊"
            home_team_raw = "主隊"
            away_pitcher = None
            identity_source = "unresolved"
            identity_diagnostic = "team_cell_missing"
            if td_team1:
                participants = [
                    _clean_text(td.get_text(" ", strip=True))
                    for td in td_team1.select("td.winnerteam, td.secondteam")
                    if _clean_text(td.get_text(" ", strip=True))
                ]
                if len(participants) == 2 and participants[0].casefold() != participants[1].casefold():
                    away_team_raw, home_team_raw = participants
                    identity_source = "participant_dom_order"
                    identity_diagnostic = None
                else:
                    h3_a = td_team1.find("h3")
                    if h3_a:
                        away_team_raw = _clean_text(h3_a.get_text(" ", strip=True))
                        identity_source = "teaminfo_h3_rows"
                        identity_diagnostic = "home_team_cell_missing"
                p_pitcher = td_team1.find("p")
                if p_pitcher:
                    away_pitcher = p_pitcher.get_text(strip=True) or None

            # Parse legacy two-row sports (for example baseball and basketball).
            home_pitcher = None
            r2 = rows[i + 1] if i + 1 < len(rows) else None
            event_row_count = 2
            if r1.get("gameid"):
                event_game_id = str(r1.get("gameid"))
                continuations = []
                for candidate in rows[i + 1:i + 3]:
                    if candidate.find("td", class_="td-gameinfo") or str(candidate.get("gameid") or "") != event_game_id:
                        break
                    continuations.append(candidate)
                if continuations:
                    r2 = continuations[0]
                    r3 = continuations[1] if len(continuations) > 1 else None
                    event_row_count = 1 + len(continuations)
                else:
                    r3 = None
            else:
                r3 = None
                # Header row span describes how many market rows belong to a
                # football event, even in archived HTML without gameid attributes.
                if "td-gameinfo_football" in (td_game.get("class") or []):
                    event_row_count = 3
                    r2 = rows[i + 1] if i + 1 < len(rows) else None
                    r3 = rows[i + 2] if i + 2 < len(rows) else None

            if identity_source != "participant_dom_order" and r2:
                td_team2 = r2.find("td", class_="td-teaminfo")
                if td_team2:
                    h3_h = td_team2.find("h3")
                    if h3_h:
                        home_team_raw = _clean_text(h3_h.get_text(" ", strip=True))
                        identity_source = "teaminfo_h3_rows"
                        identity_diagnostic = None if away_team_raw not in ("客隊", "") else "away_team_cell_missing"
                    p_h_pitcher = td_team2.find("p")
                    if p_h_pitcher:
                        home_pitcher = p_h_pitcher.get_text(strip=True) or None

            identity_placeholders = {"", "客隊", "主隊", "未知", "unknown", "away", "home", "tbd"}
            identity_incomplete = (
                away_team_raw.strip().casefold() in identity_placeholders
                or home_team_raw.strip().casefold() in identity_placeholders
                or away_team_raw.strip().casefold() == home_team_raw.strip().casefold()
            )
            if identity_incomplete:
                identity_diagnostic = identity_diagnostic or "placeholder_or_duplicate_team"

            # Never let fallback labels seed the global identity/event registries.
            can_away = (GLOBAL_TEAM_REGISTRY.resolve(away_team_raw, sport=event_sport, league=event_league)
                        if not identity_incomplete else None)
            can_home = (GLOBAL_TEAM_REGISTRY.resolve(home_team_raw, sport=event_sport, league=event_league)
                        if not identity_incomplete else None)

            away_display = can_away.display_name_zh if can_away else away_team_raw
            home_display = can_home.display_name_zh if can_home else home_team_raw

            start_utc = parse_playsport_time_to_utc(game_time, reference_date=event_date)

            # Match or create canonical event
            canonical_ev = GLOBAL_EVENT_MATCHER.match_or_create(
                sport=event_sport,
                league=event_league,
                away_name=away_team_raw,
                home_name=home_team_raw,
                start_time_utc=start_utc,
                taiwan_event_id=match_id,
                away_pitcher=away_pitcher,
                home_pitcher=home_pitcher,
            ) if not identity_incomplete else None

            # Parse betting options from r1 (away) and r2 (home)
            options = self._extract_options_from_dom(r1, r2, match_id, source_competition or league_name, game_time,
                                                     away_display, home_display, r3=r3)

            current_match = {
                "match_id": match_id,
                "event_id": match_id,
                "canonical_event_id": (canonical_ev.canonical_event_id if canonical_ev else
                                       f"PLAYSPORT_{alliance_id}_{event_league}_{game_id or match_id}_{start_utc or 'TIME_UNKNOWN'}"),
                "league": event_league,
                "canonical_league": event_league,
                "source_competition": source_competition or league_name,
                "playsport_game_id": game_id or None,
                "sport": event_sport,
                "alliance_id": alliance_id,
                "game_time": game_time,
                "start_time_utc": start_utc,
                "away_team": away_display,
                "home_team": home_display,
                "_identity_incomplete": identity_incomplete,
                "_identity_source": identity_source,
                "_identity_diagnostic": identity_diagnostic,
                "away_pitcher": away_pitcher,
                "home_pitcher": home_pitcher,
                "options": options,
            }
            matches.append(current_match)
            i += max(1, event_row_count)

        return matches

    def _extract_options_from_dom(
        self,
        r1: BeautifulSoup,
        r2: Optional[BeautifulSoup],
        match_id: str,
        league_name: str,
        game_time: str,
        away_team: str,
        home_team: str,
        r3: Optional[BeautifulSoup] = None,
    ) -> List[Dict[str, Any]]:
        """Extract options using exact table cell classes (td-bank-bet01/02/03)."""
        options: List[Dict[str, Any]] = []

        # Row 1 (Away): Spread (01), ML (03), Over/Under (02)
        cells_to_parse = [
            ("讓分", "td-bank-bet01", "客", r1),
            ("不讓分", "td-bank-bet03", "客", r1),
            ("大小", "td-bank-bet02", "大", r1),
        ]
        # Row 2 (Home): Spread (01), ML (03), Over/Under (02)
        if r2:
            cells_to_parse.extend([
                ("讓分", "td-bank-bet01", "主", r2),
                ("不讓分", "td-bank-bet03", "主", r2),
                ("大小", "td-bank-bet02", "小", r2),
            ])
        # Soccer draw odds occupy the third market row and use bank-bet01.
        if r3:
            cells_to_parse.append(("和局", "td-bank-bet01", "和", r3))

        for market_type, cls_name, default_side, row in cells_to_parse:
            td = row.find("td", class_=cls_name)
            if not td:
                continue

            td_next = td.find_next_sibling("td")
            opt_data = self._parse_bank_cell(td, td_next, default_side)
            if not opt_data:
                continue

            odds = opt_data["odds"]
            side = opt_data["side"]
            line = opt_data["line"]
            consensus_ratio = opt_data["consensus_ratio"]
            vote_count = opt_data["vote_count"]

            if side == "和":
                market_type = "和局"
                selection = f"和局 ({odds})"
            elif market_type == "讓分":
                team = away_team if side == "客" else home_team
                selection = f"{team} {line or ''} ({odds})"
            elif market_type == "不讓分":
                team = away_team if side == "客" else home_team
                selection = f"{team} 不讓分勝 ({odds})"
            else:  # 大小
                selection = f"{side} {line or ''}分 ({odds})"

            opt_id = f"{match_id}_{market_type}_{side}_{odds}".replace(".", "_").replace(" ", "_")

            options.append({
                "option_id": opt_id,
                "match_id": match_id,
                "event_id": match_id,
                "league": league_name,
                "game_time": game_time,
                "away_team": away_team,
                "home_team": home_team,
                "market_type": market_type,
                "market": market_type,
                "side": side,
                "line": line,
                "selection": selection,
                "odds": odds,
                "taiwan_odds": odds,
                "consensus_ratio": consensus_ratio,
                "vote_count": vote_count,
            })

        return options

    def _parse_bank_cell(
        self, td_cell: BeautifulSoup, next_cell: Optional[BeautifulSoup], default_side: str
    ) -> Optional[Dict[str, Any]]:
        """Parse bank betting cell text, line, and odds."""
        txt = td_cell.get_text(strip=True)
        if not txt or txt == "-":
            return None

        odds = 0.0
        line = None
        side = "客" if "客" in txt else "主" if "主" in txt else "和" if "和" in txt else "大" if "大" in txt else "小" if "小" in txt else default_side

        if "," in txt:
            parts = txt.split(",")
            try:
                odds = float(parts[1].strip())
                left = parts[0].strip()
                l_match = re.search(r"([+-]?\d+(?:\.\d+)?)", left)
                if l_match:
                    line = l_match.group(1)
            except Exception:
                pass
        else:
            m = re.search(r"(\d+(?:\.\d+)?)", txt)
            if m:
                try:
                    odds = float(m.group(1))
                except Exception:
                    pass

        if odds <= 1.0:
            return None

        crowd_ratio = None
        vote_count = None
        if next_cell:
            s_txt = next_cell.get_text(strip=True)
            m_s = re.search(r"(\d+)%\s*(?:(\d+)\s*人預測)?", s_txt)
            if m_s:
                crowd_ratio = float(m_s.group(1)) / 100.0
                if m_s.group(2):
                    vote_count = int(m_s.group(2))

        return {
            "side": side,
            "line": line,
            "odds": odds,
            "consensus_ratio": crowd_ratio,
            "vote_count": vote_count,
        }

    def fetch_all_active_matches(
        self, selected_alliances: Optional[List[str]] = None, force_refresh: bool = False
    ) -> List[Dict[str, Any]]:
        alliances = selected_alliances or ["1", "4"]
        all_matches: List[Dict[str, Any]] = []

        for aid in alliances:
            try:
                matches = self.fetch_scale_matches(aid, force_refresh=force_refresh)
                all_matches.extend(matches)
            except Exception as exc:
                logger.error("Error fetching alliance %s: %s", aid, exc)

        return all_matches
