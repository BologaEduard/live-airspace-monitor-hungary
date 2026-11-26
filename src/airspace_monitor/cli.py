"""Command-line entry point for bounded OpenSky recording."""

import argparse
import json
import logging
import math
import sqlite3
from pathlib import Path

from airspace_monitor.collector import collect
from airspace_monitor.config import load_credentials
from airspace_monitor.detector import detect_recording
from airspace_monitor.features import WindowConfig, export_features
from airspace_monitor.opensky_client import OpenSkyClient
from airspace_monitor.preprocess import audit_recording
from airspace_monitor.storage import SnapshotStore
from airspace_monitor.trajectories import segment_observations


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
    segment = commands.add_parser("segment", help="Build trajectories from audited observations.")
    segment.add_argument("--observations", type=Path, required=True)
    segment.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    segment.add_argument("--max-gap-seconds", type=positive_float, default=120)
    features = commands.add_parser("features", help="Compute causal sliding-window kinematics.")
    features.add_argument("--observations", type=Path, required=True)
    features.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    features.add_argument("--window-seconds", type=positive_float, default=300)
    features.add_argument("--min-duration-seconds", type=positive_float, default=180)
    features.add_argument("--min-points", type=positive_int, default=8)
    features.add_argument("--max-sample-gap-seconds", type=positive_float, default=45)
    features.add_argument("--max-gap-seconds", type=positive_float, default=120)
    detector = commands.add_parser("detect", help="Run rule-based screening on recorded polls.")
    detector.add_argument("--db", type=Path, required=True)
    detector.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    serve = commands.add_parser("serve", help="Open the local web preview on loopback only.")
    serve.add_argument(
        "--db", type=Path, help="Recording to read; defaults to the newest local recording."
    )
    serve.add_argument("--port", type=positive_int, default=8000)
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    if args.command == "serve":
        if args.port > 65535:
            parser.error("Port must be at most 65535.")
        try:
            import uvicorn

            from airspace_monitor.app import create_app
            from airspace_monitor.preview import latest_recording
        except ImportError:
            parser.exit(1, 'Install the web extra first: python -m pip install -e ".[web]"\n')
        root = Path(__file__).resolve().parents[2]
        web_dir = root / "web" / "dist"
        if not (web_dir / "index.html").is_file():
            parser.exit(1, "Frontend build missing. Run npm.cmd --prefix web run build.\n")
        recording = args.db if args.db is not None else latest_recording(root / "data" / "raw")
        uvicorn.run(create_app(recording, web_dir), host="127.0.0.1", port=args.port)
        return
    if args.command == "features":
        try:
            feature_config = WindowConfig(
                window_seconds=args.window_seconds,
                min_duration_seconds=args.min_duration_seconds,
                min_points=args.min_points,
                max_sample_gap_seconds=args.max_sample_gap_seconds,
                max_segment_gap_seconds=args.max_gap_seconds,
            )
        except ValueError as error:
            parser.error(str(error))
    if args.command in {"audit", "segment", "features", "detect"}:
        try:
            if args.command == "audit":
                report = audit_recording(
                    args.db,
                    args.output_dir,
                    max_age_seconds=args.max_age_seconds,
                )
            elif args.command == "segment":
                report = segment_observations(
                    args.observations,
                    args.output_dir,
                    max_gap_seconds=args.max_gap_seconds,
                )
            elif args.command == "features":
                report = export_features(args.observations, args.output_dir, config=feature_config)
            else:
                report = detect_recording(args.db, args.output_dir)
        except (OSError, sqlite3.Error, ValueError):
            parser.exit(
                1, "Cannot process recording; check the input schema and output directory.\n"
            )
        summary = {"counts": report["counts"], "report": report["outputs"]["report"]}
        if "polls" in report:
            summary["polls"] = report["polls"]
        if "segment_count" in report:
            summary["segment_count"] = report["segment_count"]
        if "alert_event_counts" in report:
            summary["alert_event_counts"] = report["alert_event_counts"]
            summary["opened_alert_counts_by_type"] = report["opened_alert_counts_by_type"]
            summary["source_reason_counts"] = report["source_reason_counts"]
            summary["active_alert_count"] = report["active_alert_count"]
        print(json.dumps(summary, indent=2))
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
