from __future__ import annotations

import ast
from importlib.metadata import version
from pathlib import Path
import sys
from typing import Sequence, TextIO


RULE_NAME = "ExcessiveMethodLength"
RULE_PRIORITY = 3
METHOD_LENGTH_LIMIT = 100


def run(arguments: Sequence[str], stdout: TextIO, stderr: TextIO) -> int:
    if arguments == ["--help"] or arguments == ["-h"]:
        stdout.write(_help_text())
        return 0
    if arguments == ["--version"]:
        stdout.write(f"{version('messpy')}\n")
        return 0
    if len(arguments) != 3:
        stderr.write("usage: messpy <paths> <format> <ruleset[,ruleset...]> [options]\n")
        return 1

    path_argument, report_format, ruleset = arguments
    if report_format != "text":
        stderr.write(f"Unsupported report format: {report_format}\n")
        return 1
    if ruleset != "codesize":
        stderr.write(f"Unsupported ruleset: {ruleset}\n")
        return 1

    path = Path(path_argument)
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError) as error:
        stderr.write(f"Unable to process {path}: {error}\n")
        return 1

    findings = _excessive_method_length_findings(path, tree)
    for finding in findings:
        stdout.write(f"{finding}\n")
    return 2 if findings else 0


def main() -> None:
    raise SystemExit(run(sys.argv[1:], sys.stdout, sys.stderr))


def _excessive_method_length_findings(path: Path, tree: ast.Module) -> list[str]:
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        line_count = node.end_lineno - node.lineno + 1
        if line_count <= METHOD_LENGTH_LIMIT:
            continue
        display_path = path.as_posix()
        message = (
            f"The method {node.name} has {line_count} lines of code. "
            f"The configured limit is {METHOD_LENGTH_LIMIT}."
        )
        findings.append(
            f"{display_path}:{node.lineno}: {RULE_NAME} "
            f"[priority {RULE_PRIORITY}] {message}"
        )
    return findings


def _help_text() -> str:
    return (
        "usage: messpy <path> text codesize\n"
        "\n"
        "Exit codes: 0 clean, 1 errors, 2 findings.\n"
    )
