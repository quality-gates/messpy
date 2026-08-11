from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from html import escape as html_escape
import json
import re
import symtable
import sys
import token
import tokenize
from importlib.metadata import PackageNotFoundError, version
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TextIO

from .rulesets import LoadedRule, RulesetError, filter_rules, load_rulesets

METHOD_LENGTH_RULE_NAME = "ExcessiveMethodLength"
CYCLOMATIC_COMPLEXITY_RULE_NAME = "CyclomaticComplexity"
NPATH_COMPLEXITY_RULE_NAME = "NPathComplexity"
EXCESSIVE_PARAMETER_LIST_RULE_NAME = "ExcessiveParameterList"
EXCESSIVE_CLASS_LENGTH_RULE_NAME = "ExcessiveClassLength"
EXCESSIVE_PUBLIC_COUNT_RULE_NAME = "ExcessivePublicCount"
TOO_MANY_FIELDS_RULE_NAME = "TooManyFields"
TOO_MANY_METHODS_RULE_NAME = "TooManyMethods"
TOO_MANY_PUBLIC_METHODS_RULE_NAME = "TooManyPublicMethods"
EXCESSIVE_CLASS_COMPLEXITY_RULE_NAME = "ExcessiveClassComplexity"
SHORT_CLASS_NAME_RULE_NAME = "ShortClassName"
LONG_CLASS_NAME_RULE_NAME = "LongClassName"
SHORT_VARIABLE_RULE_NAME = "ShortVariable"
LONG_VARIABLE_RULE_NAME = "LongVariable"
SHORT_METHOD_NAME_RULE_NAME = "ShortMethodName"
CONSTANT_NAMING_CONVENTIONS_RULE_NAME = "ConstantNamingConventions"
BOOLEAN_GET_METHOD_NAME_RULE_NAME = "BooleanGetMethodName"
UNUSED_LOCAL_VARIABLE_RULE_NAME = "UnusedLocalVariable"
UNUSED_FORMAL_PARAMETER_RULE_NAME = "UnusedFormalParameter"
UNUSED_PRIVATE_FIELD_RULE_NAME = "UnusedPrivateField"
UNUSED_PRIVATE_METHOD_RULE_NAME = "UnusedPrivateMethod"
REPORT_FORMATS = frozenset(
    {"text", "xml", "json", "html", "ansi", "github", "gitlab", "checkstyle", "sarif"}
)
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
        "--color",
    }
)
BOOLEAN_OPTIONS = frozenset(
    {
        "--ignore-errors-on-exit",
        "--ignore-tests",
        "--ignore-violations-on-exit",
        "--strict",
        "--verbose",
    }
)
DIRECTIVE_PATTERN = re.compile(
    r"^messpy-(disable-next-line|disable|enable)(?:\s+(.+?))?$", re.IGNORECASE
)
RULE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
    strict: bool
    verbose: bool
    color: str
    show_help: bool
    show_version: bool


class CliError(Exception):
    def __init__(self, message: str, ignore_errors_on_exit: bool = False) -> None:
        super().__init__(message)
        self.ignore_errors_on_exit = ignore_errors_on_exit


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    rule_name: str
    priority: int
    message: str
    suppressed: bool = False
    context: str = ""


@dataclass(frozen=True)
class ProcessingError:
    path: Path
    line: int
    message: str


@dataclass(frozen=True)
class CallableInfo:
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    name: str
    kind: str
    parameter_count: int


@dataclass(frozen=True)
class ClassInfo:
    node: ast.ClassDef
    name: str
    fields: tuple[str, ...]
    methods: tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]


@dataclass(frozen=True)
class NamingTarget:
    name: str
    line: int
    role: str


@dataclass(frozen=True)
class NamingCallable:
    node: ast.FunctionDef | ast.AsyncFunctionDef
    role: str


@dataclass(frozen=True)
class ScopeUsage:
    used_names: frozenset[str]
    free_names: frozenset[str]


@dataclass(frozen=True)
class PrivateMemberUsage:
    accessed_names: frozenset[str]
    exported_names: frozenset[str]
    requires_conservative_handling: bool


def run(arguments: Sequence[str], stdout: TextIO, stderr: TextIO) -> int:
    parsed_arguments: ParsedArguments | None = None
    try:
        parsed_arguments = _parse_arguments(arguments)
        if parsed_arguments.show_help:
            stdout.write(_help_text())
            return 0
        if parsed_arguments.show_version:
            stdout.write(f"{_messpy_version()}\n")
            return 0
        if parsed_arguments.report_format.lower() not in REPORT_FORMATS:
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
        reported_findings = findings if parsed_arguments.strict else _unsuppressed(findings)
        report = _render_report(
            parsed_arguments.report_format,
            reported_findings,
            processing_errors,
            _use_color(parsed_arguments, stdout),
        )
        if parsed_arguments.report_file is None:
            stdout.write(report)
        else:
            _write_report(parsed_arguments.report_file, report)
        return _exit_status(
            reported_findings,
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


def _messpy_version() -> str:
    try:
        return version("messpy")
    except PackageNotFoundError:
        return "0.1.0"


def _parse_arguments(arguments: Sequence[str]) -> ParsedArguments:
    positionals: list[str] = []
    suffixes = {".py", ".pyi"}
    exclusions: list[str] = []
    report_file: Path | None = None
    ignore_tests = False
    ignore_errors_on_exit = False
    ignore_violations_on_exit = False
    strict = False
    verbose = False
    color = "auto"
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
            elif option_name == "--color":
                color = _parse_color(option_value, ignore_errors_on_exit)
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
            elif option_name == "--strict":
                strict = True
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
            strict=strict,
            verbose=verbose,
            color=color,
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
        strict=strict,
        verbose=verbose,
        color=color,
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


def _parse_color(value: str, ignore_errors_on_exit: bool) -> str:
    color = value.casefold()
    if color in {"auto", "always", "never"}:
        return color
    raise CliError(
        f"--color expects auto, always, or never, received '{value}'.", ignore_errors_on_exit
    )


def _analyze(
    source_files: Sequence[Path], rules: Sequence[LoadedRule]
) -> tuple[list[Finding], list[ProcessingError]]:
    findings: list[Finding] = []
    processing_errors: list[ProcessingError] = []
    for source_file in source_files:
        try:
            source = source_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_file))
        except SyntaxError as error:
            line = error.lineno or 1
            processing_errors.append(
                ProcessingError(source_file, line, f"Could not parse {source_file}: {error.msg}")
            )
            continue
        except (OSError, UnicodeError) as error:
            processing_errors.append(ProcessingError(source_file, 1, f"Could not process {source_file}: {error}"))
            continue
        findings.extend(_apply_suppressions(source, _findings(source_file, source, tree, rules)))
    return findings, processing_errors


def _render_report(
    report_format: str,
    findings: Sequence[Finding],
    processing_errors: Sequence[ProcessingError],
    color: bool,
) -> str:
    renderer = {
        "text": lambda: _text_report_with_color(findings, processing_errors, color),
        "xml": lambda: _xml_report(findings, processing_errors),
        "json": lambda: _json_report(findings, processing_errors),
        "html": lambda: _html_report(findings, processing_errors),
        "ansi": lambda: _text_report_with_color(findings, processing_errors, True),
        "github": lambda: _github_report(findings, processing_errors),
        "gitlab": lambda: _gitlab_report(findings, processing_errors),
        "checkstyle": lambda: _checkstyle_report(findings, processing_errors),
        "sarif": lambda: _sarif_report(findings, processing_errors),
    }
    return renderer[report_format.casefold()]()


def _ordered_findings(findings: Sequence[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda finding: (
            _report_path(finding.path),
            finding.line,
            finding.rule_name,
            finding.message,
            finding.context,
            finding.priority,
        ),
    )


def _ordered_errors(errors: Sequence[ProcessingError]) -> list[ProcessingError]:
    return sorted(errors, key=lambda error: (_report_path(error.path), error.line, error.message))


def _report_path(path: Path) -> str:
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved_path.as_posix()


def _finding_record(finding: Finding) -> dict[str, str | int | bool]:
    return {
        "path": _report_path(finding.path),
        "line": finding.line,
        "column": 1,
        "ruleName": finding.rule_name,
        "priority": finding.priority,
        "message": finding.message,
        "context": finding.context,
        "suppressed": finding.suppressed,
    }


def _error_record(error: ProcessingError) -> dict[str, str | int | bool]:
    return {
        "path": _report_path(error.path),
        "line": error.line,
        "column": 1,
        "ruleName": "ProcessingError",
        "priority": 1,
        "message": error.message,
        "context": "",
        "suppressed": False,
    }


def _json_report(findings: Sequence[Finding], processing_errors: Sequence[ProcessingError]) -> str:
    return json.dumps(
        {
            "tool": {"name": "messpy", "version": _messpy_version()},
            "findings": [_finding_record(finding) for finding in _ordered_findings(findings)],
            "errors": [_error_record(error) for error in _ordered_errors(processing_errors)],
        },
        indent=2,
    ) + "\n"


def _xml_attributes(values: dict[str, str | int | bool]) -> str:
    return "".join(f' {name}="{html_escape(str(value), quote=True)}"' for name, value in values.items())


def _xml_report(findings: Sequence[Finding], processing_errors: Sequence[ProcessingError]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<messpy version="{_messpy_version()}">',
        f'  <tool name="messpy" version="{_messpy_version()}" />',
        "  <findings>",
    ]
    lines.extend(f"    <finding{_xml_attributes(_finding_record(finding))} />" for finding in _ordered_findings(findings))
    lines.extend(["  </findings>", "  <errors>"])
    lines.extend(f"    <error{_xml_attributes(_error_record(error))} />" for error in _ordered_errors(processing_errors))
    lines.extend(["  </errors>", "</messpy>"])
    return "\n".join(lines) + "\n"


def _html_report(findings: Sequence[Finding], processing_errors: Sequence[ProcessingError]) -> str:
    lines = [
        "<!DOCTYPE html>",
        '<html><head><meta charset="utf-8"><title>messpy report</title></head><body>',
        "<h1>messpy report</h1>",
        "<table><tr><th>Path</th><th>Line</th><th>Rule</th><th>Priority</th><th>Message</th><th>Context</th><th>State</th></tr>",
    ]
    for finding in _ordered_findings(findings):
        record = _finding_record(finding)
        lines.append(
            "<tr>"
            f"<td>{html_escape(str(record['path']))}</td><td>{record['line']}</td>"
            f"<td>{html_escape(str(record['ruleName']))}</td><td>{record['priority']}</td>"
            f"<td>{html_escape(str(record['message']))}</td><td>{html_escape(str(record['context']))}</td>"
            f"<td>{'suppressed' if record['suppressed'] else ''}</td></tr>"
        )
    lines.append("</table>")
    if processing_errors:
        lines.extend(
            [
                "<h2>Processing errors</h2>",
                "<table><tr><th>Path</th><th>Line</th><th>Rule</th><th>Message</th></tr>",
            ]
        )
        for error in _ordered_errors(processing_errors):
            record = _error_record(error)
            lines.append(
                f"<tr><td>{html_escape(str(record['path']))}</td><td>{record['line']}</td><td>ProcessingError</td>"
                f"<td>{html_escape(str(record['message']))}</td></tr>"
            )
        lines.append("</table>")
    lines.append("</body></html>")
    return "\n".join(lines) + "\n"


def _text_report_with_color(
    findings: Sequence[Finding], processing_errors: Sequence[ProcessingError], color: bool
) -> str:
    entries = [_colored_finding(finding, color) for finding in _ordered_findings(findings)]
    entries.extend(_colored_error(error, color) for error in _ordered_errors(processing_errors))
    return "" if not entries else "\n".join(entries) + "\n"


def _colored_finding(finding: Finding, color: bool) -> str:
    label = f"{finding.rule_name} [priority {finding.priority}]"
    if finding.suppressed:
        label += " [suppressed]"
    if color:
        label = f"\x1b[33m{label}\x1b[0m"
        message = f"\x1b[31m{finding.message}\x1b[0m"
    else:
        message = finding.message
    return f"{_report_path(finding.path)}:{finding.line}: {label} {message}"


def _colored_error(error: ProcessingError, color: bool) -> str:
    message = f"ProcessingError {error.message}"
    if color:
        message = f"\x1b[31m{message}\x1b[0m"
    return f"{_report_path(error.path)}:{error.line}: {message}"


def _github_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A").replace(":", "%3A").replace(",", "%2C")


def _github_report(findings: Sequence[Finding], processing_errors: Sequence[ProcessingError]) -> str:
    lines = []
    for finding in _ordered_findings(findings):
        record = _finding_record(finding)
        title = _github_escape(f"{record['ruleName']} [priority {record['priority']}]")
        message = _github_escape(
            f"{record['message']} (context: {record['context']})"
            f"{' [suppressed]' if record['suppressed'] else ''}"
        )
        lines.append(
            f"::warning file={_github_escape(str(record['path']))},line={record['line']},col=1,title={title}::{message}"
        )
    for error in _ordered_errors(processing_errors):
        record = _error_record(error)
        lines.append(
            f"::error file={_github_escape(str(record['path']))},line={record['line']},col=1,title=ProcessingError::{_github_escape(str(record['message']))}"
        )
    return "" if not lines else "\n".join(lines) + "\n"


def _gitlab_severity(priority: int) -> str:
    return {1: "blocker", 2: "critical", 3: "major", 4: "minor", 5: "info"}[priority]


def _gitlab_entry(record: dict[str, str | int | bool]) -> dict[str, object]:
    path = str(record["path"])
    line = int(record["line"])
    rule_name = str(record["ruleName"])
    message = str(record["message"])
    fingerprint_input = f"{path}:{line}:1:{rule_name}:{message}".encode("utf-8")
    return {
        "type": "issue",
        "tool": {"name": "messpy", "version": _messpy_version()},
        "check_name": rule_name,
        "description": f"{message} (context: {record['context']})"
        f"{' [suppressed]' if record['suppressed'] else ''}",
        "fingerprint": fingerprint_input.hex(),
        "severity": _gitlab_severity(int(record["priority"])),
        "location": {"path": path, "lines": {"begin": line}},
        "priority": record["priority"],
        "context": record["context"],
        "suppressed": record["suppressed"],
    }


def _gitlab_report(findings: Sequence[Finding], processing_errors: Sequence[ProcessingError]) -> str:
    entries = [_gitlab_entry(_finding_record(finding)) for finding in _ordered_findings(findings)]
    entries.extend(_gitlab_entry(_error_record(error)) for error in _ordered_errors(processing_errors))
    return json.dumps(entries, indent=2) + "\n"


def _checkstyle_report(findings: Sequence[Finding], processing_errors: Sequence[ProcessingError]) -> str:
    records = [*(_finding_record(finding) for finding in _ordered_findings(findings))]
    records.extend(_error_record(error) for error in _ordered_errors(processing_errors))
    by_path: dict[str, list[dict[str, str | int | bool]]] = defaultdict(list)
    for record in records:
        by_path[str(record["path"])].append(record)
    lines = [f'<checkstyle tool="messpy" version="{_messpy_version()}">']
    for path in sorted(by_path):
        lines.append(f'  <file name="{html_escape(path, quote=True)}">')
        for record in by_path[path]:
            severity = "error" if int(record["priority"]) <= 2 else "warning"
            source = f"messpy.{record['ruleName']}"
            lines.append(
                "    <error"
                f' line="{record["line"]}" column="1" severity="{severity}"'
                f' message="{html_escape(str(record["message"]), quote=True)}"'
                f' source="{html_escape(source, quote=True)}"'
                f' context="{html_escape(str(record["context"]), quote=True)}"'
                f' priority="{record["priority"]}" suppressed="{str(record["suppressed"]).lower()}" />'
            )
        lines.append("  </file>")
    lines.append("</checkstyle>")
    return "\n".join(lines) + "\n"


def _sarif_level(priority: int) -> str:
    return "error" if priority <= 2 else "warning"


def _sarif_location(record: dict[str, str | int | bool]) -> dict[str, object]:
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": record["path"]},
            "region": {"startLine": record["line"], "startColumn": 1},
        }
    }


def _sarif_report(findings: Sequence[Finding], processing_errors: Sequence[ProcessingError]) -> str:
    ordered_findings = _ordered_findings(findings)
    rules = sorted({finding.rule_name for finding in ordered_findings})
    results = []
    for finding in ordered_findings:
        record = _finding_record(finding)
        result: dict[str, object] = {
            "ruleId": record["ruleName"],
            "level": _sarif_level(int(record["priority"])),
            "message": {"text": record["message"]},
            "locations": [_sarif_location(record)],
            "properties": {
                "priority": record["priority"],
                "context": record["context"],
                "suppressed": record["suppressed"],
            },
        }
        if record["suppressed"]:
            result["suppressions"] = [{"kind": "inSource"}]
        results.append(result)
    notifications = []
    for error in _ordered_errors(processing_errors):
        record = _error_record(error)
        notifications.append(
            {
                "level": "error",
                "message": {"text": f"{record['path']}:{record['line']}:1: {record['message']}"},
                "locations": [_sarif_location(record)],
            }
        )
    invocation: dict[str, object] = {"executionSuccessful": not processing_errors}
    if notifications:
        invocation["toolExecutionNotifications"] = notifications
    report = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "messpy",
                        "version": _messpy_version(),
                        "rules": [
                            {"id": name, "name": name, "shortDescription": {"text": name}}
                            for name in rules
                        ],
                    }
                },
                "results": results,
                "invocations": [invocation],
            }
        ],
    }
    return json.dumps(report, indent=2) + "\n"


def _use_color(parsed_arguments: ParsedArguments, stdout: TextIO) -> bool:
    if parsed_arguments.report_format.casefold() == "ansi":
        return True
    if parsed_arguments.report_format.casefold() != "text" or parsed_arguments.report_file is not None:
        return False
    if parsed_arguments.color == "always":
        return True
    if parsed_arguments.color == "never":
        return False
    return bool(getattr(stdout, "isatty", lambda: False)())


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
    findings: Sequence[Finding],
    processing_errors: Sequence[str],
    ignore_errors_on_exit: bool,
    ignore_violations_on_exit: bool,
) -> int:
    if processing_errors and not ignore_errors_on_exit:
        return 1
    if findings and not ignore_violations_on_exit:
        return 2
    return 0


def _findings(path: Path, source: str, tree: ast.Module, rules: Sequence[LoadedRule]) -> list[Finding]:
    return [
        *_cyclomatic_complexity_findings(path, tree, rules),
        *_npath_complexity_findings(path, tree, rules),
        *_excessive_method_length_findings(path, tree, rules),
        *_excessive_parameter_list_findings(path, tree, rules),
        *_class_findings(path, source, tree, rules),
        *_naming_findings(path, tree, rules),
        *_unused_local_variable_findings(path, source, tree, rules),
        *_unused_formal_parameter_findings(path, source, tree, rules),
        *_unused_private_field_findings(path, tree, rules),
        *_unused_private_method_findings(path, tree, rules),
    ]


def _unused_local_variable_findings(
    path: Path, source: str, tree: ast.Module, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, UNUSED_LOCAL_VARIABLE_RULE_NAME)
    if rule is None:
        return []
    findings: list[Finding] = []
    protocol_method_ids = _protocol_method_ids(tree)
    for node, table, used_names in _function_scopes(source, tree):
        if _is_conservative_callable(node, id(node) in protocol_method_ids):
            continue
        bindings = _FunctionLocalBindings()
        if isinstance(node, ast.Lambda):
            bindings.visit(node.body)
        else:
            for statement in node.body:
                bindings.visit(statement)
        reported: set[str] = set()
        for target in bindings.targets:
            symbol = table.lookup(target.id)
            if (
                target.id.startswith("_")
                or target.id in used_names
                or not symbol.is_local()
                or symbol.is_parameter()
                or target.id in reported
            ):
                continue
            reported.add(target.id)
            findings.append(
                Finding(
                    path,
                    target.lineno,
                    rule.name,
                    rule.priority,
                    f"Avoid unused local variables such as '{target.id}'.",
                    context=target.id,
                )
            )
    for node, table in _comprehension_scopes(source, tree):
        reported: set[str] = set()
        for generator in node.generators:
            for target in _target_names(generator.target):
                symbol = table.lookup(target.id)
                if (
                    target.id.startswith("_")
                    or symbol.is_referenced()
                    or not symbol.is_local()
                    or target.id in reported
                ):
                    continue
                reported.add(target.id)
                findings.append(
                    Finding(
                        path,
                        target.lineno,
                        rule.name,
                        rule.priority,
                        f"Avoid unused local variables such as '{target.id}'.",
                        context=target.id,
                    )
                )
    return findings


def _unused_formal_parameter_findings(
    path: Path, source: str, tree: ast.Module, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, UNUSED_FORMAL_PARAMETER_RULE_NAME)
    if rule is None:
        return []
    findings: list[Finding] = []
    protocol_method_ids = _protocol_method_ids(tree)
    for node, table, used_names in _function_scopes(source, tree):
        if _is_conservative_callable(node, id(node) in protocol_method_ids):
            continue
        for parameter in _arguments(node.args):
            symbol = table.lookup(parameter.arg)
            if (
                parameter.arg in {"self", "cls"}
                or parameter.arg.startswith("_")
                or parameter.arg in used_names
                or not symbol.is_parameter()
            ):
                continue
            findings.append(
                Finding(
                    path,
                    parameter.lineno,
                    rule.name,
                    rule.priority,
                    f"Avoid unused parameters such as '{parameter.arg}'.",
                    context=parameter.arg,
                )
            )
    return findings


def _is_conservative_callable(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, is_protocol_method: bool
) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
        is_protocol_method or bool(node.decorator_list) or _is_contract_method(node)
    )


def _protocol_method_ids(tree: ast.Module) -> set[int]:
    protocol_names = _protocol_base_names(tree)
    return {
        id(method)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _is_protocol(node, protocol_names)
        for method in node.body
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _function_scopes(
    source: str, tree: ast.Module
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, symtable.SymbolTable, frozenset[str]]]:
    tables: dict[tuple[str, int], symtable.SymbolTable] = {}
    _collect_function_tables(symtable.symtable(source, "<source>", "exec"), tables)
    scopes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        name = node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "lambda"
        table = tables.get((name, node.lineno))
        if table is not None:
            scopes.append((node, table, _scope_usage(table).used_names))
    return scopes


def _comprehension_scopes(
    source: str, tree: ast.Module
) -> list[tuple[ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp, symtable.SymbolTable]]:
    tables: defaultdict[tuple[str, int], list[symtable.SymbolTable]] = defaultdict(list)
    _collect_comprehension_tables(symtable.symtable(source, "<source>", "exec"), tables)
    names = {
        ast.ListComp: "listcomp",
        ast.SetComp: "setcomp",
        ast.DictComp: "dictcomp",
        ast.GeneratorExp: "genexpr",
    }
    scopes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            continue
        candidates = tables[(names[type(node)], node.lineno)]
        if candidates:
            scopes.append((node, candidates.pop(0)))
    return scopes


def _collect_comprehension_tables(
    table: symtable.SymbolTable, tables: defaultdict[tuple[str, int], list[symtable.SymbolTable]]
) -> None:
    if table.get_type() == "function" and table.get_name() in {"listcomp", "setcomp", "dictcomp", "genexpr"}:
        tables[(table.get_name(), table.get_lineno())].append(table)
    for child in table.get_children():
        _collect_comprehension_tables(child, tables)


def _collect_function_tables(
    table: symtable.SymbolTable, tables: dict[tuple[str, int], symtable.SymbolTable]
) -> None:
    if table.get_type() == "function":
        tables[(table.get_name(), table.get_lineno())] = table
    for child in table.get_children():
        _collect_function_tables(child, tables)


def _scope_usage(table: symtable.SymbolTable) -> ScopeUsage:
    local_names = {name for name in table.get_identifiers() if table.lookup(name).is_local()}
    used_names = {name for name in table.get_identifiers() if table.lookup(name).is_referenced()}
    free_names = {name for name in table.get_identifiers() if table.lookup(name).is_free()}
    for child in table.get_children():
        child_usage = _scope_usage(child)
        captured = child_usage.free_names & local_names
        used_names.update(captured)
        free_names.update(child_usage.free_names - captured)
    return ScopeUsage(frozenset(used_names), frozenset(free_names))


def _unused_private_field_findings(
    path: Path, tree: ast.Module, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, UNUSED_PRIVATE_FIELD_RULE_NAME)
    if rule is None:
        return []
    usage = _private_member_usage(tree)
    if usage.requires_conservative_handling:
        return []
    findings: list[Finding] = []
    dataclass_names = _dataclass_decorator_names(tree)
    for class_info in _classes(tree):
        if _is_dataclass(class_info.node, dataclass_names):
            continue
        fields = _PrivateFieldCollector(class_info.node).collect()
        for name, line in fields.items():
            if name in usage.accessed_names or name in usage.exported_names:
                continue
            findings.append(
                Finding(
                    path,
                    line,
                    rule.name,
                    rule.priority,
                    f"Avoid unused private fields such as '{name}'.",
                    context=name,
                )
            )
    return findings


def _unused_private_method_findings(
    path: Path, tree: ast.Module, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, UNUSED_PRIVATE_METHOD_RULE_NAME)
    if rule is None:
        return []
    usage = _private_member_usage(tree)
    if usage.requires_conservative_handling:
        return []
    findings: list[Finding] = []
    for class_info in _classes(tree):
        for method in class_info.methods:
            if (
                not _is_private_name(method.name)
                or method.name in usage.accessed_names
                or method.name in usage.exported_names
                or method.decorator_list
                or _is_contract_method(method)
            ):
                continue
            findings.append(
                Finding(
                    path,
                    method.lineno,
                    rule.name,
                    rule.priority,
                    f"Avoid unused private methods such as '{method.name}'.",
                    context=method.name,
                )
            )
    return findings


class _PrivateFieldCollector(ast.NodeVisitor):
    def __init__(self, node: ast.ClassDef) -> None:
        self.node = node
        self.fields: dict[str, int] = {}
        self.loads: set[str] = set()
        self.has_unknown_dynamic_access = False
        self.receiver: str | None = None

    def collect(self) -> dict[str, int]:
        for statement in self.node.body:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for target in targets:
                    for name in _assigned_names(target):
                        self._add_field(name, statement.lineno)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.receiver = _instance_receiver(statement)
                for item in statement.body:
                    self.visit(item)
        if self.has_unknown_dynamic_access:
            return {}
        return {name: line for name, line in self.fields.items() if name not in self.loads}

    def visit_Call(self, node: ast.Call) -> None:
        names, has_unknown_access = _dynamic_attribute_accesses(node)
        self.loads.update(names)
        self.has_unknown_dynamic_access = self.has_unknown_dynamic_access or has_unknown_access
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loads.add(node.attr)
        elif (
            isinstance(node.ctx, ast.Store)
            and self.receiver is not None
            and isinstance(node.value, ast.Name)
            and node.value.id == self.receiver
        ):
            self._add_field(node.attr, node.lineno)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def _add_field(self, name: str, line: int) -> None:
        if _is_private_name(name):
            self.fields.setdefault(name, line)


def _is_private_name(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _dataclass_decorator_names(tree: ast.Module) -> set[str]:
    return {
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom) and statement.module == "dataclasses"
        for alias in statement.names
        if alias.name == "dataclass"
    } | {"dataclass"}


def _is_dataclass(node: ast.ClassDef, decorator_names: set[str]) -> bool:
    return any(
        _called_name(decorator.func if isinstance(decorator, ast.Call) else decorator) in decorator_names | {"dataclass"}
        for decorator in node.decorator_list
    )


def _private_member_usage(tree: ast.Module) -> PrivateMemberUsage:
    dynamic_names, has_unknown_dynamic_access = _dynamic_attribute_accesses(tree, _dynamic_access_aliases(tree))
    exported_names, has_unknown_exports = _exported_names(tree)
    loads = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
    } | dynamic_names
    return PrivateMemberUsage(
        frozenset(loads),
        frozenset(exported_names),
        has_unknown_dynamic_access or has_unknown_exports,
    )


def _dynamic_access_aliases(tree: ast.Module) -> set[str]:
    return {
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom) and statement.module == "builtins"
        for alias in statement.names
        if alias.name in {"getattr", "hasattr", "setattr", "delattr"}
    }


def _exported_names(tree: ast.Module) -> tuple[set[str], bool]:
    names: set[str] = set()
    has_unknown_exports = False
    for statement in ast.walk(tree):
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value
        elif (
            isinstance(statement, ast.AugAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "__all__"
        ):
            has_unknown_exports = True
            continue
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            continue
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set)) or not all(
            isinstance(element, ast.Constant) and isinstance(element.value, str) for element in value.elts
        ):
            has_unknown_exports = True
            continue
        names.update(element.value for element in value.elts if isinstance(element, ast.Constant))
    return names, has_unknown_exports


def _dynamic_attribute_accesses(node: ast.AST, aliases: set[str] | None = None) -> tuple[set[str], bool]:
    names: set[str] = set()
    has_unknown_access = False
    calls = [node] if isinstance(node, ast.Call) else ast.walk(node)
    for candidate in calls:
        if not isinstance(candidate, ast.Call):
            continue
        function_name = _called_name(candidate.func)
        if function_name in {"getattr", "hasattr", "setattr", "delattr"} | (aliases or set()):
            attribute_index = 1
        elif function_name in {"__getattribute__", "__setattr__", "__delattr__"}:
            attribute_index = 0
        else:
            continue
        if len(candidate.args) <= attribute_index:
            continue
        attribute = candidate.args[attribute_index]
        if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str):
            names.add(attribute.value)
        else:
            has_unknown_access = True
    return names, has_unknown_access


class _FunctionLocalBindings(ast.NodeVisitor):
    def __init__(self) -> None:
        self.targets: list[ast.Name] = []

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.targets.append(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self._add_target(node.name, node.lineno, node.col_offset)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self._add_target(node.name, node.lineno, node.col_offset)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self._add_target(node.name, node.lineno, node.col_offset)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._add_named_expression_targets(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._add_named_expression_targets(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._add_named_expression_targets(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._add_named_expression_targets(node)

    def _add_named_expression_targets(self, node: ast.AST) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.NamedExpr):
                self.targets.extend(_target_names(child.target))

    def _add_target(self, name: str, line: int, column: int) -> None:
        self.targets.append(ast.Name(id=name, ctx=ast.Store(), lineno=line, col_offset=column))


def _naming_findings(path: Path, tree: ast.Module, rules: Sequence[LoadedRule]) -> list[Finding]:
    targets, callables = _naming_roles(tree)
    findings: list[Finding] = []
    findings.extend(_short_class_name_findings(path, targets, rules))
    findings.extend(_long_class_name_findings(path, targets, rules))
    findings.extend(_short_variable_findings(path, targets, rules))
    findings.extend(_long_variable_findings(path, targets, rules))
    findings.extend(_short_method_name_findings(path, targets, rules))
    findings.extend(_constant_naming_findings(path, targets, rules))
    findings.extend(_boolean_get_method_name_findings(path, callables, rules))
    return findings


def _short_class_name_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, SHORT_CLASS_NAME_RULE_NAME)
    if rule is None:
        return []
    minimum = _integer_property(rule, "minimum")
    return [
        _naming_finding(
            path,
            target,
            rule,
            f"Avoid using short class names like {target.name}. Configured minimum length is {minimum}.",
        )
        for target in targets
        if target.role == "class" and not _is_exempt_target(target) and len(target.name) < minimum
    ]


def _long_class_name_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, LONG_CLASS_NAME_RULE_NAME)
    if rule is None:
        return []
    maximum = _integer_property(rule, "maximum")
    return [
        _naming_finding(
            path,
            target,
            rule,
            f"Avoid excessively long class names like {target.name}. Configured maximum length is {maximum}.",
        )
        for target in targets
        if target.role == "class" and not _is_exempt_target(target) and len(target.name) > maximum
    ]


def _short_variable_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, SHORT_VARIABLE_RULE_NAME)
    if rule is None:
        return []
    minimum = _integer_property(rule, "minimum")
    return _variable_length_findings(path, targets, rule, minimum, too_long=False)


def _long_variable_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, LONG_VARIABLE_RULE_NAME)
    if rule is None:
        return []
    maximum = _integer_property(rule, "maximum")
    return _variable_length_findings(path, targets, rule, maximum, too_long=True)


def _variable_length_findings(
    path: Path, targets: Sequence[NamingTarget], rule: LoadedRule, limit: int, too_long: bool
) -> list[Finding]:
    if too_long:
        message = lambda target: (
            f"Avoid excessively long variable names like {target.name}. Configured maximum length is {limit}."
        )
    else:
        message = lambda target: f"Avoid variables with short names like {target.name}. Configured minimum length is {limit}."
    return [
        _naming_finding(path, target, rule, message(target))
        for target in targets
        if target.role in {"parameter", "property", "variable"}
        and not _is_exempt_target(target)
        and (len(target.name) > limit if too_long else len(target.name) < limit)
    ]


def _short_method_name_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, SHORT_METHOD_NAME_RULE_NAME)
    if rule is None:
        return []
    minimum = _integer_property(rule, "minimum")
    return [
        _naming_finding(
            path,
            target,
            rule,
            f"Avoid using short method names like {target.name}(). Configured minimum length is {minimum}.",
        )
        for target in targets
        if target.role in {"function", "method"} and not _is_exempt_target(target) and len(target.name) < minimum
    ]


def _constant_naming_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, CONSTANT_NAMING_CONVENTIONS_RULE_NAME)
    if rule is None:
        return []
    return [
        _naming_finding(
            path,
            target,
            rule,
            f"The constant {target.name} should use UPPER_CASE naming.",
        )
        for target in targets
        if target.role == "constant"
        and not _is_exempt_target(target)
        and re.fullmatch(r"[A-Z][A-Z0-9_]*", target.name) is None
    ]


def _boolean_get_method_name_findings(
    path: Path, callables: Sequence[NamingCallable], rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, BOOLEAN_GET_METHOD_NAME_RULE_NAME)
    if rule is None:
        return []
    return [
        Finding(
            path,
            callable_info.node.lineno,
            rule.name,
            rule.priority,
            f"The boolean method {callable_info.node.name}() should not use the get prefix.",
            context=callable_info.node.name,
        )
        for callable_info in callables
        if callable_info.role == "method"
        and _is_getter_name(callable_info.node.name)
        and _has_boolean_result(callable_info.node)
    ]


def _naming_finding(path: Path, target: NamingTarget, rule: LoadedRule, message: str) -> Finding:
    return Finding(path, target.line, rule.name, rule.priority, message, context=target.name)


def _is_exempt_target(target: NamingTarget) -> bool:
    if target.name.startswith("_"):
        return True
    if target.role == "property" and target.name in {"i", "j", "k", "n", "x", "y", "z"}:
        return True
    return target.role in {"parameter", "variable"} and target.name in {
        "self",
        "cls",
        "e",
        "err",
        "exc",
        "ex",
        "i",
        "j",
        "k",
        "n",
        "x",
        "y",
        "z",
    }


def _is_getter_name(name: str) -> bool:
    return name.startswith("get_") or (name.startswith("get") and len(name) > 3 and name[3].isupper())


def _has_boolean_result(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return _is_boolean_annotation(node.returns) or _all_paths_return_boolean(node.body)


def _is_boolean_annotation(node: ast.expr | None) -> bool:
    return (isinstance(node, ast.Name) and node.id == "bool") or (
        isinstance(node, ast.Constant) and node.value == "bool"
    )


def _all_paths_return_boolean(statements: Sequence[ast.stmt]) -> bool:
    if not statements:
        return False
    statement, *remaining = statements
    if isinstance(statement, ast.Return):
        return statement.value is not None and _is_boolean_expression(statement.value)
    if isinstance(statement, ast.If):
        return _all_paths_return_boolean([*statement.body, *remaining]) and _all_paths_return_boolean(
            [*statement.orelse, *remaining]
        )
    if _contains_return(statement):
        return False
    return _all_paths_return_boolean(remaining)


def _contains_return(node: ast.AST) -> bool:
    if isinstance(node, ast.Return):
        return True
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return False
    return any(_contains_return(child) for child in ast.iter_child_nodes(node))


def _is_boolean_expression(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Compare)
        or isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
        or isinstance(node, ast.Constant) and isinstance(node.value, bool)
        or isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"bool", "isinstance", "issubclass"}
    )


def _called_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _cyclomatic_complexity_findings(
    path: Path, tree: ast.Module, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = next((candidate for candidate in rules if candidate.name == CYCLOMATIC_COMPLEXITY_RULE_NAME), None)
    if rule is None:
        return []
    try:
        threshold = int(rule.properties["reportlevel"])
    except (KeyError, ValueError) as error:
        raise RulesetError("CyclomaticComplexity property 'reportLevel' must be an integer.") from error
    findings: list[Finding] = []
    for callable_info in _callables(tree):
        complexity = _cyclomatic_complexity(callable_info.node)
        if complexity < threshold:
            continue
        message = (
            f"The {callable_info.kind} {callable_info.name}() has a Cyclomatic Complexity of {complexity}. "
            f"The configured cyclomatic complexity threshold is {threshold}."
        )
        findings.append(
            Finding(
                path,
                callable_info.node.lineno,
                CYCLOMATIC_COMPLEXITY_RULE_NAME,
                rule.priority,
                message,
                context=callable_info.name,
            )
        )
    return findings


def _cyclomatic_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> int:
    visitor = _CyclomaticComplexityVisitor()
    if isinstance(node, ast.Lambda):
        visitor.visit(node.body)
    else:
        for statement in node.body:
            visitor.visit(statement)
    return 1 + visitor.decisions


class _CyclomaticComplexityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.decisions = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_If(self, node: ast.If) -> None:
        self.decisions += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.decisions += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.decisions += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.decisions += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.decisions += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.decisions += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.decisions += len(node.values) - 1
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.decisions += 1 + len(node.ifs)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.decisions += len(node.cases)
        self.generic_visit(node)


def _npath_complexity_findings(path: Path, tree: ast.Module, rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = next((candidate for candidate in rules if candidate.name == NPATH_COMPLEXITY_RULE_NAME), None)
    if rule is None:
        return []
    try:
        threshold = int(rule.properties["minimum"])
    except (KeyError, ValueError) as error:
        raise RulesetError("NPathComplexity property 'minimum' must be an integer.") from error
    findings: list[Finding] = []
    for callable_info in _callables(tree):
        complexity = _npath_complexity(callable_info.node)
        if complexity < threshold:
            continue
        message = (
            f"The {callable_info.kind} {callable_info.name}() has an NPath complexity of {complexity}. "
            f"The configured NPath complexity threshold is {threshold}."
        )
        findings.append(
            Finding(
                path,
                callable_info.node.lineno,
                NPATH_COMPLEXITY_RULE_NAME,
                rule.priority,
                message,
                context=callable_info.name,
            )
        )
    return findings


def _npath_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> int:
    return _npath_expression(node.body) if isinstance(node, ast.Lambda) else _npath_block(node.body)


def _npath_block(statements: Sequence[ast.stmt]) -> int:
    complexity = 1
    for statement in statements:
        complexity *= _npath_statement(statement)
    return complexity


def _npath_statement(node: ast.stmt) -> int:
    if isinstance(node, ast.If):
        return _npath_expression(node.test) * (_npath_block(node.body) + _npath_block(node.orelse))
    if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
        condition = node.iter if isinstance(node, (ast.For, ast.AsyncFor)) else node.test
        return _npath_expression(condition) * (_npath_block(node.body) + _npath_block(node.orelse))
    if isinstance(node, (ast.Try, ast.TryStar)):
        handlers = sum(_npath_block(handler.body) for handler in node.handlers)
        return (_npath_block(node.body) + handlers) * _npath_block(node.orelse) * _npath_block(node.finalbody)
    if isinstance(node, ast.Match):
        return sum(
            _npath_block(case.body) + (_npath_expression(case.guard) if case.guard is not None else 0)
            for case in node.cases
        )
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return 1
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.Return, ast.Raise)):
        value = getattr(node, "value", None)
        return _npath_expression(value) if value is not None else 1
    return 1


def _npath_expression(node: ast.AST) -> int:
    if isinstance(node, ast.BoolOp):
        return sum(_npath_expression(value) for value in node.values)
    if isinstance(node, ast.IfExp):
        return _npath_expression(node.test) + _npath_expression(node.body) + _npath_expression(node.orelse)
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        return _npath_comprehension(node)
    if isinstance(node, ast.Lambda):
        return 1
    complexity = 1
    for child in ast.iter_child_nodes(node):
        complexity *= _npath_expression(child)
    return complexity


def _npath_comprehension(
    node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp,
) -> int:
    complexity = 1
    for generator in node.generators:
        filters = 1
        for condition in generator.ifs:
            filters += _npath_expression(condition)
        complexity *= _npath_expression(generator.iter) * filters
    if isinstance(node, ast.DictComp):
        return complexity * _npath_expression(node.key) * _npath_expression(node.value)
    return complexity * _npath_expression(node.elt)


def _excessive_parameter_list_findings(
    path: Path, tree: ast.Module, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = next((candidate for candidate in rules if candidate.name == EXCESSIVE_PARAMETER_LIST_RULE_NAME), None)
    if rule is None:
        return []
    try:
        threshold = int(rule.properties["minimum"])
    except (KeyError, ValueError) as error:
        raise RulesetError("ExcessiveParameterList property 'minimum' must be an integer.") from error
    findings: list[Finding] = []
    for callable_info in _callables(tree):
        if callable_info.parameter_count < threshold:
            continue
        message = (
            f"The {callable_info.kind} {callable_info.name} has {callable_info.parameter_count} parameters. "
            f"Consider reducing the number of parameters to less than {threshold}."
        )
        findings.append(
            Finding(
                path,
                callable_info.node.lineno,
                EXCESSIVE_PARAMETER_LIST_RULE_NAME,
                rule.priority,
                message,
                context=callable_info.name,
            )
        )
    return findings


def _parameter_count(arguments: ast.arguments) -> int:
    return (
        len(arguments.posonlyargs)
        + len(arguments.args)
        + len(arguments.kwonlyargs)
        + int(arguments.vararg is not None)
        + int(arguments.kwarg is not None)
    )


def _callables(tree: ast.Module) -> list[CallableInfo]:
    collector = _CallableCollector()
    for statement in tree.body:
        collector.visit_statement(statement, in_class_body=False)
    collector.add_lambdas(tree)
    return sorted(collector.callables, key=lambda callable_info: callable_info.node.lineno)


class _CallableCollector:
    def __init__(self) -> None:
        self.callables: list[CallableInfo] = []

    def visit_statement(self, node: ast.stmt, in_class_body: bool) -> None:
        if isinstance(node, ast.ClassDef):
            for statement in node.body:
                self.visit_statement(statement, in_class_body=True)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "method" if in_class_body else "function"
            self.callables.append(CallableInfo(node, node.name, kind, _parameter_count(node.args)))
            for statement in node.body:
                self.visit_statement(statement, in_class_body=False)
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                self.visit_statement(child, in_class_body=in_class_body)

    def add_lambdas(self, tree: ast.Module) -> None:
        self.callables.extend(
            CallableInfo(node, "<lambda>", "lambda", _parameter_count(node.args))
            for node in ast.walk(tree)
            if isinstance(node, ast.Lambda)
        )


def _naming_roles(tree: ast.Module) -> tuple[list[NamingTarget], list[NamingCallable]]:
    collector = _NamingRoleCollector()
    collector.visit(tree)
    targets = sorted(collector.targets, key=lambda target: (target.line, target.role, target.name))
    callables = sorted(collector.callables, key=lambda callable_info: callable_info.node.lineno)
    return targets, callables


class _NamingRoleCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.targets: list[NamingTarget] = []
        self.callables: list[NamingCallable] = []
        self.contexts: list[str] = []
        self.class_depth = 0
        self.receivers: list[str | None] = []
        self.constant_target_ids: set[int] = set()
        self.generic_target_ids: set[int] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._add_target(node.name, node.lineno, "class")
        self.contexts.append("class")
        self.class_depth += 1
        for statement in node.body:
            self.visit(statement)
        self.class_depth -= 1
        self.contexts.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_callable(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_callable(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if _is_type_parameter_factory(node.value):
            self.generic_target_ids.update(id(target) for name in node.targets for target in _target_names(name))
        if self._is_module_or_class_scope():
            self.constant_target_ids.update(
                id(target)
                for name in node.targets
                for target in _target_names(name)
                if re.fullmatch(r"[A-Z][A-Z0-9_]*", target.id) is not None
            )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if _is_final_annotation(node.annotation) or (
            self._is_module_or_class_scope()
            and any(re.fullmatch(r"[A-Z][A-Z0-9_]*", target.id) is not None for target in _target_names(node.target))
        ):
            self.constant_target_ids.update(id(target) for target in _target_names(node.target))
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self._add_target(node.name, node.lineno, "variable")
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self._add_target(node.name, node.lineno, "variable")
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self._add_target(node.name, node.lineno, "variable")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Store):
            return
        if id(node) in self.generic_target_ids:
            return
        role = "constant" if id(node) in self.constant_target_ids else self._variable_role()
        self._add_target(node.id, node.lineno, role)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        receiver = self.receivers[-1] if self.receivers else None
        if (
            isinstance(node.ctx, ast.Store)
            and self.class_depth > 0
            and receiver is not None
            and isinstance(node.value, ast.Name)
            and node.value.id == receiver
        ):
            self._add_target(node.attr, node.lineno, "property")
        self.generic_visit(node)

    def _visit_callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        direct_class_member = bool(self.contexts and self.contexts[-1] == "class")
        role = "property" if direct_class_member and _has_property_decorator(node) else (
            "method" if direct_class_member else "function"
        )
        self._add_target(node.name, node.lineno, role)
        self.callables.append(NamingCallable(node, role))
        for argument in _arguments(node.args):
            self._add_target(argument.arg, argument.lineno, "parameter")
        receiver = _instance_receiver(node) if direct_class_member else None
        self.contexts.append("function")
        self.receivers.append(receiver)
        for statement in node.body:
            self.visit(statement)
        self.receivers.pop()
        self.contexts.pop()

    def _variable_role(self) -> str:
        return "property" if self.contexts and self.contexts[-1] == "class" else "variable"

    def _is_module_or_class_scope(self) -> bool:
        return not self.contexts or self.contexts[-1] == "class"

    def _add_target(self, name: str, line: int, role: str) -> None:
        target = NamingTarget(name, line, role)
        if target not in self.targets:
            self.targets.append(target)


def _arguments(arguments: ast.arguments) -> list[ast.arg]:
    values = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        values.append(arguments.vararg)
    if arguments.kwarg is not None:
        values.append(arguments.kwarg)
    return values


def _target_names(node: ast.AST) -> list[ast.Name]:
    if isinstance(node, ast.Name):
        return [node]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for element in node.elts for name in _target_names(element)]
    return []


def _is_final_annotation(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "Final"
    if isinstance(node, ast.Attribute):
        return node.attr == "Final"
    return isinstance(node, ast.Subscript) and _is_final_annotation(node.value)


def _is_type_parameter_factory(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and _called_name(node.func) in {"TypeVar", "ParamSpec", "TypeVarTuple"}


def _excessive_method_length_findings(
    path: Path, tree: ast.Module, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = next((candidate for candidate in rules if candidate.name == METHOD_LENGTH_RULE_NAME), None)
    if rule is None:
        return []
    try:
        method_length_limit = int(rule.properties["minimum"])
    except (KeyError, ValueError) as error:
        raise RulesetError("ExcessiveMethodLength property 'minimum' must be an integer.") from error
    findings: list[Finding] = []
    for callable_info in _callables(tree):
        node = callable_info.node
        line_count = (node.end_lineno or node.lineno) - node.lineno + 1
        if line_count < method_length_limit:
            continue
        message = (
            f"The {callable_info.kind} {callable_info.name}() has {line_count} lines of code. "
            f"Current threshold is set to {method_length_limit}. Avoid really long methods."
        )
        findings.append(
            Finding(
                path,
                node.lineno,
                METHOD_LENGTH_RULE_NAME,
                rule.priority,
                message,
                context=callable_info.name,
            )
        )
    return findings


def _class_findings(
    path: Path, source: str, tree: ast.Module, rules: Sequence[LoadedRule]
) -> list[Finding]:
    findings: list[Finding] = []
    for class_info in _classes(tree):
        findings.extend(_excessive_class_length_findings(path, source, class_info, rules))
        findings.extend(_excessive_public_count_findings(path, class_info, rules))
        findings.extend(_too_many_fields_findings(path, class_info, rules))
        findings.extend(_too_many_methods_findings(path, class_info, rules, public_only=False))
        findings.extend(_too_many_methods_findings(path, class_info, rules, public_only=True))
        findings.extend(_excessive_class_complexity_findings(path, class_info, rules))
    return findings


def _excessive_class_length_findings(
    path: Path, source: str, class_info: ClassInfo, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, EXCESSIVE_CLASS_LENGTH_RULE_NAME)
    if rule is None:
        return []
    threshold = _integer_property(rule, "minimum")
    ignore_whitespace = _boolean_property(rule, "ignore-whitespace")
    start = class_info.node.lineno
    end = class_info.node.end_lineno or start
    lines = source.splitlines()[start - 1 : end]
    line_count = sum(bool(line.strip()) for line in lines) if ignore_whitespace else len(lines)
    if line_count < threshold:
        return []
    return [
        _class_finding(
            path,
            class_info,
            rule,
            f"The class {class_info.name} has {line_count} lines of code. "
            f"Current threshold is set to {threshold}. Avoid really long classes.",
        )
    ]


def _excessive_public_count_findings(
    path: Path, class_info: ClassInfo, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, EXCESSIVE_PUBLIC_COUNT_RULE_NAME)
    if rule is None:
        return []
    threshold = _integer_property(rule, "minimum")
    count = sum(_is_public(name) for name in class_info.fields) + sum(
        _is_public(method.name) for method in class_info.methods if not _is_contract_method(method)
    )
    if count < threshold:
        return []
    return [
        _class_finding(
            path,
            class_info,
            rule,
            f"The class {class_info.name} has {count} public methods and attributes. "
            f"Consider reducing the number of public items to less than {threshold}.",
        )
    ]


def _too_many_fields_findings(
    path: Path, class_info: ClassInfo, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, TOO_MANY_FIELDS_RULE_NAME)
    if rule is None:
        return []
    threshold = _integer_property(rule, "maxfields")
    count = len(class_info.fields)
    if count <= threshold:
        return []
    return [
        _class_finding(
            path,
            class_info,
            rule,
            f"The class {class_info.name} has {count} fields. Consider redesigning {class_info.name} "
            f"to keep the number of fields under {threshold}.",
        )
    ]


def _too_many_methods_findings(
    path: Path, class_info: ClassInfo, rules: Sequence[LoadedRule], public_only: bool
) -> list[Finding]:
    name = TOO_MANY_PUBLIC_METHODS_RULE_NAME if public_only else TOO_MANY_METHODS_RULE_NAME
    rule = _rule(rules, name)
    if rule is None:
        return []
    threshold = _integer_property(rule, "maxmethods")
    ignore = _ignore_pattern(rule)
    methods = [
        method
        for method in class_info.methods
        if not _is_contract_method(method)
        and not ignore.match(method.name)
        and (not public_only or _is_public(method.name))
    ]
    count = len(methods)
    if count <= threshold:
        return []
    if public_only:
        message = (
            f"The class {class_info.name} has {count} public methods. Consider refactoring {class_info.name} "
            f"to keep number of public methods under {threshold}."
        )
    else:
        message = (
            f"The class {class_info.name} has {count} non-getter- and setter-methods. "
            f"Consider refactoring {class_info.name} to keep number of methods under {threshold}."
        )
    return [_class_finding(path, class_info, rule, message)]


def _excessive_class_complexity_findings(
    path: Path, class_info: ClassInfo, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, EXCESSIVE_CLASS_COMPLEXITY_RULE_NAME)
    if rule is None:
        return []
    threshold = _integer_property(rule, "maximum")
    complexity = sum(_cyclomatic_complexity(method) for method in class_info.methods if not _is_contract_method(method))
    if complexity < threshold:
        return []
    return [
        _class_finding(
            path,
            class_info,
            rule,
            f"The class {class_info.name} has an overall complexity of {complexity} which is very high. "
            f"The configured complexity threshold is {threshold}.",
        )
    ]


def _classes(tree: ast.Module) -> list[ClassInfo]:
    classes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or _is_protocol(node):
            continue
        methods = tuple(
            statement
            for statement in node.body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        fields = tuple(
            dict.fromkeys(
                [
                    *(name for statement in node.body for name in _field_names(statement)),
                    *(name for method in methods for name in _instance_field_names(method)),
                ]
            )
        )
        classes.append(ClassInfo(node, node.name, fields, methods))
    return sorted(classes, key=lambda class_info: class_info.node.lineno)


def _field_names(statement: ast.stmt) -> list[str]:
    if isinstance(statement, ast.AnnAssign):
        return _assigned_names(statement.target)
    if isinstance(statement, ast.Assign):
        return [name for target in statement.targets for name in _assigned_names(target)]
    return []


def _assigned_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _assigned_names(element)]
    return []


def _instance_field_names(method: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    receiver = _instance_receiver(method)
    if receiver is None:
        return []
    collector = _InstanceFieldCollector(receiver)
    for statement in method.body:
        collector.visit(statement)
    return collector.names


def _instance_receiver(method: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    if _has_decorator(method, "staticmethod"):
        return None
    arguments = [*method.args.posonlyargs, *method.args.args]
    if not arguments:
        return None
    receiver = arguments[0].arg
    if receiver == "self" or (_has_decorator(method, "classmethod") and receiver == "cls"):
        return receiver
    return None


class _InstanceFieldCollector(ast.NodeVisitor):
    def __init__(self, receiver: str) -> None:
        self.receiver = receiver
        self.names: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._add_target(target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._add_target(node.target)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._add_target(node.target)
        self.generic_visit(node)

    def _add_target(self, target: ast.AST) -> None:
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == self.receiver:
            self.names.append(target.attr)


def _protocol_base_names(tree: ast.Module) -> set[str]:
    return {
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom) and statement.module == "typing"
        for alias in statement.names
        if alias.name == "Protocol"
    } | {"Protocol"}


def _is_protocol(node: ast.ClassDef, protocol_names: set[str] | None = None) -> bool:
    return any(
        (isinstance(base, ast.Name) and base.id in (protocol_names or {"Protocol"}))
        or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
        for base in node.bases
    )


def _is_contract_method(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return _has_decorator(method, "overload") or _is_stub_body(method.body)


def _has_property_decorator(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return _has_decorator(method, "property") or any(
        isinstance(decorator, ast.Attribute) and decorator.attr in {"getter", "setter", "deleter"}
        for decorator in method.decorator_list
    )


def _has_decorator(method: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == name)
        or (isinstance(decorator, ast.Attribute) and decorator.attr == name)
        for decorator in method.decorator_list
    )


def _is_stub_body(statements: Sequence[ast.stmt]) -> bool:
    body = list(statements)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body.pop(0)
    if not body:
        return True
    if all(isinstance(statement, ast.Pass) for statement in body):
        return True
    if len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        return body[0].value.value is Ellipsis
    return len(body) == 1 and isinstance(body[0], ast.Raise) and _raises_not_implemented(body[0])


def _raises_not_implemented(statement: ast.Raise) -> bool:
    exception = statement.exc
    if isinstance(exception, ast.Name):
        return exception.id == "NotImplementedError"
    return isinstance(exception, ast.Call) and isinstance(exception.func, ast.Name) and exception.func.id == "NotImplementedError"


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _rule(rules: Sequence[LoadedRule], name: str) -> LoadedRule | None:
    return next((candidate for candidate in rules if candidate.name == name), None)


def _integer_property(rule: LoadedRule, property_name: str) -> int:
    try:
        return int(rule.properties[property_name])
    except (KeyError, ValueError) as error:
        raise RulesetError(f"{rule.name} property '{property_name}' must be an integer.") from error


def _boolean_property(rule: LoadedRule, property_name: str) -> bool:
    value = rule.properties.get(property_name, "false").casefold()
    if value == "true":
        return True
    if value == "false":
        return False
    raise RulesetError(f"{rule.name} property '{property_name}' must be true or false.")


def _ignore_pattern(rule: LoadedRule) -> re.Pattern[str]:
    pattern = rule.properties.get("ignorepattern", "")
    flags = re.IGNORECASE if pattern.endswith(")i") else 0
    if flags:
        pattern = pattern[:-1]
    try:
        return re.compile(pattern, flags)
    except re.error as error:
        raise RulesetError(f"{rule.name} property 'ignorepattern' must be a valid regular expression.") from error


def _class_finding(path: Path, class_info: ClassInfo, rule: LoadedRule, message: str) -> Finding:
    return Finding(path, class_info.node.lineno, rule.name, rule.priority, message, context=class_info.name)


def _unsuppressed(findings: Sequence[Finding]) -> list[Finding]:
    return [finding for finding in findings if not finding.suppressed]


def _apply_suppressions(source: str, findings: Sequence[Finding]) -> list[Finding]:
    directives, source_lines = _suppression_directives(source)
    active_counts: dict[str, int] = {}
    next_line_rules: dict[int, set[str]] = {}
    directive_index = 0
    suppressed: list[Finding] = []
    for finding in sorted(findings, key=lambda candidate: candidate.line):
        while directive_index < len(directives) and directives[directive_index][0] < finding.line:
            line, action, rule_names = directives[directive_index]
            if action == "disable-next-line":
                next_line = next((candidate for candidate in source_lines if candidate > line), None)
                if next_line is not None:
                    next_line_rules.setdefault(next_line, set()).update(rule_names)
            elif action == "disable":
                for rule_name in rule_names:
                    active_counts[rule_name] = active_counts.get(rule_name, 0) + 1
            else:
                for rule_name in rule_names:
                    if active_counts.get(rule_name, 0) > 0:
                        active_counts[rule_name] -= 1
            directive_index += 1
        identity = _rule_identity(finding.rule_name)
        is_suppressed = active_counts.get(identity, 0) > 0 or identity in next_line_rules.get(
            finding.line, set()
        )
        suppressed.append(replace(finding, suppressed=is_suppressed))
    return suppressed


def _suppression_directives(source: str) -> tuple[list[tuple[int, str, set[str]]], list[int]]:
    directives: list[tuple[int, str, set[str]]] = []
    source_lines: set[int] = set()
    ignored_tokens = {
        token.COMMENT,
        token.DEDENT,
        token.ENDMARKER,
        token.INDENT,
        token.NEWLINE,
        token.NL,
    }
    for item in tokenize.generate_tokens(StringIO(source).readline):
        if item.type == token.COMMENT:
            directive = _suppression_directive(item.string, item.start[0])
            if directive is not None:
                directives.append(directive)
        elif item.type not in ignored_tokens:
            source_lines.add(item.start[0])
    return directives, sorted(source_lines)


def _suppression_directive(comment: str, line: int) -> tuple[int, str, set[str]] | None:
    match = DIRECTIVE_PATTERN.fullmatch(comment[1:].strip())
    if match is None:
        return None
    rule_text = match.group(2)
    if rule_text is None or re.search(r",\s*(?:,|$)", rule_text):
        return None
    rule_names = re.split(r"[\s,]+", rule_text.strip())
    if not rule_names or not all(RULE_NAME_PATTERN.fullmatch(name) for name in rule_names):
        return None
    return line, match.group(1).casefold(), {_rule_identity(name) for name in rule_names}


def _rule_identity(name: str) -> str:
    return name.casefold()


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
        "usage: messpy <paths> <format> <ruleset[,ruleset...]> [options]\n"
        "formats: text, xml, json, html, ansi, github, gitlab, checkstyle, sarif\n"
        "\n"
        "Source discovery:\n"
        "  --suffixes <list>  Replace source suffixes (default: .py,.pyi)\n"
        "  --exclude <paths>  Skip matching source paths\n"
        "  --ignore-tests     Skip test_*.py, *_test.py, and test or tests directories\n"
        "  Input directory symlinks are scanned; nested directory symlinks are skipped.\n"
        "\n"
        "Reporting:\n"
        "  --reportfile <path>               Write the complete report to a file\n"
        "  --color <auto|always|never>       Text color: auto on TTY, always, or never\n"
        "  --strict                          Include suppressed findings\n"
        "  --only, --enable, --disable <list> Filter loaded rules\n"
        "  --minimumpriority <1-5>           Include priorities at or above the lower bound\n"
        "  --maximumpriority <1-5>           Include priorities at or below the upper bound\n"
        "  --verbose                         Show deterministic ruleset diagnostics\n"
        "  --ignore-errors-on-exit           Return success despite processing errors\n"
        "  --ignore-violations-on-exit       Return success despite findings\n"
        "\n"
        "Exit codes: 0 clean, 1 errors, 2 findings.\n"
    )
