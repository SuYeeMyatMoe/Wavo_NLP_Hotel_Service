"""Retry only an unauthenticated readiness read before a user action."""

import os
import time
import logging
import requests
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from threading import Lock, Thread
from hotel.http_client import request


def wait_for_api(url, *, timeout=120, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    attempts, last_failure = 0, "not_started"
    while clock() < deadline:
        attempts += 1
        remaining = deadline - clock()
        # Render may need tens of seconds before forwarding the first request.
        # Keep that wake request open instead of repeatedly aborting it at 5s.
        connect_timeout = min(5, remaining / 2)
        try:
            response = request(
                "GET", url.rstrip("/") + "/healthz",
                timeout=(connect_timeout, min(60, remaining - connect_timeout)),
            )
            if response.ok and response.json().get("status") == "ok":
                return
            last_failure = "not_ready"
        except (requests.RequestException, ValueError, AttributeError) as exc:
            last_failure = type(exc).__name__
        sleep(max(0, min(2, deadline - clock())))
    logging.getLogger(__name__).warning(
        "API readiness deadline reached: attempts=%d last_failure=%s", attempts, last_failure
    )
    raise requests.Timeout("Hotel service is still starting. Please try again shortly.")


def enabled():
    return os.getenv("WAVO_WAKE_API", "false").lower() == "true"


@dataclass
class Wake:
    future: Future
    ready_at: float = 0.0


class WakeCoordinator:
    """Access-driven only: one bounded readiness task per configured API URL."""

    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.lock = Lock()
        self.tasks = {}

    def begin(self, url):
        url = url.rstrip("/")
        with self.lock:
            previous = self.tasks.get(url)
            if previous and (
                not previous.future.done()
                or (
                    previous.future.exception() is None
                    and self.clock() - previous.ready_at < 60
                )
            ):
                return previous.future
            # Only configured URLs are used; also discard expired, finished entries.
            self.tasks = {
                key: value for key, value in self.tasks.items()
                if not value.future.done() or self.clock() - value.ready_at < 60
            }
            task = Wake(Future())
            self.tasks[url] = task
            Thread(target=self._run, args=(url, task), name="wavo-api-wake", daemon=True).start()
            return task.future

    def _run(self, url, task):
        try:
            wait_for_api(url)
        except Exception as exc:
            task.future.set_exception(exc)
        else:
            task.ready_at = self.clock()
            task.future.set_result(None)


_coordinator = WakeCoordinator()


def begin_wake(url):
    return _coordinator.begin(url)


def wait_for_ready(url, *, task=None):
    try:
        (task if task is not None else begin_wake(url)).result(timeout=125)
    except FutureTimeout:
        raise requests.Timeout("Hotel service is still starting. Please try again shortly.") from None
