"""Public result-source adapters used by automatic settlement.

Adapters only normalize source facts. They do not infer a score, completion
state, team identity, or betting rule when the source omits it.
"""

from .espn import ESPNResultProvider, parse_espn_event
from .models import ResultGame
from .official_asian_baseball import OfficialAsianBaseballProvider, parse_kbo_scoreboard, parse_npb_scoreboard
from .cpbl import CPBLResultProvider, parse_cpbl_game_page, parse_cpbl_schedule_page

__all__ = [
    "ESPNResultProvider", "OfficialAsianBaseballProvider", "ResultGame",
    "parse_espn_event", "parse_kbo_scoreboard", "parse_npb_scoreboard",
    "CPBLResultProvider", "parse_cpbl_game_page", "parse_cpbl_schedule_page",
]
