from __future__ import annotations

from collections.abc import Sequence
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

import messpy.cli as cli
from messpy.rulesets import built_in_ruleset_names


NORMAL_EXIT_STATUSES = frozenset({0, 1, 2})

# Built-in rulesets that cannot load bare, mapped to the configured ruleset that scans them.
CONFIGURED_RULESETS = {"onion": str(Path(__file__).parent / "onion_scan_ruleset.xml")}

_SINGLE_RULESETS = tuple(CONFIGURED_RULESETS.get(name, name) for name in built_in_ruleset_names())

RULESETS = (*_SINGLE_RULESETS, ",".join(_SINGLE_RULESETS))

FORMATS = tuple(sorted(cli.REPORT_FORMATS))


def run_scan(
    source: bytes,
    ruleset: str,
    report_format: str = "text",
    options: Sequence[str] = (),
) -> int:
    with TemporaryDirectory() as temporary_directory:
        source_file = Path(temporary_directory) / "source.py"
        source_file.write_bytes(source)
        return run_command([str(source_file), report_format, ruleset, *options])


def run_command(arguments: Sequence[str]) -> int:
    stderr = StringIO()
    status = cli.run(list(arguments), StringIO(), stderr)
    if status not in NORMAL_EXIT_STATUSES:
        raise AssertionError(
            f"Unexpected MessPy exit status {status} for arguments {list(arguments)}\n"
            f"Stderr: {stderr.getvalue()}"
        )
    return status
