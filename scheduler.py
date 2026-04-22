"""
24/7 Aimfox Analytics Scheduler
---------------------------------
Runs a full analytics refresh every day at a configurable time,
plus an optional quick refresh every N hours.

Run:
    python scheduler.py               # daily at 07:00, quick refresh every 6h
    python scheduler.py --time 08:30  # daily at 08:30
    python scheduler.py --interval 4  # quick refresh every 4 hours
    python scheduler.py --run-now     # run once immediately then start schedule
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

import schedule

# Ensure we can import from the same directory
sys.path.insert(0, os.path.dirname(__file__))
import main as dashboard

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "scheduler.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def run_full_refresh():
    log.info("Starting full analytics refresh...")
    try:
        # Patch sys.argv so main() doesn't see scheduler args
        old_argv = sys.argv
        sys.argv = ["main.py", "--quiet"]
        paths = dashboard.main()
        sys.argv = old_argv
        log.info("Full refresh complete. Reports saved:")
        for kind, path in (paths or {}).items():
            log.info("  %-22s -> %s", kind, path)
    except Exception as e:
        log.error("Full refresh FAILED: %s", e, exc_info=True)


def run_quick_refresh():
    log.info("Starting quick refresh (no message threads)...")
    try:
        old_argv = sys.argv
        sys.argv = ["main.py", "--quiet", "--no-messages"]
        paths = dashboard.main()
        sys.argv = old_argv
        log.info("Quick refresh complete.")
    except Exception as e:
        log.error("Quick refresh FAILED: %s", e, exc_info=True)


def parse_args():
    p = argparse.ArgumentParser(description="Aimfox 24/7 Scheduler")
    p.add_argument("--time", default="07:00",
                   help="Daily full refresh time in HH:MM format (default: 07:00)")
    p.add_argument("--interval", type=int, default=6,
                   help="Hours between quick refreshes (default: 6). Set 0 to disable.")
    p.add_argument("--run-now", action="store_true",
                   help="Run a full refresh immediately before starting schedule")
    return p.parse_args()


def main():
    args = parse_args()

    log.info("=" * 60)
    log.info("Aimfox Analytics Scheduler starting")
    log.info("Daily full refresh at: %s", args.time)
    if args.interval > 0:
        log.info("Quick refresh every: %d hours", args.interval)
    log.info("=" * 60)

    # Schedule daily full refresh
    schedule.every().day.at(args.time).do(run_full_refresh)
    log.info("Scheduled: full refresh daily at %s", args.time)

    # Schedule quick (no messages) refresh every N hours
    if args.interval > 0:
        schedule.every(args.interval).hours.do(run_quick_refresh)
        log.info("Scheduled: quick refresh every %d hours", args.interval)

    # Immediate run if requested
    if args.run_now:
        log.info("Running immediate full refresh (--run-now)...")
        run_full_refresh()

    log.info("Scheduler running. Press Ctrl+C to stop.")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
