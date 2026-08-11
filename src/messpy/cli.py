from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from typing import Sequence, TextIO

from .rulesets import LoadedRule, RulesetError, filter_rules, load_rulesets


RULE_NAME = "ExcessiveMethodLength"
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
REQUIRED_ARGUMENTS = "<paths> <format> <ruleset[,ruleset...]>"
VALUE_OPTIONS = frozenset(
    {
        "--exclude",
        "--maximum-priority",
        "--maximumpriority",
        "--minimum-priority",
        "--minimumpriority",
        "--only",
        "--enable",
        "--disable",
        "--report-file",
        "--reportfile",
        "--suffixes",
    }
)
BOOLEAN_OPTIONS = frozenset(
    {
        "--ignore-errors-on-exit",
        "--ignore-tests",
        "--ignore-violations-on-exit",
        "--verbose",
    }
)


@dataclass(frozen=True)
class ParsedArguments:
    paths: list[str]
    report_format: str
    rulesets: list[str]
    suffixes: set[str]
    exclusions: list[str]
    ignore_tests: bool
    ignore_errors_on_exit: bool
    ignore_violations_on_exit: bool
    report_file: Path | None
    only: list[str]
    enable: list[str]
    disable: list[str]
    minimum_priority: int
    maximum_priority: int
    verbose: bool
    show_help: bool
    show_version: bool


class CliError(Exception):
    def __init__(self, message: str, ignore_errors_on_exit: bool = False) -> None:
        super().__init__(message)
        self.ignore_errors_on_exit = ignore_errors_on_exit


def run(arguments: Sequence[str], stdout: TextIO, stderr: TextIO) -> int:
    parsed_arguments: ParsedArguments | None = None
    try:
        parsed_arguments = _parse_arguments(arguments)
        if parsed_arguments.show_help:
            stdout.write(_help_text())
            return 0
        if parsed_arguments.show_version:
            stdout.write(f"{version('messpy')}\n")
            return 0
        if parsed_arguments.report_format.lower() != "text":
            raise CliError(f"Unknown format: {parsed_arguments.report_format}")
        rules = filter_rules(
            load_rulesets(parsed_arguments.rulesets),
            parsed_arguments.only,
            parsed_arguments.enable,
            parsed_arguments.disable,
            parsed_arguments.minimum_priority,
            parsed_arguments.maximum_priority,
        )
        if parsed_arguments.verbose:
            stderr.write(f"Loaded rules: {', '.join(rule.name for rule in rules)}\n")

        input_paths = [Path(value).resolve() for value in parsed_arguments.paths]
        source_files = _source_files(
            input_paths,
            parsed_arguments.suffixes,
            parsed_arguments.exclusions,
            parsed_arguments.ignore_tests,
        )
        findings, processing_errors = _analyze(source_files, rules)
        report = _text_report(findings, processing_errors)
        if parsed_arguments.report_file is None:
            stdout.write(report)
        else:
            _write_report(parsed_arguments.report_file, report)
        return _exit_status(
            findings,
            processing_errors,
            parsed_arguments.ignore_errors_on_exit,
            parsed_arguments.ignore_violations_on_exit,
        )
    except (CliError, RulesetError) as error:
        stderr.write(f"Error: {error}\n")
        if (parsed_arguments and parsed_arguments.ignore_errors_on_exit) or getattr(
            error, "ignore_errors_on_exit", False
        ):
            return 0
        return 1
    except OSError as error:
        stderr.write(f"Error: {error}\n")
        return 0 if parsed_arguments and parsed_arguments.ignore_errors_on_exit else 1


def main() -> None:
    raise SystemExit(run(sys.argv[1:], sys.stdout, sys.stderr))


def _parse_arguments(arguments: Sequence[str]) -> ParsedArguments:
    positionals: list[str] = []
    suffixes = {".py", ".pyi"}
    exclusions: list[str] = []
    report_file: Path | None = None
    ignore_tests = False
    ignore_errors_on_exit = False
    ignore_violations_on_exit = False
    verbose = False
    only: list[str] = []
    enable: list[str] = []
    disable: list[str] = []
    minimum_priority = 1
    maximum_priority = 5
    show_help = False
    show_version = False
    suffixes_provided = False

    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in {"-h", "--help"}:
            show_help = True
            index += 1
            continue
        if argument in {"-v", "--version"}:
            show_version = True
            index += 1
            continue
        if not argument.startswith("-"):
            positionals.append(argument)
            index += 1
            continue

        option_name, option_value = _split_option(argument)
        if option_name in VALUE_OPTIONS:
            if option_value is None:
                if index + 1 == len(arguments) or arguments[index + 1].startswith("-"):
                    raise CliError(f"Missing value for option: {option_name}", ignore_errors_on_exit)
                option_value = arguments[index + 1]
                index += 1
            if option_name in {"--report-file", "--reportfile"}:
                report_file = Path(option_value)
            elif option_name == "--suffixes":
                normalized_suffixes = _normalized_suffixes(option_value)
                suffixes = normalized_suffixes if not suffixes_provided else suffixes | normalized_suffixes
                suffixes_provided = True
            elif option_name == "--exclude":
                exclusions.extend(_split_nonempty(option_value))
            elif option_name in {"--only", "--enable", "--disable"}:
                values = _split_nonempty(option_value)
                if option_name == "--only":
                    only.extend(values)
                elif option_name == "--enable":
                    enable.extend(values)
                else:
                    disable.extend(values)
            elif option_name in {"--minimum-priority", "--minimumpriority"}:
                minimum_priority = _parse_priority(option_name, option_value, ignore_errors_on_exit)
            else:
                maximum_priority = _parse_priority(option_name, option_value, ignore_errors_on_exit)
            index += 1
            continue
        if option_name in BOOLEAN_OPTIONS:
            if option_value is not None:
                raise CliError(f"Option does not accept a value: {option_name}", ignore_errors_on_exit)
            if option_name == "--ignore-tests":
                ignore_tests = True
            elif option_name == "--ignore-errors-on-exit":
                ignore_errors_on_exit = True
            elif option_name == "--verbose":
                verbose = True
            else:
                ignore_violations_on_exit = True
            index += 1
            continue
        raise CliError(f"Unknown option: {option_name}", ignore_errors_on_exit)

    if show_help or show_version:
        if positionals:
            raise CliError(f"Unexpected positional argument: {positionals[0]}", ignore_errors_on_exit)
        return ParsedArguments(
            paths=[],
            report_format="",
            rulesets=[],
            suffixes=suffixes,
            exclusions=exclusions,
            ignore_tests=ignore_tests,
            ignore_errors_on_exit=ignore_errors_on_exit,
            ignore_violations_on_exit=ignore_violations_on_exit,
            report_file=report_file,
            only=only,
            enable=enable,
            disable=disable,
            minimum_priority=minimum_priority,
            maximum_priority=maximum_priority,
            verbose=verbose,
            show_help=show_help,
            show_version=show_version,
        )
    if len(positionals) < 3:
        raise CliError(f"Missing required arguments: {REQUIRED_ARGUMENTS}", ignore_errors_on_exit)
    if len(positionals) > 3:
        raise CliError(f"Unexpected positional argument: {positionals[3]}", ignore_errors_on_exit)

    paths = _split_nonempty(positionals[0])
    if not paths:
        raise CliError("At least one input path is required", ignore_errors_on_exit)
    rulesets = _split_nonempty(positionals[2])
    if not rulesets:
        raise CliError("At least one ruleset is required", ignore_errors_on_exit)
    if minimum_priority > maximum_priority:
        raise CliError("Minimum priority must not exceed maximum priority.", ignore_errors_on_exit)
    return ParsedArguments(
        paths=paths,
        report_format=positionals[1],
        rulesets=rulesets,
        suffixes=suffixes,
        exclusions=exclusions,
        ignore_tests=ignore_tests,
        ignore_errors_on_exit=ignore_errors_on_exit,
        ignore_violations_on_exit=ignore_violations_on_exit,
        report_file=report_file,
        only=only,
        enable=enable,
        disable=disable,
        minimum_priority=minimum_priority,
        maximum_priority=maximum_priority,
        verbose=verbose,
        show_help=False,
        show_version=False,
    )


def _split_option(argument: str) -> tuple[str, str | None]:
    option_name, separator, option_value = argument.partition("=")
    return option_name, option_value if separator else None


def _parse_priority(option_name: str, value: str, ignore_errors_on_exit: bool) -> int:
    try:
        priority = int(value)
    except ValueError as error:
        raise CliError(
            f"{option_name} expects a priority between 1 and 5, received '{value}'.",
            ignore_errors_on_exit,
        ) from error
    if not 1 <= priority <= 5:
        raise CliError(
            f"{option_name} expects a priority between 1 and 5, received '{value}'.",
            ignore_errors_on_exit,
        )
    return priority


def _analyze(source_files: Sequence[Path], rules: Sequence[LoadedRule]) -> tuple[list[str], list[str]]:
    findings: list[str] = []
    processing_errors: list[str] = []
    for source_file in source_files:
        try:
            source = source_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_file))
        except SyntaxError as error:
            line = error.lineno or 1
            processing_errors.append(
                f"{source_file.as_posix()}:{line}: ProcessingError Could not parse {source_file}: {error.msg}"
            )
            continue
        except (OSError, UnicodeError) as error:
            processing_errors.append(
                f"{source_file.as_posix()}:1: ProcessingError Could not process {source_file}: {error}"
            )
            continue
        findings.extend(_excessive_method_length_findings(source_file, tree, rules))
    return findings, processing_errors


def _text_report(findings: Sequence[str], processing_errors: Sequence[str]) -> str:
    entries = sorted([*findings, *processing_errors])
    return "" if not entries else "\n".join(entries) + "\n"


def _write_report(report_file: Path, report: str) -> None:
    temporary_file: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=report_file.parent,
            prefix=f".{report_file.name}.",
            delete=False,
        ) as output:
            temporary_file = Path(output.name)
            output.write(report)
        temporary_file.replace(report_file)
    except OSError as error:
        if temporary_file is not None:
            temporary_file.unlink(missing_ok=True)
        raise CliError(f"Unable to write report {report_file}: {error}") from error


def _exit_status(
    findings: Sequence[str],
    processing_errors: Sequence[str],
    ignore_errors_on_exit: bool,
    ignore_violations_on_exit: bool,
) -> int:
    if processing_errors and not ignore_errors_on_exit:
        return 1
    if findings and not ignore_violations_on_exit:
        return 2
    return 0


def _excessive_method_length_findings(
    path: Path, tree: ast.Module, rules: Sequence[LoadedRule]
) -> list[str]:
    rule = next((candidate for candidate in rules if candidate.name == RULE_NAME), None)
    if rule is None:
        return []
    try:
        method_length_limit = int(rule.properties["minimum"])
    except (KeyError, ValueError) as error:
        raise RulesetError("ExcessiveMethodLength property 'minimum' must be an integer.") from error
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        line_count = node.end_lineno - node.lineno + 1
        if line_count <= method_length_limit:
            continue
        display_path = path.as_posix()
        message = (
            f"The method {node.name} has {line_count} lines of code. "
            f"The configured limit is {method_length_limit}."
        )
        findings.append(
            f"{display_path}:{node.lineno}: {RULE_NAME} "
            f"[priority {rule.priority}] {message}"
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
        "Reporting:\n"
        "  --reportfile <path>               Write the complete report to a file\n"
        "  --only, --enable, --disable <list> Filter loaded rules\n"
        "  --minimumpriority <1-5>           Include priorities at or above the lower bound\n"
        "  --maximumpriority <1-5>           Include priorities at or below the upper bound\n"
        "  --verbose                         Show deterministic ruleset diagnostics\n"
        "  --ignore-errors-on-exit           Return success despite processing errors\n"
        "  --ignore-violations-on-exit       Return success despite findings\n"
        "\n"
        "Exit codes: 0 clean, 1 errors, 2 findings.\n"
    )
