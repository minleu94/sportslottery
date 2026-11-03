"""Composition helpers for the legacy market pipeline's default providers.

Application code can inject provider adapters directly. The compatibility
``MarketForwardPipeline()`` entry point uses this factory only when a provider
was omitted, keeping concrete provider construction out of the orchestration
module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from integrations.odds.the_odds_api import SPORT_KEY_MAP


@dataclass(frozen=True)
class MarketProviderCapabilities:
    """Provider-facing league keys and preferred labels needed for query planning."""

    sport_key_map: Mapping[str, str]
    preferred_league_labels: Mapping[str, str]


DEFAULT_MARKET_PROVIDER_CAPABILITIES = MarketProviderCapabilities(
    sport_key_map=SPORT_KEY_MAP,
    preferred_league_labels={
        "baseball_mlb": "MLB",
        "basketball_nba": "NBA",
        "americanfootball_nfl": "NFL",
        "soccer_epl": "EPL",
        "soccer_spain_la_liga": "LALIGA",
        "soccer_uefa_champs_league": "CHAMPIONS_LEAGUE",
        "soccer_germany_bundesliga": "BUNDESLIGA",
        "soccer_italy_serie_a": "SERIE_A",
    },
)


def build_default_market_providers(*, taiwan: bool, international: bool):
    """Construct only the omitted legacy provider at the composition boundary."""
    taiwan_provider = None
    international_provider = None
    if taiwan:
        from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter

        taiwan_provider = PlaysportOddsAdapter()
    if international:
        from integrations.odds.the_odds_api import TheOddsApiClient

        international_provider = TheOddsApiClient()
    return taiwan_provider, international_provider
