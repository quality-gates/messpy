from __future__ import annotations

import ast
from collections import Counter
from io import StringIO
from itertools import product
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from messpy.cli import run
from messpy.rulesets import load_rulesets


class Policy(NamedTuple):
    priority: int
    minimum: int


def write_policy(path: Path, policy: Policy) -> None:
    path.write_text(
        '<ruleset><rule ref="ExcessiveMethodLength">'
        f"<priority>{policy.priority}</priority>"
        f'<properties><property name="minimum" value="{policy.minimum}"/></properties>'
        "</rule></ruleset>",
        encoding="utf-8",
    )


def write_wrapper(path: Path, policies: tuple[Policy, ...]) -> None:
    references = "".join(
        f'<rule ref="policy-{policy.priority}-{policy.minimum}.xml"/>' for policy in policies
    )
    path.write_text(f"<ruleset>{references}</ruleset>", encoding="utf-8")


def verify_xml(directory: Path) -> bool:
    policies = tuple(
        Policy(priority, minimum) for priority, minimum in product(range(1, 6), (3, 5, 50))
    )
    for policy in policies:
        write_policy(directory / f"policy-{policy.priority}-{policy.minimum}.xml", policy)

    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    wrapper = directory / "wrapper.xml"
    for length in (1, 2):
        for sequence in product(policies, repeat=length):
            write_wrapper(wrapper, sequence)
            rules = load_rulesets([str(wrapper)])
            if len(rules) != 1 or rules[0].name != "ExcessiveMethodLength":
                key = f"{length}-policy rule selection"
                counts[key] += 1
                examples.setdefault(key, f"policies={sequence}, loaded={rules!r}")
                continue
            expected = sequence[-1]
            actual = Policy(rules[0].priority, rules[0].integer("minimum"))
            for field in Policy._fields:
                if getattr(actual, field) != getattr(expected, field):
                    key = f"{length}-policy {field}"
                    counts[key] += 1
                    examples.setdefault(key, f"policies={sequence}, expected={expected}, actual={actual}")

    print("XML cases: 15 single policies and 225 ordered pairs")
    for length in (1, 2):
        failures = [key for key in sorted(counts) if key.startswith(f"{length}-policy ")]
        if not failures:
            print(f"  PASS: {length}-policy priority and minimum match the last explicit policy")
        for key in failures:
            print(f"  FAIL: {key}: {counts[key]} case(s); {examples[key]}")
    return not counts


def verify_cli(directory: Path) -> bool:
    source = directory / "sample.py"
    source.write_text("def sample():\n    pass\n    pass\n    pass\n", encoding="utf-8")
    wrapper = directory / "wrapper.xml"
    write_wrapper(wrapper, (Policy(3, 50), Policy(3, 3)))
    stdout, stderr = StringIO(), StringIO()
    status = run([str(source), "text", str(wrapper)], stdout, stderr)
    report = stdout.getvalue()
    passed = (
        status == 2
        and "ExcessiveMethodLength" in report
        and "threshold is set to 3" in report
        and not stderr.getvalue()
    )
    print(
        f"CLI case: {'PASS' if passed else 'FAIL'}: expected exit 2 and a threshold 3 finding; "
        f"exit={status}, report={report!r}, stderr={stderr.getvalue()!r}"
    )
    return passed


def verify_partial_override(directory: Path) -> bool:
    wrapper = directory / "partial-override.xml"
    wrapper.write_text(
        '<ruleset><rule ref="policy-3-3.xml"/>'
        '<rule ref="ExcessiveMethodLength"><priority>2</priority></rule></ruleset>',
        encoding="utf-8",
    )
    rules = load_rulesets([str(wrapper)])
    actual = [(rule.name, rule.priority, rule.integer("minimum")) for rule in rules]
    expected = [("ExcessiveMethodLength", 2, 3)]
    passed = actual == expected
    print(
        f"Partial direct override: {'PASS' if passed else 'FAIL'}: "
        f"expected={expected!r}, actual={actual!r}"
    )
    return passed


def verify_symbolic() -> bool:
    contracts = Path(__file__).with_name("contracts.py")
    tree = ast.parse(contracts.read_text(encoding="utf-8"), filename=str(contracts))
    lines = {node.name: node.lineno for node in tree.body if isinstance(node, ast.FunctionDef)}
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    passed = True
    for name in ("nested_priority", "nested_minimum"):
        if name not in lines:
            print(f"CrossHair {name}: ERROR: contract is missing")
            passed = False
            continue
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "crosshair",
                "check",
                "--analysis_kind=asserts",
                "--report_all",
                "--per_condition_timeout=10",
                f"{contracts}:{lines[name]}",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        output = (result.stdout + result.stderr).strip()
        lines_of_output = result.stdout.strip().splitlines()
        confirmed = (
            result.returncode == 0
            and len(lines_of_output) == 1
            and lines_of_output[0].endswith(": info: Confirmed over all paths.")
            and not result.stderr
        )
        outcome = "INCONCLUSIVE"
        if confirmed:
            outcome = "PASS"
        elif result.returncode == 1 and "error: AssertionError" in output:
            outcome = "FAIL"
        print(f"CrossHair {name}: {outcome}: {output or 'no result'}")
        passed = passed and confirmed
    return passed


def main() -> int:
    with TemporaryDirectory(prefix="messpy-ruleset-verification-") as temporary:
        directory = Path(temporary)
        xml_passed = verify_xml(directory)
        cli_passed = verify_cli(directory)
        partial_override_passed = verify_partial_override(directory)
    symbolic_passed = verify_symbolic()
    return 0 if xml_passed and cli_passed and partial_override_passed and symbolic_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
