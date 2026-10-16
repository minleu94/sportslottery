#!/usr/bin/env python3
"""Playsport Billboard Expert Adapter (Layer A - Verified Expert).

Fetches genuine expert recommendations from Playsport Billboard rankers'
actual prediction pages (/member/{userid}/prediction?allianceid={aid}).
Extracts real picks from 'table.bank-tablecon' (Taiwan lottery) and 'sellpredict-item'.
Validates:
1. Exact match identity (away & home teams)
2. Exact market (讓分, 不讓分, 大小)
3. Exact line match (spread handicap e.g. -1.5 vs -1.5, total e.g. 8.5 vs 8.5)
4. Date validation (pick date matches game date)
5. Multi-expert consensus aggregation across top 10~20 rankers

Returns None if no verified expert pick matches the TaiwanLeg. Never invents fake picks!
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
import time
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from core.identity import GLOBAL_TEAM_REGISTRY, normalize_league_and_sport
from core.identity.timezone import TAIPEI_TZ
from core.scraper import PlaysportScraper
from integrations.common.models import PredictionSignal, TaiwanLeg, VerifiedExpertPick

logger = logging.getLogger(__name__)

ALLIANCE_MAP = {
    "MLB": "1",
    "NPB": "2",
    "CPBL": "6",
    "KBO": "9",
    "足球": "4",
    "NBA": "3",
    "WNBA": "7",
    "NFL": "93",
}

TOP_RANKERS_SURVEY_LIMIT = 15
PARSED_PICK_CACHE_TTL_SECONDS = 300


def _normalize_date(value: str) -> Optional[str]:
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value or "")
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))).date().isoformat()
    except ValueError:
        return None


def _publication_evidence(soup: BeautifulSoup) -> tuple[Optional[str], str, str]:
    """Read explicit publication labels; generic page/game dates are ambiguous."""
    date_pattern = re.compile(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})")
    time_pattern = re.compile(r"(?:T|\s)(\d{1,2}:\d{2})(?::\d{2})?")
    label = soup.find(string=re.compile(r"發文時間|發表時間|發布時間|預測時間|推牌時間|發文日期|預測日期"))
    candidates = [label.parent.get_text(" ", strip=True) if label and label.parent else ""]
    for attr in ("data-published-at", "datetime", "data-publish-time"):
        node = soup.find(attrs={attr: True})
        if node:
            candidates.append(str(node.get(attr)))
    for text in candidates:
        date_match = date_pattern.search(text)
        if not date_match:
            continue
        pick_date = _normalize_date(date_match.group(1))
        if not pick_date:
            continue
        iso_match = re.search(
            r"\d{4}[-/]\d{1,2}[-/]\d{1,2}[T ]\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?",
            text,
        )
        if iso_match:
            try:
                iso_value = iso_match.group(0).replace("Z", "+00:00")
                iso_value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", iso_value)
                published_at = datetime.fromisoformat(iso_value)
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=TAIPEI_TZ)
                published_at = published_at.astimezone(timezone.utc)
                return published_at.astimezone(TAIPEI_TZ).date().isoformat(), published_at.isoformat(), "DATETIME"
            except ValueError:
                pass
        time_match = time_pattern.search(text)
        if not time_match:
            return pick_date, "TIMESTAMP_UNKNOWN", "DATE_ONLY"
        try:
            taipei_dt = datetime.fromisoformat(f"{pick_date}T{time_match.group(1)}:00").replace(tzinfo=TAIPEI_TZ)
            return pick_date, taipei_dt.astimezone(timezone.utc).isoformat(), "DATETIME"
        except ValueError:
            return pick_date, "TIMESTAMP_UNKNOWN", "DATE_ONLY"
    return None, "TIMESTAMP_UNKNOWN", "UNKNOWN"


class PlaysportExpertAdapter:
    """Extracts authentic expert recommendations from Playsport Leaderboards & Member Pages."""

    SOURCE_CATEGORY = "VERIFIED_EXPERT"
    INDEPENDENCE_GROUP = "PLAYSPORT_EXPERT"

    def __init__(self, scraper: Optional[PlaysportScraper] = None):
        self.scraper = scraper or PlaysportScraper()
        self._expert_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._parsed_picks_cache: Dict[str, List[VerifiedExpertPick]] = {}
        self._parsed_picks_at: Dict[str, float] = {}
        self._source_status: Dict[str, Any] = {}
        self._force_refresh_alliances: set[str] = set()
        self._last_parse_diagnostics: List[Dict[str, Any]] = []
        self._parse_diagnostics_by_alliance: Dict[str, List[Dict[str, Any]]] = {}

    def get_source_status(self) -> Dict[str, Any]:
        """Expose board and member-page freshness/failure state to callers."""
        return dict(self._source_status)

    def get_parse_diagnostics(self, alliance_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return raw member rows that were excluded from verified pick voting."""
        if alliance_id is None:
            rows = [row for group in self._parse_diagnostics_by_alliance.values() for row in group]
        else:
            rows = self._parse_diagnostics_by_alliance.get(str(alliance_id), [])
        return [dict(row) for row in rows]

    def invalidate_parsed_cache(self, alliance_id: Optional[str] = None) -> None:
        """Drop parsed picks only; leave HTTP cache intact unless refresh is requested."""
        if alliance_id is None:
            self._parsed_picks_cache.clear()
            self._parsed_picks_at.clear()
            return
        key = str(alliance_id)
        self._parsed_picks_cache.pop(key, None)
        self._parsed_picks_at.pop(key, None)

    def refresh(self, alliance_id: Optional[str] = None) -> None:
        """Force fresh public board/member-page requests on the next lookup."""
        self.invalidate_parsed_cache(alliance_id)
        if alliance_id is None:
            self._force_refresh_alliances.update(set(ALLIANCE_MAP.values()))
        else:
            self._force_refresh_alliances.add(str(alliance_id))

    def _get_alliance_id(self, leg: TaiwanLeg) -> str:
        """Determine Playsport alliance_id from leg sport and league."""
        if leg.sport == "baseball":
            if "CPBL" in leg.league or "中職" in leg.league:
                return "6"
            if "NPB" in leg.league or "日棒" in leg.league:
                return "2"
            if "KBO" in leg.league or "韓棒" in leg.league:
                return "9"
            return "1"  # Default MLB
        if leg.sport == "soccer":
            return "4"
        if leg.sport == "football":
            return "93"
        if leg.sport == "basketball":
            return "7"
        return "1"

    def _load_expert_picks_for_alliance(self, alliance_id: str) -> List[VerifiedExpertPick]:
        """Load and parse picks from top rankers for a given alliance."""
        cached_at = self._parsed_picks_at.get(alliance_id, 0)
        if alliance_id in self._parsed_picks_cache and cached_at and time.time() - cached_at < PARSED_PICK_CACHE_TTL_SECONDS:
            return self._parsed_picks_cache[alliance_id]

        force_refresh = alliance_id in self._force_refresh_alliances

        try:
            board_result = self.scraper.fetch_expert_leaderboards(alliance_id=alliance_id, force_refresh=force_refresh)
        except (AttributeError, TypeError):
            # Keep compatibility with older scraper test doubles.
            try:
                board_result = self.scraper.fetch_expert_leaderboards(alliance_id=alliance_id)
            except AttributeError:
                board_result = {"rankers": self.scraper.fetch_expert_leaderboard(alliance_id=alliance_id),
                            "source_status": "UNKNOWN", "source_urls": [], "observed_at": None,
                            "cache_age_minutes": None, "boards": {}}
        except Exception as exc:
            logger.warning("Failed to fetch expert boards for alliance %s: %s", alliance_id, exc)
            board_result = {"rankers": [], "source_status": "FETCH_ERROR", "source_urls": [],
                            "observed_at": None, "cache_age_minutes": None, "boards": {}}
        rankers = board_result.get("rankers", [])
        all_picks: List[VerifiedExpertPick] = []
        member_statuses: List[Dict[str, Any]] = []
        alliance_diagnostics: List[Dict[str, Any]] = []

        # Survey top 10-15 rankers on the billboard
        for ranker in rankers[:TOP_RANKERS_SURVEY_LIMIT]:
            userid = ranker.get("userid")
            if not userid:
                continue
            try:
                try:
                    member_result = self.scraper.fetch_member_prediction_page_result(
                        userid=userid, alliance_id=alliance_id, force_refresh=force_refresh)
                except TypeError:
                    member_result = self.scraper.fetch_member_prediction_page_result(userid=userid, alliance_id=alliance_id)
            except AttributeError:
                html = self.scraper.fetch_member_prediction_page(userid=userid, alliance_id=alliance_id)
                member_result = {"html": html, "source_url": f"https://www.playsport.cc/member/{userid}/prediction?allianceid={alliance_id}",
                                 "source_status": "UNKNOWN", "observed_at": None, "cache_age_minutes": None}
            except Exception as exc:
                member_result = {"html": None, "source_url": f"https://www.playsport.cc/member/{userid}/prediction?allianceid={alliance_id}",
                                 "source_status": "FETCH_ERROR", "failure_status": str(exc), "observed_at": None,
                                 "cache_age_minutes": None}
            member_statuses.append({key: member_result.get(key) for key in (
                "source_url", "source_status", "failure_status", "observed_at", "cache_age_minutes")})
            html = member_result.get("html")
            if not html:
                continue

            parse_ranker = dict(ranker)
            parse_ranker.update({
                "source_url": member_result.get("source_url"),
                "source_status": member_result.get("source_status", "UNKNOWN"),
                "observed_at": member_result.get("observed_at"),
                "cache_age_minutes": member_result.get("cache_age_minutes"),
            })
            parsed = self._parse_member_prediction_html(html, alliance_id, parse_ranker)
            alliance_diagnostics.extend(self._last_parse_diagnostics)
            if member_statuses:
                member_statuses[-1]["unverified_row_count"] = len(self._last_parse_diagnostics)
                member_statuses[-1]["unverified_rows"] = [dict(row) for row in self._last_parse_diagnostics]
            for pick in parsed:
                pick.source_metadata = {
                    "source_kind": "member_prediction_page",
                    "board_kinds": list(ranker.get("board_kinds", [])),
                    "source_urls": list(board_result.get("source_urls", [])) + [member_result.get("source_url")],
                    "observed_at": member_result.get("observed_at"),
                    "source_status": member_result.get("source_status", "UNKNOWN"),
                    "cache_age_minutes": member_result.get("cache_age_minutes"),
                    "publication_time_precision": getattr(pick, "publication_time_precision", "UNKNOWN"),
                    "historical_win_rate": ranker.get("historical_win_rate"),
                    "board_entries": ranker.get("board_entries", []),
                }
            all_picks.extend(parsed)

        # A user can occur on both boards; a repeated row on their page is still one actual pick.
        unique: Dict[tuple, VerifiedExpertPick] = {}
        for pick in all_picks:
            key = (pick.expert_userid, pick.away_team, pick.home_team, pick.market, pick.side,
                   pick.line, pick.pick_date)
            unique.setdefault(key, pick)
        all_picks = list(unique.values())
        self._source_status[alliance_id] = {
            "source_kind": "playsport_public_leaderboards_and_member_pages",
            "board_kinds": ["main_prediction", "win_rate"],
            "source_urls": list(board_result.get("source_urls", [])),
            "observed_at": board_result.get("observed_at"),
            "source_status": board_result.get("source_status", "UNKNOWN"),
            "cache_age_minutes": board_result.get("cache_age_minutes"),
            "publication_time_precision": "UNKNOWN",
            "board_sources": [
                {key: board.get(key) for key in ("source_url", "source_status", "failure_status", "observed_at", "cache_age_minutes")}
                for board in board_result.get("boards", {}).values()
            ],
            "member_pages": member_statuses,
        }
        self._parse_diagnostics_by_alliance[alliance_id] = alliance_diagnostics
        self._parsed_picks_cache[alliance_id] = all_picks
        self._parsed_picks_at[alliance_id] = time.time()
        self._force_refresh_alliances.discard(alliance_id)
        return all_picks

    def _parse_member_prediction_html(
        self, html_text: str, alliance_id: str, ranker: Dict[str, Any]
    ) -> List[VerifiedExpertPick]:
        """Parse only a single, explicitly Taiwan-market pick from one DOM row.

        Ambiguous/international/result rows remain inspectable through
        ``get_parse_diagnostics`` and never become voting picks.
        """
        soup = BeautifulSoup(html_text, "html.parser")
        family_league, family_sport = normalize_league_and_sport("", alliance_id)
        picks: List[VerifiedExpertPick] = []
        diagnostics: List[Dict[str, Any]] = []

        # Unknown publication date stays unknown; board calculation time is not pick time.
        pick_date, pick_timestamp, publication_precision = _publication_evidence(soup)

        tables = soup.find_all("table", class_="sellpredict-item")

        def diagnostic(table, raw_pick: str, reason: str, away_raw: str = "", home_raw: str = "") -> None:
            bet_cell = table.select_one("td.bonusinfo")
            classes = list(bet_cell.get("class", [])) if bet_cell else []
            diagnostics.append({
                "raw_pick": raw_pick,
                "source_url": ranker.get("source_url"),
                "source_status": ranker.get("source_status", "UNKNOWN"),
                "observed_at": ranker.get("observed_at"),
                "cache_age_minutes": ranker.get("cache_age_minutes"),
                "publication_time_precision": publication_precision,
                "pick_date": pick_date,
                "pick_timestamp": pick_timestamp,
                "dom_classes": classes,
                "away_team": away_raw,
                "home_team": home_raw,
                "board_kinds": list(ranker.get("board_kinds", [])),
                "reason": reason,
            })

        payout_result = re.compile(r"(?:贏|輸)\s*\d+(?:\.\d+)?\s*%")
        total_pattern = re.compile(
            r"(?P<side>[大小])\s*(?P<line>\d+(?:\.\d+)?)|(?<!\d)(?P<line_reversed>\d+(?:\.\d+)?)\s*(?P<side_reversed>大分|小分)"
        )
        spread_pattern = re.compile(r"\b(主|客)\s*([+-])\s*(\d+(?:\.\d+)?)")

        for t in tables:
            # Use an event-level competition label when the member page exposes
            # one. Soccer's alliance is a mixed-league family, so missing row
            # competition stays explicitly unknown instead of defaulting EPL.
            competition_node = t.select_one(
                ".football__nameWorld, [data-competition], [data-league-name], [data-league]"
            )
            source_competition = ""
            if competition_node:
                source_competition = str(
                    competition_node.get("data-competition")
                    or competition_node.get("data-league-name")
                    or competition_node.get("data-league")
                    or competition_node.get_text(" ", strip=True)
                ).strip()
            if str(alliance_id) == "4":
                canonical_league, canonical_sport = normalize_league_and_sport(
                    source_competition, alliance_id
                )
            elif source_competition:
                canonical_league, canonical_sport = normalize_league_and_sport(
                    source_competition, alliance_id
                )
            else:
                canonical_league, canonical_sport = family_league, family_sport
            r1 = t.find("tr")
            if not r1:
                diagnostic(t, "", "MISSING_EVENT_ROW")
                continue
            tds = r1.find_all("td")
            if len(tds) < 2:
                diagnostic(t, "", "MISSING_TEAM_CONTEXT")
                continue
            team_cell = tds[1]
            team_text = team_cell.get_text(" ", strip=True)
            parts = team_text.split()
            if len(parts) < 2:
                bet_cell = t.select_one("td.bonusinfo")
                diagnostic(t, bet_cell.get_text(" ", strip=True) if bet_cell else "", "MISSING_TEAM_CONTEXT")
                continue

            away_raw = parts[0].replace("(主)", "").strip()
            home_raw = parts[1].replace("(主)", "").strip()

            can_away = GLOBAL_TEAM_REGISTRY.resolve(away_raw, sport=canonical_sport, league=canonical_league)
            can_home = GLOBAL_TEAM_REGISTRY.resolve(home_raw, sport=canonical_sport, league=canonical_league)

            r2_list = t.find_all("tr")
            if len(r2_list) < 2:
                diagnostic(t, "", "MISSING_PICK_ROW", away_raw, home_raw)
                continue
            r2 = r2_list[1]
            bet_cell = r2.find("td", class_="bonusinfo")
            if not bet_cell:
                diagnostic(t, "", "MISSING_PICK_CELL", away_raw, home_raw)
                continue
            bet_text = bet_cell.get_text(" ", strip=True)
            if not bet_text:
                diagnostic(t, bet_text, "EMPTY_PICK_TEXT", away_raw, home_raw)
                continue
            classes = set(bet_cell.get("class", []))
            in_taiwan_container = bool(t.find_parent("table", class_="bank-tablecon"))
            if "betinfo_i" in classes or "國際盤" in bet_text:
                diagnostic(t, bet_text, "INTERNATIONAL_NON_TAIWAN", away_raw, home_raw)
                continue
            if not in_taiwan_container and "betinfo" not in classes:
                diagnostic(t, bet_text, "UNKNOWN_MARKET_SOURCE_LABEL", away_raw, home_raw)
                continue
            if any(sep in bet_text for sep in ("|", "｜", ";", "；", "/")):
                diagnostic(t, bet_text, "MULTI_CONTEXT", away_raw, home_raw)
                continue
            if payout_result.search(bet_text):
                diagnostic(t, bet_text, "SETTLEMENT_RESULT_NOT_PICK", away_raw, home_raw)
                continue

            # Classify by complete market expressions; never borrow the first
            # number from a row because it may be a result, rank, or another market.
            total_matches = list(total_pattern.finditer(bet_text))
            spread_matches = list(spread_pattern.finditer(bet_text))
            ml_marker = bool(re.search(r"不讓分|獨贏|勝負|[主客]勝", bet_text))
            market_kinds = sum(bool(items) for items in (total_matches, spread_matches)) + int(ml_marker)
            if market_kinds == 0:
                diagnostic(t, bet_text, "UNSUPPORTED_OR_INCOMPLETE_MARKET", away_raw, home_raw)
                continue
            if market_kinds != 1:
                diagnostic(t, bet_text, "MULTI_MARKET_AMBIGUOUS", away_raw, home_raw)
                continue

            market = side = line = None
            if total_matches:
                if len(total_matches) != 1:
                    diagnostic(t, bet_text, "MULTIPLE_TOTAL_DIRECTIONS_OR_LINES", away_raw, home_raw)
                    continue
                match = total_matches[0]
                side_label = match.group("side") or match.group("side_reversed")
                side = side_label[0]
                line = match.group("line") or match.group("line_reversed")
                market = "大小"
            elif spread_matches:
                if len(spread_matches) != 1:
                    diagnostic(t, bet_text, "MULTIPLE_SPREAD_DIRECTIONS_OR_LINES", away_raw, home_raw)
                    continue
                match = spread_matches[0]
                market = "讓分"
                side = match.group(1)
                line = f"{match.group(2)}{match.group(3)}"
                # Any second direction or unsigned line marker means the row
                # contains another selection that this parser cannot disambiguate.
                residual = bet_text.replace(match.group(0), "", 1)
                if re.search(r"(?:主|客)\s*[+-]?\s*\d|讓分|受讓", residual):
                    diagnostic(t, bet_text, "MULTIPLE_SPREAD_DIRECTIONS_OR_LINES", away_raw, home_raw)
                    continue
            else:
                if "和局" in bet_text or "平局" in bet_text:
                    side = "和"
                elif "主" in bet_text and "客" not in bet_text:
                    side = "主"
                elif "客" in bet_text and "主" not in bet_text:
                    side = "客"
                elif away_raw in bet_text and home_raw not in bet_text:
                    side = "客"
                elif home_raw in bet_text and away_raw not in bet_text:
                    side = "主"
                if not side:
                    diagnostic(t, bet_text, "ML_SIDE_AMBIGUOUS", away_raw, home_raw)
                    continue
                market = "不讓分"
                # Result fragments without percentages still aren't an unambiguous pick.
                if re.search(r"\d+\s*分\s*(?:贏|輸)", bet_text):
                    diagnostic(t, bet_text, "SETTLEMENT_RESULT_NOT_PICK", away_raw, home_raw)
                    continue

            if not market or not side or (market in {"大小", "讓分"} and line is None):
                diagnostic(t, bet_text, "UNSUPPORTED_OR_INCOMPLETE_MARKET", away_raw, home_raw)
                continue

            if market and side:
                event_id = str(t.get("gameid") or t.get("data-game-id") or t.get("data-match-id") or "")
                if not event_id:
                    for anchor in t.select("a[href]"):
                        id_match = re.search(r"(?:gameid|matchid|eventid)=(\w+)", anchor.get("href", ""), re.I)
                        if id_match:
                            event_id = id_match.group(1)
                            break
                picks.append(
                    VerifiedExpertPick(
                        expert_userid=str(ranker.get("userid", "")),
                        expert_nickname=str(ranker.get("nickname", "榜首大神")),
                        rank=int(ranker.get("rank", 1)),
                        win_percentage=float(ranker.get("historical_win_rate", ranker.get("winpercentage", 0.0)) or 0.0),
                        wins=int(ranker.get("wingame", 0)),
                        losses=int(ranker.get("losegame", 0)),
                        sport=canonical_sport,
                        league=canonical_league,
                        event_id=event_id,
                        away_team=away_raw,
                        home_team=home_raw,
                        market=market,
                        side=side,
                        line=line,
                        raw_pick=bet_text,
                        pick_date=pick_date,
                        pick_timestamp=pick_timestamp,
                        verified_via="playsport_member_prediction_page",
                    )
                )
                picks[-1].publication_time_precision = publication_precision

        self._last_parse_diagnostics = diagnostics

        return picks

    def _matches_event(self, p: VerifiedExpertPick, leg: TaiwanLeg) -> bool:
        """Check if an expert pick refers to the same match as the TaiwanLeg."""
        if leg.signal_evidence.get("identity_ambiguous"):
            return False
        if p.event_id and leg.event_id and p.event_id != str(leg.event_id):
            return False
        placeholders = {"", "客隊", "主隊", "未知", "unknown", "away", "home", "tbd"}
        raw_names = [str(name or "").strip().casefold() for name in
                     (leg.away_team, leg.home_team, p.away_team, p.home_team)]
        if any(name in placeholders for name in raw_names):
            return False
        def normalize_full_name(name: str) -> str:
            return re.sub(r"[\s()（）\[\]【】,，.。_-]+", "", str(name or "")).casefold()

        normalized_names = [normalize_full_name(name) for name in
                            (leg.away_team, leg.home_team, p.away_team, p.home_team)]
        if any(len(name) < 2 for name in normalized_names):
            return False
        aid = self._get_alliance_id(leg)
        canonical_league, canonical_sport = normalize_league_and_sport(leg.league, aid)
        can_away = GLOBAL_TEAM_REGISTRY.resolve(leg.away_team, sport=canonical_sport, league=canonical_league)
        can_home = GLOBAL_TEAM_REGISTRY.resolve(leg.home_team, sport=canonical_sport, league=canonical_league)
        away_id = can_away.canonical_id if can_away else leg.away_team
        home_id = can_home.canonical_id if can_home else leg.home_team

        p_can_away = GLOBAL_TEAM_REGISTRY.resolve(p.away_team, sport=canonical_sport, league=canonical_league)
        p_can_home = GLOBAL_TEAM_REGISTRY.resolve(p.home_team, sport=canonical_sport, league=canonical_league)
        p_away_id = p_can_away.canonical_id if p_can_away else p.away_team
        p_home_id = p_can_home.canonical_id if p_can_home else p.home_team

        if can_away and can_home and p_can_away and p_can_home:
            return away_id == p_away_id and home_id == p_home_id

        leg_away, leg_home, pick_away, pick_home = normalized_names
        return leg_away == pick_away and leg_home == pick_home

    def _matches_line(self, p: VerifiedExpertPick, leg: TaiwanLeg) -> bool:
        """Verify exact line/spread match.

        A pick of Cubs -1.5 MUST NOT match Cubs -2.5 or Cubs ML.
        A pick of Over 8.5 MUST NOT match Over 9.5.
        """
        if leg.market == "不讓分":
            return p.line is None and leg.line is None

        # Spread and total picks require both exact lines.
        if p.line is None or leg.line is None:
            return False
        if leg.line is not None and p.line is not None:
            try:
                leg_val = float(leg.line)
                p_val = float(p.line)
                return abs(leg_val - p_val) < 1e-4
            except (ValueError, TypeError):
                return str(leg.line).strip() == str(p.line).strip()

        return False

    def _matches_date(self, p: VerifiedExpertPick, leg: TaiwanLeg) -> bool:
        """Verify pick date matches the leg's scheduled game date."""
        if not p.pick_date:
            # Unknown publication date cannot be used to make a pregame claim.
            return False

        # Extract date from leg.start_time_utc or leg.start_time if present
        leg_date = None
        if leg.start_time_utc:
            try:
                timestamp = datetime.fromisoformat(leg.start_time_utc.replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    return False
                leg_date = timestamp.astimezone(TAIPEI_TZ).date().isoformat()
            except (ValueError, TypeError):
                leg_date = None
        elif leg.start_time and re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", leg.start_time):
            m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", leg.start_time)
            if m:
                leg_date = m.group(1).replace("/", "-")

        return bool(leg_date and p.pick_date and leg_date == p.pick_date)

    def _is_pre_event(self, pick: VerifiedExpertPick, leg: TaiwanLeg) -> bool:
        """Require an aware, observed member-page timestamp before an aware event start."""
        if not leg.start_time_utc or not pick.pick_date:
            return False
        try:
            start = datetime.fromisoformat(leg.start_time_utc.replace("Z", "+00:00"))
            if start.tzinfo is None:
                return False
            meta = getattr(pick, "source_metadata", {})
            observed = meta.get("observed_at")
            board_observed = self._source_status.get(self._get_alliance_id(leg), {}).get("observed_at")
            published = pick.pick_timestamp if pick.pick_timestamp != "TIMESTAMP_UNKNOWN" else None
            evidence_times = [value for value in (published, observed, board_observed) if value]
            if not evidence_times:
                return False
            for evidence_time in evidence_times:
                evidence = datetime.fromisoformat(str(evidence_time).replace("Z", "+00:00"))
                if evidence.tzinfo is None or evidence.astimezone(timezone.utc) >= start.astimezone(timezone.utc):
                    return False
            return True
        except (TypeError, ValueError):
            return False

    def get_expert_signal(self, leg: TaiwanLeg) -> Optional[PredictionSignal]:
        """Evaluate multi-expert consensus for this specific TaiwanLeg.

        Requirements:
        1. Exact event identity match.
        2. Exact market match.
        3. Exact line match.
        4. Date validation.
        5. Aggregates all agreeing & opposing experts among top surveyed rankers.

        Returns PredictionSignal if at least one verified expert picked this selection.
        Returns None if no verified expert picked it.
        """
        aid = self._get_alliance_id(leg)
        expert_picks = self._load_expert_picks_for_alliance(aid)

        if not expert_picks:
            return None

        agreeing_picks: List[VerifiedExpertPick] = []
        opposing_picks: List[VerifiedExpertPick] = []

        for p in expert_picks:
            # 1. Match event
            if not self._matches_event(p, leg):
                continue

            # 2. Match date
            if not self._matches_date(p, leg):
                continue

            # A page captured after kickoff cannot substantiate a pregame signal.
            if not self._is_pre_event(p, leg):
                continue

            # 3. Match market
            if p.market != leg.market:
                continue

            # 4. Match exact line
            if not self._matches_line(p, leg):
                continue

            # 5. Check side agreement
            if p.side == leg.side:
                agreeing_picks.append(p)
            else:
                opposing_picks.append(p)

        if not agreeing_picks:
            # Honest reality: No expert chose this specific option
            return None

        agreeing_cnt = len(agreeing_picks)
        opposing_cnt = len(opposing_picks)
        total_voted = agreeing_cnt + opposing_cnt
        consensus_ratio = round(agreeing_cnt / total_voted, 2) if total_voted > 0 else 1.0

        avg_win_pct = round(sum(p.win_percentage for p in agreeing_picks) / agreeing_cnt, 1)
        total_wins = sum(p.wins for p in agreeing_picks)
        total_losses = sum(p.losses for p in agreeing_picks)
        sample_size = total_wins + total_losses

        # Sort agreeing picks by rank (best rank first)
        agreeing_picks.sort(key=lambda x: x.rank)
        top_rank = agreeing_picks[0].rank
        top_expert_name = agreeing_picks[0].expert_nickname

        # Confidence assessment based on consensus and win percentage
        freshness = self._source_status.get(aid, {})
        source_age = freshness.get("cache_age_minutes")
        board_source_fresh = (freshness.get("source_status") == "LIVE" or
                        (freshness.get("source_status") == "CACHED" and source_age is not None and source_age <= 15))
        member_sources_fresh = all(
            getattr(p, "source_metadata", {}).get("source_status") == "LIVE" or
            (getattr(p, "source_metadata", {}).get("source_status") == "CACHED" and
             getattr(p, "source_metadata", {}).get("cache_age_minutes") is not None and
             getattr(p, "source_metadata", {}).get("cache_age_minutes") <= 15)
            for p in agreeing_picks
        )
        source_fresh = board_source_fresh and member_sources_fresh
        if source_fresh and consensus_ratio >= 0.70 and total_voted >= 3:
            confidence = "HIGH"
        elif source_fresh and total_voted >= 1:
            confidence = "MED"
        else:
            confidence = "LOW"

        source_name = f"玩運彩專家群 ({agreeing_cnt}位大神共識 {int(consensus_ratio*100)}%)"

        expert_details = [
            {
                "userid": p.expert_userid,
                "nickname": p.expert_nickname,
                "expert_name": p.expert_nickname,
                "rank": p.rank,
                "win_percentage": p.win_percentage,
                "wins": p.wins,
                "losses": p.losses,
                "raw_pick": p.raw_pick,
                "pick_date": p.pick_date,
                "pick_timestamp": p.pick_timestamp,
                "source_url": f"https://www.playsport.cc/member/{p.expert_userid}/prediction?allianceid={aid}",
                "source_kind": getattr(p, "source_metadata", {}).get("source_kind", "member_prediction_page"),
                "board_kinds": getattr(p, "source_metadata", {}).get("board_kinds", []),
                "publication_time_precision": getattr(p, "publication_time_precision", "UNKNOWN"),
            }
            for p in agreeing_picks
        ]
        signal_source_urls = list(dict.fromkeys(
            list(freshness.get("source_urls", [])) +
            [detail["source_url"] for detail in expert_details]
        ))
        member_statuses = [row.get("source_status", "UNKNOWN") for row in freshness.get("member_pages", [])]
        signal_source_status = ("PARTIAL" if any(status not in ("LIVE", "CACHED") for status in member_statuses)
                                else freshness.get("source_status", "UNKNOWN"))

        return PredictionSignal(
            source_id="playsport_taiwan_experts",
            source_name=source_name,
            source_type="EXPERT",
            event_id=leg.event_id,
            market=leg.market,
            selection=leg.selection,
            probability=None,
            score=avg_win_pct,
            confidence=confidence,
            pick=f"{leg.selection} ({agreeing_cnt}/{total_voted}共識)",
            rank=top_rank,
            source_category=self.SOURCE_CATEGORY,
            independence_group=self.INDEPENDENCE_GROUP,
            timestamp=freshness.get("observed_at") or agreeing_picks[0].pick_timestamp,
            data_as_of=freshness.get("observed_at"),
            data_age_hours=(round(float(source_age) / 60.0, 3) if source_age is not None else None),
            freshness_status=("LIVE" if freshness.get("source_status") == "LIVE" else
                              "FRESH" if source_fresh else "STALE" if freshness.get("source_status") == "STALE_CACHE" else "UNKNOWN"),
            metadata={
                "source_category": self.SOURCE_CATEGORY,
                "independence_group": self.INDEPENDENCE_GROUP,
                "agreeing_count": agreeing_cnt,
                "opposing_count": opposing_cnt,
                "total_voted": total_voted,
                "consensus_ratio": consensus_ratio,
                "historical_win_rate": avg_win_pct,
                "average_win_pct": avg_win_pct,
                "support_ratio": consensus_ratio,
                "probability_semantics": "historical leaderboard win rate; not this event's outcome probability",
                "total_wins": total_wins,
                "total_losses": total_losses,
                "sample_size": sample_size,
                "top_expert_name": top_expert_name,
                "top_rank": top_rank,
                "verified_pick": agreeing_picks[0].raw_pick,
                "expert_details": expert_details,
                "verified_via": "playsport_member_prediction_page",
                "source_kind": freshness.get("source_kind"),
                "board_kinds": freshness.get("board_kinds", []),
                "board_role": "candidate_discovery_only",
                "verified_pick_count": len(expert_details),
                "total_voted": total_voted,
                "source_urls": signal_source_urls,
                "observed_at": freshness.get("observed_at"),
                "source_status": signal_source_status,
                "board_source_status": freshness.get("source_status", "UNKNOWN"),
                "cache_age_minutes": freshness.get("cache_age_minutes"),
                "board_sources": freshness.get("board_sources", []),
                "publication_time_precision": ("DATETIME" if all(getattr(p, "publication_time_precision", "UNKNOWN") == "DATETIME" for p in agreeing_picks)
                                               else "DATE_ONLY" if all(p.pick_date for p in agreeing_picks) else "UNKNOWN"),
                "pick_timestamp": agreeing_picks[0].pick_timestamp,
                "pick_date": agreeing_picks[0].pick_date,
                "member_pages": freshness.get("member_pages", []),
                "confidence_basis": {
                    "support_ratio": consensus_ratio,
                    "verified_same_match_market_line_votes": total_voted,
                    "sources_are_one_platform_family": True,
                    "freshness_verified": source_fresh,
                    "historical_win_rate_used_as_probability": False,
                },
            },
        )
