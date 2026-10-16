"""AppTest checks that displayed source state does not overclaim evidence."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


def _run_overview(tmp_path, status, leg_status=None):
    payload = {
        "expert_statuses": {
            "PLAYSPORT_EXPERT": {
                "source_status": status,
                "board_kinds": ["main_prediction", "win_rate"],
                "source_urls": ["https://www.playsport.cc/billboard/mainPrediction?allianceid=1"],
                "observed_at": "2026-10-12T12:00:00Z",
                "cache_age_minutes": 0 if status == "LIVE" else 2000,
                "member_pages": [{"source_url": "https://www.playsport.cc/member/example/prediction"}],
                "verified_pick_count": 0,
            }
        },
        "legs": [{
            "event_name": "主隊 vs 客隊",
            "signal_evidence": {
                "expert_source_status": leg_status or status,
                "expert_board_kinds": ["main_prediction", "win_rate"],
                "expert_observed_at": "2026-10-12T12:00:00Z",
                "publication_time_precision": "UNKNOWN",
                "expert_source_urls": ["https://www.playsport.cc/member/example/prediction"],
                "verified_experts": [],
            },
        }],
        "model_summary": [{
            "source_id": "toy_model",
            "source_name": "測試模型",
            "probability": 0.6,
            "confidence_interval": None,
            "metadata": {
                "probability_status": "UNVALIDATED_MODEL_ESTIMATE",
                "market_fair_method": "BREAKEVEN_BASELINE_NOT_DEVIGGED",
            },
        }],
    }
    code = (
        "import sys\\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\\n"
        "from ui.source_overview import render_source_overview\\n"
        f"payload = {payload!r}\\n"
        "render_source_overview(payload['expert_statuses'], payload['legs'], payload['model_summary'])\\n"
    )
    return AppTest.from_string("import json\n" + code.replace("\\n", "\n"), default_timeout=10).run()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("UNKNOWN", "沒有足夠狀態資料判斷來源是否可讀"),
        ("HTTP_403", "網站拒絕本次公開頁請求"),
        ("PARSE_EMPTY", "頁面可取得，但未解析到預期榜單或推牌資料"),
    ],
)
def test_statuses_have_visible_explanations_and_no_pick_claim(tmp_path, status, expected):
    app = _run_overview(tmp_path, status)
    assert not app.exception
    visible = " ".join(
        element.value for bucket in (app.caption, app.info, app.markdown, app.text)
        for element in bucket if isinstance(element.value, str)
    )
    assert expected in visible
    assert "沒有可驗證推牌" in visible
    assert "未推" not in visible
    assert "反對" in visible


def test_live_readable_page_without_pick_is_not_counted_as_verified(tmp_path):
    app = _run_overview(tmp_path, "LIVE")
    assert not app.exception
    visible = " ".join(
        element.value for bucket in (app.caption, app.info, app.markdown, app.text)
        for element in bucket if isinstance(element.value, str)
    )
    assert "本次成功讀取遠端公開頁" in visible
    assert "可驗證推牌數" in visible
    assert "0" in visible
    assert "沒有可驗證推牌" in visible
    assert "未經實證校準的模型估計" in visible
    assert "沒有實證校準區間" in visible
