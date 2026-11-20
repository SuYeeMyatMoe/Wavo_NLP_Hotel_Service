"""Reuse transport connections, never credentials or cookies between requests."""

from threading import local

import requests

_thread = local()


def request(method, url, **kwargs):
    if not hasattr(_thread, "session"):
        _thread.session = requests.Session()
    session = _thread.session
    try:
        return session.request(method, url, **kwargs)
    finally:
        session.cookies.clear()
