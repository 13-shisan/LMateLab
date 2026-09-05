from __future__ import annotations

import argparse
import time

import models  # noqa: F401
import models_competition_agent  # noqa: F401
import models_workflow  # noqa: F401
from database import SessionLocal
from services.competition_agent.service import process_next_run


def main() -> int:
    parser = argparse.ArgumentParser(description="Process restricted competition Agent runs")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--poll-seconds", type=float)
    parser.add_argument("--max-idle-cycles", type=int, default=1)
    args = parser.parse_args()
    if args.poll_seconds is not None and not 0.2 <= args.poll_seconds <= 30:
        parser.error("--poll-seconds must be between 0.2 and 30")
    if not 0 <= args.max_idle_cycles <= 10000:
        parser.error("--max-idle-cycles must be between 0 and 10000")

    idle_cycles = 0
    while True:
        with SessionLocal() as session:
            run = process_next_run(session)
        if run is not None:
            idle_cycles = 0
            print(f"processed {run.id} {run.status}", flush=True)
        else:
            idle_cycles += 1
            if args.once or (
                args.max_idle_cycles and idle_cycles >= args.max_idle_cycles
            ):
                print("idle", flush=True)
                return 0
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
