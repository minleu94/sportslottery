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
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
import yaml

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "line_notifier.yaml"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"


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

    def reply_message(
        self,
        reply_token: str,
        text: str,
        quick_replies: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Send a reply to an incoming webhook message using replyToken (free quota)."""
        token = str(self.config.get("channel_access_token") or "").strip()
        if not token or not reply_token:
            return {
                "success": False,
                "status_code": 0,
                "error": "LINE_NOT_CONFIGURED",
                "message": "尚未設定 Channel Access Token 或無效的 reply_token",
            }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        msg_obj: Dict[str, Any] = {
            "type": "text",
            "text": text,
        }
        if quick_replies:
            msg_obj["quickReply"] = {
                "items": [
                    {
                        "type": "action",
                        "action": {
                            "type": "message",
                            "label": item.get("label", item.get("text", ""))[:20],
                            "text": item.get("text", "")[:300],
                        },
                    }
                    for item in quick_replies[:13]
                ]
            }

        payload = {
            "replyToken": reply_token,
            "messages": [msg_obj],
        }

        try:
            resp = self.session.post(LINE_REPLY_URL, headers=headers, json=payload, timeout=8.0)
            if resp.status_code == 200:
                logger.info("LINE reply delivered successfully via replyToken.")
                return {"success": True, "status_code": 200}
            else:
                err_text = resp.text
                logger.warning("LINE reply failed [%d]: %s", resp.status_code, err_text)
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "error": "HTTP_ERROR",
                    "message": err_text,
                }
        except Exception as exc:
            logger.error("Network error while replying to LINE API: %s", exc)
            return {
                "success": False,
                "status_code": 0,
                "error": "NETWORK_EXCEPTION",
                "message": str(exc),
            }

    @staticmethod
    def default_quick_replies() -> List[Dict[str, str]]:
        """Standard quick reply shortcuts displayed above keyboard in LINE chat."""
        return [
            {"label": "🎯 找20倍串關", "text": "20倍"},
            {"label": "🔥 找50倍高賠", "text": "50倍"},
            {"label": "💰 查戰績錢包", "text": "查戰績"},
            {"label": "☀️ 今日開盤", "text": "今日開盤"},
            {"label": "🛡️ 聽牌對沖", "text": "對沖"},
            {"label": "📋 完整功能表", "text": "功能表"},
        ]

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

    @staticmethod
    def format_parlay_leg(leg: Dict[str, Any], idx: int) -> str:
        """Format a betting selection with sport icon, clean Chinese league, matchup, kickoff time, and market."""
        sport = str(leg.get("sport") or "").lower().strip()
        raw_league = str(leg.get("league") or "").strip()
        market = str(leg.get("market") or "").strip()
        selection = str(leg.get("selection") or "").strip()
        # Clean redundant trailing odds inside selection text (e.g. "大 2.5分 (1.68)" -> "大 2.5分")
        clean_selection = re.sub(r"\s*\(\d+(?:\.\d+)?\)\s*$", "", selection).strip() or selection
        odds = float(leg.get("taiwan_odds") or 1.0)
        line = leg.get("line")
        away = str(leg.get("away_team") or "客隊").strip()
        home = str(leg.get("home_team") or "主隊").strip()
        start_time = leg.get("start_time_utc") or leg.get("start_time")

        # 1. Sport Icon & League Normalization
        SPORT_ICONS = {
            "baseball": "⚾",
            "basketball": "🏀",
            "soccer": "⚽",
            "football": "🏈",
            "hockey": "🏒",
            "tennis": "🎾",
        }

        LEAGUE_CHINESE_MAP = {
            "mlb": ("⚾", "MLB (美國職棒)"),
            "nba": ("🏀", "NBA (美國職籃)"),
            "wnba": ("🏀", "WNBA (女子職籃)"),
            "cpbl": ("⚾", "CPBL (中華職棒)"),
            "npb": ("⚾", "NPB (日本職棒)"),
            "kbo": ("⚾", "KBO (韓國職棒)"),
            "nfl": ("🏈", "NFL (美式足球)"),
            "nhl": ("🏒", "NHL (北美冰球)"),
            "premier": ("⚽", "英超 (英格蘭超級聯賽)"),
            "premier_league": ("⚽", "英超 (英格蘭超級聯賽)"),
            "epl": ("⚽", "英超 (英格蘭超級聯賽)"),
            "laliga": ("⚽", "西甲 (西班牙甲級聯賽)"),
            "serie_a": ("⚽", "義甲 (義大利甲級聯賽)"),
            "bundesliga": ("⚽", "德甲 (德國甲級聯賽)"),
            "ligue_1": ("⚽", "法甲 (法國甲級聯賽)"),
            "mls": ("⚽", "MLS (美國足球大聯盟)"),
            "columbia_primera_a": ("⚽", "哥倫比亞甲級足球聯賽"),
            "colombia_primera_a": ("⚽", "哥倫比亞甲級足球聯賽"),
            "costa_rica_primera": ("⚽", "哥斯大黎加甲級足球聯賽"),
            "afc_champions_league": ("⚽", "亞冠足球聯賽"),
            "champions_league": ("⚽", "歐冠足球聯賽"),
            "europa_league": ("⚽", "歐霸足球盃"),
            "j_league": ("⚽", "J聯盟 (日本職業足球)"),
            "k_league": ("⚽", "K聯盟 (韓國職業足球)"),
            "cpbl_(中職)": ("⚾", "CPBL (中華職棒)"),
            "npb_(日棒)": ("⚾", "NPB (日本職棒)"),
            "kbo_(韓棒)": ("⚾", "KBO (韓國職棒)"),
            "足球": ("⚽", "焦點足球賽事"),
        }

        norm_league = raw_league.lower().replace(" ", "_").replace("-", "_")
        # Strip generic "unknown_" prefix if present
        clean_raw = re.sub(r"^unknown_", "", raw_league, flags=re.IGNORECASE).strip()
        clean_norm = re.sub(r"^unknown_", "", norm_league, flags=re.IGNORECASE).strip()

        if norm_league in LEAGUE_CHINESE_MAP:
            icon, league_name = LEAGUE_CHINESE_MAP[norm_league]
        elif clean_norm in LEAGUE_CHINESE_MAP:
            icon, league_name = LEAGUE_CHINESE_MAP[clean_norm]
        elif clean_raw and clean_raw.lower() not in ("unknown", "soccer", "baseball", "basketball", "football", ""):
            icon = SPORT_ICONS.get(sport, "🎯")
            league_name = clean_raw
        else:
            # Fallback for generic/unknown
            icon = SPORT_ICONS.get(sport, "🎯")
            if sport == "soccer":
                league_name = "國際足球錦標賽"
            elif sport == "baseball":
                league_name = "職業棒球賽事"
            elif sport == "basketball":
                league_name = "職業籃球賽事"
            elif sport == "football":
                league_name = "美式足球賽事"
            elif sport == "hockey":
                league_name = "職業冰球賽事"
            else:
                league_name = "精選賽事"

        # 2. Matchup Formatting
        matchup = f"{away} vs {home}"

        # 3. Kickoff Time Formatting (convert UTC to Taipei Time)
        time_str = ""
        if start_time:
            try:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                clean_ts = str(start_time).replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_ts)
                taipei_tz = ZoneInfo("Asia/Taipei")
                dt_loc = dt.astimezone(taipei_tz) if dt.tzinfo else dt
                time_str = f" ⏰ {dt_loc.strftime('%m/%d %H:%M')}"
            except Exception:
                if len(str(start_time)) <= 16:
                    time_str = f" ⏰ {start_time}"

        # 4. Market & Selection Formatting
        if market == "讓分":
            line_part = f" [{line}]" if line else ""
            market_str = f"讓分盤{line_part} ➔ 【{clean_selection}】({odds:.2f}x)"
        elif market == "大小":
            line_part = f" [{line}]" if line else ""
            market_str = f"大小分{line_part} ➔ 【{clean_selection}】({odds:.2f}x)"
        elif market == "不讓分":
            market_str = f"不讓分 ➔ 【{clean_selection}】({odds:.2f}x)"
        elif market:
            line_part = f" [{line}]" if line else ""
            market_str = f"{market}{line_part} ➔ 【{clean_selection}】({odds:.2f}x)"
        else:
            market_str = f"【{clean_selection}】({odds:.2f}x)"

        return (
            f"{idx}. {icon} [{league_name}]\n"
            f"   {matchup}{time_str}\n"
            f"   🎯 {market_str}"
        )

    @staticmethod
    def get_menu_text() -> str:
        """Full interactive menu formatted for mobile LINE chat."""
        return (
            "🐕 【瘋狗流 LINE 助手指令說明 · 功能表】\n"
            "===========================\n"
            "您可以直接傳送以下指令（或點選下方快捷按鈕）：\n\n"
            "🎯 【智慧串關推薦】\n"
            "• 輸入「20倍」、「30倍」、「50倍」或任何數字\n"
            "  ➔ AI 即時從今日各聯賽盤口中，演算最高勝率、正期望值 (+EV) 的串關組合！\n\n"
            "💰 【資產與戰績管理】\n"
            "• 輸入「查戰績」、「錢包」或「餘額」\n"
            "  ➔ 即時查詢本週可玩額度 (NT$200/週)、已下注金額與保留儲備池！\n\n"
            "☀️ 【即時開盤雷達】\n"
            "• 輸入「今日開盤」或「雷達」\n"
            "  ➔ 查詢今日有開盤之聯賽與可玩場次簡報！\n\n"
            "🛡️ 【聽牌對沖與鎖利】\n"
            "• 輸入「對沖」或「聽牌」\n"
            "  ➔ 檢查手頭未結算注單，若只剩最後一關，即時計算 100% 鎖利或 0 虧損保本對沖計畫！\n\n"
            "📋 【重新呼叫選單】\n"
            "• 輸入「功能表」、「選單」或「說明」\n"
            "===========================\n"
            "💡 提示：點擊下方快捷按鈕即可一鍵送出！"
        )

    def handle_user_message(
        self,
        user_text: str,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        wallet_mgr: Optional[Any] = None,
    ) -> str:
        """Process inbound text commands from LINE (e.g. '20倍', '功能表', '查戰績', '今日開盤', '對沖')."""
        import re
        cmd = user_text.strip().lower()
        if not cmd:
            return self.get_menu_text()

        # 1. Greetings & Menu Triggers
        menu_triggers = [
            "功能表", "選單", "menu", "help", "說明", "指令", "你好", "您好", "哈囉",
            "hello", "hi", "嗨", "開始", "start", "安安", "?", "？", "怎麼用"
        ]
        if any(cmd == t for t in menu_triggers):
            return self.get_menu_text()

        # 2. Match Target Multiplier: e.g. "20", "20倍", "20x", "50倍", "100"
        mult_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:倍|x|X)?", cmd)
        if mult_match and ("倍" in cmd or "x" in cmd or cmd.isdigit() or "串" in cmd):
            target_mult = float(mult_match.group(1))
            if 1.5 <= target_mult <= 1000:
                sport_filter = None
                if any(w in cmd for w in ["足球", "soccer"]):
                    sport_filter = "soccer"
                elif any(w in cmd for w in ["棒球", "baseball"]):
                    sport_filter = "baseball"
                elif any(w in cmd for w in ["籃球", "basketball"]):
                    sport_filter = "basketball"
                elif any(w in cmd for w in ["美足", "football", "nfl"]):
                    sport_filter = "football"
                return self._search_parlay_for_bot(target_mult, parlay_engine, available_legs, sport_filter=sport_filter)

        # 3. Wallet & Staking Performance: e.g. "戰績", "錢包", "餘額", "本週"
        if any(k in cmd for k in ["戰績", "錢包", "餘額", "本金", "獲利", "本週"]):
            return self._get_wallet_status_text(wallet_mgr)

        # 4. Season Radar / Daily Matchups: e.g. "雷達", "開盤", "今天", "賽程"
        if any(k in cmd for k in ["雷達", "開盤", "今天", "賽程", "賽事"]):
            return self._get_radar_status_text()

        # 5. Hedging / Breakeven Queries: e.g. "對沖", "對衝", "聽牌", "鎖利", "保本"
        if any(k in cmd for k in ["對沖", "對衝", "聽牌", "鎖利", "保本"]):
            return self._get_hedging_status_text()

        # 6. Fallback to Menu with Prompt
        return (
            "🐕 【瘋狗流 LINE 助手指令說明】\n"
            "---------------------------\n"
            f"收到指令：「{user_text}」\n"
            "未能辨識此關鍵字。您可以點擊下方快捷按鈕，或參考以下指令：\n\n"
            "• 發送「20倍」➔ 智慧搜尋 20 倍串關\n"
            "• 發送「查戰績」➔ 查看每週額度與獲利\n"
            "• 發送「今日開盤」➔ 查看開盤聯賽與場次\n"
            "• 發送「對沖」➔ 聽牌對沖保本計算\n"
            "• 發送「功能表」➔ 查看完整功能說明"
        )

    def _search_parlay_for_bot(
        self,
        target_mult: float,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        sport_filter: Optional[str] = None,
    ) -> str:
        """Execute parlay combo search and format betting recommendation with Kelly sizing."""
        try:
            if not parlay_engine:
                from core.signal_hub import SignalHub
                from core.parlay_engine import ParlayEngine
                parlay_engine = ParlayEngine(signal_hub=SignalHub())

            if not available_legs:
                from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter
                adapter = PlaysportOddsAdapter()
                raw_legs = adapter.get_taiwan_legs()
                if raw_legs:
                    available_legs = [parlay_engine.signal_hub.evaluate_taiwan_leg(leg) for leg in raw_legs]

            if not available_legs:
                return (
                    f"🎯 目標倍率：{target_mult:.1f} 倍\n"
                    "---------------------------\n"
                    "⚠️ 目前盤口處於交界或夜間封盤時段，無合格即時開盤賽事。\n"
                    "系統已記錄您的需求，早盤開出新盤口時將優先為您運算推薦！"
                )

            search_pool = available_legs
            sport_note = ""
            if sport_filter:
                filtered = [
                    l for l in available_legs
                    if (getattr(l, "sport", None) or (isinstance(l, dict) and l.get("sport"))) == sport_filter
                ]
                if len(filtered) >= 2:
                    search_pool = filtered
                else:
                    sport_names = {"soccer": "足球", "baseball": "棒球", "basketball": "籃球", "football": "美足"}
                    sport_note = f"⚠️ 今日開盤之【{sport_names.get(sport_filter, sport_filter)}】合格賽事不足以單獨組成串關，以下為您提供跨球種高勝率推薦：\n\n"

            res = parlay_engine.search_parlays(
                legs=search_pool,
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
                total_odds = float(best.get("total_odds", target_mult))
                joint_prob = float(best.get("joint_probability", 0.0)) * 100
                ev_pct = float(best.get("parlay_ev_pct", 0.0))
                legs = best.get("legs", [])

                # Kelly sizing recommendation
                from core.kelly import calculate_kelly_stake
                kelly_res = calculate_kelly_stake(
                    win_probability=max(0.01, min(0.99, joint_prob / 100.0)),
                    decimal_odds=total_odds,
                    bankroll=200.0,
                )
                recommended_stake = kelly_res.get("quarter_kelly_stake", 10.0)

                lines = []
                if sport_note:
                    lines.append(sport_note.strip())
                lines.extend([
                    f"🎯 【{best.get('parlay_name', '精選串關')} · 總賠率 {total_odds}x】",
                    f"⚖️ 估算勝率：{joint_prob:.1f}% | 期望值 EV：{ev_pct:+.1f}%",
                    f"💵 建議注碼：NT$ {recommended_stake:.0f} (1/4 凱利風控)",
                    "---------------------------",
                ])
                for idx, l in enumerate(legs, start=1):
                    lines.append(self.format_parlay_leg(l, idx))
                lines.append("---------------------------")
                lines.append("祝您場場過關，財庫滿載！🐕")
                return "\n".join(lines)
            else:
                return (
                    f"🔍 已為您精算 {target_mult:.1f} 倍組合。\n"
                    "目前盤口中暫無完全符合 +EV 與風控標準之理想組合，建議微調倍率（如「10倍」或「30倍」）重新嘗試！"
                )
        except Exception as exc:
            logger.error("Error in _search_parlay_for_bot: %s", exc)
            return f"搜尋組合時發生錯誤，請稍候重試：{exc}"

    def _get_wallet_status_text(self, wallet_mgr: Optional[Any] = None) -> str:
        """Format wallet and financial discipline report."""
        try:
            if not wallet_mgr:
                from core.wallet import WeeklyWalletManager
                wallet_mgr = WeeklyWalletManager()
            status = wallet_mgr.get_status()
            return (
                "💰 【瘋狗流資金與戰績總覽】\n"
                "===========================\n"
                f"• 本週可玩餘額：NT$ {status['weekly_wallet_balance']:.2f}\n"
                f"• 本週已下注額：NT$ {status['weekly_staked']:.2f}\n"
                f"• 🔒 保留儲備池：NT$ {status['prize_pool']:.2f}\n"
                f"• 歷史累計淨利：NT$ {status.get('lifetime_net_profit', 0.0):+,.2f}\n"
                f"• 累計下注金額：NT$ {status.get('lifetime_staked', 0.0):,.2f}\n"
                f"• 累計實收派彩：NT$ {status.get('lifetime_gross_payout', 0.0):,.2f}\n"
                "===========================\n"
                "嚴守每週 NT$200 風控紀律，獲利全數入庫！🐕"
            )
        except Exception as exc:
            logger.error("Error reading wallet: %s", exc)
            return f"錢包數據讀取異常：{exc}"

    def _get_radar_status_text(self) -> str:
        """Format active league radar status."""
        try:
            from core.season_radar import SeasonRadar
            radar = SeasonRadar()
            summary = radar.scan()
            active = [r for r in summary if r.get("status") == "GREEN"]
            if active:
                lines = [
                    "☀️ 【今日運彩賽季開盤雷達】",
                    "===========================",
                ]
                for r in active:
                    lines.append(f"🟢 {r.get('icon', '⚽')} {r.get('name')}：{r.get('taiwan_market_count', 0)} 場開盤")
                lines.append("===========================")
                lines.append("您可以直接傳送「20倍」或點選下方按鈕開始組單！")
                return "\n".join(lines)
            return "☀️ 今日各聯賽盤口目前多處於交界或休兵時段，稍後開盤將自動更新！"
        except Exception as exc:
            logger.error("Error reading radar: %s", exc)
            return f"賽季雷達讀取異常：{exc}"

    def _get_hedging_status_text(self) -> str:
        """Format current hedging/arbitrage status for active open tickets."""
        try:
            from core.ticket_recorder import TicketRecorder
            from core.hedging import calculate_hedge
            recorder = TicketRecorder()
            open_tickets = recorder.list_tickets(status_filter="OPEN")
            if not open_tickets:
                return (
                    "🛡️ 【對沖保本狀態查詢】\n"
                    "---------------------------\n"
                    "目前系統中暫無進行中的未結算注單。\n"
                    "下注後系統會自動全程盯盤，一旦進入最後一關「聽牌」，會第一時間主動推播對沖方案給您！"
                )

            hedging_ready = []
            for t in open_tickets:
                legs = t.get("legs", [])
                if len(legs) >= 2:
                    pending_legs = [l for l in legs if l.get("outcome") in (None, "PENDING", "")]
                    if len(pending_legs) == 1:
                        hedging_ready.append((t, pending_legs[0]))

            if hedging_ready:
                t, pending = hedging_ready[0]
                analysis = calculate_hedge(
                    ticket_stake=float(t.get("stake", 0.0)),
                    potential_payout=float(t.get("potential_payout", 0.0)),
                    opposing_odds=1.75,
                    opposing_selection="反向盤口",
                )
                return (
                    "🔔 【恭喜聽牌！即時對沖方案】\n"
                    "===========================\n"
                    f"🎫 串關：{t.get('sports_summary', '運彩高倍串關')}\n"
                    f"🎯 潛在派彩：NT$ {float(t.get('potential_payout', 0.0)):,.2f}\n"
                    f"⏳ 最後決戰：[{pending.get('league')}] {pending.get('away_team')} vs {pending.get('home_team')}\n"
                    f"手持關卡：【{pending.get('selection')}】\n\n"
                    "🛡️ 建議對沖策略：\n"
                    f"• ① 保本對沖：反買 NT$ {analysis['breakeven_stake']:.0f} ➔ 0 虧損\n"
                    f"• ② 絕對鎖利：反買 NT$ {analysis['guaranteed_stake']:.0f} ➔ 保底淨賺 NT$ {analysis['guaranteed_profit']:,.2f}！"
                )

            return (
                f"🛡️ 【對沖監控中】\n"
                "---------------------------\n"
                f"目前共有 {len(open_tickets)} 張進行中的未結算注單。\n"
                "目前尚未達到最後一關聽牌條件，系統正密切監控賽事結果中！"
            )
        except Exception as exc:
            logger.error("Error reading hedging: %s", exc)
            return f"對沖狀態查詢異常：{exc}"
