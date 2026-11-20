"""Warm inference resources without holding up health checks or sign-in."""

import logging
from threading import Event, Thread
from time import perf_counter

log = logging.getLogger("uvicorn.error.wavo.startup")


def loaders():
    from hotel.nlp import bundle, lexicon
    from hotel.intelligence import vader
    from hotel.languages import text_detector
    from hotel.store import voice_ready

    def voice():
        if voice_ready():
            from livekit import api  # noqa: F401

    return (bundle, lexicon, vader, text_detector, voice)


class WarmupRunner:
    def __init__(self):
        self.stop = Event()
        self.thread = Thread(target=self.run, name="wavo-warmup", daemon=True)

    def run(self):
        for load in loaders():
            if self.stop.is_set():
                break
            started = perf_counter()
            try:
                load()
                log.info("resource=%s warmup_ms=%.1f", load.__name__, (perf_counter() - started) * 1000)
            except Exception as exc:
                # Accessors can retry; never log provider details or input content.
                log.warning("resource=%s warmup_failed=%s", load.__name__, type(exc).__name__)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join()
