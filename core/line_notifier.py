#!/usr/bin/env python3
"""LINE Bot Messaging API Notification Engine (LINE 即時推播引擎).

Supports real-time alerts for:
1. STEAM_DROP (📉 賠率跳水警報 - 熱錢急湧)
2. TICKET_SETTLEMENT (🎉 注單自動對獎/中獎報喜入庫)
3. HEDGING_ALERT (🔔 聽牌對衝提示 - 最後一關鎖定保本/獲利)
4. MORNING_RADAR (☀️ 每日開盤賽季雷達簡報)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
import yaml

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "line_notifier.yaml"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


class LineNotifier:
    """Sends real-time sports betting alerts to LINE via LINE Messaging API."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        session: Optional[requests.Session] = None,
    ):
        self.config_path = config_path or CONFIG_PATH
        self.session = session or requests.Session()
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """Load LINE Bot settings from YAML config or environment variables."""
        cfg: Dict[str, Any] = {
            "enabled": False,
            "channel_access_token": "",
            "user_id": "",
            "notify_events": {
                "steam_drop": True,
                "ticket_settlement": True,
                "hedging_alert": True,
                "morning_radar": True,
            },
        }

        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f) or {}
                if isinstance(loaded, dict):
                    cfg.update(loaded)
            except Exception as exc:
                logger.warning("Failed to load line_notifier.yaml: %s", exc)

        # Environment variable overrides
        env_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
        env_user = os.environ.get("LINE_USER_ID")
        if env_token:
            cfg["channel_access_token"] = env_token
        if env_user:
            cfg["user_id"] = env_user

        # Auto-enable if token and user_id are set, unless explicitly disabled in file
        if cfg["channel_access_token"] and cfg["user_id"] and "enabled" not in cfg:
            cfg["enabled"] = True

        return cfg

    def save_config(self, new_cfg: Dict[str, Any]) -> None:
        """Persist updated LINE Bot credentials and preference settings."""
        self.config.update(new_cfg)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.config, f, allow_unicode=True, sort_keys=False)

    def is_configured(self) -> bool:
        """Check whether LINE credentials are fully populated and active."""
        token = str(self.config.get("channel_access_token") or "").strip()
        user_id = str(self.config.get("user_id") or "").strip()
        return bool(self.config.get("enabled", False) and token and user_id)

    def send_push_message(
        self,
        text: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a plain text push message to the configured LINE User ID or Group ID."""
        token = str(self.config.get("channel_access_token") or "").strip()
        target = str(user_id or self.config.get("user_id") or "").strip()

        if not token or not target:
            return {
                "success": False,
                "status_code": 0,
                "error": "LINE_NOT_CONFIGURED",
                "message": "尚未設定 Channel Access Token 或 User ID",
            }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        payload = {
            "to": target,
            "messages": [
                {
                    "type": "text",
                    "text": text,
                }
            ],
        }

        try:
            resp = self.session.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=8.0)
            if resp.status_code == 200:
                logger.info("LINE message successfully delivered to %s", target[:6] + "...")
                return {"success": True, "status_code": 200}
            else:
                err_text = resp.text
                logger.warning("LINE push failed [%d]: %s", resp.status_code, err_text)
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "error": "HTTP_ERROR",
                    "message": err_text,
                }
        except Exception as exc:
            logger.error("Network error while connecting to LINE API: %s", exc)
            return {
                "success": False,
                "status_code": 0,
                "error": "NETWORK_EXCEPTION",
                "message": str(exc),
            }

    def test_connection(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Send an instant test ping to verify LINE bot integration."""
        msg = (
            "🐕 【台灣運彩 瘋狗流決策台】\n"
            "---------------------------\n"
            "✅ LINE 即時通知推播連線成功！\n\n"
            "本頻道將即時向您傳送：\n"
            "• 📉 盤口跳水與誘盤情報\n"
            "• 🎉 賽果自動對獎與中獎入庫\n"
            "• 🔔 串關聽牌對衝保本提醒\n"
            "• ☀️ 每日賽季開盤雷達簡報\n\n"
            "祝您場場過關，財庫滿載！🎯"
        )
        return self.send_push_message(msg, user_id=user_id)

    # -------------------------------------------------------------------------
    # High-level Alert Event Dispatchers
    # -------------------------------------------------------------------------

    def notify_steam_drop(
        self,
        league: str,
        match_title: str,
        market: str,
        selection: str,
        old_odds: float,
        new_odds: float,
        delta_odds: float,
        delta_pct: float,
    ) -> Dict[str, Any]:
        """Trigger alert when a severe odds drop (sharp money inflow) is detected."""
        if not self.config.get("notify_events", {}).get("steam_drop", True):
            return {"skipped": True, "reason": "EVENT_DISABLED"}

        text = (
            "📉 【盤口跳水警報！熱錢湧入】\n"
            "---------------------------\n"
            f"🏆 賽事：[{league}] {match_title}\n"
            f"🎯 玩法：{market} ➔ 【{selection}】\n"
            f"📊 賠率變動：{old_odds:.2f} ➔ {new_odds:.2f} ({delta_odds:+.2f} / {delta_pct:+.1%})\n\n"
            "💡 情報提示：\n"
            "此關卡短時間內遭遇大額資金重注，莊家緊急下調賠率以防範風險。可留意納入今日串關組合！"
        )
        return self.send_push_message(text)

    def notify_ticket_settlement(
        self,
        ticket: Dict[str, Any],
        won: bool,
        actual_payout: float,
        prize_pool: float,
        weekly_balance: float,
    ) -> Dict[str, Any]:
        """Trigger celebration or settlement report when tickets are resolved."""
        if not self.config.get("notify_events", {}).get("ticket_settlement", True):
            return {"skipped": True, "reason": "EVENT_DISABLED"}

        sports = ticket.get("sports_summary") or "運彩串關"
        stake = ticket.get("stake", 0.0)
        total_odds = ticket.get("placed_odds") or ticket.get("total_odds", 1.0)

        if won:
            net_profit = actual_payout - stake
            text = (
                "🎉 【瘋狗出擊 · 中獎報喜！】\n"
                "---------------------------\n"
                f"🎫 組合：{sports}\n"
                f"🔥 賠率：{total_odds:.2f} 倍\n"
                f"💵 下注本金：NT$ {stake:,.0f}\n"
                f"💰 實際派彩：NT$ {actual_payout:,.2f} (+NT$ {net_profit:,.2f})\n\n"
                "🔒 獲利已全數撥入【保留儲備池】！\n"
                f"• 目前儲備池總額：NT$ {prize_pool:,.2f}\n"
                f"• 本週可玩餘額：NT$ {weekly_balance:,.2f}"
            )
        else:
            text = (
                "ℹ️ 【注單結算通知】\n"
                "---------------------------\n"
                f"🎫 組合：{sports} ({total_odds:.2f}x)\n"
                f"💵 投入本金：NT$ {stake:,.0f}\n"
                "結果：未全數命中，再接再厲！\n"
                f"• 本週剩餘可玩額度：NT$ {weekly_balance:,.2f}"
            )

        return self.send_push_message(text)

    def notify_hedging_alert(
        self,
        ticket: Dict[str, Any],
        pending_leg: Dict[str, Any],
        hedge_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Trigger urgent alert when a multi-leg parlay is 'Hedging Ready' (聽牌)."""
        if not self.config.get("notify_events", {}).get("hedging_alert", True):
            return {"skipped": True, "reason": "EVENT_DISABLED"}

        sports = ticket.get("sports_summary") or "運彩高倍串關"
        potential_payout = float(ticket.get("potential_payout", 0.0))
        stake = float(ticket.get("stake", 0.0))

        match_str = f"{pending_leg.get('away_team')} vs {pending_leg.get('home_team')}"
        opposing_bet = hedge_analysis.get("opposing_selection", "反向盤口")
        hedge_odds = float(hedge_analysis.get("hedge_odds", 1.75))
        breakeven_stake = float(hedge_analysis.get("breakeven_stake", 0.0))
        guaranteed_stake = float(hedge_analysis.get("guaranteed_stake", 0.0))
        guaranteed_profit = float(hedge_analysis.get("guaranteed_profit", 0.0))

        text = (
            "🔔 【恭喜聽牌！對衝保本通知】\n"
            "---------------------------\n"
            f"🎫 串關：{sports}\n"
            f"🎯 潛在派彩高達：NT$ {potential_payout:,.2f} (本金 NT$ {stake:,.0f})\n"
            f"⏳ 最後決戰：[{pending_leg.get('league')}] {match_str}\n"
            f"目前手持關卡：【{pending_leg.get('selection')}】\n\n"
            "🛡️ 建議對衝策略（反買對家鎖利）：\n"
            f"• 標的：【{opposing_bet}】(反向賠率約 {hedge_odds:.2f})\n"
            f"• ① 保本對衝：反買 NT$ {breakeven_stake:.0f} ➔ 倒此關仍立於不敗 (0 虧損)\n"
            f"• ② 100% 絕對鎖利：反買 NT$ {guaranteed_stake:.0f} ➔ 無論最後一場輸贏，保底淨賺 NT$ {guaranteed_profit:,.2f}！"
        )
        return self.send_push_message(text)

    def notify_morning_radar(
        self,
        radar_summary: List[Dict[str, Any]],
        top_picks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Daily briefing for green-light leagues and actionable high +EV legs."""
        if not self.config.get("notify_events", {}).get("morning_radar", True):
            return {"skipped": True, "reason": "EVENT_DISABLED"}

        green_leagues = [r for r in radar_summary if r.get("status") == "GREEN"]
        leagues_str = "、".join(f"{r['icon']}{r['name']}({r['taiwan_market_count']}場)" for r in green_leagues) or "今日各聯賽休兵"

        picks_text = ""
        if top_picks:
            picks_lines = []
            for p in top_picks[:3]:
                ev_str = f"🔥 +EV {p['ev']:+.1f}%" if p.get("ev") else ""
                picks_lines.append(f"• [{p['league']}] {p['match']} ➔ {p['selection']} ({p['odds']}x) {ev_str}")
            picks_text = "\n🌟 今日焦點價值關卡推薦：\n" + "\n".join(picks_lines)

        text = (
            "☀️ 【今日運彩賽季雷達簡報】\n"
            "---------------------------\n"
            f"🟢 今日開盤聯賽：\n{leagues_str}\n"
            f"{picks_text}\n\n"
            "祝今日選盤順利，穩中求勝！🐕"
        )
        return self.send_push_message(text)

    def handle_user_message(
        self,
        user_text: str,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        wallet_mgr: Optional[Any] = None,
    ) -> str:
        """Process inbound text commands from LINE (e.g. '20倍', '查戰績', '今日開盤')."""
        import re
        cmd = user_text.strip().lower()

        # Match multiplier commands: e.g. "20", "20倍", "20x", "50倍"
        mult_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:倍|x|X)?", cmd)
        if mult_match and ("倍" in cmd or "x" in cmd or cmd.isdigit()):
            target_mult = float(mult_match.group(1))
            if 1.5 <= target_mult <= 500:
                if parlay_engine and available_legs:
                    res = parlay_engine.search_parlays(
                        legs=available_legs,
                        target_odds=target_mult,
                        tolerance=0.25,
                        min_legs=2,
                        max_legs=6,
                        search_budget=30000,
                    )
                    top_combos = []
                    for tier, combos in res.items():
                        top_combos.extend(combos)
                    if top_combos:
                        best = top_combos[0]
                        lines = [
                            f"🎯 【{best.get('parlay_name')} · 總賠率 {best.get('total_odds')}x】",
                            f"⚖️ 估計勝率: {best.get('joint_probability', 0)*100:.1f}% | EV: {best.get('parlay_ev_pct', 0):+.1f}%",
                            "---------------------------",
                        ]
                        for idx, l in enumerate(best.get("legs", []), start=1):
                            lines.append(f"{idx}. [{l.get('league')}] {l.get('away_team')} vs {l.get('home_team')} ➔ 【{l.get('selection')}】({l.get('taiwan_odds')}x)")
                        lines.append("---------------------------")
                        lines.append("祝您場場過關！🐕")
                        return "\n".join(lines)
                    return f"已為您搜尋約 {target_mult} 倍組合，但目前各盤口尚無完全吻合之高信賴推薦，建議調整倍率或稍後重試！"
                return f"收到！目標倍率 {target_mult} 倍。目前後端決策引擎正在加載即時盤口，請稍候刷新！"

        if "戰績" in cmd or "錢包" in cmd or "餘額" in cmd:
            if wallet_mgr:
                status = wallet_mgr.get_status()
                return (
                    "💰 【瘋狗流資金與戰績總覽】\n"
                    "---------------------------\n"
                    f"• 本週可玩餘額：NT$ {status['weekly_wallet_balance']:.2f}\n"
                    f"• 本週已下注：NT$ {status['weekly_staked']:.2f}\n"
                    f"• 🔒 保留儲備池：NT$ {status['prize_pool']:.2f}\n"
                    f"• 累計歷史淨利：NT$ {status.get('lifetime_net_profit', 0.0):+,.2f}\n"
                    "---------------------------\n"
                    "落實每週 NT$200 風控，守住每一分獲利！"
                )
            return "錢包模組讀取中..."

        if "雷達" in cmd or "開盤" in cmd or "今天" in cmd:
            return "☀️ 欲查看今日開盤，請在決策台點選「① 今日可玩 (賽季雷達)」或發送目標倍率（如「20倍」）獲取推薦！"

        return (
            "🐕 【瘋狗流 LINE 助手指令說明】\n"
            "---------------------------\n"
            "您可以直接傳送：\n"
            "• 「20倍」或「50x」➔ 自動為您尋找最佳串關組合\n"
            "• 「查戰績」或「餘額」➔ 查看每週錢包與儲備池最新數據\n"
            "• 「今日開盤」➔ 查詢今日賽程狀態\n\n"
            "輸入任何數字（如 15、30、100）即可開始組單！"
        )
