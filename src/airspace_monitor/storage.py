"""Append-only raw collection storage; each poll is committed immediately."""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from airspace_monitor.config import BoundingBox
from airspace_monitor.opensky_client import CollectionAttempt


class SnapshotStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        try:
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise ValueError("Unsupported recording database schema version.")
            with self.connection:
                self.connection.execute("""
                    CREATE TABLE IF NOT EXISTS collection_attempts (
                        id INTEGER PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        bbox_json TEXT NOT NULL,
                        requested_at TEXT NOT NULL,
                        completed_at TEXT NOT NULL,
                        phase TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        http_status INTEGER,
                        raw_body TEXT,
                        api_time INTEGER,
                        vector_count INTEGER,
                        remaining_credits INTEGER,
                        retry_after_seconds REAL
                    )
                """)
                self.connection.execute("""
                    CREATE INDEX IF NOT EXISTS idx_attempts_api_time
                    ON collection_attempts(api_time)
                """)
                self.connection.execute("PRAGMA user_version = 1")
        except Exception:
            self.connection.close()
            raise

    def save(self, attempt: CollectionAttempt, *, run_id: str, bbox: BoundingBox) -> int:
        record = asdict(attempt)
        record.update(run_id=run_id, bbox_json=json.dumps(bbox.as_params(), sort_keys=True))
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO collection_attempts (
                    run_id, bbox_json, requested_at, completed_at, phase, outcome,
                    http_status, raw_body, api_time, vector_count, remaining_credits,
                    retry_after_seconds
                ) VALUES (
                    :run_id, :bbox_json, :requested_at, :completed_at, :phase, :outcome,
                    :http_status, :raw_body, :api_time, :vector_count, :remaining_credits,
                    :retry_after_seconds
                )
            """,
                record,
            )
        return cursor.lastrowid

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SnapshotStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
