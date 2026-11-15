#!/usr/bin/env python3
"""Compare public CLI observations with a revision before structural refactoring."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap

ROOT = Path(__file__).resolve().parent.parent
RUNNER = '''import json, sys
from io import StringIO
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from messpy.cli import run
results = []
for arguments in json.load(sys.stdin):
    report = Path(arguments[arguments.index("--reportfile") + 1]) if "--reportfile" in arguments else None
    if report is not None:
        report.unlink(missing_ok=True)
    out, err = StringIO(), StringIO()
    status = run(arguments, out, err)
    contents = report.read_text(encoding="utf-8") if report is not None and report.exists() else None
    results.append([status, out.getvalue(), err.getvalue(), contents])
json.dump(results, sys.stdout)
'''


def corpus() -> list[str]:
    sources = set()
    for test in sorted((ROOT / "tests").glob("test_*.py")):
        for node in ast.walk(ast.parse(test.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            source = textwrap.dedent(node.value)
            try:
                tree = ast.parse(source)
            except (SyntaxError, ValueError):
                continue
            if any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.Import, ast.ImportFrom)) for item in tree.body):
                sources.add(source)
    sources.update(path.read_text(encoding="utf-8") for path in sorted((ROOT / "tests" / "fixtures").rglob("*.py")))
    return sorted(sources)


def requests(directory: Path) -> list[list[str]]:
    scan = [str(directory), "json", "codesize,design,naming,unusedcode,explicitness"]
    cases = [
        scan, [*scan, "--strict"], [*scan, "--ignore-violations-on-exit"],
        ["--help"], ["--version"], [], ["--unknown"],
        ["--ignore-errors-on-exit", "--unknown"], ["--unknown", "--ignore-errors-on-exit"],
        [*scan, "--suffixes", ".pyi"], [*scan, "--suffixes", ".pyi", "--suffixes", ".py"],
        [*scan, "--minimum-priority", "6"], [*scan, "--strict=yes"],
    ]
    for report_format in ("text", "json", "xml", "html"):
        cases.append([str(directory), report_format, "python", "--reportfile", str(directory.parent / "report")])
    return cases


def observe(source: Path, cases: list[list[str]]) -> list:
    result = subprocess.run(
        [sys.executable, "-c", RUNNER, str(source / "src")], input=json.dumps(cases),
        text=True, capture_output=True, cwd=ROOT, check=True,
    )
    if result.stderr:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def verify(revision: str, candidate: Path) -> None:
    archive = subprocess.run(["git", "archive", revision, "src/messpy"], cwd=ROOT, capture_output=True, check=True).stdout
    with tempfile.TemporaryDirectory(prefix="messpy-state-parity-") as temporary:
        directory = Path(temporary)
        archive_path = directory / "baseline.tar"
        archive_path.write_bytes(archive)
        baseline = directory / "baseline"
        with tarfile.open(archive_path) as bundle:
            bundle.extractall(baseline, filter="data")
        fixtures = directory / "corpus"
        fixtures.mkdir()
        sources = corpus()
        for index, source in enumerate(sources):
            (fixtures / f"case_{index:04}.py").write_text(source, encoding="utf-8")
        (fixtures / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        cases = requests(fixtures)
        expected = observe(baseline, cases)
        actual = observe(candidate, cases)
        mismatches = [index for index, pair in enumerate(zip(expected, actual)) if pair[0] != pair[1]]
        if mismatches:
            for index in mismatches:
                print(f"Case {index} differs: expected status {expected[index][0]}, observed {actual[index][0]}; "
                      f"stdout lengths {len(expected[index][1])}/{len(actual[index][1])}, "
                      f"report lengths {len(expected[index][3] or '')}/{len(actual[index][3] or '')}")
            raise SystemExit(f"public behavior differs in {len(mismatches)} cases")
        print(f"Public behavior matches {revision} on {len(sources)} source samples and {len(cases)} CLI cases.")


def verify_negative_control(revision: str, candidate: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="messpy-state-negative-") as temporary:
        broken = Path(temporary)
        shutil.copytree(candidate / "src", broken / "src", ignore=shutil.ignore_patterns("__pycache__"))
        cli = broken / "src" / "messpy" / "cli.py"
        before = "return replace(self, parsed=parsed, index=index)"
        source = cli.read_text(encoding="utf-8")
        if source.count(before) != 1:
            raise AssertionError("Argument cursor transition moved; update the negative control")
        cli.write_text(source.replace(before, "return replace(self, parsed=parsed, index=len(self.arguments))"), encoding="utf-8")
        try:
            verify(revision, broken)
        except SystemExit as failure:
            if isinstance(failure.code, str) and failure.code.startswith("public behavior differs"):
                print("Negative control detected: an argument cursor that stops after its first token.")
                return
            raise
        raise AssertionError("The comparison accepted a broken argument cursor")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="3448957")
    parser.add_argument("--candidate", type=Path, default=ROOT)
    parser.add_argument("--negative-control", action="store_true", help="Require detection of a deliberately broken cursor in a temporary copy")
    arguments = parser.parse_args()
    check = verify_negative_control if arguments.negative_control else verify
    check(arguments.baseline, arguments.candidate.resolve())
