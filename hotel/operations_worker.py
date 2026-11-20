"""Run independently: python -m hotel.operations_worker. No browser required."""

import argparse
import time
import logging
from threading import Event, Thread
from hotel.monitoring import tick
from hotel.notifications import publish_one


def cycle(stop=None):
    tick()
    for _ in range(100):
        if stop is not None and stop.is_set():
            break
        if not publish_one():
            break


class OperationsRunner:
    """One stoppable loop owned by the single API process's lifespan."""

    def __init__(self, interval=15):
        self.interval = interval
        self.stop = Event()
        self.thread = Thread(target=self.run, name="wavo-operations", daemon=True)

    def run(self):
        while not self.stop.is_set():
            try:
                cycle(self.stop)
            except Exception:
                logging.getLogger(__name__).warning(
                    "Operations cycle unavailable; retrying."
                )
            self.stop.wait(self.interval)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            cycle()
        except Exception:
            if args.once:
                raise
            print(
                "Operations cycle unavailable; check database configuration. Retrying in 15 seconds.",
                flush=True,
            )
        if args.once:
            return
        time.sleep(15)


if __name__ == "__main__":
    main()
