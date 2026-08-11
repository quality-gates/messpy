from __future__ import annotations

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from messpy.cli import run


NORMAL_EXIT_STATUSES = frozenset({0, 1, 2})


def run_source_analysis(source_bytes: bytes) -> None:
    with TemporaryDirectory() as temporary_directory:
        source_file = Path(temporary_directory) / "source.py"
        source_file.write_bytes(source_bytes)
        status = run([str(source_file), "text", "codesize"], StringIO(), StringIO())
    if status not in NORMAL_EXIT_STATUSES:
        raise AssertionError(f"Unexpected MessPy exit status: {status}")
