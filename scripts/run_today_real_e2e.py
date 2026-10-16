#!/usr/bin/env python3
"""Run Today Real End-to-End Live Pipeline.

Strictly real production data:
Taiwan markets -> Crowd -> Verified Experts -> Models -> Freshness -> Signal Hub -> 10~500x Parlay
"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.parlay_engine import ParlayEngine
from core.scraper import PlaysportScraper
from core.signal_hub import SignalHub
from integrations.experts.playsport_crowd import PlaysportCrowdAdapter
from integrations.experts.playsport_expert import PlaysportExpertAdapter
from integrations.models.external.fivethirtyeight_mlb_elo import FiveThirtyEightMLBEloAdapter
from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_e2e():
    scraper = PlaysportScraper()
    odds_adapter = PlaysportOddsAdapter(scraper=scraper)
    expert_adapter = PlaysportExpertAdapter(scraper=scraper)
    crowd_adapter = PlaysportCrowdAdapter()
    dixon_adapter = PenaltyblogDixonColesAdapter()
    elo_adapter = FiveThirtyEightMLBEloAdapter()

    hub = SignalHub(
        expert_adapter=expert_adapter,
        crowd_adapter=crowd_adapter,
    )
    engine = ParlayEngine()

    print("Fetching today's live Taiwan legs across leagues...")
    raw_legs = odds_adapter.get_taiwan_legs(["1", "4", "93", "6", "2", "7"])
    print(f"Total Taiwan legs retrieved: {len(raw_legs)}")

    enriched_legs = []
    for leg in raw_legs:
        # Evaluate with signal hub
        el = hub.evaluate_taiwan_leg(leg)
        enriched_legs.append(el)

    print(f"Enriched {len(enriched_legs)} legs with Signal Hub evidence.")

    # Show live sample legs (Requirement 25)
    print("\n=======================================================")
    print("LIVE EXAMPLE LEGS AUDIT (REAL TODAY DATA)")
    print("=======================================================")
    for leg in enriched_legs[:4]:
        sig_ev = leg.signal_evidence
        print(f"\n[Leg] {leg.league} | Event #{leg.event_id} | {leg.away_team} vs {leg.home_team}")
        print(f"  Market: {leg.market} | Selection: {leg.selection} | Odds: {leg.taiwan_odds:.2f}")
        print(f"  Odds Scraped At: {leg.odds_scraped_at} | Status: {leg.odds_status} (Age: {leg.odds_age_minutes:.1f}m)")
        print(f"  Crowd Consensus: {sig_ev.get('crowd_desc', 'N/A')} (Timestamp: {sig_ev.get('crowd_snapshot_timestamp', 'N/A')})")
        print(f"  Expert Pick: {sig_ev.get('expert_desc', 'N/A')}")
        models_desc = "; ".join(sig_ev.get("models_desc", [])) or "None"
        print(f"  External Model: {models_desc}")
        if sig_ev.get("model_provenances"):
            p = sig_ev["model_provenances"][0]
            print(f"  Model Data As Of: {p.get('latest_match_date', 'N/A')} | Freshness: {p.get('freshness_status', 'N/A')}")
        if sig_ev.get("model_market_delta_pp") is not None:
            print(f"  Delta pp: {sig_ev.get('model_market_delta_pp'):+.1f} pp (Model {int(sig_ev.get('model_probability', 0)*100)}% vs Implied {int(sig_ev.get('market_implied_probability', 0)*100)}%)")
        print(f"  Evidence Quality Badge: {sig_ev.get('agreement_badge', 'N/A')} (Score: {sig_ev.get('quality_score', 0.0)})")

    # Count candidates across ranges (Requirement 26)
    ranges = [
        ("10x ~ 25x (穩健防守)", 10.0, 25.0),
        ("25x ~ 75x (狂犬推進)", 25.0, 75.0),
        ("75x ~ 200x (瘋狗進攻)", 75.0, 200.0),
        ("200x ~ 500x (極限 Moonshot)", 200.0, 500.0),
    ]

    print("\n=======================================================")
    print("REAL CANDIDATE COUNTS PER ODDS RANGE (TODAY)")
    print("=======================================================")
    range_summary = {}
    for name, min_o, max_o in ranges:
        res = engine.search_parlays(
            legs=enriched_legs,
            min_odds=min_o,
            max_odds=max_o,
            signal_filter="wild",
            min_legs=2,
            max_legs=6,
        )
        hc = len(res["high_consensus"])
        ag = len(res["aggressive"])
        ms = len(res["moonshot"])
        tot = hc + ag + ms
        range_summary[name] = {"HIGH": hc, "AGGRESSIVE": ag, "MOONSHOT": ms, "TOTAL": tot}
        print(f"{name:<28}: HIGH={hc} | AGGRESSIVE={ag} | MOONSHOT={ms} | TOTAL={tot}")

    out_file = PROJECT_ROOT / "data" / "cache" / "today_e2e_summary.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(range_summary, f, indent=2)
    print(f"\nSaved today's E2E summary to {out_file}")


if __name__ == "__main__":
    run_e2e()
