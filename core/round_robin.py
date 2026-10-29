#!/usr/bin/env python3
"""Taiwan Sports Lottery Round Robin (過關組合 / 輪串) Engine.

Computes official Taiwan Sports Lottery combination bets (3串4, 4串5, 4串11, 5串16, 5串26, 6串22, etc.),
generates sub-parlay combinations, and evaluates resilience / breakeven analysis
(e.g., "倒 1 關還能拿回多少錢？是否保本？").
"""

from __future__ import annotations

import itertools
import math
from typing import Any, Dict, List, Optional, Tuple


# Official Taiwan Sports Lottery Round Robin Specifications
# Maps number of matches N -> dict of combination codes
ROUND_ROBIN_SPECS: Dict[int, Dict[str, Dict[str, Any]]] = {
    3: {
        "3_3": {"sub_sizes": [2], "count": 3, "label": "3 串 3 (2 關共 3 注)", "desc": "包含 3 注 2 關組合"},
        "3_4": {"sub_sizes": [2, 3], "count": 4, "label": "3 串 4 (2關+3關, 共 4 注)", "desc": "包含 3 注 2 關 + 1 注 3 關"},
        "3_7": {"sub_sizes": [1, 2, 3], "count": 7, "label": "3 串 7 (含單場共 7 注)", "desc": "全覆蓋：3 注單場 + 3 注 2 關 + 1 注 3 關"},
    },
    4: {
        "4_4": {"sub_sizes": [3], "count": 4, "label": "4 串 4 (3 關共 4 注)", "desc": "包含 4 注 3 關組合"},
        "4_5": {"sub_sizes": [3, 4], "count": 5, "label": "4 串 5 (3關+4關, 共 5 注 - 經典防倒保本)", "desc": "包含 4 注 3 關 + 1 注 4 關 (最熱門防倒 1 關組合)"},
        "4_6": {"sub_sizes": [2], "count": 6, "label": "4 串 6 (2 關共 6 注)", "desc": "包含 6 注 2 關組合"},
        "4_11": {"sub_sizes": [2, 3, 4], "count": 11, "label": "4 串 11 (2關+3關+4關, 共 11 注 - 雙層避險)", "desc": "包含 6 注 2 關 + 4 注 3 關 + 1 注 4 關 (倒 2 關仍有機會保本)"},
        "4_15": {"sub_sizes": [1, 2, 3, 4], "count": 15, "label": "4 串 15 (含單場共 15 注)", "desc": "全覆蓋：4 注單場 + 6 注 2 關 + 4 注 3 關 + 1 注 4 關"},
    },
    5: {
        "5_5": {"sub_sizes": [4], "count": 5, "label": "5 串 5 (4 關共 5 注)", "desc": "包含 5 注 4 關組合"},
        "5_6": {"sub_sizes": [4, 5], "count": 6, "label": "5 串 6 (4關+5關, 共 6 注 - 5關防倒首選)", "desc": "包含 5 注 4 關 + 1 注 5 關"},
        "5_10": {"sub_sizes": [2], "count": 10, "label": "5 串 10 (2 關共 10 注)", "desc": "包含 10 注 2 關組合"},
        "5_16": {"sub_sizes": [3, 4, 5], "count": 16, "label": "5 串 16 (3關+4關+5關, 共 16 注)", "desc": "包含 10 注 3 關 + 5 注 4 關 + 1 注 5 關"},
        "5_20": {"sub_sizes": [2, 3], "count": 20, "label": "5 串 20 (2關+3關, 共 20 注)", "desc": "包含 10 注 2 關 + 10 注 3 關"},
        "5_26": {"sub_sizes": [2, 3, 4, 5], "count": 26, "label": "5 串 26 (2關至5關, 共 26 注 - 終極防空護盾)", "desc": "包含 10 注 2 關 + 10 注 3 關 + 5 注 4 關 + 1 注 5 關"},
    },
    6: {
        "6_6": {"sub_sizes": [5], "count": 6, "label": "6 串 6 (5 關共 6 注)", "desc": "包含 6 注 5 關組合"},
        "6_7": {"sub_sizes": [5, 6], "count": 7, "label": "6 串 7 (5關+6關, 共 7 注 - 6關防倒首選)", "desc": "包含 6 注 5 關 + 1 注 6 關"},
        "6_15": {"sub_sizes": [2], "count": 15, "label": "6 串 15 (2 關共 15 注)", "desc": "包含 15 注 2 關組合"},
        "6_20": {"sub_sizes": [3], "count": 20, "label": "6 串 20 (3 關共 20 注)", "desc": "包含 20 注 3 關組合"},
        "6_22": {"sub_sizes": [4, 5, 6], "count": 22, "label": "6 串 22 (4關+5關+6關, 共 22 注)", "desc": "包含 15 注 4 關 + 6 注 5 關 + 1 注 6 關"},
        "6_35": {"sub_sizes": [3, 4], "count": 35, "label": "6 串 35 (3關+4關, 共 35 注)", "desc": "包含 20 注 3 關 + 15 注 4 關"},
        "6_42": {"sub_sizes": [3, 4, 5, 6], "count": 42, "label": "6 串 42 (3關至6關, 共 42 注)", "desc": "包含 20 注 3 關 + 15 注 4 關 + 6 注 5 關 + 1 注 6 關"},
        "6_57": {"sub_sizes": [2, 3, 4, 5, 6], "count": 57, "label": "6 串 57 (2關至6關, 共 57 注 - 豪華大滿貫)", "desc": "包含 15 注 2 關 + 20 注 3 關 + 15 注 4 關 + 6 注 5 關 + 1 注 6 關"},
    },
}


class RoundRobinEngine:
    """Calculates and simulates Taiwan Sports Lottery Round Robin bets."""

    @staticmethod
    def get_supported_combinations(num_legs: int) -> Dict[str, Dict[str, Any]]:
        """Return available combination specs for given number of legs."""
        return ROUND_ROBIN_SPECS.get(num_legs, {})

    @staticmethod
    def generate_sub_bets(legs: List[Dict[str, Any]], sub_sizes: List[int]) -> List[Dict[str, Any]]:
        """Generate all distinct sub-parlays for given subset sizes."""
        sub_bets = []
        n = len(legs)
        for k in sub_sizes:
            if k > n:
                continue
            for combo_indices in itertools.combinations(range(n), k):
                sub_legs = [legs[i] for i in combo_indices]
                odds_val = 1.0
                for l in sub_legs:
                    l_odds = float(l.get("odds") or l.get("taiwan_odds", 1.0))
                    odds_val *= l_odds
                sub_bets.append({
                    "combo_k": k,
                    "indices": combo_indices,
                    "legs": sub_legs,
                    "odds": round(odds_val, 4),
                    "summary": f"{k} 關組合: " + " × ".join(str(l.get('selection')) for l in sub_legs),
                })
        return sub_bets

    @classmethod
    def simulate_resilience(
        cls,
        legs: List[Dict[str, Any]],
        combo_key: str,
        unit_stake: float = 10.0,
    ) -> Dict[str, Any]:
        """Simulate payout matrix across all outcomes (All-win, 1-miss, 2-misses)."""
        num_legs = len(legs)
        specs = cls.get_supported_combinations(num_legs)
        spec = specs.get(combo_key)
        if not spec:
            raise ValueError(f"不支援 {num_legs} 場的過關組合代碼: {combo_key}")

        sub_sizes = spec["sub_sizes"]
        sub_bets = cls.generate_sub_bets(legs, sub_sizes)
        total_combinations = len(sub_bets)
        total_stake = round(total_combinations * unit_stake, 2)

        # 1. Best Case: 全過 (All N legs win)
        all_win_payout = round(sum(sb["odds"] * unit_stake for sb in sub_bets), 2)
        all_win_profit = round(all_win_payout - total_stake, 2)
        all_win_roi = round((all_win_profit / total_stake) * 100.0, 1) if total_stake > 0 else 0.0

        # 2. Case: 倒 1 關 (Any 1 leg loses)
        # There are N scenarios: each scenario assumes leg i misses
        payouts_1_miss: List[Dict[str, Any]] = []
        for miss_idx in range(num_legs):
            missed_leg = legs[miss_idx]
            # Surviving sub-bets: those that DO NOT contain miss_idx
            surviving = [sb for sb in sub_bets if miss_idx not in sb["indices"]]
            payout_val = round(sum(sb["odds"] * unit_stake for sb in surviving), 2)
            profit_val = round(payout_val - total_stake, 2)
            payouts_1_miss.append({
                "missed_index": miss_idx,
                "missed_leg": missed_leg.get("selection") or f"關卡 {miss_idx+1}",
                "surviving_count": len(surviving),
                "payout": payout_val,
                "profit": profit_val,
            })

        min_1_miss = min(p["payout"] for p in payouts_1_miss) if payouts_1_miss else 0.0
        max_1_miss = max(p["payout"] for p in payouts_1_miss) if payouts_1_miss else 0.0
        avg_1_miss = round(sum(p["payout"] for p in payouts_1_miss) / len(payouts_1_miss), 2) if payouts_1_miss else 0.0
        min_profit_1_miss = round(min_1_miss - total_stake, 2)

        # 3. Case: 倒 2 關 (Any 2 legs lose)
        payouts_2_miss: List[float] = []
        if num_legs >= 4:
            for miss_pair in itertools.combinations(range(num_legs), 2):
                surviving = [sb for sb in sub_bets if not (miss_pair[0] in sb["indices"] or miss_pair[1] in sb["indices"])]
                payout_val = round(sum(sb["odds"] * unit_stake for sb in surviving), 2)
                payouts_2_miss.append(payout_val)

        min_2_miss = min(payouts_2_miss) if payouts_2_miss else 0.0
        avg_2_miss = round(sum(payouts_2_miss) / len(payouts_2_miss), 2) if payouts_2_miss else 0.0

        # Resilience Grade Assignment
        if min_1_miss >= total_stake:
            grade = "SHIELD_PROFIT"
            grade_badge = "🟢 完美防倒 (倒 1 關保證保本且獲利！)"
            grade_desc = f"極佳容錯！即使倒了最高賠率那關，最少仍可拿回 NT$ {min_1_miss:,.2f} (淨賺 +NT$ {min_profit_1_miss:,.2f})"
        elif avg_1_miss >= total_stake:
            grade = "SHIELD_COVER"
            grade_badge = "🟡 穩健避險 (倒 1 關平均回本)"
            grade_desc = f"良好避險！倒 1 關平均可拿回 NT$ {avg_1_miss:,.2f}，收回大部或全部本金"
        elif min_1_miss >= total_stake * 0.70:
            grade = "SHIELD_DEFENSE"
            grade_badge = "🟡 減震回本 (倒 1 關收回 70%+ 本金)"
            grade_desc = f"大幅降低全損風險！倒 1 關仍可保住 NT$ {min_1_miss:,.2f} ~ {max_1_miss:,.2f}"
        else:
            grade = "HIGH_EXPLOSIVE"
            grade_badge = "🔴 爆發進攻型 (需全中獲取極大派彩)"
            grade_desc = f"全中時派彩高達 NT$ {all_win_payout:,.2f} (ROI +{all_win_roi}%)；倒關回本比例較低"

        return {
            "num_legs": num_legs,
            "combo_key": combo_key,
            "combo_label": spec["label"],
            "combo_desc": spec["desc"],
            "unit_stake": unit_stake,
            "total_combinations": total_combinations,
            "total_stake": total_stake,
            "sub_sizes": sub_sizes,
            "sub_bets_count": len(sub_bets),
            "sub_bets": sub_bets,
            "all_win": {
                "payout": all_win_payout,
                "profit": all_win_profit,
                "roi_pct": all_win_roi,
            },
            "one_miss": {
                "min_payout": min_1_miss,
                "max_payout": max_1_miss,
                "avg_payout": avg_1_miss,
                "min_profit": min_profit_1_miss,
                "is_guaranteed_breakeven": min_1_miss >= total_stake,
                "scenarios": payouts_1_miss,
            },
            "two_miss": {
                "min_payout": min_2_miss,
                "avg_payout": avg_2_miss,
                "has_coverage": max(payouts_2_miss) > 0 if payouts_2_miss else False,
            },
            "grade": grade,
            "grade_badge": grade_badge,
            "grade_desc": grade_desc,
        }

    @classmethod
    def evaluate_round_robin_settlement(
        cls,
        legs: List[Dict[str, Any]],
        combo_key: str,
        legs_eval: List[Dict[str, Any]],
        unit_stake: float,
        total_stake: float,
    ) -> Dict[str, Any]:
        """Evaluate real settlement of a Round Robin combination bet given game outcomes."""
        num_legs = len(legs)
        specs = cls.get_supported_combinations(num_legs)
        spec = specs.get(combo_key)
        if not spec:
            raise ValueError(f"不支援 {num_legs} 場的過關組合代碼: {combo_key}")

        sub_sizes = spec["sub_sizes"]
        sub_bets = cls.generate_sub_bets(legs, sub_sizes)

        sub_results = []
        total_payout = 0.0
        all_resolved = True
        winning_sub_count = 0
        void_sub_count = 0

        for sb in sub_bets:
            indices = sb["indices"]
            sub_evals = [legs_eval[i] for i in indices if i < len(legs_eval)]

            # Check sub-bet outcome
            sub_has_lost = any(e["status"] == "LOST" for e in sub_evals)
            sub_all_resolved = all(e["status"] in ("WON", "LOST", "VOID", "PUSH") for e in sub_evals)
            sub_all_void = all(e["status"] in ("VOID", "PUSH") for e in sub_evals)

            if sub_has_lost:
                sub_status = "LOST"
                sub_payout = 0.0
            elif not sub_all_resolved:
                all_resolved = False
                sub_status = "PENDING"
                sub_payout = 0.0
            elif sub_all_void:
                sub_status = "VOID"
                sub_payout = unit_stake
                void_sub_count += 1
                total_payout += sub_payout
            else:
                sub_status = "WON"
                # Effective odds = product of effective_odds of non-void legs
                eff_odds = 1.0
                for e in sub_evals:
                    if e["status"] not in ("VOID", "PUSH"):
                        eff_odds *= e.get("effective_odds", float(e.get("odds", 1.0)))
                sub_payout = round(unit_stake * eff_odds, 2)
                winning_sub_count += 1
                total_payout += sub_payout

            sub_results.append({
                "summary": sb["summary"],
                "indices": indices,
                "status": sub_status,
                "payout": sub_payout,
            })

        total_payout = round(total_payout, 2)
        net_profit = round(total_payout - total_stake, 2)

        if not all_resolved:
            can_settle = False
            final_status = "OPEN"
            summary = f"進行中 ({winning_sub_count}/{len(sub_bets)} 注已命中，累積派彩 NT$ {total_payout:,.2f})"
        else:
            can_settle = True
            if winning_sub_count > 0:
                final_status = "WON"
                summary = f"🎉 過關組合命中 {winning_sub_count}/{len(sub_bets)} 注！總派彩 NT$ {total_payout:,.2f} (淨利 {'+' if net_profit>=0 else ''}NT$ {net_profit:,.2f})"
            elif void_sub_count == len(sub_bets):
                final_status = "VOID"
                summary = "全數退盤 (賽事無效退款)"
            else:
                final_status = "LOST"
                summary = f"未命中任何子組合 (0/{len(sub_bets)} 注命中)"

        return {
            "can_settle": can_settle,
            "final_status": final_status,
            "payout": total_payout,
            "net_profit": net_profit,
            "winning_sub_count": winning_sub_count,
            "total_sub_count": len(sub_bets),
            "sub_results": sub_results,
            "summary": summary,
        }
