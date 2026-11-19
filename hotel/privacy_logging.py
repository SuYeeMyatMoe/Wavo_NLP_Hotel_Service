"""Suppress provider payloads regardless of transcript retention consent."""

import logging


def install():
    original = logging.getLogRecordFactory()
    if getattr(original, "wavo_private", False):
        return

    def private(*args, **kwargs):
        record = original(*args, **kwargs)
        if record.name.startswith(
            ("livekit", "google", "httpx", "httpcore", "websockets")
        ):
            record.msg = "Provider event; payload omitted by retention policy."
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return record

    private.wavo_private = True
    logging.setLogRecordFactory(private)
