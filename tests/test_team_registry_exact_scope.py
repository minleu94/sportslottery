from core.identity.team_alias import CanonicalTeam,TeamRegistry


def test_nba_scope_does_not_accept_wnba_substring():
    sun=CanonicalTeam("WNBA_CT","basketball","WNBA","CT","Connecticut Sun","康乃狄克太陽","太陽",[])
    registry=TeamRegistry(teams=[sun])
    assert registry.resolve("Connecticut Sun",sport="basketball",league="WNBA").canonical_id=="WNBA_CT"
    assert registry.resolve("Connecticut Sun",sport="basketball",league="NBA") is None
