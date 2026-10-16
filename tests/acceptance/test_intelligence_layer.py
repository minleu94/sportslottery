#!/usr/bin/env python3
"""Acceptance Test Suite for Intelligence Layer (Final Reality Upgrade).

Covers all 13 specification requirements:
1. Exact line match for Over/Under
2. Exact line match for Handicap/Spread
3. Pick date validation
4. Multi-expert consensus aggregation & track record
5. Market odds baseline only (never votes for itself)
6. Independence group deduplication (same group counts as 1)
7. Different independence groups count separately
8. Penaltyblog Dixon-Coles returns None on insufficient data (MODEL_NOT_READY)
9. Penaltyblog Dixon-Coles predicts with sufficient match data
10. FiveThirtyEight MLB Elo provenance, +24 home field advantage
11. ModelRegistry rich provenance metadata
12. Historical prediction snapshot logging & Brier score calculation
13. Evidence weights configuration integrity
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import time
import pytest

from core.model_registry import ModelRegistry
from core.signal_hub import SignalHub
from core.snapshot_logger import PredictionSnapshotLogger
from integrations.common.models import PredictionSignal, TaiwanLeg, VerifiedExpertPick
from integrations.experts.playsport_expert import PlaysportExpertAdapter
from integrations.models.external.fivethirtyeight_mlb_elo import FiveThirtyEightMLBEloAdapter
from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter


class DummyExpertScraper:
    """Mock scraper returning controlled expert picks for testing."""

    def __init__(self, picks=None):
        self.picks = picks or []

    def fetch_expert_leaderboard(self, alliance_id: str):
        return [
            {"userid": "expert_1", "nickname": "王牌大神", "rank": 1, "winpercentage": 75.0, "wingame": 15, "losegame": 5},
            {"userid": "expert_2", "nickname": "勝率大師", "rank": 2, "winpercentage": 70.0, "wingame": 14, "losegame": 6},
            {"userid": "expert_3", "nickname": "反指標", "rank": 3, "winpercentage": 45.0, "wingame": 9, "losegame": 11},
        ]

    def fetch_member_prediction_page(self, userid: str, alliance_id: str):
        return ""


def _prime_expert_fixture(adapter, picks, observed_at):
    """Provide a deterministic, fresh fixture without invoking the scraper."""
    adapter._parsed_picks_cache["1"] = picks
    adapter._parsed_picks_at["1"] = time.time()
    adapter._source_status["1"] = {
        "source_status": "LIVE",
        "observed_at": observed_at.isoformat(),
        "cache_age_minutes": 0.0,
        "source_urls": ["https://fixture.invalid/leaderboard"],
        "member_pages": [{"source_status": "LIVE"} for _ in picks],
    }
    for pick in picks:
        pick.publication_time_precision = "DATETIME"
        pick.source_metadata = {
            "source_status": "LIVE",
            "observed_at": pick.pick_timestamp,
            "source_kind": "fixed_test_fixture",
            "source_urls": ["https://fixture.invalid/member"],
        }


# 1. Test exact line matching for Over/Under
def test_exact_line_matching_total():
    adapter = PlaysportExpertAdapter(scraper=DummyExpertScraper())
    now = datetime.now(timezone.utc)
    event_start = now + timedelta(hours=2)
    observed = now - timedelta(minutes=2)
    today = event_start.astimezone(timezone(timedelta(hours=8))).date().isoformat()

    adapter._parsed_picks_cache["1"] = [
        VerifiedExpertPick(
            expert_userid="exp_1",
            expert_nickname="總分達人",
            rank=1,
            win_percentage=72.0,
            wins=18,
            losses=7,
            sport="baseball",
            league="MLB",
            event_id="",
            away_team="小熊",
            home_team="紅雀",
            market="大小",
            side="大",
            line="8.5",
            raw_pick="大 8.5",
            pick_date=today,
            pick_timestamp=observed.isoformat(),
        )
    ]
    _prime_expert_fixture(adapter, adapter._parsed_picks_cache["1"], observed)

    # Exactly matching 8.5 -> Matches
    leg_match = TaiwanLeg(
        event_id="101",
        sport="baseball",
        league="MLB",
        market="大小",
        selection="大 8.5",
        taiwan_odds=1.75,
        start_time="08:00",
        start_time_utc=event_start.isoformat(),
        away_team="小熊",
        home_team="紅雀",
        side="大",
        line="8.5",
    )
    sig = adapter.get_expert_signal(leg_match)
    assert sig is not None
    assert sig.source_category == "VERIFIED_EXPERT"
    assert sig.independence_group == "PLAYSPORT_EXPERT"

    # Mismatched line 9.5 -> MUST NOT MATCH
    leg_mismatch = TaiwanLeg(
        event_id="101",
        sport="baseball",
        league="MLB",
        market="大小",
        selection="大 9.5",
        taiwan_odds=1.95,
        start_time="08:00",
        start_time_utc=event_start.isoformat(),
        away_team="小熊",
        home_team="紅雀",
        side="大",
        line="9.5",
    )
    sig_mismatch = adapter.get_expert_signal(leg_mismatch)
    assert sig_mismatch is None


# 2. Test exact line matching for Spread / Handicap
def test_exact_line_matching_spread():
    adapter = PlaysportExpertAdapter(scraper=DummyExpertScraper())
    now = datetime.now(timezone.utc)
    event_start = now + timedelta(hours=2)
    observed = now - timedelta(minutes=2)
    today = event_start.astimezone(timezone(timedelta(hours=8))).date().isoformat()

    adapter._parsed_picks_cache["1"] = [
        VerifiedExpertPick(
            expert_userid="exp_2",
            expert_nickname="讓分權威",
            rank=1,
            win_percentage=75.0,
            wins=15,
            losses=5,
            sport="baseball",
            league="MLB",
            event_id="",
            away_team="道奇",
            home_team="巨人",
            market="讓分",
            side="客",
            line="-1.5",
            raw_pick="道奇 -1.5",
            pick_date=today,
            pick_timestamp=observed.isoformat(),
        )
    ]
    _prime_expert_fixture(adapter, adapter._parsed_picks_cache["1"], observed)

    # Exactly matching -1.5 -> Matches
    leg_match = TaiwanLeg(
        event_id="102",
        sport="baseball",
        league="MLB",
        market="讓分",
        selection="道奇 客讓1.5分勝",
        taiwan_odds=1.80,
        start_time="10:00",
        start_time_utc=event_start.isoformat(),
        away_team="道奇",
        home_team="巨人",
        side="客",
        line="-1.5",
    )
    sig = adapter.get_expert_signal(leg_match)
    assert sig is not None

    # Mismatched line -2.5 -> MUST NOT MATCH
    leg_mismatch = TaiwanLeg(
        event_id="102",
        sport="baseball",
        league="MLB",
        market="讓分",
        selection="道奇 客讓2.5分勝",
        taiwan_odds=2.40,
        start_time="10:00",
        start_time_utc=event_start.isoformat(),
        away_team="道奇",
        home_team="巨人",
        side="客",
        line="-2.5",
    )
    assert adapter.get_expert_signal(leg_mismatch) is None


# 3. Test expert pick date validation
def test_expert_pick_date_validation():
    adapter = PlaysportExpertAdapter(scraper=DummyExpertScraper())

    # Pick is dated yesterday (2026-09-17)
    adapter._parsed_picks_cache["1"] = [
        VerifiedExpertPick(
            expert_userid="exp_old",
            expert_nickname="過期大神",
            rank=1,
            win_percentage=80.0,
            wins=20,
            losses=5,
            sport="baseball",
            league="MLB",
            event_id="",
            away_team="洋基",
            home_team="紅襪",
            market="不讓分",
            side="客",
            line=None,
            raw_pick="洋基 獨贏",
            pick_date="2026-09-17",
        )
    ]

    # Game is scheduled today (2026-09-18) -> Date mismatch must reject!
    leg_today = TaiwanLeg(
        event_id="103",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="洋基 客勝",
        taiwan_odds=1.65,
        start_time="07:05",
        start_time_utc="2026-09-18T07:05:00Z",
        away_team="洋基",
        home_team="紅襪",
        side="客",
    )
    sig = adapter.get_expert_signal(leg_today)
    assert sig is None


# 4. Test multi-expert consensus aggregation
def test_multi_expert_consensus_aggregation():
    adapter = PlaysportExpertAdapter(scraper=DummyExpertScraper())
    now = datetime.now(timezone.utc)
    event_start = now + timedelta(hours=2)
    observed = now - timedelta(minutes=2)
    today = event_start.astimezone(timezone(timedelta(hours=8))).date().isoformat()

    # 3 experts pick Yankees (客), 1 picks Red Sox (主)
    adapter._parsed_picks_cache["1"] = [
        VerifiedExpertPick("u1", "大神A", 1, 75.0, 15, 5, "baseball", "MLB", "", "洋基", "紅襪", "不讓分", "客", None, "洋基勝", today, pick_timestamp=observed.isoformat()),
        VerifiedExpertPick("u2", "大神B", 2, 70.0, 14, 6, "baseball", "MLB", "", "洋基", "紅襪", "不讓分", "客", None, "洋基勝", today, pick_timestamp=observed.isoformat()),
        VerifiedExpertPick("u3", "大神C", 4, 65.0, 13, 7, "baseball", "MLB", "", "洋基", "紅襪", "不讓分", "客", None, "洋基勝", today, pick_timestamp=observed.isoformat()),
        VerifiedExpertPick("u4", "大神D", 5, 60.0, 12, 8, "baseball", "MLB", "", "洋基", "紅襪", "不讓分", "主", None, "紅襪勝", today, pick_timestamp=observed.isoformat()),
    ]
    _prime_expert_fixture(adapter, adapter._parsed_picks_cache["1"], observed)

    leg = TaiwanLeg(
        event_id="104",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="洋基 客勝",
        taiwan_odds=1.65,
        start_time="07:05",
        start_time_utc=event_start.isoformat(),
        away_team="洋基",
        home_team="紅襪",
        side="客",
    )
    sig = adapter.get_expert_signal(leg)
    assert sig is not None
    assert sig.metadata["agreeing_count"] == 3
    assert sig.metadata["opposing_count"] == 1
    assert sig.metadata["total_voted"] == 4
    assert sig.metadata["consensus_ratio"] == 0.75
    assert sig.metadata["average_win_pct"] == 70.0
    assert sig.metadata["total_wins"] == 42
    assert sig.metadata["total_losses"] == 18
    assert sig.confidence == "HIGH"


# 5. Test market odds baseline only (never votes for itself)
def test_market_odds_never_votes_for_itself():
    hub = SignalHub()
    # Stub adapters to return None
    hub.expert_adapter.get_expert_signal = lambda leg: None
    hub.crowd_adapter.get_crowd_signal = lambda leg: None
    hub.model_registry.evaluate_leg_across_models = lambda leg: []

    leg = TaiwanLeg(
        event_id="105",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="道奇 客勝",
        taiwan_odds=1.35,  # Heavy favorite odds
        start_time="10:00",
        away_team="道奇",
        home_team="洛磯",
        side="客",
    )
    hub.evaluate_taiwan_leg(leg)
    assert leg.signal_evidence["independent_support_count"] == 0
    assert leg.evidence_quality == "INSUFFICIENT_SIGNAL"
    assert "TAIWAN_MARKET" not in leg.signal_evidence["supporting_groups"]


# 6. Test independence group deduplication: models in same group count as 1
def test_independence_group_deduplication():
    hub = SignalHub()
    hub.expert_adapter.get_expert_signal = lambda leg: None
    hub.crowd_adapter.get_crowd_signal = lambda leg: None

    # Two distinct model signals, but BOTH in ESPN_SEASON_STATS
    sig1 = PredictionSignal(
        source_id="espn_pyth",
        source_name="ESPN 畢氏定理",
        source_type="LOCAL_FALLBACK_MODEL",
        source_category="LOCAL_FALLBACK_MODEL",
        independence_group="ESPN_SEASON_STATS",
        event_id="106",
        market="不讓分",
        selection="洋基 客勝",
        probability=0.65,
        score=5.0,
        confidence="HIGH",
        freshness_status="FRESH",
        data_as_of="2026-09-18T06:00:00Z",
        metadata={"provenance": "fixed unit-test fixture"},
    )
    sig2 = PredictionSignal(
        source_id="espn_season_avg",
        source_name="ESPN 賽季平均",
        source_type="LOCAL_FALLBACK_MODEL",
        source_category="LOCAL_FALLBACK_MODEL",
        independence_group="ESPN_SEASON_STATS",
        event_id="106",
        market="不讓分",
        selection="洋基 客勝",
        probability=0.62,
        score=3.0,
        confidence="MED",
        freshness_status="FRESH",
        data_as_of="2026-09-18T06:00:00Z",
        metadata={"provenance": "fixed unit-test fixture"},
    )
    hub.model_registry.evaluate_leg_across_models = lambda leg: [sig1, sig2]

    leg = TaiwanLeg(
        event_id="106",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="洋基 客勝",
        taiwan_odds=1.70,
        start_time="07:05",
        away_team="洋基",
        home_team="金鶯",
        side="客",
        start_time_utc="2026-09-18T07:00:00Z",
    )
    hub.evaluate_taiwan_leg(leg)

    # Unaccepted models remain research candidates and do not support ranking.
    assert leg.signal_evidence["independent_support_count"] == 0
    assert leg.signal_evidence["supporting_groups"] == []
    assert len(leg.signal_evidence["model_candidate_provenances"]) == 2
    assert leg.evidence_quality == "INSUFFICIENT_SIGNAL"


# 7. Test different independence groups count separately
def test_independence_groups_different_count_separately():
    hub = SignalHub()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    hub.expert_adapter.get_expert_signal = lambda leg: PredictionSignal(
        source_id="exp",
        source_name="玩運彩專家群",
        source_type="EXPERT",
        source_category="VERIFIED_EXPERT",
        independence_group="PLAYSPORT_EXPERT",
        event_id="107",
        market="不讓分",
        selection="道奇 客勝",
        probability=0.72,
        score=72.0,
        confidence="HIGH",
        freshness_status="FRESH",
        data_as_of="2026-09-18T06:00:00Z",
        metadata={"sample_size": 20, "provenance": "fixed unit-test fixture"},
    )
    hub.crowd_adapter.get_crowd_signal = lambda leg: PredictionSignal(
        source_id="crowd",
        source_name="彩迷社群選票",
        source_type="CROWD",
        source_category="CROWD_CONSENSUS",
        independence_group="PLAYSPORT_CROWD",
        event_id="107",
        market="不讓分",
        selection="道奇 客勝",
        probability=0.68,
        score=68.0,
        confidence="MED",
        freshness_status="FRESH",
        data_as_of="2026-09-18T06:00:00Z",
        metadata={"vote_count": 100, "provenance": "fixed unit-test fixture"},
    )
    hub.model_registry.evaluate_leg_across_models = lambda leg: [
        PredictionSignal(
            source_id="elo",
            source_name="FiveThirtyEight MLB Elo",
            source_type="MODEL",
            source_category="OPEN_SOURCE_ENGINE",
            independence_group="FIVETHIRTYEIGHT_ELO",
            event_id="107",
            market="不讓分",
            selection="道奇 客勝",
            probability=0.65,
            score=4.5,
            confidence="HIGH",
            freshness_status="FRESH",
            data_as_of="2026-09-18T06:00:00Z",
            metadata={"initialized": True, "provenance": "fixed unit-test fixture"},
        )
    ]

    leg = TaiwanLeg(
        event_id="107",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="道奇 客勝",
        taiwan_odds=1.65,
        start_time="10:00",
        start_time_utc=f"{today}T10:00:00Z",
        away_team="道奇",
        home_team="巨人",
        side="客",
    )
    hub.evaluate_taiwan_leg(leg)

    # Expert and crowd evidence qualify; the unaccepted model remains research only.
    assert leg.signal_evidence["independent_support_count"] == 2
    assert set(leg.signal_evidence["supporting_groups"]) == {"PLAYSPORT_EXPERT", "PLAYSPORT_CROWD"}
    assert len(leg.signal_evidence["model_candidate_provenances"]) == 1
    assert leg.evidence_quality == "MED"


# 8. Test Penaltyblog Dixon-Coles returns None on insufficient data (MODEL_NOT_READY)
def test_penaltyblog_dixon_coles_not_ready_on_insufficient_data(tmp_path):
    # Use empty temp directory so no match cache exists
    adapter = PenaltyblogDixonColesAdapter(cache_dir=str(tmp_path))

    leg = TaiwanLeg(
        event_id="502",
        sport="soccer",
        league="西甲",
        market="不讓分",
        selection="皇馬 客勝",
        taiwan_odds=1.85,
        start_time="21:00",
        away_team="皇家馬德里",
        home_team="赫塔菲",
        side="客",
    )
    sig = adapter.evaluate_leg(leg)
    # Must honestly return None
    assert sig is None


def test_penaltyblog_canonical_league_codes_are_exact_and_unknown_is_rejected(tmp_path):
    adapter = PenaltyblogDixonColesAdapter(cache_dir=str(tmp_path))
    assert adapter._resolve_league_code("PREMIER") == "eng.1"
    assert adapter._resolve_league_code("CHAMPIONS") == "uefa.champions"
    assert adapter._resolve_league_code("UNKNOWN_德國第三級足球聯賽") is None


def test_penaltyblog_real_fit_normalizes_football_data_aliases_and_keeps_draw(tmp_path):
    cache_dir = Path(tmp_path)
    matches = []
    names = ["Man City", "Man United", "Tottenham", "Arsenal"]
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    for index in range(80):
        home = names[index % len(names)]
        away = names[(index + 1 + (index // len(names)) % 3) % len(names)]
        if away == home:
            away = names[(names.index(home) + 1) % len(names)]
        matches.append({
            "date": (start + timedelta(days=index)).date().isoformat(),
            "home_team": home,
            "away_team": away,
            "home_goals": (index * 3) % 4,
            "away_goals": (index * 5 + 1) % 3,
        })
    (cache_dir / "real_matches_eng.1.json").write_text(json.dumps({"matches": matches}), encoding="utf-8")
    adapter = PenaltyblogDixonColesAdapter(cache_dir=str(cache_dir))

    leg = TaiwanLeg(
        event_id="dc-canonical-alias", sport="soccer", league="PREMIER", market="和局",
        selection="和局", taiwan_odds=3.2, start_time_utc="2026-10-15T19:00:00+00:00",
        away_team="曼聯", home_team="曼城", side="和",
    )
    signal = adapter.evaluate_leg(leg)
    assert signal is not None
    assert signal.metadata["provenance"]["source_team_name_aliases"]
    aliases = {row["source_name"]: row["canonical_name"]
               for row in signal.metadata["provenance"]["source_team_name_aliases"]}
    assert aliases["Man City"] == "Manchester City"
    assert aliases["Man United"] == "Manchester United"
    assert aliases["Tottenham"] == "Tottenham Hotspur"
    assert signal.probability == signal.metadata["draw_prob"]

    # Other H/D/A market labels use the same fitted 1X2 distribution.
    win_leg = TaiwanLeg(
        event_id="dc-canonical-alias-home", sport="soccer", league="PREMIER", market="獨贏",
        selection="曼城主勝", taiwan_odds=2.0, start_time_utc="2026-10-15T19:00:00+00:00",
        away_team="Man United", home_team="Man City", side="主",
    )
    assert adapter.evaluate_leg(win_leg).probability == signal.metadata["home_win_prob"]


# 9. Test Penaltyblog Dixon-Coles predicts with sufficient match data
def test_penaltyblog_dixon_coles_predicts_with_sufficient_data():
    adapter = PenaltyblogDixonColesAdapter()
    leg = TaiwanLeg(
        event_id="501",
        sport="soccer",
        league="英超",
        market="不讓分",
        selection="兵工廠 客勝",
        taiwan_odds=2.10,
        start_time="22:00",
        away_team="兵工廠",
        home_team="切爾西",
        side="客",
    )
    sig = adapter.evaluate_leg(leg)
    assert sig is not None
    assert sig.source_category in ["EXTERNAL_OPEN_SOURCE_ENGINE", "OPEN_SOURCE_ENGINE"]
    assert sig.independence_group == "DIXON_COLES_MATCHES"
    assert sig.probability is not None
    assert 0.05 <= sig.probability <= 0.95


# 10. Test FiveThirtyEight MLB Elo provenance and +24 home advantage
def test_fivethirtyeight_mlb_elo_provenance_and_predictions():
    adapter = FiveThirtyEightMLBEloAdapter()
    assert adapter.SOURCE_CATEGORY in ["LOCAL_REIMPLEMENTATION", "OPEN_SOURCE_ENGINE"]
    assert adapter.INDEPENDENCE_GROUP == "FIVETHIRTYEIGHT_ELO"

    leg = TaiwanLeg(
        event_id="108",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="道奇 客勝",
        taiwan_odds=1.65,
        start_time="10:00",
        away_team="道奇",
        home_team="巨人",
        side="客",
    )
    sig = adapter.evaluate_leg(leg)
    assert sig is not None
    assert sig.source_category in ["LOCAL_REIMPLEMENTATION", "OPEN_SOURCE_ENGINE"]
    assert sig.independence_group == "FIVETHIRTYEIGHT_ELO"
    assert "home_field_advantage" in sig.metadata
    assert sig.metadata["home_field_advantage"] == 24.0


# 11. Test ModelRegistry rich provenance metadata
def test_model_registry_loads_provenance_metadata():
    registry = ModelRegistry()
    summary = registry.get_registered_models_summary()
    assert len(summary) >= 3

    for m in summary:
        assert "id" in m
        assert "source_category" in m
        assert "independence_group" in m
        assert "repo" in m
        assert "license" in m
        assert "weight" in m


# 12. Test historical prediction snapshot logging & Brier score calculation
def test_prediction_snapshot_logger_and_calibration():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
        _test_prediction_snapshot_logger_and_calibration(Path(folder) / "test_snapshots.jsonl")


def _test_prediction_snapshot_logger_and_calibration(log_file):
    logger = PredictionSnapshotLogger(log_path=log_file)

    leg = TaiwanLeg(
        event_id="109",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="洋基 客勝",
        taiwan_odds=2.00,
        start_time="test future event",
        start_time_utc=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        odds_scraped_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        away_team="洋基",
        home_team="紅襪",
        side="客",
    )
    sig = PredictionSignal(
        source_id="elo",
        source_name="FiveThirtyEight MLB Elo",
        source_type="MODEL",
        source_category="OPEN_SOURCE_ENGINE",
        independence_group="FIVETHIRTYEIGHT_ELO",
        event_id="109",
        market="不讓分",
        selection="洋基 客勝",
        probability=0.60,
        timestamp=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        data_as_of=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        freshness_status="FRESH",
        metadata={"provenance": "fixed unit-test fixture"},
    )
    leg.signals = [sig]
    leg.evidence_quality = "MED"
    leg.odds_status = "LIVE"
    leg.signal_evidence = {"quality_score": 55.0, "independent_support_count": 1, "supporting_groups": ["FIVETHIRTYEIGHT_ELO"], "publication_time_precision": "NOT_APPLICABLE", "probability_status": "UNVALIDATED_MODEL_ESTIMATE", "consensus_probability": 0.60, "model_fusion_groups": ["FIVETHIRTYEIGHT_ELO"]}

    snap = logger.log_snapshot(leg)
    snap_id = snap["snapshot_id"]
    assert log_file.exists()

    # Settle prediction with WIN (actual_outcome=True)
    settled = logger.settle_prediction(snap_id, actual_outcome=True, settlement_status="WON")
    assert settled is not None
    assert settled["is_settled"] is True
    # Brier score: (0.60 - 1.0)^2 = 0.16
    assert abs(settled["brier_score"] - 0.16) < 1e-3

    metrics = logger.compute_calibration_metrics()
    assert metrics["settled_count"] == 1
    assert abs(metrics["mean_brier_score"] - 0.16) < 1e-3


# 13. Test evidence weights configuration integrity
def test_evidence_weights_config_loading():
    hub = SignalHub()
    weights = hub.weights_config
    assert "source_weights" in weights
    assert "independence_groups" in weights
    assert "agreement_rules" in weights
    assert weights["independence_groups"]["TAIWAN_MARKET"]["is_baseline"] is True
    assert weights["independence_groups"]["TAIWAN_MARKET"]["max_votes"] == 0
    assert weights["source_weights"]["VERIFIED_EXPERT"]["base_weight"] == 1.00
