#!/usr/bin/env python3
"""🐕 台灣運彩「瘋狗流」高倍串關決策台.

核心三問：
① 今天有什麼可以玩？ (賽季雷達: 🟢/🟡/🔴)
② 我想玩幾倍，哪些組合值得看？ (瘋狗看盤: 10~500倍 串關 & Signal Hub)
③ 我這週還有多少錢可以玩？ (每週 NT$200 錢包與獲利保留池)
"""

from __future__ import annotations

import json
import hashlib
import sys
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

# Ensure core package on path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.model_registry import ModelRegistry
from core.bet_validation import assess_leg, REASON_LABELS
from core.parlay_engine import ParlayEngine
from core.performance_metrics import PerformanceMetricsEngine
from ui.metric_format import metric_number
from core.scraper import ALLIANCE_MAP, PlaysportScraper
from core.season_radar import SeasonRadar
from core.shadow_portfolio import ShadowPortfolioManager
from core.signal_hub import SignalHub
from core.strategy_version import STRATEGY_VERSION, get_strategy_metadata
from core.ticket_recorder import TicketRecorder
from core.wallet import WEEKLY_PLAY_CAP, WeeklyWalletManager
from integrations.common.models import TaiwanLeg
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter
from ui.metric_guide import probability_label, render_leg_source_evidence
from ui.source_overview import render_source_overview
from ui.ticket_submission import readiness, recommendation_fingerprint, record_recommendation
from ui.navigation import render_sidebar_navigation
from core.parlay_validation import shared_event_exposure
from ui.model_acceptance_display import acceptance_rows, acceptance_label
from ui.research_overview import render_research_overview, read_jsonl
from core.research_paths import research_paths
from core.parlay_validation import evaluate_parlay_forward


st.set_page_config(
    page_title="台灣運彩 瘋狗流決策台",
    page_icon="🐕",
    layout="wide",
    initial_sidebar_state="expanded",
)
render_sidebar_navigation()

# Custom Styling
st.markdown(
    """
    <style>
    .brand-header {
        font-size: 2.2rem;
        font-weight: 900;
        background: linear-gradient(90deg, #ff4b4b, #ff9100);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.1rem;
    }
    .brand-sub {
        font-size: 1.05rem;
        color: #9e9e9e;
        margin-bottom: 0.8rem;
    }
    .source-health-ribbon {
        background: #141622;
        border: 1px solid #282a3d;
        border-radius: 8px;
        padding: 10px 16px;
        margin-bottom: 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
    }
    .wallet-metric-box {
        background: #181924;
        border: 1px solid #2d2f3f;
        border-radius: 12px;
        padding: 16px;
        text-align: center;
    }
    .ticket-card {
        background: #1e1f2b;
        border: 1px solid #36384d;
        border-radius: 12px;
        padding: 18px;
        margin-bottom: 14px;
    }
    .radar-card-green {
        background: rgba(46, 125, 50, 0.15);
        border: 1px solid #2e7d32;
        border-radius: 10px;
        padding: 14px;
        margin-bottom: 10px;
    }
    .radar-card-yellow {
        background: rgba(245, 124, 0, 0.15);
        border: 1px solid #f57c00;
        border-radius: 10px;
        padding: 14px;
        margin-bottom: 10px;
    }
    .radar-card-red {
        background: rgba(198, 40, 40, 0.10);
        border: 1px solid #5c2020;
        border-radius: 10px;
        padding: 14px;
        margin-bottom: 10px;
        opacity: 0.75;
    }
    .why-box {
        background: #151622;
        border: 1px solid #292c3f;
        border-radius: 8px;
        padding: 12px 16px;
        margin-top: 8px;
        margin-bottom: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


from core.snapshot_logger import PredictionSnapshotLogger

@st.cache_resource
def get_system_components(prediction_manifest_hash: str):
    # Invalidate cached adapter instances when executable prediction code or
    # configuration changes; presentation-only edits preserve this cache key.
    wallet_mgr = WeeklyWalletManager()
    ticket_recorder = TicketRecorder(wallet=wallet_mgr)
    odds_adapter = PlaysportOddsAdapter()
    signal_hub = SignalHub()
    parlay_engine = ParlayEngine(signal_hub=signal_hub)
    season_radar = SeasonRadar()
    snapshot_logger = PredictionSnapshotLogger()
    shadow_portfolio = ShadowPortfolioManager()
    metrics_engine = PerformanceMetricsEngine()
    return wallet_mgr, ticket_recorder, odds_adapter, signal_hub, parlay_engine, season_radar, snapshot_logger, shadow_portfolio, metrics_engine


runtime_prediction_hash = get_strategy_metadata()["prediction_manifest_hash"]
wallet_mgr, ticket_recorder, odds_adapter, signal_hub, parlay_engine, _cached_radar, snapshot_logger, shadow_portfolio, metrics_engine = get_system_components(runtime_prediction_hash)
season_radar = SeasonRadar()


# Header Brand
st.markdown("<div class='brand-header'>🐕 台灣運彩「瘋狗流」決策系統</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='brand-sub'>賽季雷達 · 10~500倍 情報串關 · 每週 NT$ 200 娛樂風控</div>",
    unsafe_allow_html=True,
)

st.caption("資料來源：玩運彩公開盤口、專家推薦與投票；模型與 EV 由專案計算。各筆時效請查看推薦證據，MLB Elo 目前為實驗估計。")

# Top Wallet Banner (Always visible & prominent)
wallet_status = wallet_mgr.get_status()

w_col1, w_col2, w_col3, w_col4 = st.columns(4)
with w_col1:
    st.metric(
        label="💰 ① 本週可玩餘額",
        value=f"NT$ {wallet_status['weekly_wallet_balance']:.2f}",
        delta=f"本週預算上限 NT$ {wallet_status['weekly_play_cap']:.0f}",
    )
with w_col2:
    st.metric(
        label="🎯 ② 本週已下注",
        value=f"NT$ {wallet_status['weekly_staked']:.2f}",
        delta=f"累計下注 NT$ {wallet_status.get('lifetime_staked', 0.0):,.0f}",
    )
with w_col3:
    st.metric(
        label="🔒 ③ 保留儲備池 (Reserve Bankroll)",
        value=f"NT$ {wallet_status['prize_pool']:.2f}",
        delta=f"累計淨利 NT$ {wallet_status.get('lifetime_net_profit', 0.0):+,.0f}",
    )
with w_col4:
    ext_limit_str = f"NT$ {wallet_status['weekly_external_deposited']:.0f} / {wallet_status['weekly_external_deposited'] + wallet_status['external_deposit_remaining']:.0f}"
    st.metric(
        label="💵 ④ 本週外部補金",
        value=ext_limit_str,
        delta="不足 200 才補" if wallet_status["can_deposit"] else "儲備池已充盈",
    )

st.markdown("---")



@st.cache_data(ttl=120, show_spinner=False)
def get_cached_forward_parlay_metrics(parlays_path_str: str, experiment_id: str, mtime: float):
    parlay_file = Path(parlays_path_str)
    if not parlay_file.exists():
        return evaluate_parlay_forward([], experiment_id)
    records = read_jsonl(parlay_file)
    return evaluate_parlay_forward(records, experiment_id)


@st.cache_data(ttl=120, show_spinner=False)
def get_cached_snapshot_analytics(snapshots_path_str: str, mtime: float):
    try:
        logger = PredictionSnapshotLogger(Path(snapshots_path_str))
    except TypeError:
        logger = PredictionSnapshotLogger()
    snaps = logger.get_all_snapshots()
    eng = PerformanceMetricsEngine()
    cohort = eng.forward_cohort(snaps)
    return {
        "snapshots": snaps,
        "cohort": cohort,
        "agree_data": eng.evaluate_agreement_buckets(snaps),
        "ev_data": eng.evaluate_ev_buckets(snaps),
        "delta_data": eng.evaluate_model_market_delta_buckets(snaps),
        "crowd_data": eng.evaluate_crowd_buckets(snaps),
        "expert_data": eng.evaluate_expert_metrics(snaps),
    }


# Main 4-Tab Layout
tab_radar, tab_parlay, tab_wallet, tab_research = st.tabs([
    "① 今日可玩 (賽季雷達)",
    "② 瘋狗看盤 (10~500倍 組單)",
    "③ 資金紀錄 (NT$200 錢包與戰績)",
    "📊 影子評估與前瞻驗證 (Research / Performance)",
])


# -------------------------------------------------------------
# TAB 1: 賽季雷達 (今天有什麼可以玩？)
# -------------------------------------------------------------
with tab_radar:
    col_r_header, col_r_btn = st.columns([3, 1])
    with col_r_header:
        st.markdown("### 📡 今日賽事雷達")
        st.caption("🟢 綠燈：賽季中且今日台彩有開盤；🟡 黃燈：賽季中但今日台彩未開盤；🔴 紅燈：休賽季。")
    with col_r_btn:
        if st.button("🔄 刷新盤口與模型資料", use_container_width=True):
            st.session_state["force_odds_refresh"] = True
            if hasattr(signal_hub.expert_adapter, "refresh"):
                signal_hub.expert_adapter.refresh()
            if hasattr(signal_hub.model_registry, "refresh"):
                signal_hub.model_registry.refresh()
            st.rerun()

    force_refresh = st.session_state.pop("force_odds_refresh", False)
    if force_refresh:
        st.session_state.pop("cached_radar_state", None)
        st.session_state.pop("cached_enriched_pool", None)
        st.session_state.pop("parlay_search_progress", None)

    # Fetch live Taiwan legs
    with st.spinner("正在探測今日賽程與台灣運彩盤口..."):
        all_taiwan_legs = odds_adapter.get_taiwan_legs(
            list(ALLIANCE_MAP),
            force_refresh=force_refresh,
        )

    radar_eligible_legs = [leg for leg in all_taiwan_legs if assess_leg(leg)["is_ready"]]
    radar_tuples = tuple((l.canonical_event_id or l.event_id, l.league, l.sport) for l in radar_eligible_legs)
    now_ts = datetime.now(timezone.utc).timestamp()
    cached_radar = st.session_state.get("cached_radar_state")
    cached_enriched = st.session_state.get("cached_enriched_pool", {})
    evaluated_candidates = cached_enriched.get("legs") if isinstance(cached_enriched, dict) else None

    if not force_refresh and cached_radar and cached_radar.get("tuples") == radar_tuples and now_ts - cached_radar.get("time", 0) < 300:
        radar_summary = cached_radar["data"]
    else:
        try:
            radar_summary = season_radar.get_radar_summary(
                taiwan_legs=radar_eligible_legs, check_live_espn=True, evaluated_legs=evaluated_candidates
            )
        except TypeError:
            try:
                import importlib
                import core.season_radar
                importlib.reload(core.season_radar)
                season_radar = core.season_radar.SeasonRadar()
                radar_summary = season_radar.get_radar_summary(
                    taiwan_legs=radar_eligible_legs, check_live_espn=True, evaluated_legs=evaluated_candidates
                )
            except Exception:
                radar_summary = season_radar.get_radar_summary(
                    taiwan_legs=radar_eligible_legs, check_live_espn=True
                )
        st.session_state["cached_radar_state"] = {"tuples": radar_tuples, "time": now_ts, "data": radar_summary}

    # Show radar lights
    cols_radar = st.columns(3)
    for idx, r in enumerate(radar_summary):
        col = cols_radar[idx % 3]
        with col:
            css_class = (
                "radar-card-green" if r["status"] == "GREEN"
                else "radar-card-yellow" if r["status"] == "YELLOW"
                else "radar-card-red"
            )
            count_info = f"<b>{r['taiwan_market_count']} 場盤口開盤</b>" if r["taiwan_market_count"] > 0 else "今日無盤口"
            opp_badge = r.get("opportunity_badge", "")
            opp_html = f"<div style='margin-top:6px; font-size:0.85rem; font-weight:600; color:#4ade80; background:rgba(74,222,128,0.1); padding:2px 8px; border-radius:4px; display:inline-block;'>{opp_badge}</div>" if opp_badge else ""
            st.markdown(
                f"""
                <div class='{css_class}'>
                    <div style='display:flex; justify-content:space-between; align-items:center;'>
                        <span style='font-size:1.15rem; font-weight:bold;'>{r['icon']} {r['name']}</span>
                        <span style='font-size:1.25rem;'>{r['light_emoji']}</span>
                    </div>
                    <div style='margin-top:6px; font-size:0.9rem; color:#ccc;'>
                        狀態：{r['status_text']} · {count_info}
                    </div>
                    {opp_html}
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("---")
    st.markdown("#### 📋 點選聯賽查看今日台灣運彩對戰詳情")

    active_leagues_with_games = [r for r in radar_summary if r["taiwan_market_count"] > 0]

    source_statuses = odds_adapter.get_source_status()
    with st.expander("資料來源與賽事身份狀態", expanded=not active_leagues_with_games):
        for aid, status in source_statuses.items():
            name = ALLIANCE_MAP.get(str(aid), str(aid))
            age = status.get("cache_age_minutes")
            age_text = f"{age:.1f} 分鐘" if isinstance(age, (int, float)) else "未知"
            raw_status = status.get("source_status", "UNKNOWN")
            if raw_status == "CACHED" and isinstance(age, (int, float)) and age <= 15:
                display_status = "TTL 快取 · FRESH"
            elif raw_status == "LIVE_NO_EVENTS":
                provenance = status.get("cache_provenance")
                display_status = ("今日無賽事 · TTL 快取確認" if provenance == "CACHED"
                                  else "今日無賽事 · LIVE 確認")
            elif raw_status == "STALE_CACHE":
                display_status = "舊快取 · STALE_CACHE"
            elif raw_status == "LIVE":
                display_status = "LIVE"
            elif str(raw_status).startswith("HTTP_") or raw_status in {"FETCH_ERROR", "PARSE_EMPTY", "UNAVAILABLE"}:
                display_status = f"抓取/解析失敗 · {raw_status}"
            else:
                display_status = str(raw_status)
            st.markdown(f"**{name} · {display_status}**")
            completeness = status.get("identity_completeness_rate")
            if isinstance(completeness, (float, int)):
                st.caption(f"主客隊身份完整率：{completeness:.1%}（{status.get('identity_complete_count', 0)}/{status.get('identity_total_count', 0)} 場）。")
            st.caption(
                f"來源觀測時間：{status.get('observed_at') or '無可用觀測'} · "
                f"觀測年齡：{age_text} · "
                f"本次抓取嘗試：{status.get('attempted_at') or '未發出新抓取（使用 TTL 快取）'} · "
                f"盤口賽事：{status.get('market_match_count', 0)}/{status.get('match_count', 0)} · "
                f"主客隊身份不完整：{status.get('placeholder_identity_count', 0)} 場"
            )
            if status.get("failure_status") or status.get("error"):
                st.warning(f"抓取來源狀態：{status.get('failure_status') or 'unknown'}；{status.get('error') or '未提供錯誤細節'}")
            elif status.get("source_status") == "LIVE_NO_EVENTS":
                st.info(f"來源頁面於 {status.get('observed_at') or '未知時間'} 明確標示「此日無比賽」；這是有效的空賽程回應，不是抓取失敗。")
            elif status.get("source_status") in {"LIVE", "CACHED", "STALE_CACHE"} and not status.get("market_match_count"):
                st.info("來源有回應但沒有解析到盤口賽事；這與抓取失敗是不同狀態。")
            st.caption(status.get("source_url") or "來源網址未提供")

    if not active_leagues_with_games:
        st.info("目前沒有可展示的已解析盤口賽事。請先查看上方各來源狀態，區分無盤、身份不完整、快取或抓取失敗。")
    else:
        for r in active_leagues_with_games:
            with st.expander(f"{r['icon']} {r['name']} — 今日共 {r['taiwan_market_count']} 場開盤 (點擊展開盤口)", expanded=(r["code"] == "MLB")):
                matching_legs = [
                    l for l in all_taiwan_legs
                    if (r["code"] in l.league.upper()) or (r["name"] in l.league) or (r["code"] == "MLB" and l.sport == "baseball" and "MLB" in l.league)
                ]
                # Group by event_id
                grouped_events: Dict[str, List[TaiwanLeg]] = {}
                for l in matching_legs:
                    grouped_events.setdefault(l.event_id, []).append(l)

                eval_lookup = {}
                if evaluated_candidates:
                    for el in evaluated_candidates:
                        eid_key = getattr(el, "canonical_event_id", None) or getattr(el, "event_id", "")
                        eval_lookup[(eid_key, getattr(el, "market", ""), getattr(el, "selection", ""))] = el
                        eval_lookup[(getattr(el, "event_id", ""), getattr(el, "market", ""), getattr(el, "selection", ""))] = el

                for eid, ev_legs in grouped_events.items():
                    first_l = ev_legs[0]
                    st.markdown(f"**⏰ {first_l.start_time} | 台灣運彩賽事編號 #{eid}**")
                    st.write(f"**{first_l.away_team} (客)** vs **{first_l.home_team} (主)**")

                    opt_strs = []
                    for leg in ev_legs[:6]:
                        el = eval_lookup.get((leg.canonical_event_id or leg.event_id, leg.market, leg.selection)) or eval_lookup.get((leg.event_id, leg.market, leg.selection))
                        ev_data = getattr(el, "signal_evidence", {}) or {} if el else {}
                        leg_ev = ev_data.get("sharp_expected_value_pct", ev_data.get("expected_value_pct"))
                        prob = float(ev_data.get("consensus_probability", 0.0) or 0.0)

                        if isinstance(leg_ev, (int, float)) and leg_ev > 0:
                            opt_strs.append(f"<b><code>{leg.selection}</code></b> ({leg.taiwan_odds} <span style='color:#4ade80; font-size:0.85rem;'>🔥 +EV {leg_ev:+.1f}%</span>)")
                        elif prob >= 0.55 and leg.taiwan_odds <= 2.0:
                            opt_strs.append(f"<b><code>{leg.selection}</code></b> ({leg.taiwan_odds} <span style='color:#60a5fa; font-size:0.85rem;'>🛡️ {prob*100:.0f}%</span>)")
                        else:
                            opt_strs.append(f"<code>{leg.selection}</code> ({leg.taiwan_odds})")
                    if opt_strs:
                        st.markdown("<div style='font-size:0.9rem; color:#bbb; margin-top:2px;'>盤口情報： " + " · ".join(opt_strs) + "</div>", unsafe_allow_html=True)
                    st.markdown("<hr style='margin: 8px 0; border-color: #2d2f3f;'>", unsafe_allow_html=True)


# -------------------------------------------------------------
# TAB 2: 瘋狗看盤 (10~500倍 串關組單 & Signal Hub)
# -------------------------------------------------------------
with tab_parlay:
    st.markdown("### 🔥 瘋狗看盤決策台")
    st.caption("設定目標總賠率，系統透過 Signal Hub (台灣盤口 + 大神榜 + 彩迷選票 + 開源模型) 自動搜尋最佳串關組合。")
    st.info("賠率決定派彩；1 ÷ 賠率是打平門檻。模型估計命中率、社群支持率與大神歷史勝率各有不同意思；HIGH 情報不對應固定勝率，正 EV 也取決於估計是否準確。")

    # Step 1: Target Multiplier & Signal Filter
    col_p1, col_p2 = st.columns([2, 3])
    with col_p1:
        st.markdown("#### ① 今天你想玩幾倍？")
        odds_mode = st.radio(
            "倍率與策略風格：",
            [
                "🛡️ 穩健銀行家模式 (Banker: 1.5x ~ 6x 高勝率累積獎金池)",
                "🎯 指定目標倍率 (Target ±20%)",
                "📊 自由賠率區間 (Range)",
            ],
            horizontal=False,
        )
        target_val = None
        tolerance_val = 0.20
        min_search_legs = 2
        max_search_legs = 6

        if "穩健銀行家模式" in odds_mode:
            target_odds_range = (1.5, 6.0)
            target_val = 2.5
            tolerance_val = 0.35
            min_search_legs = 2
            max_search_legs = 3
            st.info("💡 **穩健銀行家模式 (Banker Mode)**：鎖定 2~3 關高勝率與正期望值 (+EV) 定海神針關卡，總倍率約 1.5x ~ 6x。兼具極高勝率與低風險，小額派彩全數撥入【保留儲備池】，細水長流穩健壯大每週戰力！")
            st.caption(f"鎖定搜尋賠率：**{target_odds_range[0]:.1f}x ~ {target_odds_range[1]:.1f}x** (限定 2~3 關高勝率)")
        elif "指定目標倍率" in odds_mode:
            target_val = st.number_input("🎯 目標總倍率 (x)", min_value=1.5, max_value=500.0, value=20.0, step=1.0)
            tolerance_pct = st.slider("容許浮動範圍 (±%)", min_value=5, max_value=40, value=20, step=5)
            tolerance_val = tolerance_pct / 100.0
            target_odds_range = (max(1.05, target_val * (1.0 - tolerance_val)), target_val * (1.0 + tolerance_val))
            st.caption(f"鎖定搜尋賠率：**{target_odds_range[0]:.1f}x ~ {target_odds_range[1]:.1f}x**")
            if target_val <= 6.0:
                max_search_legs = 3
        else:
            preset = st.radio(
                "快捷區間：",
                [
                    "🛡️ 銀行家模式 (1.8x ~ 4.0x，2~3關高勝率)",
                    "📈 穩中求勝 (4.0x ~ 10.0x，精選穩健)",
                    "🔥 瘋狗起步 (10x ~ 25x)",
                    "🚀 瘋狗狂暴 (25x ~ 75x)",
                    "🌕 極限登月 (75x ~ 200x)",
                    "🛸 超級巨星 (200x ~ 500x)",
                    "自訂滑桿",
                ],
                horizontal=False,
            )
            if "1.8x ~ 4.0x" in preset:
                target_odds_range = (1.8, 4.0)
                max_search_legs = 3
            elif "4.0x ~ 10.0x" in preset:
                target_odds_range = (4.0, 10.0)
                max_search_legs = 4
            elif "10x ~ 25x" in preset:
                target_odds_range = (10.0, 25.0)
            elif "25x ~ 75x" in preset:
                target_odds_range = (25.0, 75.0)
            elif "75x ~ 200x" in preset:
                target_odds_range = (75.0, 200.0)
            elif "200x ~ 500x" in preset:
                target_odds_range = (200.0, 500.0)
            else:
                target_odds_range = st.slider(
                    "目標總賠率範圍 (賠率)",
                    min_value=1.5,
                    max_value=500.0,
                    value=(2.0, 15.0),
                    step=0.5,
                )
                if target_odds_range[1] <= 6.0:
                    max_search_legs = 3

    with col_p2:
        st.markdown("#### ② 選擇混串賽事與情報過濾")
        all_sports = list(ALLIANCE_MAP.keys())

        cross_sport = st.checkbox("☑ 全部混串 (跨界混合 NBA + MLB + 足球 + NFL + 職棒)", value=True)

        if cross_sport:
            chosen_alliances = all_sports
            st.info("已啟用跨界混串！系統將跨籃球 (NBA)、棒球 (MLB/職棒)、足球、美足同時尋找最佳倍率組合。")
        else:
            chosen_alliances = st.multiselect(
                "選擇指定賽事：",
                options=all_sports,
                default=["1", "3", "4"],
                format_func=lambda x: ALLIANCE_MAP.get(x, x),
            )

        filter_choice = st.selectbox(
            "🛡️ 外部情報品質門檻：",
            [
                "normal (標準: 排除無外部情報之關卡)",
                "value_only (價值優先: 僅限具備 +EV 正期望值或高勝率之關卡)",
                "strict (嚴格: 僅限 2+ 獨立來源支持)",
                "wild (狂野: 容許全部盤口)",
            ],
            index=0,
        )
        signal_filter_code = (
            "value_only" if "value_only" in filter_choice
            else "strict" if "strict" in filter_choice
            else "wild" if "wild" in filter_choice
            else "normal"
        )

        available_stake = max(0.0, min(float(wallet_status["weekly_wallet_balance"]), float(wallet_status["weekly_play_cap"] - wallet_status["weekly_staked"])))
        has_stake_budget = available_stake >= 10.0
        stake_per_bet = st.number_input(
            "💵 本張注金 (NT$)",
            min_value=10.0,
            max_value=max(10.0, available_stake),
            value=min(20.0, max(10.0, available_stake)),
            step=10.0,
            help="從你本週的 NT$ 200 錢包扣款",
            disabled=not has_stake_budget,
        )
        if not has_stake_budget:
            st.caption("本週餘額或下注額度不足 NT$10，目前只能查看組合。")

    st.markdown("---")

    search_budget = st.number_input("搜尋運算預算（節點數）", min_value=10000, max_value=2000000,
                                    value=50000, step=10000,
                                    help="所有合格選項都會納入搜尋；預算耗盡時會明確標示尚未搜完，可提高預算重試。")
    # Run Parlay Search
    with st.spinner("Signal Hub 正在聚合情報並計算串關組合..."):
        if cross_sport:
            all_candidate_legs = all_taiwan_legs
        else:
            all_candidate_legs = odds_adapter.get_taiwan_legs(chosen_alliances)
        candidate_source_statuses = odds_adapter.get_source_status()

        # Cache enriched legs to avoid redundant multi-model evaluations on every slider adjustment
        raw_quotes_hash = hashlib.sha256(json.dumps([[l.canonical_event_id or l.event_id, l.market, l.selection, l.taiwan_odds, l.odds_scraped_at] for l in all_candidate_legs], sort_keys=True).encode()).hexdigest()
        cached_enriched = st.session_state.get("cached_enriched_pool", {})
        if cached_enriched.get("hash") == raw_quotes_hash and not force_refresh:
            enriched_legs = cached_enriched["legs"]
        else:
            enriched_legs = [signal_hub.evaluate_taiwan_leg(leg) for leg in all_candidate_legs]
            st.session_state["cached_enriched_pool"] = {"hash": raw_quotes_hash, "legs": enriched_legs}

        current_pool = enriched_legs
        quote_scope = [{k:leg.to_dict().get(k) for k in ("canonical_event_id","event_id","market","side","selection","line","taiwan_odds","odds_scraped_at","start_time_utc")} for leg in current_pool]
        context_hash = hashlib.sha256(json.dumps({"quotes":quote_scope,"range":target_odds_range,
            "target":target_val,"tolerance":tolerance_val,"filter":signal_filter_code,
            "min_legs":min_search_legs,"max_legs":max_search_legs,
            "identity":get_strategy_metadata().get("code_hash")},sort_keys=True,default=str).encode('utf-8')).hexdigest()
        saved_search = st.session_state.get("parlay_search_progress", {})
        continue_search = st.button("繼續同批資料的搜尋", disabled=not saved_search or saved_search.get("complete",True))
        reset_search = st.button("以目前資料重新開始搜尋")
        reusable = (not reset_search and saved_search.get("context_hash") == context_hash
                    and all(assess_leg(leg)["is_ready"] for leg in saved_search.get("legs",[])))
        if reusable:
            enriched_legs = saved_search["legs"]
            search_scope = saved_search["scope_as_of"]
        else:
            search_scope = datetime.now(timezone.utc).isoformat()
            if continue_search and saved_search:
                st.info("盤口、範圍、程式版本或時效已改變，已開始新的搜尋。")
        search_diagnostics = {}
        if reusable and not continue_search:
            parlay_results = saved_search["result"]
            search_diagnostics = saved_search["diagnostics"]
        else:
            parlay_results = parlay_engine.search_parlays(
                legs=enriched_legs,min_odds=target_odds_range[0],max_odds=target_odds_range[1],
                target_odds=target_val,tolerance=tolerance_val,signal_filter=signal_filter_code,
                min_legs=min_search_legs,max_legs=max_search_legs,diagnostics=search_diagnostics,search_budget=int(search_budget),
                resume_state=saved_search.get("state") if reusable else None,scope_as_of=search_scope,
            )
            state = parlay_results.search_state
            search_diagnostics.pop("resume_state", None)
            st.session_state["parlay_search_progress"] = {"context_hash":context_hash,"scope_as_of":search_scope,
                "legs":enriched_legs,"state":state,"result":parlay_results,"diagnostics":search_diagnostics,
                "complete":search_diagnostics["search_complete"]}
        st.caption("續搜固定初次搜尋的同批情報；新盤口、過期或已開賽資料會重新開始。排名優先證據支持，其次為未驗證的估計EV。")
    checks = [assess_leg(leg) for leg in enriched_legs]
    ready_count = sum(check["is_ready"] for check in checks)
    raw_source_option_count = sum(int(candidate_source_statuses.get(str(aid), {}).get("option_count", 0) or 0)
                                  for aid in chosen_alliances)
    placeholder_option_count = sum(int(candidate_source_statuses.get(str(aid), {}).get("placeholder_identity_option_count", 0) or 0)
                                   for aid in chosen_alliances)
    if raw_source_option_count == 0 and enriched_legs:
        raw_source_option_count = len(enriched_legs)
    source_count = raw_source_option_count
    identity_complete_count = sum(not bool(leg.signal_evidence.get("identity_incomplete")) for leg in enriched_legs)
    ready_legs = [leg for leg, check in zip(enriched_legs, checks) if check["is_ready"] and leg.eligible_for_parlay]
    quality_legs = [leg for leg in ready_legs if (
        signal_filter_code == "wild" or
        (signal_filter_code == "normal" and leg.evidence_quality != "INSUFFICIENT_SIGNAL") or
        (signal_filter_code == "strict" and leg.evidence_quality in {"HIGH", "MED"}
         and parlay_engine._independent_valid_support_count(leg) >= 2)
    )]
    quality_events = {leg.canonical_event_id or leg.event_id for leg in quality_legs}
    unique_combinations = set()
    for bucket in ("high_consensus", "aggressive", "moonshot"):
        for combo in parlay_results.get(bucket, []):
            unique_legs = tuple(sorted((
                str(leg.get("canonical_event_id") or leg.get("event_id") or leg.get("match_id") or ""),
                str(leg.get("market") or leg.get("market_type") or ""),
                str(leg.get("selection") or ""),
                "" if leg.get("line") is None else str(leg.get("line")),
            ) for leg in combo.get("legs", [])))
            unique_combinations.add(unique_legs)
    combination_count = len(unique_combinations)
    st.caption(
        f"來源解析選項 {source_count} · 身份不完整選項 {placeholder_option_count} · 已轉成單關 {len(enriched_legs)} · 主客隊身份完整 {identity_complete_count} · "
        f"可用單關 {len(ready_legs)} · 通過目前情報門檻的賽事 {len(quality_events)} · "
        f"倍率範圍內目前列出的唯一候選組合 {combination_count}。"
    )
    if search_diagnostics:
        if not search_diagnostics.get("search_complete", False):
            st.warning("搜尋預算已用完，結果尚不完整；目前找到的組合仍可查看。空結果不能判定沒有符合組合，可按繼續搜尋累積進度。")
        with st.expander("查看組合搜尋範圍", expanded=False):
            st.write(f"已納入全部合格的 {search_diagnostics['search_event_count']} 場、"
                     f"{search_diagnostics['search_option_count']} 個選項，搜尋 "
                     f"{search_diagnostics['min_legs']}～{search_diagnostics['max_legs']} 關；每場最多選一個選項。")
            st.caption(f"搜尋狀態：{'已完成' if search_diagnostics.get('search_complete') else '尚未完成'}；"
                       f"本次使用 {search_diagnostics.get('visited_nodes_this_call', 0):,} / {search_diagnostics.get('search_budget', 0):,} 節點，累計 {search_diagnostics.get('visited_nodes_total', 0):,} 節點；"
                       f"核對 {search_diagnostics['checked_combinations']:,} 個完整組合，"
                       f"{search_diagnostics['odds_matching_combinations']:,} 個落在倍率範圍。"
                       "每種風格顯示排名最高的12組。倍數剪枝只排除已證明無法落在範圍的分支。")
    gate_rows = acceptance_rows(enriched_legs)
    if gate_rows:
        with st.expander("查看模型在各聯賽與玩法的驗收狀態", expanded=False):
            st.caption("未通過驗收的模型會保存研究預測；推薦支持數與排序機率只採用通過本場範圍驗收的模型。")
            st.table(gate_rows)
    if combination_count == 0:
        if source_count == 0:
            st.warning("目前沒有盤口選項；請看來源狀態判斷是抓取失敗、快取不可用或來源無盤。")
        elif placeholder_option_count >= source_count and source_count > 0:
            st.warning("目前來源選項的賽事主客隊身份不完整，已全部排除。")
        elif not enriched_legs:
            st.warning("來源頁面有選項，但沒有可轉成單關的有效賠率選項。")
        elif ready_count == 0:
            st.warning("選項存在，但沒有通過開賽時間、盤口新鮮度、玩法及賠率檢查的單關。")
        elif not quality_events or len(quality_events) < 2:
            st.warning("單關可用，但目前情報門檻下不足兩場不同賽事，無法組串。")
        else:
            st.warning("目前尚未找到符合倍率的組合；請先查看搜尋是否完成，再調整倍率、範圍或搜尋預算。")
    excluded_reasons = Counter(reason for check in checks for reason in check["reasons"])
    if excluded_reasons:
        with st.expander("查看未通過核對的原因", expanded=False):
            st.table([{"原因": REASON_LABELS[reason], "盤口選項數": count} for reason, count in excluded_reasons.items()])
            st.caption("EVENT_STARTED 與 ODDS_STALE 可同時套用到同一選項（例如已開賽的舊盤），所以原因列是可重疊的原因次數，不能相加成選項總數。來源新鮮度也不等於單關可用，還要通過身份、玩法、情報門檻及倍率組合檢查。")

            reason_choice = st.selectbox("選擇原因查看盤口明細", list(excluded_reasons),
                                        format_func=lambda key: REASON_LABELS[key])
            excluded_details = []
            for leg, check in zip(enriched_legs, checks):
                if reason_choice not in check["reasons"]:
                    continue
                row = leg.to_dict() if hasattr(leg, "to_dict") else leg
                excluded_details.append({"賽事":row.get("canonical_event_id") or row.get("event_id"),
                    "聯賽":row.get("league"), "選項":row.get("selection"), "盤線":row.get("line"),
                    "賠率":row.get("taiwan_odds"), "抓取時間UTC":row.get("odds_scraped_at"),
                    "開賽UTC":row.get("start_time_utc"), "所有原因":"、".join(REASON_LABELS[r] for r in check["reasons"]),
                    "來源":row.get("source_url") or (row.get("signal_evidence") or {}).get("source_url")})
            st.caption("時效門檻：盤口觀測15分鐘內，且賽事尚未開賽；重新取得資料不保證已開賽選項能恢復可用。")
            st.dataframe(excluded_details, hide_index=True, width="stretch")

    # 3 Display Categories
    bucket_choice = st.radio(
        "選擇組合風格：",
        [
            f"🟢 共識較高 ({len(parlay_results['high_consensus'])} 組)",
            f"🟡 比較瘋 ({len(parlay_results['aggressive'])} 組)",
            f"🔴 極限 Moonshot ({len(parlay_results['moonshot'])} 組)",
        ],
        horizontal=True,
    )

    if "共識較高" in bucket_choice:
        active_list = parlay_results["high_consensus"]
        category_desc = "情報支持程度較高的候選組合；這個分類不代表已驗證的高勝率，仍需查看每關的證據。"
    elif "比較瘋" in bucket_choice:
        active_list = parlay_results["aggressive"]
        category_desc = "證據較少或倍率較高的候選組合；分類不代表勝率。"
    else:
        active_list = parlay_results["moonshot"]
        category_desc = "高倍率或關卡較多的候選組合；需要逐關核對，不代表更有價值。"

    st.caption(category_desc)

    with st.expander("📊 查看跨運動開源模型與情報覆蓋矩陣 (Model Coverage Matrix)", expanded=False):
        model_summary = signal_hub.model_registry.get_registered_models_summary()
        for model in model_summary:
            model["source_id"] = model["id"]
            observations = [signal for leg in enriched_legs for signal in leg.signals if signal.source_id == model["id"]]
            if observations:
                signal = observations[0]
                model.update(metadata=signal.metadata, data_as_of=signal.data_as_of,
                             freshness_status=signal.freshness_status, probability=signal.probability,
                             probability_status="UNVALIDATED_MODEL_ESTIMATE" if signal.freshness_status in {"LIVE", "FRESH"} and signal.metadata.get("initialized") is not False else "REFERENCE_ONLY")
        render_source_overview(signal_hub.expert_adapter.get_source_status(),
                               [leg.to_dict() for leg in enriched_legs], model_summary)
        st.caption("載入成功只代表模型可呼叫，不表示本場有足夠資料、資料即時或已驗證準確。盤口、社群與專家資料請核對各關的來源與時間。")

    if not active_list:
        st.warning(f"在 {target_odds_range[0]}x ~ {target_odds_range[1]}x 範圍內沒有通過目前資料與情報門檻的此類組合。請查看排除原因與來源狀態；資料不足時會保持空結果。")
    else:
        exposures = shared_event_exposure(active_list)
        if any(row["shared_event_count"] for row in exposures):
            st.info("本類候選組合有共用賽事：買多張仍會集中承擔同場結果，請查看各張的共用風險。")
        for idx, item in enumerate(active_list, start=1):
            with st.container():
                current_readiness = readiness(item)
                has_model_estimate = all(leg.get("signal_evidence", {}).get("model_accepted_ids") for leg in item["legs"])
                estimate_label = "單關模型已驗收的串關情境" if has_model_estimate else "含市場基準的串關情境"
                ev_val = item.get("parlay_ev_pct", 0.0)
                corr_grade = item.get("correlation_risk_grade", "INDEPENDENT_CLEAN")
                joint_prob_pct = item.get("joint_probability", 0.0) * 100.0
                readiness_label = "資料核對通過" if current_readiness["is_ready"] else "資料未齊，無法記錄推薦"
                readiness_color = "#00c853" if current_readiness["is_ready"] else "#d32f2f"

                sharp_ev_pct = item.get("sharp_parlay_ev_pct")
                sharp_badge_html = ""
                if item.get("is_positive_ev") and sharp_ev_pct is not None:
                    sharp_badge_html = f"&nbsp; <span style='background:#1b5e20; color:#b9f6ca; border:1px solid #00e676; padding:2px 8px; border-radius:8px; font-weight:bold;'>🔥 國際去水正期望值 (+EV {sharp_ev_pct:+.1f}%)</span>"
                elif sharp_ev_pct is not None:
                    badge_text = item.get("sharp_summary_badge", "⚪ 市場中性/負EV")
                    sharp_badge_html = f"&nbsp; <span style='background:#2a2b36; color:#bdbdbd; padding:2px 8px; border-radius:8px; font-weight:bold;'>{badge_text} ({sharp_ev_pct:+.1f}%)</span>"

                st.markdown(
                    f"""
                    <div class='ticket-card'>
                        <div style='display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;'>
                            <div>
                                <span style='background:#ff9100; color:white; padding:3px 8px; border-radius:12px; font-weight:bold;'>No.{idx}</span> &nbsp;
                                <span style='font-size:1.25rem; font-weight:bold;'>{item['parlay_name']}</span> &nbsp;
                                <span style='font-size:1.35rem; font-weight:900; color:#00e676;'>{item['total_odds']} 倍</span> &nbsp;
                                <span style='background:{readiness_color}; color:white; padding:2px 8px; border-radius:8px; font-weight:bold;'>{readiness_label}</span>
                                {sharp_badge_html}
                            </div>
                            <div style='margin-top:4px;'>
                                先核對各關有效支持數與打平門檻；模型估計與 EV 收在下方展開區。
                            </div>
                        </div>
                        <div style='display:flex; gap:18px; margin-top:10px; padding:6px 12px; background:#1e202e; border-radius:6px; font-size:0.92rem; align-items:center; flex-wrap:wrap;'>
                            <span>🎯 <b>聯合估計勝率</b>：<span style='color:#4ade80; font-weight:bold;'>{joint_prob_pct:.1f}%</span></span>
                            <span>⚖️ <b>打平門檻</b>：<span style='color:#cbd5e1; font-weight:bold;'>{100.0/float(item['total_odds']):.1f}%</span></span>
                            <span>📊 <b>預期淨利 (EV)</b>：<span style='color:{"#4ade80" if ev_val>0 else "#f87171"}; font-weight:bold;'>{ev_val:+.1f}%</span></span>
                            <span>🛡️ <b>相關性風險</b>：<span style='color:#94a3b8;'>{corr_grade}</span></span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if current_readiness["messages"]:
                    st.warning("、".join(current_readiness["messages"]))
                exposure = exposures[idx - 1]
                if exposure["shared_event_count"]:
                    peers = "、".join(str(number) for number in exposure["overlapping_ticket_numbers"])
                    st.caption(f"共用風險：{exposure['shared_event_count']} 場與 No.{peers} 共用；最大賽事重疊比例 {exposure['maximum_event_overlap_ratio']:.0%}。")

                # Identify Weakest Leg in this parlay ticket
                weakest_leg = None
                min_support = 999
                for leg in item["legs"]:
                    sig_ev = leg.get("signal_evidence", {})
                    cnt = sig_ev.get("independent_support_count", sig_ev.get("support_count", 0))
                    if cnt < min_support:
                        min_support = cnt
                        weakest_leg = leg

                if weakest_leg:
                    w_ev = weakest_leg.get("signal_evidence", {})
                    w_badge = w_ev.get("agreement_badge") or "⚪ INSUFFICIENT"
                    st.markdown(
                        f"""
                        <div style='background: #2a1b1b; border: 1px solid #d32f2f; border-radius: 6px; padding: 6px 12px; margin-bottom: 10px; font-size: 0.88rem;'>
                            ⚠️ <b>最脆弱關卡提醒 (Weakest Leg)</b>：【{weakest_leg.get('league')}】{weakest_leg.get('away_team')} vs {weakest_leg.get('home_team')} ➔ <code>{weakest_leg.get('selection')}</code>
                            &nbsp;|&nbsp; 訊號等級：<b>{w_badge}</b> (外部獨立支援群組數: {min_support})
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                # Show Legs with Signal Hub Insights and Quantitative Value Metrics
                legs_rows = []
                for leg in item["legs"]:
                    sig_ev = leg.get("signal_evidence", {})
                    badge = sig_ev.get("agreement_badge") or "⚪ INSUFFICIENT"
                    support_count = sig_ev.get("independent_support_count", sig_ev.get("support_count", 0))

                    sharp_fair_p = sig_ev.get("sharp_fair_probability")
                    sharp_fair_str = probability_label(sharp_fair_p) if sharp_fair_p is not None else "去水未成"
                    odds_val = leg.get("odds") or leg.get("taiwan_odds", 0.0)
                    leg_ev_pct = sig_ev.get("sharp_expected_value_pct")
                    if leg_ev_pct is None and sig_ev.get("expected_value_pct") is not None:
                        leg_ev_pct = sig_ev.get("expected_value_pct")
                    if isinstance(leg_ev_pct, (int, float)):
                        ev_str = f"{leg_ev_pct:+.1f}% 🟢" if leg_ev_pct >= 0.0 else f"{leg_ev_pct:+.1f}% 🔴"
                    else:
                        ev_str = "-"
                    legs_rows.append({
                        "聯賽": leg.get("league", ""),
                        "對戰賽事": f"{leg.get('away_team')} vs {leg.get('home_team')}",
                        "玩法推薦": leg.get("selection", ""),
                        "台彩賠率": f"{odds_val:.2f}" if odds_val else "-",
                        "打平門檻": probability_label(sig_ev.get("market_implied_probability")),
                        "去水公允勝率": sharp_fair_str,
                        "單關 EV": ev_str,
                        "有效支持數": support_count,
                        "證據等級": badge,
                    })

                st.table(legs_rows)

                # Expandable Why? Drawer on each parlay ticket
                with st.expander(f"🔍 查看 No.{idx} 的模型、EV 與原始證據", expanded=False):
                    sharp_joint_p = item.get("sharp_joint_probability", 0.0) * 100.0
                    sharp_ev_val = item.get("sharp_parlay_ev_pct", 0.0)
                    st.write(
                        f"{estimate_label}串關機率：{joint_prob_pct:.2f}%｜"
                        f"{estimate_label}串關 EV：{ev_val:+.1f}%｜"
                        f"國際去水勝率：{sharp_joint_p:.2f}%｜"
                        f"國際真實 EV：{sharp_ev_val:+.1f}%｜相關性：{corr_grade}｜訊號：{item['signal_summary']}"
                    )
                    st.caption("串關機率含規則式相關性折扣，尚未驗證準確度；模型估計與 EV 不是已證實的勝率或獲利能力。")
                    st.table([{
                        "賽事": f"{leg.get('away_team')} vs {leg.get('home_team')}",
                        "排序採用機率": probability_label(leg.get("consensus_probability")),
                        "研究模型情境機率": probability_label(leg.get("signal_evidence", {}).get("model_candidate_probability_fused")),
                        "模型驗收": "、".join(acceptance_label(model.get("status")) for model in
                                             leg.get("signal_evidence", {}).get("model_acceptance_statuses", [])) or "沒有本場模型觀測",
                    } for leg in item["legs"]])
                    st.table([{
                        "賽事": f"{leg.get('away_team')} vs {leg.get('home_team')}",
                        "採用的模型機率": (probability_label(leg.get("signal_evidence", {}).get("consensus_probability"))
                                          if leg.get("signal_evidence", {}).get("model_accepted_ids")
                                          else "無模型估計"),
                        "模型估計 EV": (f"{leg.get('signal_evidence', {}).get('expected_value_pct', 0.0):+.1f}%"
                                        if leg.get("signal_evidence", {}).get("probability_status") == "UNVALIDATED_MODEL_ESTIMATE"
                                        else "無模型估計"),
                        "不確定性": "未完成實證校準",
                    } for leg in item["legs"]])
                    for leg_idx, leg in enumerate(item["legs"], start=1):
                        sig_ev = leg.get("signal_evidence", {})
                        st.markdown(
                            f"**關卡 {leg_idx}：【{leg.get('league')}】{leg.get('away_team')} vs {leg.get('home_team')} ➔ `{leg.get('selection')}` (台彩賠率 {leg.get('odds')})**"
                        )
                        col_why1, col_why2 = st.columns(2)
                        with col_why1:
                            st.markdown("**① 玩運彩記錄的運彩盤口（第三方來源）**")
                            st.write(f"- 官方賽事編號：`#{leg.get('event_id')}` | 盤口玩法：`{leg.get('market_type')}`")
                            st.write(f"- 記錄賠率：`{leg.get('odds'):.2f}` 倍 | 打平門檻：`{probability_label(sig_ev.get('market_implied_probability'))}`")
                            if sig_ev.get("market_fair_method") in {"COMPLETE_MARKET_PROPORTIONAL", "TWO_WAY_PROPORTIONAL"}:
                                st.caption(f"完整同場同玩法盤口按比例去水：{probability_label(sig_ev.get('market_fair_probability'))}。此值是市場估計，並非真實勝率。")
                            else:
                                st.caption("盤口不完整，未完成去水；使用 1 ÷ 賠率作為打平基準。")
                            odds_st = leg.get("odds_status", "UNKNOWN")
                            if odds_st == "STALE_CACHE":
                                st.warning("⚠️ **台彩賠率可能已過期**（本機快取大於15分鐘，建議下單前至台彩官網核實最新賠率）")
                            else:
                                st.caption(f"盤口狀態：`{odds_st}` (抓取時間: {leg.get('odds_scraped_at') or '未知'})")

                            st.markdown("**② 人類專家與社群選票 (HUMAN Family)**")
                            exp_desc = sig_ev.get("expert_desc", "無驗證大神主推")
                            if sig_ev.get("verified_experts") or sig_ev.get("has_verified_expert"):
                                st.write(f"- 玩運彩專家公開推薦：{exp_desc}")
                            else:
                                st.write("- 玩運彩專家：本次未取得可配對此關卡的公開推薦。")

                            crowd_cnt = sig_ev.get("vote_count")
                            crowd_ratio = sig_ev.get("consensus_ratio")
                            crowd_age = sig_ev.get("crowd_age_minutes")
                            votes_label = f"{crowd_cnt} 票" if crowd_cnt is not None else "票數未知"
                            age_label = f"{crowd_age:.0f} 分鐘前" if isinstance(crowd_age, (int, float)) else "時間未知"
                            st.write(f"- 社群支持率：`{probability_label(crowd_ratio)}` ({votes_label}, {age_label})")
                            st.caption("這是選擇此選項的人數比例，不是比賽命中率。")

                        with col_why2:
                            st.markdown("**③ 模型機率與 EV 估計**")
                            c_prob = sig_ev.get("consensus_probability")
                            ev_p = sig_ev.get("expected_value_pct", 0.0)
                            ci = sig_ev.get("confidence_interval")
                            if sig_ev.get("probability_status") == "UNVALIDATED_MODEL_ESTIMATE":
                                st.write(f"- 未校準模型估計命中率：`{probability_label(c_prob)}`")
                            else:
                                st.write("- 本關没有有效模型機率；以下試算只有市場基準。")
                            if ci and len(ci) == 2:
                                st.caption(f"啟發式估計範圍：{probability_label(ci[0])} ～ {probability_label(ci[1])}；尚未完成實證校準，不能視為已驗證的 90% 區間。")
                            else:
                                st.caption("信賴區間與保守 EV 未知；需要足夠的前瞻樣本驗證。")
                            st.write(f"- 模型估計 EV：`{ev_p:+.1f}%`。公式：估計命中率 × 賠率 − 1。")
                            st.write(f"- ⚖️ 來源獨立族群：`{', '.join(sig_ev.get('source_families', ['MARKET']))}`")

                            models_list = sig_ev.get("models_desc", [])
                            if models_list:
                                for m_desc in models_list:
                                    st.write(f"- 🤖 `{m_desc}`")
                            else:
                                st.write("- 🤖 統計模型：*無完整攻防數據，誠實略過* (MODEL_NOT_READY)")

                            st.markdown("**④ 賽事排程與串關關聯防護**")
                            st.write(f"- ⏰ 預計開賽時間：`{leg.get('start_time')}`")
                            if leg.get("away_pitcher") or leg.get("home_pitcher"):
                                st.write(f"- ⚾ 先發投手對決：`{leg.get('away_pitcher') or '未公布'}` (客) vs `{leg.get('home_pitcher') or '未公布'}` (主)")
                            st.write(f"- 串關相關風險：**{corr_grade}** (規則折扣：`{item.get('correlation_penalty', 0.0)*100:.1f}%`)")
                        render_leg_source_evidence(leg)

                        st.markdown("<hr style='margin: 6px 0; border-color: #26273b;'>", unsafe_allow_html=True)

                col_bet_l, col_bet_m, col_bet_r = st.columns([2, 1, 1])
                item_key = recommendation_fingerprint(item, 0, item["total_odds"])[:20]
                with col_bet_l:
                    pot_payout = round(stake_per_bet * item["total_odds"], 2)
                    p_joint = float(item.get("sharp_joint_probability") or item.get("joint_probability") or 0.0)
                    o_ticket = float(item.get("total_odds") or 2.0)
                    b_net = o_ticket - 1.0
                    f_star = max(0.0, (b_net * p_joint - (1.0 - p_joint)) / b_net) if b_net > 0 else 0.0
                    q_kelly_stake = max(10.0, min(50.0, round(available_stake * f_star * 0.25 / 10.0) * 10.0))
                    kelly_note = (
                        f"📐 <b>凱利建議注金</b>：<span style='color:#4ade80; font-weight:bold;'>NT$ {q_kelly_stake:.0f}</span> (1/4 Kelly 依據勝率優勢分配)"
                        if f_star > 0
                        else "📐 <b>凱利建議注金</b>：<span style='color:#f87171;'>NT$ 10</span> (無正EV/極低勝率，維持最低微額娛樂)"
                    )
                    st.write(
                        f"下注 **NT$ {stake_per_bet:.0f}** ➔ "
                        f"若全過、按目前推薦賠率派彩：<span style='color:#00e676; font-size:1.2rem; font-weight:bold;'>NT$ {pot_payout:,.2f}</span> "
                        f"(若中獎將全額鎖入【保留儲備池】)",
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"<div style='font-size:0.86rem; color:#bbb; margin-top:3px;'>{kelly_note}</div>", unsafe_allow_html=True)
                with col_bet_m:
                    placed_odds_input = st.number_input(
                        "實際下注賠率 (Placed Odds)",
                        min_value=1.05,
                        max_value=5000.0,
                        value=float(item["total_odds"]),
                        step=0.1,
                        key=f"plc_odds_{item_key}",
                        help="台灣運彩固定賠率以實際被出單接受時為準。若到店下注時賠率變動可在此微調，保障 CLV 準確性。",
                    )
                with col_bet_r:
                    fingerprint = recommendation_fingerprint(item, stake_per_bet, placed_odds_input)
                    submissions = st.session_state.setdefault("ticket_submissions", {})
                    submission = submissions.setdefault(fingerprint, {"key": str(uuid.uuid4())})
                    if st.button("📝 記錄已購買注單", key=f"btn_bet_{item_key}", type="primary", use_container_width=True,
                                 disabled=not current_readiness["is_ready"] or not has_stake_budget or bool(submission.get("ticket_id"))):
                        try:
                            res, snapshot_warnings = record_recommendation(
                                ticket_recorder, snapshot_logger, item, stake_per_bet,
                                placed_odds_input, submission["key"],
                            )
                            submission.update(ticket_id=res["ticket_id"], warnings=snapshot_warnings)
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                    if submission.get("ticket_id"):
                        st.success(f"本機注單 #{submission['ticket_id'][:8]} 已記錄，注金 NT$ {stake_per_bet:.2f} 已扣一次。")
                        for warning in submission.get("warnings", []):
                            st.warning(warning + "；注單內仍保留完整來源資料。")
                        if st.button("建立另一筆同組紀錄", key=f"new_submission_{item_key}"):
                            submissions[fingerprint] = {"key": str(uuid.uuid4())}
                            st.rerun()
                st.caption("此按鈕只更新本機帳本；請在實際購買並取得注單後記錄。人工標記的派彩不代表官方驗證。")

                st.markdown("<hr style='border-color:#2e3040; margin:15px 0;'>", unsafe_allow_html=True)


# -------------------------------------------------------------
# TAB 3: 資金紀錄 (每週 NT$200 錢包與戰績)
# -------------------------------------------------------------
with tab_wallet:
    st.markdown("### 💰 資金紀錄與會計帳本 (Capital & Reserve Governance)")
    st.caption("嚴格貫徹每週 NT$200 娛樂預算：中獎派彩全額撥入【保留儲備池】，下週不足 200 才從外部補。")

    # Lifetime Accounting Summary Table
    st.markdown("#### 📊 全期會計流水 (Lifetime Ledger Breakdown)")
    l_col1, l_col2, l_col3, l_col4 = st.columns(4)
    with l_col1:
        st.metric("累計外部入金", f"NT$ {wallet_status.get('lifetime_external_deposited', 0.0):,.2f}")
    with l_col2:
        st.metric("累計下注金額", f"NT$ {wallet_status.get('lifetime_staked', 0.0):,.2f}")
    with l_col3:
        st.metric("累計總派彩 (Gross)", f"NT$ {wallet_status.get('lifetime_gross_payout', 0.0):,.2f}")
    with l_col4:
        pnl_val = wallet_status.get('lifetime_net_profit', 0.0)
        st.metric("累計淨利 (Net P&L)", f"NT$ {pnl_val:+,.2f}", delta=f"{'+' if pnl_val>0 else ''}{pnl_val:,.2f}")

    st.markdown("---")

    # Financial Control Center
    col_fc1, col_fc2 = st.columns(2)
    with col_fc1:
        st.markdown("#### 💵 外部補金 (補足每週 NT$200 缺口)")
        if wallet_status["can_deposit"]:
            st.info(f"本週尚可自備現金補入：**NT$ {wallet_status['external_deposit_remaining']:.2f}**")
            dep_val = st.number_input(
                "補入金額 (NT$)",
                min_value=0.01,
                max_value=float(wallet_status["external_deposit_remaining"]),
                value=float(wallet_status["external_deposit_remaining"]),
                step=10.0,
            )
            if st.button("確認補金入錢包", type="primary"):
                try:
                    wallet_mgr.deposit_external(dep_val)
                    st.success(f"已補入 NT$ {dep_val}，可玩餘額更新為 NT$ {wallet_status['weekly_wallet_balance'] + dep_val:.2f}！")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        else:
            st.success("✅ 本週戰力已達 NT$ 200 上限（由本週錢包或保留儲備池全額資助），無須自掏腰包！")

    with col_fc2:
        st.markdown("#### 🏦 保留儲備池提領至銀行")
        if wallet_status["prize_pool"] > 0:
            st.write(f"目前保留儲備池餘額：**NT$ {wallet_status['prize_pool']:.2f}** (已累計提領: NT$ {wallet_status.get('lifetime_withdrawn', 0.0):,.2f})")
            wd_val = st.number_input(
                "提領金額 (NT$)",
                min_value=0.01,
                max_value=float(wallet_status["prize_pool"]),
                value=float(wallet_status["prize_pool"]),
                step=10.0,
            )
            if st.button("確認提領儲備"):
                try:
                    wallet_mgr.withdraw_from_prize_pool(wd_val)
                    st.success(f"已提領 NT$ {wd_val} 離開賭桌，落袋為安！")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        else:
            st.caption("保留儲備池目前為 NT$ 0。中獎後的獎金會全額鎖定在這裡！")

    st.markdown("---")
    st.markdown("### 🎫 注單歷史清單")
    st.caption("以下是本機記錄。歷史人工補記與通過推薦核對的注單分開標示；手動結算需按實際票券結果填寫。")

    tickets = ticket_recorder.list_tickets(limit=30)
    if not tickets:
        st.info("尚無下注紀錄。前往「瘋狗看盤」選一張試試！")
    else:
        open_list = [t for t in tickets if t["status"] == "OPEN"]
        settled_list = [t for t in tickets if t["status"] != "OPEN"]

        if open_list:
            st.markdown(f"#### ⏳ 進行中注單 ({len(open_list)} 張)")
            for ot in open_list:
                with st.expander(f"【未結算】{ot['sports_summary']} | 總賠率 {ot['total_odds']}x | 下注 NT$ {ot['stake']} ➔ 預期派彩 NT$ {ot['potential_payout']:,.2f}", expanded=True):
                    plc = ot.get("placed_odds") or ot.get("total_odds")
                    rec = ot.get("recommendation_odds") or plc
                    mode_label = "推薦核對通過" if ot.get("entry_mode") == "recommendation" else "人工歷史補記"
                    st.caption(f"來源: {mode_label} | 記錄時間: {ot['created_at'][:19]} | 注單號: #{ot['id'][:8]} | 推薦賠率: {rec}x | 實注賠率: {plc}x")
                    for leg in ot["legs"]:
                        st.write(f"• [{leg.get('league')}] {leg.get('away_team')} vs {leg.get('home_team')} ➔ **{leg.get('selection')}** (賠率: {leg.get('odds')})")

                    c_act1, c_act2, c_act3 = st.columns(3)
                    with c_act1:
                        if st.button("🎉 全額中獎！(全數入保留池)", key=f"win_act_{ot['id']}", type="primary"):
                            ticket_recorder.settle_ticket(ot["id"], won=True)
                            st.balloons()
                            st.success(f"🎊 恭喜！派彩 NT$ {ot['potential_payout']:,.2f} 已鎖入保留儲備池！")
                            st.rerun()
                    with c_act2:
                        if st.button("❌ 標記未過關", key=f"lose_act_{ot['id']}"):
                            ticket_recorder.settle_ticket(ot["id"], won=False)
                            st.info("注單已標記未過關。保持心態，嚴格遵守每週 NT$200！")
                            st.rerun()
                    with c_act3:
                        if st.button("⚪ 全額退盤 (VOID 退本金)", key=f"void_act_{ot['id']}"):
                            ticket_recorder.settle_ticket(ot["id"], won=False, is_void=True)
                            st.info(f"注單已標記無效退費 (VOID)，本金 NT$ {ot['stake']} 已退入保留儲備池！")
                            st.rerun()

                    with st.expander("🛠️ 自訂實際派彩金額（部分走盤、退盤或賠率異動）", expanded=False):
                        custom_payout_val = st.number_input(
                            "實際領回金額 (NT$)",
                            min_value=0.0,
                            max_value=1000000.0,
                            value=float(ot["potential_payout"]),
                            step=10.0,
                            key=f"custom_payout_{ot['id']}",
                        )
                        if st.button("確認以自訂金額結算中獎", key=f"custom_win_{ot['id']}"):
                            ticket_recorder.settle_ticket(ot["id"], won=True, custom_payout=custom_payout_val)
                            st.balloons()
                            st.success(f"已按自訂金額 NT$ {custom_payout_val:.2f} 結算並撥入保留儲備池！")
                            st.rerun()

        if settled_list:
            st.markdown(f"#### 📜 歷史已結算注單 ({len(settled_list)} 張)")
            hist_display = []
            for stt in settled_list:
                status_str = stt["status"]
                pnl = stt["actual_payout"] - stt["stake"]
                clv_val = stt.get("clv")
                clv_str = f"{clv_val*100:+.1f}%" if clv_val is not None else "N/A"
                hist_display.append({
                    "日期": (stt.get("settled_at") or stt["created_at"])[:10],
                    "來源": "推薦核對通過" if stt.get("entry_mode") == "recommendation" else "人工歷史補記",
                    "賽事組合": stt.get("sports_summary", "混串"),
                    "實注賠率": f"{stt.get('placed_odds') or stt['total_odds']}x",
                    "收盤賠率": f"{stt.get('closing_odds')}x" if stt.get('closing_odds') else "未記錄",
                    "CLV": clv_str,
                    "下注": f"NT$ {stt['stake']:.0f}",
                    "狀態": "✅ 中獎" if status_str == "WON" else "⚪ 退盤" if status_str == "VOID" else "❌ 未中",
                    "總派彩": f"NT$ {stt['actual_payout']:,.2f}",
                    "淨損益": f"{'+' if pnl>0 else ''}NT$ {pnl:,.2f}",
                })
            st.table(hist_display)

# -------------------------------------------------------------
# TAB 4: 影子評估與前瞻驗證 (Research / Performance)
# -------------------------------------------------------------
with tab_research:
    st.markdown("### 📊 影子評估與前瞻驗證中心 (Shadow Forward Evaluation)")
    meta = get_strategy_metadata()

    st.markdown(
        f"""
        <div style='background:#12141f; border:1px solid #2d314d; border-radius:10px; padding:14px 20px; margin-bottom:16px;'>
            <div style='display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;'>
                <div>
                    <span style='color:#00e676; font-weight:bold; font-size:1.1rem;'>🔒 策略版本凍結中：<code>{STRATEGY_VERSION}</code></span>
                    &nbsp;|&nbsp;
                    <span style='color:#9e9e9e; font-size:0.88rem;'>代碼簽章：<code>{meta['code_version']}</code> · 凍結基準日：{meta['frozen_date']}</span>
                </div>
                <div>
                    <span style='background:#2a1a1f; color:#ff8a80; border:1px solid #b71c1c; padding:3px 10px; border-radius:6px; font-size:0.82rem;'>
                        🛡️ 嚴禁測試期調參 (No Mid-Test Weight Tuning)
                    </span>
                </div>
            </div>
            <div style='margin-top:8px; font-size:0.85rem; color:#aaa;'>
                ⚠️ <b>真實定位宣告</b>：本系統為台灣運彩決策支援與前瞻研究平台（Decision Support & Research Platform），非穩賺保證獲利系統。所有統計指標均強制標記樣本數 N。
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Fetch data
    render_research_overview()
    r_paths = research_paths()
    snap_p = r_paths["snapshots"]
    parl_p = r_paths["parlays"]
    snap_mtime = snap_p.stat().st_mtime if snap_p.exists() else 0.0
    parl_mtime = parl_p.stat().st_mtime if parl_p.exists() else 0.0

    snap_analysis = get_cached_snapshot_analytics(str(snap_p), snap_mtime)
    snapshots = snap_analysis["snapshots"]
    current_cohort = snap_analysis["cohort"]
    agree_data = snap_analysis["agree_data"]
    ev_data = snap_analysis["ev_data"]
    delta_data = snap_analysis["delta_data"]
    crowd_data = snap_analysis["crowd_data"]
    expert_data = snap_analysis["expert_data"]

    portfolio_summary = shadow_portfolio.get_portfolio_summary(strategy_version=STRATEGY_VERSION, eligible_only=True)
    settled_snaps = current_cohort["observations"]
    st.caption(f"成績分組：目前預測實驗；有效且去重的二元觀測 {len(settled_snaps)} 筆，"
               f"唯一賽事 {current_cohort['audit']['unique_event_count']} 場。不同設定與未通過封存核對的紀錄不計入此組。")

    # 4 Top Metrics
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1:
        st.metric(
            label="📸 預測快照累積",
            value=f"{len(snapshots)} 筆",
            delta=f"已結算 {len(settled_snaps)} 筆 (目標 N≥200)",
        )
    with m_col2:
        sh_pl = portfolio_summary["net_pl"]
        sh_roi = portfolio_summary["roi_pct"]
        sh_n = portfolio_summary["settled_tickets"]
        sample_tag = "⚠️ N<30" if portfolio_summary["is_insufficient_sample"] else "✅ N≥30"
        st.metric(
            label=f"🧪 合格影子組合損益 ({sample_tag})",
            value=f"NT$ {sh_pl:+.2f}",
            delta=f"ROI {metric_number(sh_roi, '+.1f', suffix='%', sample_size=sh_n)} (N = {sh_n})",
        )
        st.caption(f"排除其它策略或未合格注單 {portfolio_summary['excluded_tickets']} 張。")
    with m_col3:
        high_data = agree_data.get("HIGH", {})
        high_n = high_data.get("sample_size", 0)
        high_hr = metric_number(high_data.get('hit_rate'), ".1f", scale=100, suffix="%") if high_n else "尚無合格樣本"
        st.metric(
            label="🎯 HIGH 前瞻樣本命中率",
            value=high_hr,
            delta=f"N = {high_n} ({'不足30' if high_n < 30 else '仍需檢驗準確度'})",
        )
    with m_col4:
        st.metric(
            label="💰 真實 NT$200 錢包 (獨立隔離)",
            value=f"NT$ {wallet_status['weekly_wallet_balance']:.2f}",
            delta="影子測試 0% 影響真實金流",
        )

    # Progress bar to First Milestone (N >= 200)
    target_milestone = 200
    cur_settled = len(settled_snaps)
    pct = min(1.0, cur_settled / float(target_milestone))
    st.progress(pct, text=f"🏁 第一里程碑進度 (First Milestone): {cur_settled} / {target_milestone} 筆結算 (滿 200 筆或 30 天出具首份正式前瞻報告)")
    with st.expander("整張串關的前瞻驗證與樣本不確定性", expanded=False):
        ticket_metrics = get_cached_forward_parlay_metrics(str(parl_p), current_cohort["target_experiment_id"], parl_mtime)
        st.caption("只計目前實驗的賽前封存注單；共用賽事與同賽事日組合會合併成事件群。退盤與打平不計二元機率準確度。")
        st.table([{"倍率區間": tier, "唯一注單數": values["n"], "事件日群數": values["event_slate_cluster_count"],
                   "平均估計機率": probability_label(values["mean_estimated_probability"]),
                   "實際命中率": probability_label(values["hit_rate"]), "Brier": values["brier"],
                   "Log loss": values["log_loss"], "固定單位 ROI (%)": values["roi_pct"]}
                  for tier, values in ticket_metrics["tiers"].items()])
        for tier, values in ticket_metrics["tiers"].items():
            intervals = values["cluster_bootstrap_ci95"]
            if intervals:
                st.caption(f"{tier}：ROI 95% 群組區間 {intervals['roi_pct'][0]:.2f}%～{intervals['roi_pct'][1]:.2f}%；"
                           f"命中率區間 {intervals['hit_rate'][0]:.1%}～{intervals['hit_rate'][1]:.1%}。")
            else:
                st.caption(f"{tier}：事件群不足，95% 區間保持未知。")

    st.markdown("---")

    # Section 1: Agreement Buckets Table
    st.markdown("#### ① 信號品質階梯表現 (Agreement Buckets)")
    st.caption("只計本策略合格前瞻樣本，排除未知時間、賽後資料與退盤。HIGH 是否優於 MED／LOW 仍需檢驗；達到 30 筆不保證有統計證據。")

    agree_rows = []
    for b_name in ["HIGH", "MED", "LOW", "INSUFFICIENT"]:
        b_info = agree_data.get(b_name, {})
        n = b_info.get("sample_size", 0)
        agree_rows.append({
            "共識階梯": b_name,
            "樣本數 (N)": n,
            "命中數": b_info.get("wins", 0),
            "前瞻命中率": metric_number(b_info.get('hit_rate'), ".1f", scale=100, suffix="%") if n else "未知",
            "平均賠率": metric_number(b_info.get('average_odds'), ".2f"),
            "實盤 ROI": metric_number(b_info.get('roi_pct'), "+.1f", suffix="%"),
            "樣本狀態": "不足30" if n < 30 else "需統計檢验",
        })
    st.table(agree_rows)

    # Section 2: CLV Closing Line Value Analysis
    st.markdown("#### ② 實盤盤口價值審計 (Closing Line Value / CLV)")
    st.caption("CLV = (下注賠率 / 收盤賠率) − 1。正值表示取得的價格較高；需比較同場、同玩法與同讓分線，不能單憑 CLV 證明有獲利能力。")
    clv_analytics = ticket_recorder.get_clv_analytics()
    clv_col1, clv_col2, clv_col3 = st.columns(3)
    with clv_col1:
        st.metric(
            label="📈 平均 CLV 超額回報",
            value=metric_number(clv_analytics['avg_clv_pct'], "+.2f", suffix="%", sample_size=clv_analytics['sample_size']),
            delta=("> 0% 表示取得價格較高，仍需檢驗" if clv_analytics['avg_clv_pct'] >= 0 else "低於收盤賠率") if clv_analytics['sample_size'] else "尚無可比較的價格紀錄",
        )
    with clv_col2:
        st.metric(
            label="🎯 擊敗收盤盤口率 (Beat Closing Line)",
            value=metric_number(clv_analytics['beating_closing_line_rate'], ".1f", suffix="%", sample_size=clv_analytics['sample_size']),
            delta=f"優勢單數: {clv_analytics['positive_clv_count']} / {clv_analytics['sample_size']}",
        )
    with clv_col3:
        n_clv = clv_analytics['sample_size']
        clv_status_tag = "樣本不足 30" if n_clv < 30 else "達到30筆，仍需檢驗；收盤價格由本機記錄提供"
        st.metric(
            label="🔍 CLV 審計樣本數",
            value=f"{n_clv} 筆注單",
            delta=clv_status_tag,
        )

    # Section 3: EV Buckets Table
    st.markdown("#### ③ 期望值分層表現 (Expected Value / EV Buckets)")
    st.caption("核心問題：**理論 EV 越高的注單，在實盤長跑中是否確實產生正回報？負 EV 陷阱注單是否如期失血？**")
    ev_data = metrics_engine.evaluate_ev_buckets(snapshots)
    ev_rows = []
    for ev_name, ev_info in ev_data.items():
        n = ev_info.get("sample_size", 0)
        brier_str = f"{ev_info.get('brier_score', 0.0):.4f}" if ev_info.get("brier_score") is not None else "N/A"
        ev_rows.append({
            "EV 分層 (Expected Value)": ev_name,
            "樣本數 (N)": n,
            "命中數": ev_info.get("wins", 0),
            "實盤勝率": metric_number(ev_info.get('hit_rate'), ".1f", scale=100, suffix="%"),
            "實盤 ROI": metric_number(ev_info.get('roi_pct'), "+.1f", suffix="%"),
            "Brier Score": brier_str,
            "樣本狀態": "⚠️ INSUFFICIENT_SAMPLE" if ev_info.get("is_insufficient_sample") else "✅ VALID_SAMPLE",
        })
    st.table(ev_rows)

    # Section 4: Model-Market Delta Buckets Table
    st.markdown("#### ④ 模型 vs 盤口差值表現 (Model-Market Delta Buckets)")
    st.caption("核心問題：**當模型勝率顯著高於台彩隱含勝率（Delta > +5pp）時，誰勝出的機率更高？**")

    delta_data = metrics_engine.evaluate_model_market_delta_buckets(snapshots)
    delta_rows = []
    for d_name, d_info in delta_data.items():
        n = d_info.get("sample_size", 0)
        brier_str = f"{d_info.get('brier_score', 0.0):.4f}" if d_info.get("brier_score") is not None else "N/A"
        delta_rows.append({
            "Delta 區間 (Model - Market)": d_name,
            "樣本數 (N)": n,
            "命中數": d_info.get("wins", 0),
            "實盤勝率": metric_number(d_info.get('hit_rate'), ".1f", scale=100, suffix="%"),
            "實盤 ROI": metric_number(d_info.get('roi_pct'), "+.1f", suffix="%"),
            "Brier Score": brier_str,
            "樣本狀態": "⚠️ INSUFFICIENT_SAMPLE" if d_info.get("is_insufficient_sample") else "✅ VALID_SAMPLE",
        })
    st.table(delta_rows)

    # Section 5: Multi-Source Tabs (Crowd, Expert, Model Calibration)
    st.markdown("#### ⑤ 外部情報源與模型校準分析")
    c_tab1, c_tab2, c_tab3 = st.tabs([
        "👥 彩迷投票選票檢驗 (Crowd)",
        "🧙 大神與分析師榜 (Verified Experts)",
        "📈 機率模型校準 (Model Calibration)",
    ])

    with c_tab1:
        st.markdown("**彩迷支持率階梯表現**")
        st.caption("核心問題：**極高彩迷支持率（>70%）是真實領先指標，抑或純粹是大眾熱門偏誤？**")
        crowd_data = metrics_engine.evaluate_crowd_buckets(snapshots)
        crowd_rows = []
        for cr_name, cr_info in crowd_data.items():
            crowd_rows.append({
                "支持率區間": cr_name,
                "樣本數 (N)": cr_info.get("sample_size", 0),
                "命中數": cr_info.get("wins", 0),
                "實盤勝率": metric_number(cr_info.get('hit_rate'), ".1f", scale=100, suffix="%"),
                "實盤 ROI": metric_number(cr_info.get('roi_pct'), "+.1f", suffix="%"),
                "樣本狀態": "⚠️ INSUFFICIENT_SAMPLE" if cr_info.get("is_insufficient_sample") else "✅ VALID_SAMPLE",
            })
        st.table(crowd_rows)

    with c_tab2:
        expert_data = metrics_engine.evaluate_expert_metrics(snapshots)
        st.markdown("**大神支持數量分佈**")
        exp_count_rows = []
        for ec_name, ec_info in expert_data.get("consensus_count_buckets", {}).items():
            exp_count_rows.append({
                "大神推薦數": ec_name,
                "樣本數 (N)": ec_info.get("sample_size", 0),
                "命中數": ec_info.get("wins", 0),
                "實盤勝率": metric_number(ec_info.get('hit_rate'), ".1f", scale=100, suffix="%"),
                "實盤 ROI": metric_number(ec_info.get('roi_pct'), "+.1f", suffix="%"),
                "樣本狀態": "⚠️ INSUFFICIENT_SAMPLE" if ec_info.get("is_insufficient_sample") else "✅ VALID_SAMPLE",
            })
        st.table(exp_count_rows)

        st.markdown("**獨立驗證大神個人表現排行榜**")
        lead = expert_data.get("leaderboard", {})
        if not lead:
            st.info("尚無已結算的驗證專家個人注單記錄。")
        else:
            lead_rows = []
            for ename, einfo in lead.items():
                lead_rows.append({
                    "專家名稱": ename,
                    "樣本數 (N)": einfo.get("sample_size", 0),
                    "勝率": metric_number(einfo.get('win_rate'), ".1f", scale=100, suffix="%"),
                    "平均賠率": metric_number(einfo.get('average_odds'), ".2f"),
                    "實盤 ROI": metric_number(einfo.get('roi_pct'), "+.1f", suffix="%"),
                    "樣本狀態": "⚠️ INSUFFICIENT_SAMPLE" if einfo.get("is_insufficient_sample") else "✅ VALID",
                })
            st.table(lead_rows)

    with c_tab3:
        st.markdown("**機率模型校準表 (Calibration Table)**")
        st.caption("預測勝率區間 vs 實盤命中率對比。理想模型之校準誤差應接近 0。")
        calib_data = metrics_engine.evaluate_calibration_bins(snapshots)
        calib_rows = []
        for cb_name, cb_info in calib_data.items():
            calib_rows.append({
                "預測機率區間": cb_name,
                "樣本數 (N)": cb_info.get("sample_size", 0),
                "平均預測機率": metric_number(cb_info.get('avg_predicted_prob'), ".1f", scale=100, suffix="%"),
                "實盤命中率": metric_number(cb_info.get('empirical_hit_rate'), ".1f", scale=100, suffix="%"),
                "校準誤差 (Delta)": metric_number(cb_info.get('calibration_error'), ".2f", scale=100, suffix=" pp"),
                "樣本狀態": "⚠️ INSUFFICIENT_SAMPLE" if cb_info.get("is_insufficient_sample") else "✅ VALID_SAMPLE",
            })
        st.table(calib_rows)

    st.markdown("---")

    # Section 6: Shadow Portfolio Recent Bets
    st.markdown("#### ⑥ 影子虛擬投資組合近期注單 (NT$10 Virtual Stake)")
    recent_shadow = shadow_portfolio.get_recent_tickets(15)
    if not recent_shadow:
        st.info("尚未產生影子注單。可執行 `python main.py snapshot` 自動記錄本日最佳組合。")
    else:
        sh_display = []
        for stt in recent_shadow:
            sh_display.append({
                "注單編號": stt["id"][:14] + "...",
                "日期": stt["date"],
                "類型": stt["selection_category"],
                "階梯": stt["multiplier_tier"],
                "總賠率": f"{stt['total_odds']}x",
                "虛擬注金": f"NT$ {stt['virtual_stake']:.0f}",
                "狀態": "✅ 中獎" if stt["status"] == "WON" else "❌ 未中" if stt["status"] == "LOST" else "⏳ 等待開獎",
                "派彩": f"NT$ {stt['actual_payout']:.2f}",
                "淨損益": f"{'+' if stt['net_profit']>0 else ''}NT$ {stt['net_profit']:.2f}",
            })
        st.table(sh_display)

    st.markdown("---")
    st.markdown(
        """
        <div style='font-size:0.85rem; color:#888; text-align:center;'>
            ⚙️ <b>指令列維運工具</b>：<br>
            每日快照：<code>python main.py snapshot</code> &nbsp;|&nbsp; 
            完賽結算：<code>python main.py settle</code> &nbsp;|&nbsp; 
            產出週報：<code>python main.py weekly-report</code>
        </div>
        """,
        unsafe_allow_html=True,
    )

