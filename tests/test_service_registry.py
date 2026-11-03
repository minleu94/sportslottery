from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from server import service_registry


@pytest.fixture
def registry_state(monkeypatch):
    monkeypatch.setattr(service_registry, "_shared_services", None)
    monkeypatch.setattr(service_registry, "_profile_mgr", None)


def test_concurrent_initialization_publishes_one_complete_tuple_compatible_bundle(monkeypatch, registry_state):
    counts = {}
    count_lock = threading.Lock()

    def factory(name):
        def make(*args, **kwargs):
            with count_lock:
                counts[name] = counts.get(name, 0) + 1
            return object()
        return make

    for attr, name in (
        ("PlaysportOddsAdapter", "odds_adapter"),
        ("SignalHub", "signal_hub"),
        ("ParlayEngine", "parlay_engine"),
        ("SeasonRadar", "season_radar"),
        ("PredictionSnapshotLogger", "snapshot_logger"),
        ("PerformanceMetricsEngine", "metrics_engine"),
        ("ShadowPortfolioManager", "shadow_portfolio"),
        ("ProfileManager", "profile_mgr"),
    ):
        monkeypatch.setattr(service_registry, attr, factory(name))

    barrier = threading.Barrier(12)

    def get_bundle():
        barrier.wait(timeout=3)
        return service_registry.get_services()

    with ThreadPoolExecutor(max_workers=12) as pool:
        bundles = list(pool.map(lambda _: get_bundle(), range(12)))

    assert counts == {
        "odds_adapter": 1,
        "signal_hub": 1,
        "parlay_engine": 1,
        "season_radar": 1,
        "snapshot_logger": 1,
        "metrics_engine": 1,
        "shadow_portfolio": 1,
        "profile_mgr": 1,
    }
    assert all(isinstance(bundle, tuple) and len(bundle) == 8 for bundle in bundles)
    assert len({id(bundle.signal_hub) for bundle in bundles}) == 1
    assert len({id(bundle.profile_mgr) for bundle in bundles}) == 1


def test_failed_construction_does_not_publish_partial_shared_services(monkeypatch, registry_state):
    calls = 0

    def fail_first_signal_hub():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated construction failure")
        return object()

    monkeypatch.setattr(service_registry, "PlaysportOddsAdapter", lambda: object())
    monkeypatch.setattr(service_registry, "SignalHub", fail_first_signal_hub)

    with pytest.raises(RuntimeError, match="simulated construction failure"):
        service_registry.get_services()

    assert service_registry._shared_services is None
    assert service_registry._profile_mgr is None

    monkeypatch.setattr(service_registry, "ParlayEngine", lambda **_kwargs: object())
    monkeypatch.setattr(service_registry, "SeasonRadar", lambda: object())
    monkeypatch.setattr(service_registry, "PredictionSnapshotLogger", lambda: object())
    monkeypatch.setattr(service_registry, "PerformanceMetricsEngine", lambda: object())
    monkeypatch.setattr(service_registry, "ShadowPortfolioManager", lambda: object())
    monkeypatch.setattr(service_registry, "ProfileManager", lambda: object())

    assert len(service_registry.get_services()) == 8
    assert service_registry._shared_services is not None
