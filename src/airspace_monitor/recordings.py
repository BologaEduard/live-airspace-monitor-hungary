"""Read a bounded prefix of a recording without modifying or locking it for long."""

import sqlite3
from pathlib import Path
from typing import Iterator


class RecordingReader:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        try:
            if self.connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Unsupported recording database schema version.")
            self.max_attempt_id = self.connection.execute(
                "SELECT COALESCE(MAX(id), 0) FROM collection_attempts"
            ).fetchone()[0]
        except Exception:
            self.connection.close()
            raise

    def attempts(self) -> Iterator[dict]:
        last_id = 0
        while last_id < self.max_attempt_id:
            # Finish each SELECT before processing the batch, allowing the collector to write.
            rows = self.connection.execute(
                "SELECT * FROM collection_attempts WHERE id > ? AND id <= ? ORDER BY id LIMIT 256",
                (last_id, self.max_attempt_id),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                yield dict(row)
            last_id = rows[-1]["id"]

    def __enter__(self) -> "RecordingReader":
        return self

    def __exit__(self, *exc: object) -> None:
        self.connection.close()
