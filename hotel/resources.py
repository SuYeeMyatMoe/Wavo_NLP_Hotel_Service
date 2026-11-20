"""Process-local resources loaded once even during concurrent cold requests."""

from functools import lru_cache, wraps
from threading import RLock


def singleton(loader):
    lock = RLock()
    cached = lru_cache(maxsize=1)(loader)

    @wraps(loader)
    def load():
        with lock:
            return cached()

    def clear():
        with lock:
            cached.cache_clear()

    setattr(load, "cache_clear", clear)
    setattr(load, "cache_info", cached.cache_info)
    return load
