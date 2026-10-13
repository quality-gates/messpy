from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import tempfile


SEMANTIC_SOURCE = '''print("loaded")
def calculate(value):
    return value + 1
def mutate(values):
    values.append(1)
def private():
    values = []
    mutate(values)
    return len(values)
def shared(values):
    mutate(values)
def unknown(value, callback):
    return callback(value)
async def task(value):
    print(value)
def cold(value):
    return task(value)
async def force(value):
    work = task(value)
    await work
'''
SEMANTIC_FINDINGS = Counter({
    ("<module>", "ImplicitOutput", 1): 1,
    ("mutate", "ImplicitOutput", 5): 1,
    ("shared", "ImplicitOutput", 11): 1,
    ("unknown", "UnknownEffect", 13): 1,
    ("task", "ImplicitOutput", 15): 1,
    ("force", "ImplicitOutput", 20): 1,
})


def _run(executable: Path, paths: str, rulesets: str) -> dict:
    result = subprocess.run(
        [executable, paths, "json", rulesets, "--ignore-tests", "--strict"],
        capture_output=True, text=True, check=False,
    )
    if result.stderr or result.returncode not in {0, 2}:
        raise AssertionError(f"installed analysis failed ({result.returncode}): {result.stderr}")
    report = json.loads(result.stdout)
    if report["errors"]:
        raise AssertionError(f"installed analysis returned processing errors: {report['errors']}")
    expected_status = 2 if report["findings"] else 0
    if result.returncode != expected_status:
        raise AssertionError(f"installed analysis exited {result.returncode}; expected {expected_status}")
    return report


def _records(findings: list[dict]) -> Counter:
    return Counter((finding["context"], finding["ruleName"], finding["line"]) for finding in findings)


def _closed_observations(report: dict, sources: dict[Path, str]) -> None:
    rules = {"ImplicitInput", "ImplicitOutput", "UnknownEffect"}
    owners = {path: _owners(source) for path, source in sources.items()}
    for finding in report["findings"]:
        path = Path(finding["path"]).resolve()
        if path not in sources:
            raise AssertionError(f"finding has an unanalysed path: {finding}")
        if finding["ruleName"] not in rules or finding["context"] not in owners[path]:
            raise AssertionError(f"finding has an invalid rule or owner: {finding}")
        if type(finding["line"]) is not int or not 1 <= finding["line"] <= len(sources[path].splitlines()):
            raise AssertionError(f"finding has an invalid effect line: {finding}")
        if finding["suppressed"] or not finding["message"]:
            raise AssertionError(f"finding is suppressed or has no explanation: {finding}")


def _owners(source: str) -> set[str]:
    tree = ast.parse(source)
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    names = {node.name for node in ast.walk(tree) if isinstance(node, functions)}
    names.update(f"{owner.name}.{node.name}" for owner in ast.walk(tree) if isinstance(owner, ast.ClassDef)
                 for node in owner.body if isinstance(node, functions))
    return names | {"<module>", "<lambda>", "<genexpr>"}


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    return f"{_dotted(node.value)}.{node.attr}" if isinstance(node, ast.Attribute) else ""


def _production_expectations(source: str) -> tuple[Counter, Counter]:
    tree = ast.parse(source)
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    ambient_defaults = {"sys.argv", "sys.stdout", "sys.stderr"}
    inputs = Counter(("<module>", "ImplicitInput", value.lineno) for value in main.args.defaults
                     if _dotted(value) in ambient_defaults)
    if len(inputs) != 3:
        raise AssertionError("main must retain three literal ambient defaults for artifact verification")
    destination = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_destination_file_mode")
    calls = [node for node in ast.walk(destination) if isinstance(node, ast.Call)]
    operations = {"report_file.stat", "stat.S_IMODE", "os.umask"}
    unknown = Counter(("_destination_file_mode", "UnknownEffect", max(call.lineno for call in calls if _dotted(call.func) == operation))
                      for operation in operations)
    return inputs, unknown


def verify(executable: Path) -> None:
    structural = _run(executable, "src/messpy", "rulesets/messpy-onion.xml,codesize,design,unusedcode")
    if structural["findings"]:
        raise AssertionError(f"production structural/onion violations: {structural['findings']}")
    sources = {path.resolve(): path.read_text(encoding="utf-8") for path in Path("src/messpy").glob("*.py")}
    report = _run(executable, "src/messpy", "explicitness")
    _closed_observations(report, sources)
    cli = Path("src/messpy/cli.py").resolve()
    findings = [finding for finding in report["findings"] if Path(finding["path"]).resolve() == cli]
    inputs, unknown = _production_expectations(sources[cli])
    checks = [
        (_records([finding for finding in findings if finding["context"] == "_help_text"]), Counter()),
        (_records([finding for finding in findings if finding["context"] == "<module>" and finding["ruleName"] == "ImplicitInput"]), inputs),
        (_records([finding for finding in findings if finding["context"] == "_destination_file_mode"]), unknown),
    ]
    for actual, expected in checks:
        if actual != expected:
            raise AssertionError(f"production explicitness mismatch: {actual}; expected {expected}")
    with tempfile.TemporaryDirectory() as temporary:
        fixture = Path(temporary) / "artifact_semantics.py"
        fixture.write_text(SEMANTIC_SOURCE, encoding="utf-8")
        semantic = _run(executable, str(fixture), "explicitness")
        _closed_observations(semantic, {fixture.resolve(): SEMANTIC_SOURCE})
        if _records(semantic["findings"]) != SEMANTIC_FINDINGS:
            raise AssertionError(f"artifact semantics mismatch: {_records(semantic['findings'])}; expected {SEMANTIC_FINDINGS}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_self_analysis.py MESSPY")
    verify(Path(sys.argv[1]))
