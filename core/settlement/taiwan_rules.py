#!/usr/bin/env python3
"""Taiwan Sports Lottery Official Settlement Rules Engine (Version 2.0).

PROVENANCE & SPECIFICATION:
- Rule Version: 2026-v2-taiwan-official
- Source: 台灣運彩官方網站 投注規範與各項運動認定說明
  https://www.sportslottery.com.tw/zh-tw/game-rules
- Taiwan Sports Lottery Official Announcement:
  味全龍 vs 台鋼雄鷹 第五局因雨中斷裁定提前結束:
  「不讓分賽前投注有效，其餘尚未出現結果的賽前投注無效退費 (VOID)。」
  https://article.sportslottery.com.tw/zh-tw/announcement/20/5193

Statuses Supported:
- WON: Selection won according to official Taiwan rules.
- LOST: Selection lost.
- PUSH: Line pushed exactly (odds = 1.0).
- VOID: Selection declared void / refund (odds = 1.0).
- PENDING: Game in progress, postponed within window, or not yet officially concluded.
- UNRESOLVED: Score discrepancies or missing definitive data.
- SETTLEMENT_NOT_SUPPORTED: Unsupported novelty/niche sport market.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

RULE_VERSION = "2026-v2-taiwan-official"
SOURCE_URL = "https://www.sportslottery.com.tw/zh-tw/game-rules"
EFFECTIVE_FROM = "2024-01-01"


class OfficialCompletionStatus:
    """Official match completion states under Taiwan Sports Lottery regulations."""
    REGULATION_COMPLETED = "REGULATION_COMPLETED"  # 正常完賽 (棒球滿9局/8.5局/延長賽; 足球90分; 籃球延長賽)
    CALLED_GAME_SHORTENED = "CALLED_GAME_SHORTENED"  # 主辦單位因天候裁定提前結束 (Called Game)
    SUSPENDED_NOT_RESUMED = "SUSPENDED_NOT_RESUMED"  # 保留比賽未於補賽窗口期內復賽完成
    POSTPONED_BEYOND_WINDOW = "POSTPONED_BEYOND_WINDOW"  # 賽事延期且超出台彩有效窗口
    CANCELLED = "CANCELLED"  # 賽事取消
    IN_PROGRESS = "IN_PROGRESS"  # 比賽進行中


@dataclass
class SettlementResult:
    """Structured settlement outcome containing full rule lineage."""
    status: str                         # 'WON', 'LOST', 'PUSH', 'VOID', 'PENDING', 'UNRESOLVED'
    reason: str
    rule_version: str = RULE_VERSION
    source_url: str = SOURCE_URL
    effective_odds: float = 1.0        # 1.0 for VOID/PUSH, original for WON, 0.0 for LOST
    market_category: str = ""
    is_called_game: bool = False

    def __iter__(self) -> Iterator[str]:
        """Allows unpacking as: status, reason = evaluate_taiwan_market(...)."""
        yield self.status
        yield self.reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "rule_version": self.rule_version,
            "source_url": self.source_url,
            "effective_odds": self.effective_odds,
            "market_category": self.market_category,
            "is_called_game": self.is_called_game,
        }


def resolve_settlement_rule_id(sport: str, league: str, market: str) -> str:
    """Deterministically assign official settlement rule ID."""
    sport_lower = str(sport).lower()
    league_upper = str(league).upper()
    market_str = str(market)

    if sport_lower == "baseball" or "棒" in league_upper or "MLB" in league_upper or "NPB" in league_upper or "CPBL" in league_upper:
        if "不讓分" in market_str or "獨贏" in market_str:
            return "MLB_FULLGAME_ML"
        elif "讓分" in market_str:
            return "MLB_FULLGAME_SPREAD"
        elif "大小" in market_str or "總分" in market_str:
            return "MLB_FULLGAME_TOTAL"
        return "BASEBALL_FULLGAME_OTHER"

    elif sport_lower == "soccer" or "足" in league_upper or "EPL" in league_upper or "LA LIGA" in league_upper or "LALIGA" in league_upper or "PREMIER" in league_upper or "CHAMPIONS" in league_upper:
        if "不讓分" in market_str or "和局" in market_str or "獨贏" in market_str or "1X2" in market_str.upper():
            return "SOCCER_90MIN_1X2"
        elif "大小" in market_str or "總分" in market_str:
            return "SOCCER_90MIN_TOTAL"
        elif "讓分" in market_str:
            return "SOCCER_90MIN_SPREAD"
        return "SOCCER_90MIN_OTHER"

    elif sport_lower == "basketball" or "籃" in league_upper or "NBA" in league_upper or "WNBA" in league_upper:
        if "讓分" in market_str:
            return "NBA_FULLGAME_SPREAD"
        elif "大小" in market_str or "總分" in market_str:
            return "NBA_FULLGAME_TOTAL"
        elif "不讓分" in market_str or "獨贏" in market_str:
            return "NBA_FULLGAME_ML"
        return "BASKETBALL_FULLGAME_OTHER"

    elif sport_lower == "football" or "美足" in league_upper or "NFL" in league_upper:
        if "不讓分" in market_str:
            return "NFL_FULLGAME_ML"
        elif "讓分" in market_str:
            return "NFL_FULLGAME_SPREAD"
        elif "大小" in market_str:
            return "NFL_FULLGAME_TOTAL"
        return "NFL_FULLGAME_OTHER"

    return "GENERIC_FULLGAME"


class TaiwanSettlementRules:
    """Official Taiwan Sports Lottery rules engine v2."""

    RULE_VERSION = RULE_VERSION
    SOURCE_URL = SOURCE_URL

    @classmethod
    def evaluate_taiwan_market(
        cls,
        rule_id: str,
        market: str,
        selection: str,
        line: Optional[float],
        away_score: int,
        home_score: int,
        side: str = "",
        is_postponed: bool = False,
        postponed_beyond_window: bool = False,
        game_status: str = "Final",
        innings_completed: Optional[float] = None,
        soccer_regulation_away: Optional[int] = None,
        soccer_regulation_home: Optional[int] = None,
        official_completion_status: Optional[str] = None,
    ) -> SettlementResult:
        """Evaluate market outcome strictly according to Taiwan Sports Lottery rules v2.

        Returns SettlementResult which can be unpacked as (status, reason).
        """
        # 1. Postponement and Cancellation Checks
        if is_postponed:
            if postponed_beyond_window:
                return SettlementResult(
                    status="VOID",
                    reason="賽事因延期且超出台彩有效補賽窗口，判定為無效投注 (VOID 退費/賠率1.0)",
                    effective_odds=1.0,
                )
            return SettlementResult(
                status="PENDING",
                reason="賽事延期但仍在有效補賽窗口內，維持等待補賽賽果 (PENDING)",
            )

        if official_completion_status in [
            OfficialCompletionStatus.SUSPENDED_NOT_RESUMED,
            OfficialCompletionStatus.POSTPONED_BEYOND_WINDOW,
            OfficialCompletionStatus.CANCELLED,
        ]:
            return SettlementResult(
                status="VOID",
                reason=f"賽事因中斷未復賽或取消 ({official_completion_status})，依台彩規章判定無效投注 (VOID)",
                effective_odds=1.0,
            )

        if game_status not in ["Final", "Completed", "Game Over"] and official_completion_status not in [
            OfficialCompletionStatus.REGULATION_COMPLETED,
            OfficialCompletionStatus.CALLED_GAME_SHORTENED,
        ]:
            return SettlementResult(
                status="PENDING",
                reason=f"賽事進行中或尚未完賽 (Status: {game_status})",
            )

        # Determine if this is a shortened/called game
        is_called_game = (
            official_completion_status == OfficialCompletionStatus.CALLED_GAME_SHORTENED
            or (innings_completed is not None and innings_completed < 8.5 and "MLB" in rule_id)
        )

        # -------------------------------------------------------------
        # 2. Baseball Rules (MLB, CPBL, NPB)
        # -------------------------------------------------------------
        if "MLB" in rule_id or "BASEBALL" in rule_id:
            # A. Called Game / Shortened Game Exception (官方裁定提前結束)
            if is_called_game:
                # Taiwan Lottery Rule:
                # 賽事中斷經主辦單位裁定提前結束時:
                # 1. 「不讓分」賽前投注有效，依裁定當下比分結算。
                # 2. 「讓分」因未滿法定9局，判定無效 (VOID)。
                # 3. 「大小分」：若中斷時已達門檻分出勝負則有效；尚未出現結果者判定無效 (VOID)。
                if rule_id.endswith("_ML") or rule_id.endswith("-ML") or "MONEYLINE" in rule_id or "不讓分" in market or market == "獨贏":
                    if away_score == home_score:
                        return SettlementResult(
                            status="VOID",
                            reason="棒球因雨/裁定提前結束且為平手，依台彩規章不讓分判定無效退費 (VOID, 賠率1.0)",
                            effective_odds=1.0,
                            is_called_game=True,
                        )
                    is_away = "客" in selection or side == "客"
                    is_home = "主" in selection or side == "主"
                    won = (away_score > home_score) if is_away else (home_score > away_score)
                    return SettlementResult(
                        status="WON" if won else "LOST",
                        reason=f"棒球裁定提前結束 (Called Game)，依台彩官方規章不讓分有效: 客 {away_score} vs 主 {home_score}",
                        is_called_game=True,
                    )

                elif "SPREAD" in rule_id or "讓分" in market:
                    return SettlementResult(
                        status="VOID",
                        reason=f"棒球因雨/裁定提前結束 (未滿法定 9 局)，依台彩官方規章讓分玩法無效退費 (VOID, 賠率1.0)",
                        effective_odds=1.0,
                        is_called_game=True,
                    )

                elif "TOTAL" in rule_id or "大小" in market:
                    tot_line = line
                    if tot_line is None:
                        m = re.search(r"(\d+\.?\d*)", selection)
                        tot_line = float(m.group(1)) if m else 7.5

                    actual_total = away_score + home_score

                    # If already over the line before stoppage, "大分" is already definitively WON
                    if actual_total > tot_line:
                        if "大" in selection:
                            return SettlementResult(
                                status="WON",
                                reason=f"棒球裁定提前結束，但總分 {actual_total} 已超過盤口 {tot_line}，結果已確定，大分有效中獎 (WON)",
                                is_called_game=True,
                            )
                        else:
                            return SettlementResult(
                                status="LOST",
                                reason=f"棒球裁定提前結束，但總分 {actual_total} 已超過盤口 {tot_line}，結果已確定，小分未過關 (LOST)",
                                is_called_game=True,
                            )
                    else:
                        # Total hasn't exceeded yet -> outcome was not yet determined -> VOID
                        return SettlementResult(
                            status="VOID",
                            reason=f"棒球裁定提前結束，總分 {actual_total} 尚未超過盤口 {tot_line}，屬尚未出現結果之投注，依台彩規章無效退費 (VOID, 賠率1.0)",
                            effective_odds=1.0,
                            is_called_game=True,
                        )

                return SettlementResult(
                    status="VOID",
                    reason="棒球裁定提前結束，其餘尚未出現結果之玩法依台彩規章無效退費 (VOID, 賠率1.0)",
                    effective_odds=1.0,
                    is_called_game=True,
                )

            # B. Standard Regulation / Extra Innings Completed
            # Moneyline
            if rule_id.endswith("_ML") or rule_id.endswith("-ML") or "MONEYLINE" in rule_id or "不讓分" in market or market == "獨贏":
                if away_score == home_score:
                    return SettlementResult(
                        status="VOID",
                        reason="棒球賽事法定與延長賽結束為平手，不讓分玩法判定無效退費 (VOID, 賠率1.0)",
                        effective_odds=1.0,
                    )
                is_away = "客" in selection or side == "客"
                is_home = "主" in selection or side == "主"
                won = (away_score > home_score) if is_away else (home_score > away_score)
                return SettlementResult(
                    status="WON" if won else "LOST",
                    reason=f"棒球不讓分結算 (含延長賽): 客 {away_score} vs 主 {home_score}",
                )

            # Spread (讓分)
            elif "SPREAD" in rule_id or "讓分" in market:
                spread = line
                if spread is None:
                    m = re.search(r"([+-]?\d+\.?\d*)", selection)
                    spread = float(m.group(1)) if m else 0.0

                is_away = "客" in selection or side == "客"
                if is_away:
                    adjusted = away_score + spread
                    if adjusted == home_score:
                        return SettlementResult(
                            status="PUSH",
                            reason=f"讓分平手 (Push), 賠率計算為 1.0 (客 {away_score} + {spread} == 主 {home_score})",
                            effective_odds=1.0,
                        )
                    return SettlementResult(
                        status="WON" if adjusted > home_score else "LOST",
                        reason=f"讓分結算: 客 {adjusted} vs 主 {home_score}",
                    )
                else:
                    adjusted = home_score + spread
                    if adjusted == away_score:
                        return SettlementResult(
                            status="PUSH",
                            reason=f"讓分平手 (Push), 賠率計算為 1.0 (主 {home_score} + {spread} == 客 {away_score})",
                            effective_odds=1.0,
                        )
                    return SettlementResult(
                        status="WON" if adjusted > away_score else "LOST",
                        reason=f"讓分結算: 主 {adjusted} vs 客 {away_score}",
                    )

            # Total (大小分)
            elif "TOTAL" in rule_id or "大小" in market:
                tot_line = line
                if tot_line is None:
                    m = re.search(r"(\d+\.?\d*)", selection)
                    tot_line = float(m.group(1)) if m else 7.5

                actual_total = away_score + home_score
                if actual_total == tot_line:
                    return SettlementResult(
                        status="PUSH",
                        reason=f"大小分平手 (Push), 賠率計算為 1.0 (總分 {actual_total} == 盤口 {tot_line})",
                        effective_odds=1.0,
                    )
                if "大" in selection:
                    return SettlementResult(
                        status="WON" if actual_total > tot_line else "LOST",
                        reason=f"大小分結算: 總分 {actual_total} vs 盤口 {tot_line}",
                    )
                elif "小" in selection:
                    return SettlementResult(
                        status="WON" if actual_total < tot_line else "LOST",
                        reason=f"大小分結算: 總分 {actual_total} vs 盤口 {tot_line}",
                    )

        # -------------------------------------------------------------
        # 3. Soccer Rules (STRICTLY 90 MINS + STOPPAGE TIME)
        # -------------------------------------------------------------
        elif "SOCCER" in rule_id:
            reg_away = soccer_regulation_away if soccer_regulation_away is not None else away_score
            reg_home = soccer_regulation_home if soccer_regulation_home is not None else home_score

            if "1X2" in rule_id or "不讓分" in market or "和局" in market:
                is_draw_selection = "和" in selection or market == "和局"
                if reg_away == reg_home:
                    if is_draw_selection:
                        return SettlementResult(
                            status="WON",
                            reason=f"足球90分鐘常規賽和局: 客 {reg_away} : 主 {reg_home}",
                        )
                    return SettlementResult(
                        status="LOST",
                        reason=f"足球90分鐘常規賽和局: 客 {reg_away} : 主 {reg_home}",
                    )
                if is_draw_selection:
                    return SettlementResult(
                        status="LOST",
                        reason=f"足球90分鐘常規賽非和局: 客 {reg_away} vs 主 {reg_home}",
                    )
                is_away = "客" in selection or side == "客"
                is_home = "主" in selection or side == "主"
                won = (reg_away > reg_home) if is_away else (reg_home > reg_away)
                return SettlementResult(
                    status="WON" if won else "LOST",
                    reason=f"足球90分鐘常規賽結算: 客 {reg_away} vs 主 {reg_home}",
                )

            elif "TOTAL" in rule_id or "大小" in market:
                tot_line = line
                if tot_line is None:
                    m = re.search(r"(\d+\.?\d*)", selection)
                    tot_line = float(m.group(1)) if m else 2.5
                actual_total = reg_away + reg_home
                if actual_total == tot_line:
                    return SettlementResult(
                        status="PUSH",
                        reason=f"足球90分鐘大小分平手 (Push, 總分 {actual_total} == {tot_line})",
                        effective_odds=1.0,
                    )
                if "大" in selection:
                    return SettlementResult(
                        status="WON" if actual_total > tot_line else "LOST",
                        reason=f"足球90分鐘大小分結算: 總分 {actual_total} vs 盤口 {tot_line}",
                    )
                elif "小" in selection:
                    return SettlementResult(
                        status="WON" if actual_total < tot_line else "LOST",
                        reason=f"足球90分鐘大小分結算: 總分 {actual_total} vs 盤口 {tot_line}",
                    )

            elif "SPREAD" in rule_id or "讓分" in market:
                spread = line
                if spread is None:
                    m = re.search(r"([+-]?\d+\.?\d*)", selection)
                    spread = float(m.group(1)) if m else 0.0
                is_away = "客" in selection or side == "客"
                if is_away:
                    adj = reg_away + spread
                    if adj == reg_home:
                        return SettlementResult(
                            status="PUSH",
                            reason=f"足球讓分平手 (Push, 客 {adj} == 主 {reg_home})",
                            effective_odds=1.0,
                        )
                    return SettlementResult(
                        status="WON" if adj > reg_home else "LOST",
                        reason=f"足球讓分結算: 客 {adj} vs 主 {reg_home}",
                    )
                else:
                    adj = reg_home + spread
                    if adj == reg_away:
                        return SettlementResult(
                            status="PUSH",
                            reason=f"足球讓分平手 (Push, 主 {adj} == 客 {reg_away})",
                            effective_odds=1.0,
                        )
                    return SettlementResult(
                        status="WON" if adj > reg_away else "LOST",
                        reason=f"足球讓分結算: 主 {adj} vs 客 {reg_away}",
                    )

        # -------------------------------------------------------------
        # 4. Basketball & Football Rules (INCLUDES OVERTIME)
        # -------------------------------------------------------------
        elif "NBA" in rule_id or "BASKETBALL" in rule_id or "NFL" in rule_id or "FOOTBALL" in rule_id:
            if rule_id.endswith("_ML") or rule_id.endswith("-ML") or "MONEYLINE" in rule_id or "不讓分" in market:
                if away_score == home_score:
                    return SettlementResult(
                        status="VOID",
                        reason="賽事含延長賽仍平手，不讓分判定無效退費 (VOID, 賠率1.0)",
                        effective_odds=1.0,
                    )
                is_away = "客" in selection or side == "客"
                won = (away_score > home_score) if is_away else (home_score > away_score)
                return SettlementResult(
                    status="WON" if won else "LOST",
                    reason=f"不讓分結算 (含延長賽): 客 {away_score} vs 主 {home_score}",
                )

            elif "SPREAD" in rule_id or "讓分" in market:
                spread = line
                if spread is None:
                    m = re.search(r"([+-]?\d+\.?\d*)", selection)
                    spread = float(m.group(1)) if m else 0.0
                is_away = "客" in selection or side == "客"
                if is_away:
                    adj = away_score + spread
                    if adj == home_score:
                        return SettlementResult(
                            status="PUSH",
                            reason=f"讓分平手 (Push, 賠率1.0)",
                            effective_odds=1.0,
                        )
                    return SettlementResult(
                        status="WON" if adj > home_score else "LOST",
                        reason=f"讓分結算: 客 {adj} vs 主 {home_score}",
                    )
                else:
                    adj = home_score + spread
                    if adj == away_score:
                        return SettlementResult(
                            status="PUSH",
                            reason=f"讓分平手 (Push, 賠率1.0)",
                            effective_odds=1.0,
                        )
                    return SettlementResult(
                        status="WON" if adj > away_score else "LOST",
                        reason=f"讓分結算: 主 {adj} vs 客 {away_score}",
                    )

            elif "TOTAL" in rule_id or "大小" in market:
                tot_line = line
                if tot_line is None:
                    m = re.search(r"(\d+\.?\d*)", selection)
                    tot_line = float(m.group(1)) if m else 215.5
                actual_total = away_score + home_score
                if actual_total == tot_line:
                    return SettlementResult(
                        status="PUSH",
                        reason=f"大小分平手 (Push, 賠率1.0)",
                        effective_odds=1.0,
                    )
                if "大" in selection:
                    return SettlementResult(
                        status="WON" if actual_total > tot_line else "LOST",
                        reason=f"大小分結算: 總分 {actual_total} vs 盤口 {tot_line}",
                    )
                elif "小" in selection:
                    return SettlementResult(
                        status="WON" if actual_total < tot_line else "LOST",
                        reason=f"大小分結算: 總分 {actual_total} vs 盤口 {tot_line}",
                    )

        return SettlementResult(
            status="SETTLEMENT_NOT_SUPPORTED",
            reason=f"尚未支援此玩法或聯賽規則 (Rule: {rule_id}, Market: {market})",
        )
