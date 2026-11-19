"""Run independently: python -m hotel.operations_worker. No browser required."""

import argparse
import time
from hotel.monitoring import tick
from hotel.notifications import publish_one


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            tick()
            for _ in range(100):
                if not publish_one():
                    break
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
