"""Bounded in-process inference jobs so audio processing cannot block hang-up."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException

pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wavo-call")
jobs = {}
lock = Lock()


def submit(owner, call, fingerprint, action):
    with lock:
        now = time.monotonic()
        expired = [
            key
            for key, job in jobs.items()
            if job["future"].done() and now - job["created"] > 300
        ]
        for key in expired:
            del jobs[key]
        for key, job in jobs.items():
            if (job["owner"], job["call"], job["fingerprint"]) == (
                owner,
                call,
                fingerprint,
            ):
                future = job["future"]
                if not future.cancelled() and not (
                    future.done() and future.exception()
                ):
                    return key
        if sum(not job["future"].done() for job in jobs.values()) >= 4:
            raise HTTPException(
                429, "Reception is busy processing audio. Please try again."
            )
        if len(jobs) >= 32:
            completed = next(
                (key for key, job in jobs.items() if job["future"].done()), None
            )
            if completed is None:
                raise HTTPException(429, "Reception is busy. Please try again.")
            del jobs[completed]
        key = str(uuid4())
        jobs[key] = {
            "owner": owner,
            "call": call,
            "fingerprint": fingerprint,
            "created": now,
            "future": pool.submit(action),
        }
        return key


def get(owner, call, key):
    with lock:
        job = jobs.get(key)
        if not job or job["owner"] != owner or job["call"] != call:
            raise HTTPException(
                404, "This audio request is unavailable. Please try again."
            )
        return job["future"]


def discard(call):
    with lock:
        for key in [key for key, job in jobs.items() if job["call"] == call]:
            jobs.pop(key)["future"].cancel()
