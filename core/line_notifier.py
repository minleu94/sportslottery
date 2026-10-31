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
from core.tunnel_runtime import load_active_runtime
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
        self.last_recommended_parlay: Optional[Dict[str, Any]] = None
        self.last_parlay_candidates: List[Dict[str, Any]] = []
        self.last_candidate_index: int = 0
        self.last_search_context: Dict[str, Any] = {}

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
        image_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a push message (text and optional image) to the configured LINE User ID or Group ID."""
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

        messages_list = []
        if image_url:
            messages_list.append({
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            })
        messages_list.append({
            "type": "text",
            "text": text,
        })

        payload = {
            "to": target,
            "messages": messages_list,
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
        image_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a reply to an incoming webhook message using replyToken (free quota), supporting images."""
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

        messages_list = []
        if image_url:
            messages_list.append({
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            })

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
        messages_list.append(msg_obj)

        payload = {
            "replyToken": reply_token,
            "messages": messages_list,
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
        """Standard main menu shortcuts displayed above keyboard in LINE chat."""
        return [
            {"label": "🎯 智慧串關", "text": "智慧串關"},
            {"label": "🛡️ 穩健保底", "text": "高勝率保底"},
            {"label": "☀️ 今日賽事", "text": "今日開盤"},
            {"label": "💰 資產戰績", "text": "查戰績"},
            {"label": "🛠️ 工具箱/QR", "text": "功能表"},
            {"label": "👤 個人設定", "text": "個人設定"},
        ]

    @staticmethod
    def parlay_quick_replies(has_next: bool = True) -> List[Dict[str, str]]:
        """Contextual actions displayed immediately after a parlay recommendation."""
        replies = [
            {"label": "📱 產生此單 QR 碼", "text": "QR"},
        ]
        if has_next:
            replies.append({"label": "🎲 換一組推薦", "text": "換一組"})
        replies.extend([
            {"label": "🎯 找20倍", "text": "20倍"},
            {"label": "🔥 找50倍", "text": "50倍"},
            {"label": "🛡️ 穩健保底", "text": "高勝率保底"},
            {"label": "🏠 回主選單", "text": "功能表"},
        ])
        return replies

    @staticmethod
    def multiplier_menu_quick_replies() -> List[Dict[str, str]]:
        """Sub-tier options when user asks for multiplier parlay menu."""
        return [
            {"label": "🛡️ 穩健 2.5倍", "text": "高勝率保底"},
            {"label": "🔥 瘋狗 10倍", "text": "10倍"},
            {"label": "🎯 經典 20倍", "text": "20倍"},
            {"label": "💥 狂暴 50倍", "text": "50倍"},
            {"label": "🚀 登月 100倍", "text": "100倍"},
            {"label": "⚽ 足球 20倍", "text": "足球 20倍"},
            {"label": "🏀 NBA 15倍", "text": "NBA 15倍"},
            {"label": "🏠 回主選單", "text": "功能表"},
        ]

    @staticmethod
    def radar_menu_quick_replies() -> List[Dict[str, str]]:
        """Sub-tier options when user inspects daily radar or sports."""
        return [
            {"label": "⚽ 足球 20倍", "text": "足球 20倍"},
            {"label": "🏀 NBA 15倍", "text": "NBA 15倍"},
            {"label": "🎯 瘋狗 20倍", "text": "20倍"},
            {"label": "🛡️ 穩健保底", "text": "高勝率保底"},
            {"label": "🏠 回主選單", "text": "功能表"},
        ]

    @staticmethod
    def wallet_menu_quick_replies() -> List[Dict[str, str]]:
        """Sub-tier options when user inspects wallet / finance."""
        return [
            {"label": "🛡️ 聽牌對沖計算", "text": "對沖"},
            {"label": "💰 重新整理戰績", "text": "查戰績"},
            {"label": "👤 玩家登入/設定", "text": "個人設定"},
            {"label": "🎯 智慧串關", "text": "智慧串關"},
            {"label": "🏠 回主選單", "text": "功能表"},
        ]

    @staticmethod
    def tools_menu_quick_replies() -> List[Dict[str, str]]:
        """Sub-tier options for tools / kiosk slip / hedging."""
        return [
            {"label": "📱 產生投注 QR 碼", "text": "QR"},
            {"label": "🛡️ 聽牌對沖計算", "text": "對沖"},
            {"label": "💰 查戰績錢包", "text": "查戰績"},
            {"label": "👤 個人設定/PIN", "text": "個人設定"},
            {"label": "🎯 找20倍串關", "text": "20倍"},
            {"label": "🏠 回主選單", "text": "功能表"},
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

    def _generate_qr_for_combo(
        self,
        combo: Dict[str, Any],
        stake: float = 100.0,
    ) -> Dict[str, Any]:
        """Generate a Taiwan Sports Lottery 3.0 QR Code image and kiosk cheat sheet."""
        from core.lottery_qr import build_lottery_slip_payload, generate_qr_code_file
        import hashlib

        legs = combo.get("legs", [])
        parlay_name = combo.get("parlay_name", f"{len(legs)} 串 1")
        total_odds = float(combo.get("total_odds", 1.0))
        potential_payout = round(stake * total_odds, 0)

        slip = build_lottery_slip_payload(
            legs=legs,
            total_stake=stake,
            parlay_name=parlay_name,
        )
        compact_code = slip["compact_code"]

        # Cache file under static/qr/
        code_hash = hashlib.sha256(compact_code.encode("utf-8")).hexdigest()[:12]
        qr_filename = f"tsl_{code_hash}.png"
        qr_file_path = ROOT_DIR / "static" / "qr" / qr_filename

        generate_qr_code_file(compact_code, qr_file_path)

        # Detect active public tunnel for image hosting
        status_file = ROOT_DIR / "data" / "line_bot_runtime.json"
        runtime = load_active_runtime(status_file)
        tunnel_url = runtime.get("tunnel_url", "")

        image_url = f"{tunnel_url}/static/qr/{qr_filename}" if tunnel_url else None

        cheat_lines = [
            "🏪 【台彩 3.0 免劃單 · 臨櫃出票條碼】",
            "===========================",
            f"🎫 組合：{parlay_name} (總賠率 {total_odds:.2f}x)",
            f"💵 建議注碼：NT$ {stake:.0f} (預期派彩 NT$ {potential_payout:,.0f})",
            "---------------------------",
            "📋 賽事選號明細 (店員代劃單對照)：",
        ]
        for idx, l in enumerate(slip["legs"], start=1):
            clean_league = re.sub(r"^unknown_", "", str(l.get("league") or ""), flags=re.IGNORECASE).strip()
            if "colombia" in clean_league.lower() or "columbia" in clean_league.lower():
                clean_league = "哥倫比亞甲級足球聯賽"
            elif clean_league.lower() == "unknown":
                clean_league = "精選賽事"
            clean_sel = re.sub(r"\s*\(\d+(?:\.\d+)?\)\s*$", "", str(l.get("selection") or "")).strip() or l.get("selection")
            cheat_lines.append(
                f"{idx}. 賽事編號 #{l['event_id']} [{clean_league}]\n"
                f"   {l['match']}\n"
                f"   ➔ 玩法：{l['market']} | 選號：【{clean_sel}】({l['odds']:.2f}x)"
            )
        cheat_lines.append("===========================")
        cheat_lines.append("📲 使用方式：")
        cheat_lines.append("至彩券行櫃檯將手機對準機台鏡頭掃描上方 QR Code，即可 1 秒免劃單出票！🎯")

        return {
            "text": "\n".join(cheat_lines),
            "image_url": image_url,
            "compact_code": compact_code,
        }

    def notify_ticket_qr(
        self,
        combo: Dict[str, Any],
        stake: float = 100.0,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Push a Taiwan Sports Lottery QR Code and slip description to LINE."""
        qr_data = self._generate_qr_for_combo(combo, stake)
        return self.send_push_message(
            text=qr_data["text"],
            user_id=user_id,
            image_url=qr_data.get("image_url"),
        )

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

        # 5. International Market Benchmark & Splits Note
        market_intel_notes = []
        evidence = leg.get("signal_evidence") or {}
        is_market_synth = bool(evidence.get("is_market_synthetic") or evidence.get("is_synthetic"))
        is_splits_synth = bool(evidence.get("is_splits_synthetic"))

        sharp_p = evidence.get("sharp_fair_probability")
        sharp_ev = evidence.get("sharp_expected_value_pct")

        if is_market_synth:
            # Synthetic fixtures must NEVER be presented as verified +EV in recommendations
            synth_p = evidence.get("synthetic_fair_probability")
            if synth_p:
                market_intel_notes.append(f"   🌐 國際參考盤口: 模擬樣本 {synth_p * 100:.1f}% (測試展示，非真實優勢)")
        elif sharp_p and sharp_ev is not None:
            ev_str = f" (+EV {sharp_ev:+.1f}%)" if sharp_ev > 0 else f" ({sharp_ev:+.1f}%)"
            market_intel_notes.append(f"   🌐 國際公允勝率: {sharp_p * 100:.1f}%{ev_str}")

        money_p = evidence.get("money_percentage")
        bet_p = evidence.get("bet_percentage")
        if money_p is not None and bet_p is not None:
            if is_splits_synth:
                market_intel_notes.append(f"   💰 國際籌碼傾向: 資金 {money_p:.0f}% / 票數 {bet_p:.0f}% (模擬數據)")
            else:
                div_note = " (⚡資金顯著分歧)" if (money_p - bet_p) >= 15.0 else ""
                market_intel_notes.append(f"   💰 國際籌碼傾向: 資金 {money_p:.0f}% / 票數 {bet_p:.0f}%{div_note}")

        extra_text = ("\n" + "\n".join(market_intel_notes)) if market_intel_notes else ""

        return (
            f"{idx}. {icon} [{league_name}]\n"
            f"   {matchup}{time_str}\n"
            f"   🎯 {market_str}{extra_text}"
        )

    @staticmethod
    def get_menu_text() -> str:
        """Full interactive menu formatted for mobile LINE chat."""
        return (
            "🐕 【瘋狗流 LINE 助手指令說明 · 功能表 / 工具箱】\n"
            "===========================\n"
            "您可以直接點選下方快捷膠囊，或傳送以下指令：\n\n"
            "📱 【彩券行免劃單 QR 碼】\n"
            "• 點選「📱 產生投注 QR 碼」或輸入「QR」\n"
            "  ➔ 即時生成台彩 3.0 機台掃描條碼，實體彩券行 1 秒出票！\n\n"
            "🛡️ 【聽牌對沖與鎖利】\n"
            "• 點選「🛡️ 聽牌對沖」或輸入「對沖」\n"
            "  ➔ 若手上注單只剩最後一關，即時計算 100% 鎖利或 0 虧損保本計畫！\n\n"
            "💰 【資金與戰績管理】\n"
            "• 點選「💰 查戰績錢包」或輸入「查戰績」\n"
            "  ➔ 查看本週 NT$200 風控錢包餘額、保留儲備池與歷史獲利！\n\n"
            "👤 【玩家設定與 PIN 碼】\n"
            "• 點選「👤 個人設定」或輸入「改密碼 0000 1234」\n"
            "  ➔ 綁定 LINE 專屬錢包或修改 PIN 密碼！\n"
            "===========================\n"
            "💡 提示：點擊下方快捷按鈕即可一鍵送出！"
        )

    def handle_user_message(
        self,
        user_text: str,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        wallet_mgr: Optional[Any] = None,
        line_user_id: Optional[str] = None,
    ) -> str:
        """Process inbound text commands from LINE (e.g. '20倍', '功能表', '查戰績', '今日開盤', '對沖')."""
        import re
        cmd = user_text.strip().lower()
        if not cmd:
            return self.get_menu_text()

        # If user is bound to a specific Profile, wire up their personal wallet
        if line_user_id and wallet_mgr is None:
            try:
                from core.profile_manager import ProfileManager
                from core.wallet import WeeklyWalletManager
                pm = ProfileManager()
                bound = pm.get_profile_by_line_user_id(line_user_id)
                if bound:
                    wallet_mgr = WeeklyWalletManager(profile_id=bound["id"])
            except Exception:
                pass

        # 1. Greetings & Menu Triggers
        menu_triggers = [
            "功能表", "選單", "menu", "help", "說明", "指令", "你好", "您好", "哈囉",
            "hello", "hi", "嗨", "開始", "start", "安安", "?", "？", "怎麼用", "功能指南"
        ]
        if any(cmd == t for t in menu_triggers):
            return self.get_menu_text()

        # 1.1 Banker Mode / High Win Rate (保底/穩健)
        if any(k in cmd for k in ["高勝率", "保底", "穩健", "銀行家", "banker"]):
            return self._search_parlay_for_bot(2.5, parlay_engine, available_legs)

        # 1.15 Next Combo / Alternative Parlay (換一組推薦)
        if any(k in cmd for k in ["換一組", "另一組", "換一張", "下一組", "換", "next", "reroll", "再一組"]):
            return self._get_next_parlay_candidate(parlay_engine, available_legs)

        # 1.2 Profile & Personal Settings (Interactive in-LINE + Public HTTPS Web Link)
        profile_reply = self._handle_profile_commands(user_text, line_user_id=line_user_id)
        if profile_reply:
            return profile_reply

        # 1.3 Multiplier Selection Menu (智慧串關選倍率)
        if any(cmd == k or k in cmd for k in ["智慧串關", "選倍率", "串關"]):
            return (
                "🎯 【瘋狗流 · 智慧串關倍率選單】\n"
                "===========================\n"
                "請直接輸入您想挑戰的目標倍率：\n\n"
                "🛡️ 【穩健保底組】(高勝率累積戰力)\n"
                "• 輸入「2倍」或「3倍」➔ 銀行家 Banker 定海神針單\n\n"
                "🔥 【瘋狗起步組】(以小博大熱門)\n"
                "• 輸入「10倍」、「20倍」或「30倍」\n\n"
                "🚀 【極限狂暴組】(十元登月發家)\n"
                "• 輸入「50倍」、「100倍」或「200倍」\n\n"
                "💡 提示：也可以指定球種，例如輸入「足球 20倍」或「NBA 10倍」！"
            )

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

        # 6. QR Code Slip Generation: e.g. "qr", "產qr", "條碼", "投注單", "qrcode"
        if any(cmd == q or q in cmd for q in ["qr", "產qr", "條碼", "投注單", "qrcode", "出票", "劃單"]):
            return self._handle_qr_request(parlay_engine, available_legs)["text"]

        # 7. Fallback to Menu with Prompt
        return (
            "🐕 【瘋狗流 LINE 助手指令說明】\n"
            "---------------------------\n"
            f"收到指令：「{user_text}」\n"
            "未能辨識此關鍵字。您可以點擊下方快捷按鈕，或參考以下指令：\n\n"
            "• 發送「20倍」➔ 智慧搜尋 20 倍串關\n"
            "• 發送「QR」➔ 取得彩券行掃描出單條碼\n"
            "• 發送「查戰績」➔ 查看每週額度與獲利\n"
            "• 發送「今日開盤」➔ 查看開盤聯賽與場次\n"
            "• 發送「對沖」➔ 聽牌對沖保本計算\n"
            "• 發送「功能表」➔ 查看完整功能說明"
        )

    def handle_user_message_full(
        self,
        user_text: str,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        wallet_mgr: Optional[Any] = None,
        line_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process inbound text command and return dict with 'text', 'image_url', and contextual 'quick_replies'."""
        cmd = user_text.strip().lower()

        # 1. QR Code Request
        if any(cmd == q or q in cmd for q in ["qr", "產qr", "條碼", "投注單", "qrcode", "出票", "劃單"]):
            qr_res = self._handle_qr_request(parlay_engine, available_legs)
            qr_res["quick_replies"] = [
                {"label": "🎲 換一組推薦", "text": "換一組"},
                {"label": "🎯 找20倍", "text": "20倍"},
                {"label": "🛡️ 穩健保底", "text": "高勝率保底"},
                {"label": "🏠 回主選單", "text": "功能表"},
            ]
            return qr_res

        # 2. Main Text Command Processing
        text_reply = self.handle_user_message(
            user_text,
            parlay_engine=parlay_engine,
            available_legs=available_legs,
            wallet_mgr=wallet_mgr,
            line_user_id=line_user_id,
        )

        # 3. Contextual Quick Reply Routing
        quick_replies = self.default_quick_replies()

        # A. Multiplier Menu requested
        if any(cmd == k or k in cmd for k in ["智慧串關", "選倍率", "串關"]):
            quick_replies = self.multiplier_menu_quick_replies()

        # B. Parlay Search or Next Candidate triggered
        elif any(k in cmd for k in ["高勝率", "保底", "穩健", "銀行家", "banker", "換一組", "另一組", "換", "next", "reroll"]) or (
            ("倍" in cmd or "x" in cmd or cmd.isdigit() or "串" in cmd) and re.search(r"\d", cmd)
        ):
            has_next = len(self.last_parlay_candidates) > 1
            quick_replies = self.parlay_quick_replies(has_next=has_next)

        # C. Season Radar requested
        elif any(k in cmd for k in ["雷達", "開盤", "今天", "賽程", "賽事"]):
            quick_replies = self.radar_menu_quick_replies()

        # D. Wallet / Performance requested
        elif any(k in cmd for k in ["戰績", "錢包", "餘額", "本金", "獲利", "本週"]):
            quick_replies = self.wallet_menu_quick_replies()

        # E. Menu / Tools requested
        elif any(cmd == t for t in ["功能表", "選單", "menu", "help", "說明", "指令", "你好", "您好", "哈囉", "hello", "hi", "嗨", "開始", "start", "安安", "?", "？", "怎麼用", "功能指南"]):
            quick_replies = self.tools_menu_quick_replies()

        return {
            "text": text_reply,
            "image_url": None,
            "quick_replies": quick_replies,
        }

    def _handle_qr_request(
        self,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Generate QR code for the last recommended parlay or find the best combo."""
        combo = self.last_recommended_parlay
        if not combo:
            # Trigger search to populate last_recommended_parlay if not yet present
            self._search_parlay_for_bot(20.0, parlay_engine, available_legs)
            combo = self.last_recommended_parlay

        if combo and combo.get("legs"):
            return self._generate_qr_for_combo(combo, stake=100.0)

        return {
            "text": (
                "📱 【彩券行 QR Code 投注單】\n"
                "---------------------------\n"
                "⚠️ 目前尚未選定或搜尋串關組合。\n"
                "請先發送目標倍率（例如「20倍」或點選下方快捷按鈕），推薦組合後即可一秒產出實體條碼！"
            ),
            "image_url": None,
        }

    def _get_next_parlay_candidate(
        self,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
    ) -> str:
        """Cycle to the next parlay candidate for the last searched target."""
        if not self.last_parlay_candidates:
            target = self.last_search_context.get("target_mult", 20.0)
            sport = self.last_search_context.get("sport_filter")
            return self._search_parlay_for_bot(target, parlay_engine, available_legs, sport_filter=sport)

        self.last_candidate_index = (self.last_candidate_index + 1) % len(self.last_parlay_candidates)
        next_combo = self.last_parlay_candidates[self.last_candidate_index]
        self.last_recommended_parlay = next_combo

        total_odds = float(next_combo.get("total_odds", 1.0))
        joint_prob = float(next_combo.get("joint_probability", 0.0)) * 100
        ev_pct = float(next_combo.get("parlay_ev_pct", 0.0))
        legs = next_combo.get("legs", [])

        from core.kelly import calculate_kelly_stake
        kelly_res = calculate_kelly_stake(
            win_probability=max(0.01, min(0.99, joint_prob / 100.0)),
            decimal_odds=total_odds,
            bankroll=200.0,
        )
        recommended_stake = kelly_res.get("quarter_kelly_stake", 10.0)

        lines = [
            f"🎲 【替換推薦 · 第 {self.last_candidate_index + 1}/{len(self.last_parlay_candidates)} 組 · 總賠率 {total_odds}x】",
            f"⚖️ 估算勝率：{joint_prob:.1f}% | 期望值 EV：{ev_pct:+.1f}%",
            f"💵 建議注碼：NT$ {recommended_stake:.0f} (1/4 凱利風控)",
            "---------------------------",
        ]
        for idx, l in enumerate(legs, start=1):
            lines.append(self.format_parlay_leg(l, idx))
        lines.append("---------------------------")
        lines.append("📲 點擊下方【📱 產生此單 QR 碼】立即生成條碼，或點【🎲 換一組推薦】瀏覽更多！")
        return "\n".join(lines)

    def _search_parlay_for_bot(
        self,
        target_mult: float,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        sport_filter: Optional[str] = None,
    ) -> str:
        """Execute parlay combo search and format betting recommendation with Kelly sizing."""
        try:
            self.last_search_context = {"target_mult": target_mult, "sport_filter": sport_filter}
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
                self.last_parlay_candidates = top_combos
                self.last_candidate_index = 0
                best = top_combos[0]
                self.last_recommended_parlay = best
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
                cand_info = f" (共 {len(top_combos)} 組候選)" if len(top_combos) > 1 else ""
                lines.extend([
                    f"🎯 【{best.get('parlay_name', '精選串關')} · 總賠率 {total_odds}x{cand_info}】",
                    f"⚖️ 估算勝率：{joint_prob:.1f}% | 期望值 EV：{ev_pct:+.1f}%",
                    f"💵 建議注碼：NT$ {recommended_stake:.0f} (1/4 凱利風控)",
                    "---------------------------",
                ])
                for idx, l in enumerate(legs, start=1):
                    lines.append(self.format_parlay_leg(l, idx))
                lines.append("---------------------------")
                lines.append("📲 點擊下方【📱 產生此單 QR 碼】立即生成條碼，或點【🎲 換一組推薦】瀏覽更多！")
                lines.append("祝您場場過關，財庫滿載！🐕")
                return "\n".join(lines)
            else:
                self.last_parlay_candidates = []
                self.last_candidate_index = 0
                return (
                    f"🔍 已為您精算 {target_mult:.1f} 倍組合。\n"
                    "目前盤口中暫無完全符合 +EV 與風控標準之理想組合，建議微調倍率（如「10倍」或「30倍」）重新嘗試！"
                )
        except Exception as exc:
            logger.error("Error in _search_parlay_for_bot: %s", exc)
            return f"搜尋組合時發生錯誤，請稍候重試：{exc}"

    def _handle_profile_commands(self, user_text: str, line_user_id: Optional[str] = None) -> Optional[str]:
        """Handle profile status, public web link, and in-LINE profile commands."""
        clean_cmd = user_text.strip()
        cmd_lower = clean_cmd.lower()

        # Check in-LINE command: e.g. "綁定 小明 1234", "登入 小明 1234"
        m_bind = re.match(r"^(?:綁定|bind|登入|login)\s+([^\s]+)(?:\s+(\d{4}))?$", clean_cmd, re.IGNORECASE)
        # Check in-LINE command: "解綁", "解除綁定"
        m_unbind = re.match(r"^(?:解綁|解除綁定|unbind)(?:\s+(\d{4}))?$", clean_cmd, re.IGNORECASE)
        # Check in-LINE command: "改密碼 0000 1234", "修改密碼 0000 1234", "改pin 0000 1234"
        m_change_pin = re.match(r"^(?:改密碼|修改密碼|變更密碼|改pin|修改pin)\s+(\d{4})\s+(\d{4})$", clean_cmd, re.IGNORECASE)
        # Check in-LINE command: e.g. "切換 小明 1234", "切換 小明"
        m_switch = re.match(r"^(?:切換|switch)\s+([^\s]+)(?:\s+(\d{4}))?$", clean_cmd, re.IGNORECASE)
        # Check in-LINE command: "新增 小王 300 1234" or "新增玩家 小王 300 1234"
        m_add = re.match(r"^(?:新增玩家|建立玩家|新增|建立|create)\s+([^\s]+)(?:\s+(\d+(?:\.\d+)?))?(?:\s+(\d{4}))?$", clean_cmd, re.IGNORECASE)
        # Check in-LINE command: "預算 500" or "修改預算 500"
        m_cap = re.match(r"^(?:修改預算|預算|限額)\s+(\d+(?:\.\d+)?)$", clean_cmd, re.IGNORECASE)

        is_profile_query = any(k in cmd_lower for k in [
            "個人設定", "profile", "玩家", "個人池", "網頁", "決策台",
            "註冊", "帳號", "網址", "連結", "手機版", "設定", "修改",
            "忘記密碼", "忘記pin", "忘記", "登入", "login"
        ])

        if not (m_bind or m_unbind or m_change_pin or m_switch or m_add or m_cap or is_profile_query):
            return None

        # This help response is independent of profile data. Keep it available
        # even when the configured SQLite storage is temporarily unreachable.
        if any(k in cmd_lower for k in ["忘記密碼", "忘記pin", "忘記碼", "忘記"]):
            return (
                "💬 【忘記密碼 / PIN 碼】\n"
                "===========================\n"
                "忘記密碼請聯絡管理員 Archie！\n\n"
                "💡 系統預設初始 PIN 碼為 0000。\n"
                "若您先前已綁定 LINE 帳號，亦可直接傳送指令：\n"
                "「改密碼 <舊PIN> <新4位數PIN>」"
            )

        try:
            import urllib.parse
            from core.profile_manager import ProfileManager
            pm = ProfileManager()
            profs = pm.list_profiles()

            # If this LINE user has bound a profile, prioritize that profile
            bound_profile = pm.get_profile_by_line_user_id(line_user_id) if line_user_id else None
            cur = bound_profile or (profs[0] if profs else {"name": "主帳號", "weekly_play_cap": 200.0, "pin_code": "0000", "id": "default"})

            # Command 1: Bind LINE user to Profile
            if m_bind:
                target_name = m_bind.group(1).strip()
                target_pin = m_bind.group(2) or "0000"
                matched = next((p for p in profs if p["name"].lower() == target_name.lower()), None)
                if not matched:
                    names = "、".join([p["name"] for p in profs])
                    return f"❌ 找不到玩家「{target_name}」。目前已建立的玩家有：{names}\n\n💡 若要建立新玩家，請輸入：新增 {target_name} 200 0000"
                if not line_user_id:
                    return f"❌ 無法取得您的 LINE 身分識別，無法執行綁定。"
                try:
                    pm.bind_line_user(matched["id"], line_user_id=line_user_id, current_pin=target_pin)
                    return (
                        f"🎉 【LINE 帳號綁定成功】！\n"
                        f"===========================\n"
                        f"• 綁定玩家：【{matched['name']}】\n"
                        f"• 每週娛樂限額：NT$ {matched['weekly_play_cap']:.0f}\n\n"
                        f"日後您在此 LINE 對話中查詢「查戰績」、「餘額」或開啟網頁，系統皆會自動對應【{matched['name']}】的專屬資金池！"
                    )
                except Exception as exc:
                    return f"❌ 綁定失敗：{exc}"

            # Command 2: Unbind LINE user
            if m_unbind:
                if not bound_profile:
                    return "ℹ️ 您目前尚未綁定任何玩家 Profile。"
                target_pin = m_unbind.group(1) or bound_profile.get("pin_code", "0000")
                try:
                    pm.unbind_line_user(bound_profile["id"], current_pin=target_pin)
                    return f"✅ 已成功解除此 LINE 帳號與玩家【{bound_profile['name']}】的綁定。"
                except Exception as exc:
                    return f"❌ 解綁失敗：{exc}"

            # Command 3: Change PIN code directly via LINE
            if m_change_pin:
                old_pin = m_change_pin.group(1)
                new_pin = m_change_pin.group(2)
                try:
                    updated = pm.update_profile(cur["id"], current_pin=old_pin, new_pin_code=new_pin)
                    return (
                        f"✅ 【PIN 碼修改成功】！\n"
                        f"玩家【{updated['name']}】的 4 位數 PIN 碼已成功更新為：{updated['pin_code']}。\n"
                        f"請妥善保管您的新密碼，登入網頁版時請輸入新 PIN 碼！"
                    )
                except Exception as exc:
                    return f"❌ 修改密碼失敗：{exc}"

            if m_switch:
                target_name = m_switch.group(1).strip()
                target_pin = m_switch.group(2) or "0000"
                matched = next((p for p in profs if p["name"].lower() == target_name.lower()), None)
                if not matched:
                    names = "、".join([p["name"] for p in profs])
                    return f"❌ 找不到玩家「{target_name}」。目前已建立的玩家有：{names}\n\n💡 若要新增玩家，請輸入：新增 {target_name} 200 0000"
                if matched.get("pin_code") and matched["pin_code"] != "0000":
                    if target_pin != matched["pin_code"]:
                        return f"🔒 玩家「{target_name}」受 PIN 碼保護。請輸入：切換 {target_name} <4位PIN碼>"
                return (
                    f"✅ 【切換成功】當前操作玩家：【{matched['name']}】！\n"
                    f"• 每週娛樂限額：NT$ {matched['weekly_play_cap']:.0f}\n"
                    f"• 資金池與戰績現已對應至該玩家專屬紀錄。"
                )

            if m_add:
                new_name = m_add.group(1).strip()
                new_cap = float(m_add.group(2)) if m_add.group(2) else 200.0
                new_pin = m_add.group(3) or "0000"
                try:
                    created = pm.create_profile(name=new_name, weekly_play_cap=new_cap, pin_code=new_pin)
                    # If this LINE user isn't bound, optionally auto-bind them
                    if line_user_id and not bound_profile:
                        pm.bind_line_user(created["id"], line_user_id=line_user_id, current_pin=new_pin)
                        bind_note = "\n🔗 已自動將此 LINE 帳號與新玩家完成綁定！"
                    else:
                        bind_note = ""
                    return (
                        f"🎉 成功建立新玩家 Profile！\n"
                        f"• 玩家名稱：【{created['name']}】\n"
                        f"• 每週娛樂限額：NT$ {created['weekly_play_cap']:.0f}\n"
                        f"• 安全 PIN 碼：{created['pin_code']}{bind_note}\n\n"
                        f"已為其配置獨立娛樂錢包與投注紀錄。"
                    )
                except Exception as exc:
                    return f"❌ 建立玩家失敗：{exc}"

            if m_cap:
                new_cap = float(m_cap.group(1))
                try:
                    updated = pm.update_profile(cur["id"], current_pin=cur.get("pin_code", "0000"), new_weekly_play_cap=new_cap)
                    return (
                        f"✅ 【{updated['name']}】每週娛樂預算已更新為：NT$ {updated['weekly_play_cap']:.0f}！\n"
                        f"（每週一自動重置額度）"
                    )
                except Exception as exc:
                    return f"❌ 更新預算失敗：{exc}"

            # Resolve public HTTPS URL and local network URL (Port 8000)
            runtime_file = ROOT_DIR / "data" / "line_bot_runtime.json"
            public_url = load_active_runtime(runtime_file).get("tunnel_url")

            lan_ip = "127.0.0.1"
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                lan_ip = s.getsockname()[0]
                s.close()
            except Exception:
                pass

            profs_str = "、".join([p["name"] for p in profs])
            user_param = f"?user={urllib.parse.quote(cur['name'])}" if cur.get("name") else ""
            
            web_parts = []
            if public_url:
                web_parts.append(
                    f"🌐 【手機公網決策台】（出門在外 4G/5G 隨時開）：\n"
                    f"👉 {public_url}{user_param}"
                )
            if lan_ip and lan_ip != "127.0.0.1":
                web_parts.append(
                    f"📶 【家用 Wi-Fi 內網連線】：\n"
                    f"👉 http://{lan_ip}:8000{user_param}"
                )
            web_parts.append("💡 進入網頁後，輸入 4 位數 PIN 碼（預設 0000）即可登入；新朋友亦可點選「快速註冊」1秒免信箱直接開通！")
            web_section = "\n" + "\n\n".join(web_parts) + "\n"

            bind_status_str = f"（已綁定此 LINE）" if bound_profile else "（未綁定，可傳送「綁定 <名字> <PIN碼>」連動）"

            return (
                "👤 【玩家 Profile 與獨立資金池】\n"
                "===========================\n"
                f"• 當前操作玩家：【{cur['name']}】{bind_status_str}\n"
                f"• 每週娛樂限額：NT$ {cur['weekly_play_cap']:.0f}\n"
                f"• 現有玩家名單：{profs_str}\n"
                f"• 安全防護：4 位數 PIN 碼保護中\n"
                f"{web_section}\n"
                "🔒 本系統支援多玩家獨立池子：\n"
                "每位玩家各自記錄每週預算、中獎保留池與下注戰績，帳目互不干擾！\n\n"
                "💬 【LINE 快捷指令說明】：\n"
                "•「綁定 <名字> <PIN>」➔ 將此 LINE 帳號綁定至玩家\n"
                "•「改密碼 <舊PIN> <新PIN>」➔ 直接在 LINE 修改密碼\n"
                "•「新增 <名字> <金額> <PIN>」➔ 建立新帳號\n"
                "•「預算 <金額>」➔ 調整目前玩家每週額度\n"
                "•「查戰績」➔ 查看目前玩家本週結算與中獎池"
            )
        except Exception as exc:
            logger.error("Error in profile handling: %s", exc)
            return f"Profile 讀取異常：{exc}"

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
            from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter
            from core.scraper import ALLIANCE_MAP
            radar = SeasonRadar()
            adapter = PlaysportOddsAdapter()
            legs = adapter.get_taiwan_legs(list(ALLIANCE_MAP))
            summary = radar.get_radar_summary(taiwan_legs=legs)
            active = [r for r in summary if r.get("status") == "GREEN" or r.get("taiwan_market_count", 0) > 0]
            if active:
                lines = [
                    "☀️ 【今日運彩賽季開盤雷達】",
                    "===========================",
                ]
                for r in active:
                    lines.append(f"🟢 {r.get('icon', '⚽')} {r.get('name')}：{r.get('taiwan_market_count', 0)} 場開盤")
                lines.append("===========================")
                lines.append("您可以直接點選【智慧串關】或傳送「20倍」開始組單！")
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
