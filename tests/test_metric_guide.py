"""User-facing semantics: real source fields survive, unknown data stays unknown."""
import json
from pathlib import Path

from bs4 import BeautifulSoup
from streamlit.testing.v1 import AppTest

from core.scraper import PlaysportScraper
from core.signal_hub import SignalHub
from core.optimizer import ParlayOptimizer
from integrations.common.models import PredictionSignal, TaiwanLeg
from integrations.experts.playsport_crowd import PlaysportCrowdAdapter
from ui.metric_guide import local_source_evidence


def test_observed_crowd_and_expert_evidence_survives_synthesis():
    leg = TaiwanLeg(
        event_id="guide1", sport="baseball", league="MLB", market="不讓分",
        selection="道奇 主勝", taiwan_odds=2, side="主",
        signal_evidence={"consensus_ratio": 0.7, "vote_count": 123, "crowd_snapshot_timestamp": "2026-10-12T10:00:00Z", "crowd_age_minutes": 5, "source_url": "https://www.playsport.cc/predict/scale?allianceid=1"},
    )
    crowd = PlaysportCrowdAdapter().get_crowd_signal(leg)
    details = [{"nickname": "Example", "raw_pick": "道奇 不讓分", "source_url": "https://www.playsport.cc/member/example/prediction?allianceid=1"}]
    expert = PredictionSignal(
        source_id="test_expert", source_name="Example", source_type="EXPERT", event_id="guide1",
        market="不讓分", selection="主", score=80, confidence="MED", source_category="VERIFIED_EXPERT",
        independence_group="PLAYSPORT_EXPERT", metadata={"expert_details": details, "agreeing_count": 1, "consensus_ratio": 1},
    )
    hub = SignalHub(expert_adapter=object(), crowd_adapter=object(), model_registry=object())
    result = hub.synthesize_signals_for_leg(leg, [crowd, expert])
    evidence = result.signal_evidence
    assert evidence["consensus_ratio"] == 0.7
    assert evidence["vote_count"] == 123
    assert evidence["crowd_age_minutes"] == 5
    assert evidence["verified_experts"] == details
    assert evidence["source_url"].startswith("https://www.playsport.cc/")
    assert "非本場勝率" in evidence["expert_desc"]


def test_unobserved_votes_do_not_become_fifty_percent():
    soup = BeautifulSoup('<table><tr><td>客2.00</td><td>暫無資料</td></tr></table>', "html.parser")
    cells = soup.find_all("td")
    parsed = PlaysportScraper()._parse_bank_cell(cells[0], cells[1], "客")
    assert parsed["consensus_ratio"] is None
    assert parsed["vote_count"] is None
    leg = TaiwanLeg(event_id="unknown", sport="baseball", league="MLB", market="不讓分", selection="客", taiwan_odds=2, signal_evidence=parsed)
    assert PlaysportCrowdAdapter().get_crowd_signal(leg) is None
    hub = SignalHub(expert_adapter=object(), crowd_adapter=object(), model_registry=object())
    result = hub.synthesize_signals_for_leg(leg, [])
    assert result.signal_evidence["consensus_ratio"] is None
    assert result.signal_evidence["vote_count"] is None
    assert ParlayOptimizer().optimize([{"match_id": "unknown", "options": [parsed]}]) == []


def test_cache_is_never_presented_as_remote_live_status(tmp_path):
    cache = tmp_path / "cache" / "playsport"
    cache.mkdir(parents=True)
    (cache / "scale_1.json").write_text(json.dumps({"cached_iso": "2020-01-01T00:00:00Z", "matches": [{}]}), encoding="utf-8")
    soccer_cache = tmp_path / "cache" / "models" / "penaltyblog_dixon_coles"
    soccer_cache.mkdir(parents=True)
    (soccer_cache / "real_matches_eng.1.json").write_text(json.dumps({
        "matches": [{"date": "2026-10-12"}] * 1200,
    }), encoding="utf-8")
    state_path = tmp_path / "model_state" / "live_mlb_elo.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "ratings": {"MLB_LAD": 1510}, "history": [{"date": "2026-10-12"}] * 120,
        "processed_game_pks": [str(i) for i in range(120)], "data_as_of": "2026-10-12T23:00:00+00:00",
        "source": "Official MLB results",
    }), encoding="utf-8")
    rows = local_source_evidence(tmp_path)
    assert "舊快取" in rows[0]["目前可確認的狀態"]
    assert rows[0]["本機紀錄數"] == 1
    assert rows[2]["本機紀錄數"] == 1200
    assert rows[2]["最近記錄時間"] == "2026-10-12"
    assert rows[2]["本機路徑"] == str(soccer_cache / "real_matches_eng.1.json")
    assert rows[3]["本機紀錄數"] == 120
    assert "官方賽果狀態" in rows[3]["目前可確認的狀態"]
    assert rows[3]["本機路徑"] == str(state_path)


def test_legacy_source_rows_are_explicitly_historical_not_current(tmp_path):
    research = tmp_path / "research"
    research.mkdir()
    rows = local_source_evidence(research)
    assert rows[2]["來源"].startswith("目前研究快取")
    assert rows[2]["本機紀錄數"] == 0
    assert rows[3]["來源"].startswith("目前研究狀態")
    assert rows[3]["本機紀錄數"] == 0
    assert all("歷史參考" in row["來源"] for row in rows[4:])
    assert all("不代表目前研究模型" in row["目前可確認的狀態"] for row in rows[4:])


def test_guide_explains_ev_with_interactive_profit_example(tmp_path):
    app = AppTest.from_string(
        "from pathlib import Path\nfrom ui.metric_guide import render_metric_guide\n"
        f"render_metric_guide(Path({str(tmp_path)!r}))\n",
        default_timeout=10,
    ).run()
    assert not app.exception
    assert app.metric[0].value == "50.00%"
    assert app.metric[1].value == "+20.00%"
    app.slider(key="guide_probability").set_value(40).run()
    assert not app.exception
    assert app.metric[1].value == "-20.00%"
    assert any("NT\\$ -4.00" in element.value for element in app.markdown)
