from __future__ import annotations

from difflib import unified_diff
from pathlib import Path
import subprocess
import sys


def verify(executable: Path, baseline: Path) -> None:
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
    expected = baseline.read_text(encoding="utf-8")
    if result.stdout != expected:
        difference = "".join(
            unified_diff(
                expected.splitlines(keepends=True),
                result.stdout.splitlines(keepends=True),
                fromfile=str(baseline),
                tofile="installed messpy self-analysis",
            )
        )
        raise AssertionError(f"self-analysis findings changed:\n{difference}")
    expected_status = 2 if expected else 0
    if result.returncode != expected_status:
        raise AssertionError(
            f"self-analysis exited {result.returncode}; expected {expected_status}"
        )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_self_analysis.py MESSPY BASELINE")
    verify(Path(sys.argv[1]), Path(sys.argv[2]))
