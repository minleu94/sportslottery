"""系統設定與資料存放管理頁面."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.storage_config import (
    get_scheduled_task_status,
    get_storage_root,
    get_storage_stats,
    set_scheduled_task_enabled,
    update_storage_location,
)
from ui.navigation import render_sidebar_navigation
from ui.theme import inject_theme
from core.profile_manager import ProfileManager

st.set_page_config(page_title="系統設定與資料存放｜瘋狗流", page_icon="⚙️", layout="wide")
render_sidebar_navigation()
inject_theme()

# Admin Archie Permission Gate
pm = ProfileManager()
auth_id = st.session_state.get("authenticated_profile_id")
active_profile = pm.get_profile(auth_id) if auth_id else None

if not active_profile or active_profile.get("name") != "Archie":
    st.error("⛔ 存取受限：【系統設定與資料存放】為系統核心最高權限，僅限管理員 Archie 存取！")
    st.info("若您是管理員 Archie，請先返回首頁以 Archie 帳號及 PIN 碼登入。")
    st.stop()

st.title("⚙️ 系統設定與資料存放管理 (管理員: Archie)")
st.caption("管理本機運彩資料庫存放路徑、C 槽防磨損保護、Windows 定期研究排程與執行狀態。")

tab_storage, tab_schedule, tab_faq = st.tabs([
    "💾 資料存放路徑與硬碟狀態",
    "⏰ 背景排程與黑視窗控制",
    "❓ 排程機制問答（優化 vs 純紀錄）",
])

with tab_storage:
    stats = get_storage_stats()
    current_root = stats["storage_root"]

    st.subheader("1. 目前資料存放位置")
    col_path, col_status = st.columns([3, 1])
    with col_path:
        st.code(current_root, language="bash")
    with col_status:
        if stats["exists"]:
            st.success("✅ 資料目錄正常")
        else:
            st.error("❌ 目錄不存在")

    # C 槽保護資訊
    if stats.get("is_junction"):
        st.info(
            "🛡️ **C 槽 SSD 防磨損保護中**：本機專案目錄的 `data/` 已透過 Windows Directory Junction "
            f"重定向至 `{stats['drive']}` 槽，專案所有快取、快照與資料庫讀寫均**不消耗 C 槽壽命**！"
        )

    # 磁碟空間狀態
    st.subheader("2. 儲存磁碟空間狀態")
    col_d1, col_d2, col_d3 = st.columns(3)
    col_d1.metric(f"所屬磁碟 ({stats['drive']})", f"{stats['drive_free_gb']} GB 可用")
    col_d2.metric("磁碟總容量", f"{stats['drive_total_gb']} GB")
    col_d3.metric("資料總佔用", f"{stats['total_data_mb']} MB ({stats['file_count']} 個檔案)")

    if stats["drive_total_gb"] > 0:
        st.progress(
            min(1.0, max(0.0, stats["drive_used_pct"] / 100)),
            text=f"磁碟已使用 {stats['drive_used_pct']}%（剩餘 {stats['drive_free_gb']} GB）",
        )

    # 重點檔案容量拆解
    st.subheader("3. 核心資料體積明細")
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    col_f1.metric("💰 錢包帳本 (war_chest.sqlite3)", f"{stats['db_size_mb']} MB")
    col_f2.metric("📜 串關紀錄 (parlay_snapshots)", f"{stats['parlay_snapshots_mb']} MB")
    col_f3.metric("🎯 預測快照 (prediction_snapshots)", f"{stats['prediction_snapshots_mb']} MB")
    col_f4.metric("⚾ MLB 官方底冊 (mlb_schedule)", f"{stats['mlb_schedule_mb']} MB")

    st.divider()

    # 調整存放路徑
    st.subheader("4. 重新設定存放資料位置")
    st.write("如果你希望將資料庫與研究紀錄移至其他硬碟（例如其他外接硬碟或特定分區），可以在下方輸入新路徑並套用：")

    new_path = st.text_input("輸入新的資料存放路徑（支援絕對路徑）", value=current_root)
    migrate_data = st.checkbox("自動將現有所有資料與資料庫遷移（複製）至新目錄", value=True)

    if st.button("🚀 儲存並套用新路徑", type="primary"):
        with st.spinner("正在驗證路徑並更新配置..."):
            success, message = update_storage_location(new_path, migrate=migrate_data)
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(message)

with tab_schedule:
    st.subheader("1. Windows 排程工作狀態")
    task_info = get_scheduled_task_status()

    if not task_info.get("available", True):
        st.warning("目前環境非 Windows，不支援 Windows 工作排程器。")
    elif not task_info.get("Exists", False):
        st.info("系統中目前未安裝 `SportsLottery-Research-Pipeline` 排程任務。")
    else:
        state_str = task_info.get("State", "UNKNOWN")
        is_enabled = task_info.get("Enabled", False)

        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            if state_str == "Ready":
                st.metric("排程狀態", "🟢 待命中 (Ready)")
            elif state_str == "Running":
                st.metric("排程狀態", "🟡 執行中 (Running)")
            elif state_str == "Disabled":
                st.metric("排程狀態", "⏸️ 已停用 (Disabled)")
            else:
                st.metric("排程狀態", state_str)

        with col_t2:
            st.metric("下次執行時間", task_info.get("NextRunTime") or "無（已停用）")

        with col_t3:
            last_res = task_info.get("LastTaskResult")
            res_label = "成功 (0)" if last_res == 0 else f"代碼 {last_res}" if last_res is not None else "未知"
            st.metric("上次執行結果", res_label)

        if task_info.get("Arguments"):
            with st.expander("查看排程完整執行參數"):
                st.code(task_info.get("Arguments"), language="bash")

        st.subheader("2. 排程控制開關")
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("▶️ 啟用自動排程（每 15 分鐘）", use_container_width=True, disabled=is_enabled):
                ok, msg = set_scheduled_task_enabled(True)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        with col_btn2:
            if st.button("⏹️ 停用自動排程", use_container_width=True, disabled=not is_enabled):
                ok, msg = set_scheduled_task_enabled(False)
                if ok:
                    st.warning(msg)
                    st.rerun()
                else:
                    st.error(msg)

    st.divider()
    st.subheader("3. 終端黑視窗防彈出防護")
    st.success(
        "🛡️ **無視窗保護已啟動**：專案已在 `core/strategy_version.py` 等模組全面套用 "
        "`subprocess.CREATE_NO_WINDOW` 標記。即使排程在背景頻繁呼叫 Git 版本檢查，"
        "也不會再彈出任何 cmd 黑色指令視窗，徹底保證背景靜默執行！"
    )

with tab_faq:
    st.subheader("💡 排程核心問答：每次排程是在持續優化？還是純紀錄？")
    st.write(
        "許多使用者會好奇：這個每 15 分鐘跑一次的 Research Pipeline，到底有沒有在「自我學習」或「自動優化」？"
    )

    st.markdown(
        """
        ### 📌 結論：它是「球隊實力數據滾動更新」+「嚴格的客觀驗證純紀錄」，**絕不在線上偷改下注策略權重**！

        這背後的設計邏輯有兩個明確層面：

        ---

        #### ① 有在持續更新的部分：**客觀賽事與戰力數據**
        - **MLB Elo 即時評分**：每次大聯盟有新比賽打完，系統會抓取官方正式比分，動態計算並更新各球隊的最新 Elo 分數。
        - **足球賽果快取**：自動更新英超、西甲等聯賽的完賽比分，提供給 Dixon-Coles 泊松模型作為最新統計母體。
        - **即時盤口與大眾情報**：每 15 分鐘抓取最新台彩賠率與玩運彩大眾投票走向。

        ---

        #### ② 絕不自動變更的部分：**下注策略與決策權重（嚴禁線上隨意調整）**
        - **遵守量化治理守則（Immutable Strategy Rule）**：
          在專案的 `core/strategy_version.py` 中明確定義：
          ```python
          GOVERNANCE_RULES = {
              "immutable_strategy": True,          # 測試期間策略凍結
              "no_mid_test_weight_changes": True,  # 嚴禁中途修改權重
              "min_sample_size_for_tuning": 100,   # 至少累積 100 場樣本才能調優
          }
          ```
        - **為什麼不讓它每 15 分鐘「自我優化」？**
          因為如果 AI 預測輸了一場就自動調高某個權重、贏了一場就加碼另一個指標，這在量化金融與統計學上稱為**「過度擬合（Overfitting）」**與**「資料洩漏（Data Snooping）」**，會產生「回測看起來天下無敵，實際下注輸到脫褲」的假象。
        - **純紀錄的價值**：
          排程在賽前 1 小時把預測**「打上時間戳印凍結封存」**，比賽結束後進行**「不可篡改的事後結算」**。透過每週報告檢驗勝率、投報率（ROI）與 Brier 分數，只有在累積足夠客觀真實樣本（>100場）後，才由研究員進行離線校準與策略升級。
        """
    )
