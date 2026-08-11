from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from pathlib import Path

from source_analysis_target import run_source_analysis


def replay_source_file(source_input: Path) -> None:
    run_source_analysis(source_input.read_bytes())


def stored_source_inputs(input_paths: Sequence[Path]) -> Iterator[Path]:
    for input_path in input_paths:
        if input_path.is_dir():
            yield from sorted(
                path
                for path in input_path.rglob("*")
                if path.is_file() and path.name != ".gitkeep"
            )
        else:
            yield input_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay stored source-analysis fuzz inputs through MessPy."
    )
    parser.add_argument("inputs", metavar="INPUT", nargs="+", type=Path)
    arguments = parser.parse_args()

    for source_input in stored_source_inputs(arguments.inputs):
        replay_source_file(source_input)
        print(f"Replayed source-analysis input: {source_input}")


if __name__ == "__main__":
    main()
