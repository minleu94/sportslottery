"""An offline-friendly education page, independent of wallet and live scraping."""
import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ui.metric_guide import render_metric_guide
from ui.source_overview import render_source_overview
from ui.navigation import render_sidebar_navigation
from ui.theme import inject_theme

st.set_page_config(page_title="指標與資料來源｜瘋狗流", page_icon="📖", layout="wide")
inject_theme()
render_sidebar_navigation()
render_metric_guide()
st.divider()
st.subheader("本頁目前執行狀態")
st.caption("這是離線說明頁，沒有傳入本次執行的來源／關卡資料；下方 UNKNOWN 表示此頁沒有即時觀測，不代表來源正常或失敗。")
render_source_overview({}, [], [])
