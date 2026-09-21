from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    from messpy.analyzer import Analysis, analyze
    from messpy.rulesets import filter_rules, load_rulesets

RULESETS = [
    "codesize",
    "naming",
    "unusedcode",
    "cleancode",
    "design",
    "controversial",
    "opinionated",
    "python",
    "codesize,naming,unusedcode,cleancode,design,controversial,opinionated",
]


def fuzz_findings(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    ruleset = fdp.PickValueInList(RULESETS)
    ignore_tests = fdp.ConsumeBool()
    source_bytes = fdp.ConsumeBytes(sys.maxsize)

    with TemporaryDirectory() as temporary_directory:
        source_file = Path(temporary_directory) / "source.py"
        source_file.write_bytes(source_bytes)
        rules = filter_rules(load_rulesets(ruleset.split(",")), [], [], [], 1, 5)
        analysis = analyze([source_file], rules=rules, ignore_tests=ignore_tests)

    assert isinstance(analysis, Analysis)
    for finding in analysis.findings:
        assert finding.line >= 1
        assert finding.rule_name
        assert finding.priority in range(1, 6)
    for error in analysis.errors:
        assert error.line >= 1
        assert error.message


def main() -> None:
    atheris.Setup(sys.argv, fuzz_findings)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
