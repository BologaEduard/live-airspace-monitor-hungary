"""Write complete UTF-8 exports, replacing old derived files only on success."""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO


@contextmanager
def atomic_text(path: Path) -> Iterator[TextIO]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        delete=False,
        prefix=".export-",
        suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with handle:
            yield handle
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json_line(stream: TextIO, record: dict) -> None:
    stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")


def write_report(path: Path, report: dict) -> None:
    with atomic_text(path) as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
