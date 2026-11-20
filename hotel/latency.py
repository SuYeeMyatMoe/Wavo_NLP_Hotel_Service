"""Content-free, request-local timings for voice processing and hang-up."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

_current: ContextVar[dict[str, float] | None] = ContextVar("call_latency", default=None)
_batch_depth = ContextVar("call_latency_batch", default=0)
log = logging.getLogger("uvicorn.error.wavo.latency")


@contextmanager
def measure(stage, **identifiers):
    values = {"db_ms": 0.0, "queries": 0}
    token = _current.set(values)
    started = perf_counter()
    try:
        yield
    finally:
        _current.reset(token)
        log.info(
            "stage=%s elapsed_ms=%.1f db_ms=%.1f queries=%d ids=%s",
            stage,
            (perf_counter() - started) * 1000,
            values["db_ms"],
            values["queries"],
            identifiers,
        )
        parent = _current.get()
        if parent is not None:
            parent["db_ms"] += values["db_ms"]
            parent["queries"] += values["queries"]


def database_elapsed(started, *, query=True):
    values = _current.get()
    if values is not None:
        if not _batch_depth.get():
            values["db_ms"] += (perf_counter() - started) * 1000
        values["queries"] += int(query)


@contextmanager
def database_batch():
    started = perf_counter()
    token = _batch_depth.set(_batch_depth.get() + 1)
    try:
        yield
    finally:
        _batch_depth.reset(token)
        database_elapsed(started, query=False)
