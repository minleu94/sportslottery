"""Fetch official MLB final scores and update the local experimental Elo state.

This command performs read-only GET requests to the MLB Stats API. It does not
place wagers or edit historical prediction/ticket records.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from integrations.models.external.live_mlb_elo import LiveMLBEloAdapter, STATE_FILE

API_BASE = "https://statsapi.mlb.com/api/v1/schedule"
SOURCE = "MLB Stats API (statsapi.mlb.com)"


class MLBStatsApiClient:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def fetch_games(self, start_date: date, end_date: date) -> list[Dict[str, Any]]:
        params = urlencode({"sportId": 1, "startDate": start_date.isoformat(),
                            "endDate": end_date.isoformat(), "hydrate": "linescore"})
        request = Request(f"{API_BASE}?{params}", headers={"Accept": "application/json", "User-Agent": "sportslottery-research/1.0"})
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        games = []
        for day in payload.get("dates", []):
            games.extend(day.get("games", []))
        return games

    def fetch_live_game(self, game_pk: str | int) -> Dict[str, Any]:
        """Fetch the authoritative live feed for one postponed MLB gamePk.

        The raw response body hash and observation metadata are retained so a
        reconciled result can be audited without changing the schedule stub.
        """
        import hashlib
        url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "sportslottery-research/1.0"})
        with urlopen(request, timeout=self.timeout) as response:
            raw = response.read()
        payload = json.loads(raw.decode("utf-8"))
        return {
            "payload": payload,
            "source_url": url,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }


def update_mlb_elo(start_date: date, end_date: date, *, state_file: Path = STATE_FILE,
                   client: Optional[Any] = None) -> Dict[str, Any]:
    if end_date < start_date:
        raise ValueError("end_date 不可早於 start_date。")
    api = client or MLBStatsApiClient()
    games = api.fetch_games(start_date, end_date)
    adapter = LiveMLBEloAdapter(state_file=state_file)
    return adapter.apply_official_games(games, source=SOURCE)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Update experimental MLB Elo from official final game results.")
    parser.add_argument("--start-date", type=date.fromisoformat, required=True, help="First MLB schedule date (YYYY-MM-DD).")
    parser.add_argument("--end-date", type=date.fromisoformat, help="Last schedule date; defaults to today in UTC.")
    parser.add_argument("--state-file", type=Path, default=STATE_FILE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    result = update_mlb_elo(args.start_date, args.end_date or datetime.now(timezone.utc).date(), state_file=args.state_file)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
