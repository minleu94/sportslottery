from integrations.models.espn_poisson_soccer import ESPNPoissonSoccerFallback


def test_soccer_fallback_accepts_exact_canonical_names_and_rejects_generic_labels():
    resolve=lambda name:ESPNPoissonSoccerFallback._resolve_league_code(None,name)
    assert resolve("PREMIER")=="eng.1"
    assert resolve("CHAMPIONS")=="uefa.champions"
    assert resolve("LALIGA")=="esp.1"
    assert resolve("英超")=="eng.1"
    assert resolve("足球") is None
    assert resolve("UNKNOWN_美國足球大聯盟") is None
    assert resolve("UNKNOWN_英超相似聯賽") is None
    assert resolve("MLS") == "usa.1"
