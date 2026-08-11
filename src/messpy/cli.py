from __future__ import annotations

import ast
from importlib.metadata import version
from pathlib import Path
import sys
from typing import Sequence, TextIO


RULE_NAME = "ExcessiveMethodLength"
RULE_PRIORITY = 3
METHOD_LENGTH_LIMIT = 100
DEFAULT_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".cache",
        ".git",
        ".hg",
        ".hypothesis",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "cache",
        "coverage",
        "dist",
        "env",
        "generated",
        "htmlcov",
        "out",
        "output",
        "site-packages",
        "tmp",
        "venv",
    }
)
TEST_DIRECTORY_NAMES = frozenset({"test", "tests", "__test__", "__tests__"})


def run(arguments: Sequence[str], stdout: TextIO, stderr: TextIO) -> int:
    if arguments == ["--help"] or arguments == ["-h"]:
        stdout.write(_help_text())
        return 0
    if arguments == ["--version"]:
        stdout.write(f"{version('messpy')}\n")
        return 0
    if len(arguments) < 3:
        stderr.write("usage: messpy <paths> <format> <ruleset[,ruleset...]> [options]\n")
        return 1

    path_argument, report_format, ruleset = arguments[:3]
    suffixes = {".py", ".pyi"}
    exclusions: list[str] = []
    ignore_tests = False
    option_arguments = arguments[3:]
    while option_arguments:
        option_name = option_arguments[0]
        if option_name == "--ignore-tests":
            ignore_tests = True
            option_arguments = option_arguments[1:]
            continue
        if len(option_arguments) < 2:
            stderr.write("Unsupported option\n")
            return 1
        option_value = option_arguments[1]
        option_arguments = option_arguments[2:]
        if option_name == "--suffixes":
            suffixes = _normalized_suffixes(option_value)
        elif option_name == "--exclude":
            exclusions.extend(_split_nonempty(option_value))
        else:
            stderr.write("Unsupported option\n")
            return 1
    if report_format != "text":
        stderr.write(f"Unsupported report format: {report_format}\n")
        return 1
    if ruleset != "codesize":
        stderr.write(f"Unsupported ruleset: {ruleset}\n")
        return 1

    input_paths = [Path(value).resolve() for value in _split_nonempty(path_argument)]
    try:
        source_files = _source_files(input_paths, suffixes, exclusions, ignore_tests)
    except OSError as error:
        stderr.write(f"Unable to process {path_argument}: {error}\n")
        return 1

    findings: list[str] = []
    for source_file in source_files:
        try:
            source = source_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_file))
        except (OSError, SyntaxError) as error:
            stderr.write(f"Unable to process {source_file}: {error}\n")
            return 1
        findings.extend(_excessive_method_length_findings(source_file, tree))

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


def _source_files(
    paths: Sequence[Path], suffixes: set[str], exclusions: Sequence[str], ignore_tests: bool
) -> list[Path]:
    source_files: set[Path] = set()
    for path in paths:
        source_files.update(_source_files_under(path, suffixes, exclusions, ignore_tests))
    return sorted(source_files, key=lambda candidate: candidate.as_posix())


def _source_files_under(
    path: Path, suffixes: set[str], exclusions: Sequence[str], ignore_tests: bool
) -> set[Path]:
    if _is_excluded(path, exclusions) or (ignore_tests and _is_test_path(path)):
        return set()
    if path.is_file():
        return {path} if path.suffix.lower() in suffixes else set()
    if not path.is_dir():
        raise OSError("Input path does not exist")

    source_files: set[Path] = set()
    for candidate in sorted(path.iterdir(), key=lambda entry: entry.name):
        if candidate.is_dir():
            if candidate.is_symlink() or candidate.name.lower() in DEFAULT_IGNORED_DIRECTORY_NAMES:
                continue
            source_files.update(_source_files_under(candidate, suffixes, exclusions, ignore_tests))
        elif (
            candidate.is_file()
            and candidate.suffix.lower() in suffixes
            and not _is_excluded(candidate, exclusions)
            and not (ignore_tests and _is_test_path(candidate))
        ):
            source_files.add(candidate.resolve())
    return source_files


def _split_nonempty(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _normalized_suffixes(value: str) -> set[str]:
    return {
        suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
        for suffix in _split_nonempty(value)
    }


def _is_excluded(path: Path, exclusions: Sequence[str]) -> bool:
    normalized_path = path.as_posix()
    return any(exclusion in normalized_path for exclusion in exclusions)


def _is_test_path(path: Path) -> bool:
    return (
        any(part.lower() in TEST_DIRECTORY_NAMES for part in path.parts[:-1])
        or path.name.lower().startswith("test_")
        or path.stem.lower().endswith("_test")
    )


def _help_text() -> str:
    return (
        "usage: messpy <paths> text codesize\n"
        "\n"
        "Source discovery:\n"
        "  --suffixes <list>  Replace source suffixes (default: .py,.pyi)\n"
        "  --exclude <paths>  Skip matching source paths\n"
        "  --ignore-tests     Skip test_*.py, *_test.py, and test or tests directories\n"
        "  Input directory symlinks are scanned; nested directory symlinks are skipped.\n"
        "\n"
        "Exit codes: 0 clean, 1 errors, 2 findings.\n"
    )
