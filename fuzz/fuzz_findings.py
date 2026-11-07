from __future__ import annotations

import sys
import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    from messpy.analyzer import Analysis, analyze_source
    from messpy.rulesets import RuleSelection, select_rules
    from scan_profile import RULESETS


RULE_SELECTIONS = [select_rules(RuleSelection(rulesets=tuple(name.split(",")))) for name in RULESETS]


def fuzz_findings(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    rules = fdp.PickValueInList(RULE_SELECTIONS)
    source = fdp.ConsumeBytes(sys.maxsize).decode("utf-8", errors="replace")
    analysis = analyze_source(source, rules=rules, filename="source.py")

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
