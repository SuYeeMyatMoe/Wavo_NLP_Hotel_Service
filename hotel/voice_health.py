"""Bounded heartbeat recovery, independent of UI sessions and conversation text."""

import asyncio
import logging
import requests


async def watch(fetch, stop, update, *, sleep=asyncio.sleep):
    failures, version = 0, None
    while True:
        await sleep(3)
        try:
            state = await fetch()
        except (RuntimeError, requests.RequestException):
            failures += 1
            logging.getLogger("wavo.voice").warning(
                "voice_status_unavailable attempt=%s", failures
            )
            if failures >= 4:
                stop()
                return
            continue
        failures = 0
        if (
            state["status"] == "Ended"
            or state.get("outcome") == "Speaking with reception"
        ):
            stop()
            return
        if version != state["version"] and state.get("outcome") == "ETA changed":
            await update(state["reply"])
        version = state["version"]
