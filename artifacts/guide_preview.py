"""Read-only preview of the same guide renderer used by the application page."""
import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ui.metric_guide import render_metric_guide
from ui.source_overview import render_source_overview

st.set_page_config(page_title="指標與資料來源｜瘋狗流", page_icon="📖", layout="wide")
render_metric_guide()
st.divider()
st.caption("離線說明預覽，沒有傳入本次來源觀測。")
render_source_overview({}, [], [])
