"""Default suite stays offline; live network checks require an explicit opt-in."""
import pytest
import requests
import urllib.request


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", default=False,
                     help="run tests marked live that make real network requests")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="live network test; pass --run-live to opt in")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def reject_unmarked_network_calls(request, monkeypatch):
    if request.config.getoption("--run-live"):
        return

    def reject(*args, **kwargs):
        raise AssertionError("Network access is disabled in the default offline test suite.")

    monkeypatch.setattr(requests.sessions.Session, "request", reject)
    monkeypatch.setattr(urllib.request, "urlopen", reject)
