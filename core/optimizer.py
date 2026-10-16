#!/usr/bin/env python3
"""Crazy Dog Parlay Optimizer (瘋狗流串關期望值最佳化引擎).

Searches for optimal parlay combinations within target odds [10x, 500x],
enforcing Taiwan Sports Lottery rules (mutually exclusive matches)
and ranking tickets by Expected Value (EV), win probability, or consensus.
Optimized with candidate pre-filtering and pruning for sub-second execution.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, Iterable, List, Optional, Tuple


class ParlayOptimizer:
    def __init__(
        self,
        min_odds: float = 10.0,
        max_odds: float = 500.0,
        min_legs: int = 2,
        max_legs: int = 8,
    ):
        self.min_odds = max(1.01, min_odds)
        self.max_odds = max(self.min_odds, max_odds)
        self.min_legs = max(1, min_legs)
        self.max_legs = max(self.min_legs, max_legs)

    def optimize(
        self,
        matches: List[Dict[str, Any]],
        min_odds: Optional[float] = None,
        max_odds: Optional[float] = None,
        min_legs: Optional[int] = None,
        max_legs: Optional[int] = None,
        only_hot: bool = False,
        min_consensus: float = 0.40,
        sort_by: str = "EV",
        top_n: int = 20,
        stake: float = 200.0,
        max_candidate_matches: int = 18,
    ) -> List[Dict[str, Any]]:
        """Search all valid parlays meeting criteria and return top ranked combinations."""
        lo_odds = min_odds if min_odds is not None else self.min_odds
        hi_odds = max_odds if max_odds is not None else self.max_odds
        lo_legs = min_legs if min_legs is not None else self.min_legs
        hi_legs = max_legs if max_legs is not None else self.max_legs

        # 1. Extract eligible options and rank matches by option quality
        ranked_matches: List[Tuple[float, str, List[Dict[str, Any]]]] = []

        for m in matches:
            m_id = str(m.get("match_id", ""))
            opts = m.get("options", [])
            eligible = []
            for opt in opts:
                if only_hot and not opt.get("is_hot", False):
                    continue
                observed_consensus = opt.get("consensus_ratio")
                if observed_consensus is None or observed_consensus < min_consensus:
                    continue
                if opt.get("odds", 0.0) <= 1.05:
                    continue
                eligible.append(opt)

            if eligible:
                # Score each option by EV indicator: (odds * fair_prob)
                eligible.sort(
                    key=lambda x: x.get("odds", 1.0) * x.get("fair_prob", 0.5) * (1.0 + x.get("consensus_ratio", 0.5)),
                    reverse=True,
                )
                best_score = (
                    eligible[0].get("odds", 1.0)
                    * eligible[0].get("fair_prob", 0.5)
                    * (1.0 + eligible[0].get("consensus_ratio", 0.5))
                )
                # Keep top 2 options for this match to avoid duplicate permutations
                ranked_matches.append((best_score, m_id, eligible[:2]))

        # Sort matches by quality and take top candidates for fast exploration
        ranked_matches.sort(key=lambda x: x[0], reverse=True)
        active_matches = ranked_matches[:max_candidate_matches]

        if len(active_matches) < lo_legs:
            return []

        match_ids = [item[1] for item in active_matches]
        matches_dict = {item[1]: item[2] for item in active_matches}

        candidates: List[Dict[str, Any]] = []

        # 2. Iterate over allowed leg counts
        effective_hi_legs = min(hi_legs, len(match_ids), 7)
        for num_legs in range(lo_legs, effective_hi_legs + 1):
            # Combinations of distinct matches (satisfies 台彩互斥原則)
            for selected_mids in itertools.combinations(match_ids, num_legs):
                option_groups = [matches_dict[mid] for mid in selected_mids]

                for leg_tuple in itertools.product(*option_groups):
                    total_odds = 1.0
                    for leg in leg_tuple:
                        total_odds *= leg["odds"]
                        if total_odds > hi_odds:
                            break

                    # Check bounds
                    if not (lo_odds <= total_odds <= hi_odds):
                        continue

                    # Calculate combined win probability & EV
                    win_prob = 1.0
                    total_consensus = 0.0
                    for leg in leg_tuple:
                        win_prob *= leg.get("fair_prob", 0.5)
                        total_consensus += leg.get("consensus_ratio", 0.5)

                    avg_consensus = total_consensus / num_legs
                    ev = (total_odds * win_prob) - 1.0
                    potential_payout = round(stake * total_odds, 2)
                    expected_payout = round(stake * total_odds * win_prob, 2)
                    expected_profit = round(expected_payout - stake, 2)

                    candidates.append({
                        "legs_count": num_legs,
                        "parlay_name": f"{num_legs} 串 1",
                        "total_odds": round(total_odds, 2),
                        "win_prob": round(win_prob, 5),
                        "win_prob_percent": round(win_prob * 100.0, 3),
                        "ev": round(ev, 4),
                        "ev_percent": round(ev * 100.0, 1),
                        "avg_consensus": round(avg_consensus * 100.0, 1),
                        "stake": stake,
                        "potential_payout": potential_payout,
                        "expected_payout": expected_payout,
                        "expected_profit": expected_profit,
                        "legs": list(leg_tuple),
                    })

        # 3. Sort candidates according to preference
        if sort_by == "EV":
            candidates.sort(key=lambda x: (x["ev"], x["total_odds"]), reverse=True)
        elif sort_by == "ODDS":
            candidates.sort(key=lambda x: x["total_odds"], reverse=True)
        elif sort_by == "PROB":
            candidates.sort(key=lambda x: (x["win_prob"], x["total_odds"]), reverse=True)
        elif sort_by == "CONSENSUS":
            candidates.sort(key=lambda x: (x["avg_consensus"], x["ev"]), reverse=True)

        top_results = candidates[:top_n]
        for idx, res in enumerate(top_results, start=1):
            res["rank"] = idx

        return top_results
