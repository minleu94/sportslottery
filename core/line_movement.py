#!/usr/bin/env python3
"""Line Movement and Steam/Trap Tracking Engine (賠率變動與跳水/誘盤監控).

Tracks the real-time trajectory of Taiwan Sports Lottery odds across multiple
observation points. Detects:
1. STEAM_DROP (賠率跳水 📉): Sharp money inflow, rapid drop (>= 0.08 or >= 4.5%).
2. REVERSE_DRIFT (逆向升水 / 誘盤 ⚠️): Unfavorable odds drift or reverse line movement.
3. STABLE (盤口平穩 ➖): Minor or no drift (|delta| < 0.08).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.bet_validation import parse_aware_time
from core.research_paths import research_paths

logger = logging.getLogger(__name__)

DEFAULT_ODDS_HISTORY_FILE = research_paths()["odds"]

# Movement thresholds
STEAM_DROP_ABS_THRESHOLD = 0.08      # e.g. dropped by 0.08 or more (1.85 -> 1.77)
STEAM_DROP_PCT_THRESHOLD = -0.045    # -4.5% drop
REVERSE_DRIFT_ABS_THRESHOLD = 0.08   # e.g. rose by 0.08 or more (1.45 -> 1.53)
REVERSE_DRIFT_PCT_THRESHOLD = 0.045  # +4.5% rise


class LineMovementTracker:
    """Monitors line movements, steam moves, and bookmaker trap anomalies."""

    def __init__(self, history_path: Optional[Path] = None):
        self.history_path = history_path or DEFAULT_ODDS_HISTORY_FILE
        self._history_cache: Optional[Dict[Tuple[str, str, str], List[Dict[str, Any]]]] = None

    def refresh(self) -> None:
        """Clear memory cache to force re-reading odds history."""
        self._history_cache = None

    def _load_history(self) -> Dict[Tuple[str, str, str], List[Dict[str, Any]]]:
        """Load and index historical odds observations by (event_id, market, selection)."""
        if self._history_cache is not None:
            return self._history_cache

        cache: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        if not self.history_path.exists():
            self._history_cache = cache
            return cache

        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        eid = str(record.get("canonical_event_id") or record.get("event_id") or "")
                        mkt = str(record.get("market") or "")
                        sel = str(record.get("selection") or "")
                        if not eid or not mkt or not sel:
                            continue
                        cache.setdefault((eid, mkt, sel), []).append(record)
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception as exc:
            logger.warning("Error reading odds history file %s: %s", self.history_path, exc)

        # Sort each timeline by observed_at
        for key, obs_list in cache.items():
            obs_list.sort(key=lambda r: parse_aware_time(r.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc))

        self._history_cache = cache
        return cache

    def get_timeline(
        self,
        event_id: str,
        market: str,
        selection: str,
        canonical_event_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get chronological list of odds observations for a specific selection."""
        history = self._load_history()
        # Try canonical event id first, then raw event id
        key_canonical = (str(canonical_event_id or ""), market, selection)
        if canonical_event_id and key_canonical in history:
            return history[key_canonical]

        key_event = (str(event_id), market, selection)
        if key_event in history:
            return history[key_event]

        return []

    def analyze_leg_movement(
        self,
        leg: Any,
        current_odds: Optional[float] = None,
        as_of: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Analyze odds movement trajectory for a TaiwanLeg."""
        eid = str(getattr(leg, "event_id", "") or "")
        cid = getattr(leg, "canonical_event_id", None)
        market = str(getattr(leg, "market", "") or getattr(leg, "market_type", "") or "")
        selection = str(getattr(leg, "selection", "") or "")
        line = getattr(leg, "line", None)

        curr = current_odds if current_odds is not None else float(getattr(leg, "taiwan_odds", 0.0) or 0.0)

        timeline = self.get_timeline(eid, market, selection, cid)

        cutoff = parse_aware_time(as_of) if as_of is not None else None
        if cutoff:
            timeline = [r for r in timeline if (parse_aware_time(r.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc)) <= cutoff]

        if not timeline:
            return {
                "has_movement": False,
                "movement_type": "NO_HISTORY",
                "open_odds": curr,
                "current_odds": curr,
                "delta_odds": 0.0,
                "pct_change": 0.0,
                "implied_prob_delta_pp": 0.0,
                "badge_html": "<span style='background:#1e202e; color:#94a3b8; padding:2px 7px; border-radius:5px; font-size:0.82rem;'>➖ 盤口初見</span>",
                "text_label": "初盤觀測",
                "summary": "首筆盤口記錄，暫無歷史跳水軌跡",
                "is_steam": False,
                "is_trap_warning": False,
                "observations_count": 1 if curr > 1.0 else 0,
                "first_observed_at": None,
                "last_observed_at": None,
                "history_points": [(datetime.now(timezone.utc).isoformat(), curr)] if curr > 1.0 else [],
            }

        # First / Opening recorded odds
        open_record = timeline[0]
        open_odds = float(open_record.get("odds", curr))
        if open_odds <= 1.0:
            open_odds = curr

        latest_record = timeline[-1]
        last_observed = latest_record.get("observed_at")
        first_observed = open_record.get("observed_at")

        delta = round(curr - open_odds, 3)
        pct = round((delta / open_odds) * 100.0, 2) if open_odds > 0 else 0.0

        p_open = (1.0 / open_odds) if open_odds > 1.0 else 0.0
        p_curr = (1.0 / curr) if curr > 1.0 else 0.0
        p_delta_pp = round((p_curr - p_open) * 100.0, 2)

        # Check for Steam Drop vs Reverse Drift
        is_steam = delta <= -STEAM_DROP_ABS_THRESHOLD or pct <= (STEAM_DROP_PCT_THRESHOLD * 100.0)
        is_trap = delta >= REVERSE_DRIFT_ABS_THRESHOLD or pct >= (REVERSE_DRIFT_PCT_THRESHOLD * 100.0)

        # Crowd reverse trap check: if crowd heavily backs it (>60%) but odds drifted UP!
        evidence = getattr(leg, "signal_evidence", {}) or {}
        crowd_ratio = evidence.get("consensus_ratio")
        crowd_pct = float(crowd_ratio * 100.0) if crowd_ratio is not None else 0.0
        if crowd_pct >= 60.0 and delta >= 0.05:
            is_trap = True

        if is_steam:
            movement_type = "STEAM_DROP"
            badge_html = f"<span style='background:#064e3b; color:#34d399; border:1px solid #059669; padding:2px 7px; border-radius:5px; font-weight:bold; font-size:0.82rem;'>📉 賠率跳水 ({open_odds:.2f} ➔ {curr:.2f}, {delta:+.2f})</span>"
            text_label = f"📉 賠率跳水 ({delta:+.2f})"
            summary = f"🔥 智慧資金湧入！開盤 {open_odds:.2f} 跳水至 {curr:.2f} (勝率預期上升 +{p_delta_pp:.1f}%)"
        elif is_trap:
            movement_type = "REVERSE_DRIFT"
            badge_html = f"<span style='background:#451a03; color:#fcd34d; border:1px solid #d97706; padding:2px 7px; border-radius:5px; font-weight:bold; font-size:0.82rem;'>⚠️ 逆向升水 ({open_odds:.2f} ➔ {curr:.2f}, {delta:+.2f})</span>"
            text_label = f"⚠️ 逆向升水 ({delta:+.2f})"
            trap_extra = "（大眾熱投但莊家逆向給甜頭，慎防誘盤！）" if crowd_pct >= 60.0 else "（莊家升水吸籌，留意先發輪休陷阱）"
            summary = f"⚠️ 警戒訊號：開盤 {open_odds:.2f} 逆向推升至 {curr:.2f} {trap_extra}"
        else:
            movement_type = "STABLE"
            badge_html = f"<span style='background:#1e202e; color:#94a3b8; border:1px solid #2d3142; padding:2px 7px; border-radius:5px; font-size:0.82rem;'>➖ 賠率平穩 ({curr:.2f})</span>"
            text_label = f"➖ 盤口平穩 ({delta:+.2f})"
            summary = f"盤口平穩：初盤 {open_odds:.2f} 現盤 {curr:.2f}，無顯著異常資金波動"

        history_points = []
        for r in timeline:
            ts = r.get("observed_at")
            o = r.get("odds")
            if ts and o:
                try:
                    history_points.append((ts, float(o)))
                except (ValueError, TypeError):
                    pass

        return {
            "has_movement": abs(delta) >= 0.05,
            "movement_type": movement_type,
            "open_odds": open_odds,
            "current_odds": curr,
            "delta_odds": delta,
            "pct_change": pct,
            "implied_prob_delta_pp": p_delta_pp,
            "badge_html": badge_html,
            "text_label": text_label,
            "summary": summary,
            "is_steam": is_steam,
            "is_trap_warning": is_trap,
            "observations_count": len(timeline),
            "first_observed_at": first_observed,
            "last_observed_at": last_observed,
            "history_points": history_points,
        }
