import asyncio
import requests
from hotel.voice_health import watch


def run(states):
    calls, stops, updates = [], [], []

    async def fetch():
        item = states[len(calls)]
        calls.append(item)
        if isinstance(item, Exception):
            raise item
        return item

    async def update(reply):
        updates.append(reply)

    async def sleep(_):
        pass

    asyncio.run(watch(fetch, lambda: stops.append(True), update, sleep=sleep))
    return calls, stops, updates


def test_transient_errors_recover_and_explicit_end_stops():
    alive = {"status": "Connected", "version": 0}
    ended = {"status": "Ended", "version": 0}
    states = [requests.Timeout(), alive, requests.ConnectionError(), alive, ended]
    calls, stops, updates = run(states)
    assert len(calls) == 5 and stops == [True] and not updates


def test_repeated_failure_is_bounded():
    calls, stops, _ = run([requests.Timeout() for _ in range(8)])
    assert len(calls) == 4 and stops == [True]


def test_verified_update_only_once_then_handoff():
    update = {
        "status": "Connected",
        "version": 2,
        "outcome": "ETA changed",
        "reply": "Updated estimate",
    }
    _, stops, updates = run(
        [
            update,
            update,
            {"status": "Connected", "version": 3, "outcome": "Speaking with reception"},
        ]
    )
    assert updates == ["Updated estimate"] and stops == [True]
