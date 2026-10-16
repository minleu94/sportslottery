from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from core.snapshot_logger import PredictionSnapshotLogger
from core.ticket_recorder import TicketRecorder
from core.wallet import WeeklyWalletManager
from integrations.common.models import TaiwanLeg
from ui.ticket_submission import readiness, recommendation_fingerprint, record_recommendation


def item():
    now = datetime.now(timezone.utc)
    leg = TaiwanLeg(event_id="ui-event", canonical_event_id="canonical-ui-event", sport="baseball", league="MLB",
                    away_team="洋基", home_team="紅襪",
                    market="大小", selection="大 8.5", side="大", line="8.5", taiwan_odds=2,
                    start_time_utc=(now + timedelta(hours=1)).isoformat(), odds_scraped_at=now.isoformat(),
                    odds_status="LIVE", signal_evidence={"source_url": "https://example.test/odds", "probability_status": "MARKET_BASELINE_ONLY"})
    return {"legs": [leg.to_dict()], "total_odds": 2, "parlay_name": "1 串 1"}


def test_retry_after_snapshot_failure_debits_only_once_and_preserves_evidence(tmp_path):
    wallet = WeeklyWalletManager(tmp_path / "wallet.db")
    wallet.deposit_external(200)
    recorder = TicketRecorder(wallet)
    ticket = item()
    key = recommendation_fingerprint(ticket, 20, 2)

    class FailedLog:
        def log_snapshot(self, leg):
            raise OSError("disk unavailable")

    first, warnings = record_recommendation(recorder, FailedLog(), ticket, 20, 2, key)
    assert len(warnings) == 1
    logger = PredictionSnapshotLogger(tmp_path / "research.jsonl")
    second, warnings = record_recommendation(recorder, logger, ticket, 20, 2, key)
    assert second["ticket_id"] == first["ticket_id"]
    assert not warnings
    assert wallet.get_status()["weekly_staked"] == 20
    snap = logger.get_all_snapshots()[0]
    assert snap["event_start"] == ticket["legs"][0]["start_time_utc"]
    assert snap["odds_timestamp"] == ticket["legs"][0]["odds_scraped_at"]
    assert snap["line"] == "8.5"
    assert recorder.list_tickets()[0]["entry_mode"] == "recommendation"


def test_stale_recommendation_is_disabled_and_rejected(tmp_path):
    ticket = item()
    ticket["legs"][0]["odds_status"] = "STALE_CACHE"
    assert readiness(ticket)["is_ready"] is False
    wallet = WeeklyWalletManager(tmp_path / "wallet.db")
    wallet.deposit_external(200)
    with pytest.raises(ValueError, match="盤口"):
        record_recommendation(TicketRecorder(wallet), object(), ticket, 20, 2, "stale")
    assert wallet.get_status()["weekly_staked"] == 0


@pytest.mark.parametrize("balance", [0, 5, 200])
def test_app_renders_small_balances_without_live_calls_or_invalid_widgets(tmp_path, monkeypatch, balance):
    import streamlit as st
    import core.wallet as wallet_module
    import core.ticket_recorder as recorder_module
    import core.signal_hub as hub_module
    import core.season_radar as radar_module
    import core.snapshot_logger as snapshot_module
    import core.shadow_portfolio as shadow_module
    import integrations.odds.playsport_taiwan_odds as odds_module

    wallet = WeeklyWalletManager(tmp_path / "ui.db")
    if balance:
        wallet.deposit_external(balance)
    recorder = TicketRecorder(wallet)
    monkeypatch.setattr(wallet_module, "WeeklyWalletManager", lambda: wallet)
    monkeypatch.setattr(recorder_module, "TicketRecorder", lambda wallet: recorder)
    monkeypatch.setattr(odds_module, "PlaysportOddsAdapter", lambda: SimpleNamespace(
        get_taiwan_legs=lambda *a, **kw: [], get_source_status=lambda: {}))
    monkeypatch.setattr(hub_module, "SignalHub", lambda: SimpleNamespace(
        model_registry=SimpleNamespace(get_registered_models_summary=lambda: []),
        expert_adapter=SimpleNamespace(get_source_status=lambda: {})))
    monkeypatch.setattr(radar_module, "SeasonRadar", lambda: SimpleNamespace(get_radar_summary=lambda **kw: []))
    monkeypatch.setattr(snapshot_module, "PredictionSnapshotLogger", lambda: PredictionSnapshotLogger(tmp_path / "snapshots.jsonl"))
    original_shadow = shadow_module.ShadowPortfolioManager
    monkeypatch.setattr(shadow_module, "ShadowPortfolioManager", lambda: original_shadow(db_path=tmp_path / "shadow.db"))
    st.cache_resource.clear()
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
    assert not app.exception
    stake_widget = next(widget for widget in app.number_input if "本張注金" in widget.label)
    assert stake_widget.disabled is (balance < 10)
    st.cache_resource.clear()
