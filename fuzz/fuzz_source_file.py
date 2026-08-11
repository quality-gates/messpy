from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    from messpy.cli import run


def fuzz_source_file(source_bytes: bytes) -> None:
    with TemporaryDirectory() as temporary_directory:
        source_file = Path(temporary_directory) / "source.py"
        source_file.write_bytes(source_bytes)
        run([str(source_file), "text", "codesize"], StringIO(), StringIO())


def main() -> None:
    atheris.Setup(sys.argv, fuzz_source_file)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
