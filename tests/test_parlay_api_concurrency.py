from concurrent.futures import ThreadPoolExecutor
import threading
import time

from server import api


def _reset_search_controls():
    with api._parlay_search_lock:
        api._parlay_search_inflight.clear()
    api._parlay_search_capacity = threading.BoundedSemaphore(6)
    api._parlay_search_slots = threading.BoundedSemaphore(2)


def test_identical_simultaneous_parlay_searches_are_coalesced(monkeypatch):
    _reset_search_controls()
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def execute(_req):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=3)
        return {"result": calls}

    monkeypatch.setattr(api, "_execute_parlay_search", execute)
    req = api.ParlaySearchRequest(target_odds=18)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(api.search_parlays, req, {})
        assert entered.wait(timeout=2)
        second_started = threading.Event()

        def run_second():
            second_started.set()
            return api.search_parlays(req, {})

        second = pool.submit(run_second)
        assert second_started.wait(timeout=2)
        with api._parlay_search_lock:
            shared = next(iter(api._parlay_search_inflight.values()))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with shared._condition:
                if shared._condition._waiters:
                    break
            time.sleep(0.005)
        else:
            raise AssertionError("second request did not join the in-flight search")
        release.set()
        assert first.result(timeout=3) == {"result": 1}
        assert second.result(timeout=3) == {"result": 1}

    assert calls == 1
    # Completed results are not cached: a later manual search recomputes.
    monkeypatch.setattr(api, "_execute_parlay_search", lambda _req: {"result": 2})
    assert api.search_parlays(req, {}) == {"result": 2}


def test_parlay_search_rejects_when_unique_request_capacity_is_full(monkeypatch):
    _reset_search_controls()
    api._parlay_search_capacity = threading.BoundedSemaphore(0)
    monkeypatch.setattr(api, "_execute_parlay_search", lambda _req: {})

    try:
        api.search_parlays(api.ParlaySearchRequest(target_odds=18), {})
    except api.HTTPException as exc:
        assert exc.status_code == 429
        assert exc.headers["Retry-After"] == "5"
    else:
        raise AssertionError("a unique request should be rejected when the queue is full")
