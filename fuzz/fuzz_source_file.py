from __future__ import annotations

import sys

import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    from source_analysis_target import run_source_analysis


def fuzz_source_file(source_bytes: bytes) -> None:
    run_source_analysis(source_bytes)


def main() -> None:
    atheris.Setup(sys.argv, fuzz_source_file)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
