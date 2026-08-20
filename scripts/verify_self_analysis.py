from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def verify(executable: Path) -> None:
    result = subprocess.run(
        [
            executable,
            "src/messpy",
            "text",
            "python",
            "--ignore-tests",
            "--strict",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stderr:
        raise AssertionError(f"self-analysis wrote to stderr:\n{result.stderr}")
    if result.stdout:
        raise AssertionError(f"self-analysis found production-code violations:\n{result.stdout}")
    if result.returncode != 0:
        raise AssertionError(f"self-analysis exited {result.returncode}; expected 0")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_self_analysis.py MESSPY")
    verify(Path(sys.argv[1]))
