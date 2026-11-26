"""Bounded, read-only presentation data for the local web foundation."""

import json
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from airspace_monitor.airspace import AIRPORTS
from airspace_monitor.config import BoundingBox
from airspace_monitor.preprocess import finite_number, timestamp, valid_numeric
from airspace_monitor.recordings import RecordingReader


def latest_recording(directory: Path) -> Path | None:
    recordings = list(directory.glob("*.sqlite3"))
    return max(recordings, key=lambda path: path.stat().st_mtime) if recordings else None


def _aircraft(row: object, api_time: int) -> dict | None:
    if not isinstance(row, list) or len(row) < 17 or row[8] is not False:
        return None
    if not isinstance(row[0], str) or re.fullmatch(r"[0-9a-fA-F]{6}", row[0]) is None:
        return None
    if not valid_numeric("longitude", row[5]) or not valid_numeric("latitude", row[6]):
        return None
    if not timestamp(row[3]) or row[3] > api_time:
        return None
    record = {
        "icao24": row[0].lower(),
        "callsign": row[1].strip() if isinstance(row[1], str) else None,
        "registration_country": row[2] if isinstance(row[2], str) else None,
        "longitude": row[5],
        "latitude": row[6],
        "time_position": row[3],
        "position_age_seconds": api_time - row[3],
        "position_stale": api_time - row[3] > 30,
        "last_contact": row[4] if timestamp(row[4]) and row[4] <= api_time else None,
        "squawk": row[14] if isinstance(row[14], str) else None,
    }
    for name, index in (
        ("baro_altitude", 7),
        ("velocity", 9),
        ("true_track", 10),
        ("vertical_rate", 11),
        ("geo_altitude", 13),
    ):
        record[name] = row[index] if valid_numeric(name, row[index]) else None
    return record


def _analysis(recording: Path, reader: RecordingReader) -> dict:
    directory = recording.parent.parent / "processed"
    report_path = directory / f"{recording.stem}.detection.json"
    events_path = directory / f"{recording.stem}.alerts.jsonl"
    unavailable = {"available": False, "as_of_time": None, "total_candidates": None, "events": []}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if Path(report["source_database"]).resolve() != recording.resolve():
            return unavailable
        maximum = report["max_attempt_id"]
        if type(maximum) is not int or not 0 <= maximum <= reader.max_attempt_id:
            return unavailable
        events = deque(maxlen=24)
        with events_path.open(encoding="utf-8") as stream:
            for line in stream:
                event = json.loads(line)
                if (
                    isinstance(event, dict)
                    and event.get("event") == "opened"
                    and timestamp(event.get("source_api_time"))
                    and timestamp(event.get("event_time"))
                    and type(event.get("source_attempt_id")) is int
                    and event["source_attempt_id"] <= maximum
                ):
                    events.append(event)
        row = reader.connection.execute(
            "SELECT api_time FROM collection_attempts WHERE id <= ? AND outcome = 'success' "
            "ORDER BY id DESC LIMIT 1",
            (maximum,),
        ).fetchone()
        return {
            "available": True,
            "as_of_time": row[0] if row else None,
            "total_candidates": report["alert_event_counts"].get("opened", 0),
            "events": list(events),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return unavailable


def read_preview(recording: Path | None, *, max_frames: int = 48, now: float | None = None) -> dict:
    if type(max_frames) is not int or not 1 <= max_frames <= 120:
        raise ValueError("Preview frame limit must be between 1 and 120.")
    clock = datetime.now(timezone.utc).timestamp() if now is None else now
    if not finite_number(clock):
        raise ValueError("Invalid preview clock.")
    result = {
        "mode": "recording",
        "frames": [],
        "bbox": BoundingBox().as_params(),
        "source": {"status": "no_recording", "recording_name": None, "polls_total": 0},
        "analysis": {
            "available": False,
            "as_of_time": None,
            "total_candidates": None,
            "events": [],
        },
        "airports": [
            {"icao": a.icao, "latitude": a.latitude, "longitude": a.longitude} for a in AIRPORTS
        ],
    }
    if recording is None:
        return result
    with RecordingReader(recording) as reader:
        summary = reader.connection.execute(
            "SELECT COUNT(*), SUM(outcome != 'success'), MIN(api_time), MAX(api_time) "
            "FROM collection_attempts WHERE id <= ?",
            (reader.max_attempt_id,),
        ).fetchone()
        latest = reader.connection.execute(
            "SELECT outcome, completed_at FROM collection_attempts "
            "WHERE id <= ? ORDER BY id DESC LIMIT 1",
            (reader.max_attempt_id,),
        ).fetchone()
        rows = reader.connection.execute(
            "SELECT id, run_id, api_time, completed_at, raw_body, bbox_json "
            "FROM collection_attempts WHERE id <= ? AND outcome = 'success' "
            "ORDER BY id DESC LIMIT ?",
            (reader.max_attempt_id, max_frames),
        ).fetchall()
        previous_time = -1
        run_id = rows[0]["run_id"] if rows else None
        for row in reversed(rows):
            if row["run_id"] != run_id:
                continue
            try:
                payload = json.loads(row["raw_body"])
                api_time = payload["time"]
                if (
                    not timestamp(api_time)
                    or api_time >= 253402300800
                    or api_time != row["api_time"]
                    or api_time <= previous_time
                ):
                    continue
                states = payload["states"]
                if states is None:
                    states = []
                if not isinstance(states, list):
                    continue
                completed = datetime.fromisoformat(row["completed_at"])
                if completed.tzinfo is None or api_time > completed.timestamp():
                    continue
                scope = json.loads(row["bbox_json"])
                if (
                    not isinstance(scope, dict)
                    or set(scope) != {"lamin", "lomin", "lamax", "lomax"}
                    or not all(finite_number(value) for value in scope.values())
                ):
                    continue
                bbox = BoundingBox(**scope)
            except (ValueError, KeyError, TypeError, OverflowError):
                continue
            aircraft = [
                plane for state in states if (plane := _aircraft(state, api_time)) is not None
            ]
            result["frames"].append(
                {
                    "time": api_time,
                    "completed_at": int(completed.timestamp()),
                    "attempt_id": row["id"],
                    "aircraft": aircraft,
                    "raw_count": len(states),
                    "ground_count": sum(
                        isinstance(state, list) and len(state) > 8 and state[8] is True
                        for state in states
                    ),
                }
            )
            result["bbox"] = bbox.as_params()
            previous_time = api_time
        last_time = result["frames"][-1]["time"] if result["frames"] else None
        age = clock - last_time if last_time is not None else None
        status = "fresh_recording" if age is not None and 0 <= age <= 45 else "saved_recording"
        if not result["frames"]:
            status = "no_usable_frames"
        elif latest["outcome"] != "success":
            status = "source_interrupted"
        elif age is not None and age < 0:
            status = "source_clock_unknown"
        result["source"] = {
            "status": status,
            "recording_name": recording.name,
            "polls_total": summary[0],
            "failed_polls": summary[1] or 0,
            "first_api_time": summary[2],
            "last_api_time": last_time,
            "age_seconds": age,
            "latest_attempt_id": reader.max_attempt_id,
        }
        result["analysis"] = _analysis(recording, reader)
    return result
