"""Command-line entry point for bounded OpenSky recording."""

import argparse
import json
import logging
import math
import sqlite3
from pathlib import Path

from airspace_monitor.collector import collect
from airspace_monitor.config import load_credentials
from airspace_monitor.opensky_client import OpenSkyClient
from airspace_monitor.preprocess import audit_recording
from airspace_monitor.storage import SnapshotStore


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Must be a finite positive number.")
    return number


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer.")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Airspace Monitor for Hungary.")
    commands = parser.add_subparsers(dest="command")
    collector = commands.add_parser("collect", help="Record OpenSky snapshots to SQLite.")
    collector.add_argument("--credentials", type=Path, help="Local OAuth credentials JSON file.")
    collector.add_argument("--db", type=Path, default=Path("data/raw/opensky.sqlite3"))
    collector.add_argument("--interval-seconds", type=positive_float, default=15)
    collector.add_argument("--duration-seconds", type=positive_float, default=3600)
    collector.add_argument("--max-polls", type=positive_int)
    collector.add_argument("--timeout-seconds", type=positive_float, default=15)
    audit = commands.add_parser("audit", help="Audit a read-only prefix of a recording.")
    audit.add_argument("--db", type=Path, required=True)
    audit.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    audit.add_argument("--max-age-seconds", type=positive_float, default=30)
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    if args.command == "audit":
        try:
            report = audit_recording(
                args.db,
                args.output_dir,
                max_age_seconds=args.max_age_seconds,
            )
        except (OSError, sqlite3.Error, ValueError):
            parser.exit(1, "Cannot audit recording; check the input schema and output directory.\n")
        print(
            json.dumps(
                {
                    "polls": report["polls"],
                    "counts": report["counts"],
                    "report": report["outputs"]["report"],
                },
                indent=2,
            )
        )
        return
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        credentials = load_credentials(args.credentials)
    except ValueError as error:
        parser.error(str(error))
    client = OpenSkyClient(credentials, timeout=args.timeout_seconds)
    try:
        with SnapshotStore(args.db) as store:
            summary = collect(
                client,
                store,
                interval_seconds=args.interval_seconds,
                duration_seconds=args.duration_seconds,
                max_polls=args.max_polls,
            )
    except KeyboardInterrupt:
        print("Collection interrupted. Completed polls have been saved.")
        raise SystemExit(130) from None
    except (OSError, sqlite3.Error, ValueError):
        # Avoid printing external exception text which can contain sensitive values.
        parser.exit(1, "Cannot open or write the recording database.\n")
    finally:
        client.close()
    print(
        f"run={summary.run_id} attempts={summary.attempts} successes={summary.successes} "
        f"failures={summary.failures} stop={summary.stop_reason}"
    )
    if summary.successes == 0 or summary.stop_reason in {"non_retryable_error", "failure_limit"}:
        raise SystemExit(1)
