from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field as dataclass_field, replace
from html import escape as html_escape
import json
import os
import re
import stat
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TextIO

from . import __version__
from .analyzer import DEFAULT_SUFFIXES, Finding, ProcessingError, analyze
from .rulesets import RulesetError, filter_rules, load_rulesets


REPORT_FORMATS = frozenset(
    {"text", "xml", "json", "html", "ansi", "github", "gitlab", "checkstyle", "sarif"}
)


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


@dataclass(frozen=True)
class RuleSelection:
    rulesets: tuple[str, ...]
    only: tuple[str, ...]
    enable: tuple[str, ...]
    disable: tuple[str, ...]
    minimum_priority: int
    maximum_priority: int


@dataclass(frozen=True)
class ExitPolicy:
    ignore_errors_on_exit: bool
    ignore_violations_on_exit: bool


@dataclass(frozen=True)
class ParsedArguments:
    paths: tuple[str, ...]
    report_format: str
    suffixes: frozenset[str]
    exclusions: tuple[str, ...]
    ignore_tests: bool
    report_file: Path | None
    strict: bool
    verbose: bool
    color: str
    show_help: bool
    show_version: bool
    rule_selection: RuleSelection
    exit_policy: ExitPolicy


class CliError(Exception):
    def __init__(self, message: str, ignore_errors_on_exit: bool = False) -> None:
        super().__init__(message)
        self.ignore_errors_on_exit = ignore_errors_on_exit


def run(arguments: Sequence[str], stdout: TextIO, stderr: TextIO) -> int:
    parsed_arguments: ParsedArguments | None = None
    try:
        parsed_arguments = _parse_arguments(arguments)
        early_exit_status = _handle_help_or_version(parsed_arguments, stdout)
        if early_exit_status is not None:
            return early_exit_status
        return _run_analysis(parsed_arguments, stdout, stderr)
    except (CliError, RulesetError) as error:
        stderr.write(f"Error: {error}\n")
        if (parsed_arguments and parsed_arguments.exit_policy.ignore_errors_on_exit) or getattr(
            error, "ignore_errors_on_exit", False
        ):
            return 0
        return 1
    except (OSError, ValueError) as error:
        stderr.write(f"Error: {error}\n")
        return 0 if parsed_arguments and parsed_arguments.exit_policy.ignore_errors_on_exit else 1


def _handle_help_or_version(parsed_arguments: ParsedArguments, stdout: TextIO) -> int | None:
    if parsed_arguments.show_help:
        stdout.write(_help_text())
        return 0
    if parsed_arguments.show_version:
        stdout.write(f"{_messpy_version()}\n")
        return 0
    return None


def _run_analysis(parsed_arguments: ParsedArguments, stdout: TextIO, stderr: TextIO) -> int:
    if parsed_arguments.report_format.lower() not in REPORT_FORMATS:
        raise CliError(f"Unknown format: {parsed_arguments.report_format}")
    selection = parsed_arguments.rule_selection
    rules = filter_rules(
        load_rulesets(selection.rulesets),
        selection.only,
        selection.enable,
        selection.disable,
        selection.minimum_priority,
        selection.maximum_priority,
    )
    if parsed_arguments.verbose:
        stderr.write(f"Loaded rules: {', '.join(rule.name for rule in rules)}\n")

    analysis = analyze(
        parsed_arguments.paths,
        rules=rules,
        suffixes=parsed_arguments.suffixes,
        exclusions=parsed_arguments.exclusions,
        ignore_tests=parsed_arguments.ignore_tests,
    )
    reported_findings = analysis.findings if parsed_arguments.strict else _unsuppressed(analysis.findings)
    report = _render_report(
        parsed_arguments.report_format,
        reported_findings,
        analysis.errors,
        _use_color(parsed_arguments, stdout),
    )
    if parsed_arguments.report_file is None:
        stdout.write(report)
    else:
        _write_report(parsed_arguments.report_file, report)
    return _exit_status(
        reported_findings,
        analysis.errors,
        parsed_arguments.exit_policy.ignore_errors_on_exit,
        parsed_arguments.exit_policy.ignore_violations_on_exit,
    )


def main(
    argv: Sequence[str] = sys.argv,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> None:
    raise SystemExit(run(argv[1:], stdout, stderr))


def _messpy_version() -> str:
    return __version__


@dataclass(frozen=True)
class _RuleSelectionState:
    only: tuple[str, ...] = ()
    enable: tuple[str, ...] = ()
    disable: tuple[str, ...] = ()
    minimum_priority: int = 1
    maximum_priority: int = 5


@dataclass(frozen=True)
class _ArgumentParseState:
    positionals: tuple[str, ...] = ()
    suffixes: frozenset[str] = frozenset(DEFAULT_SUFFIXES)
    suffixes_provided: bool = False
    exclusions: tuple[str, ...] = ()
    report_file: Path | None = None
    ignore_tests: bool = False
    ignore_errors_on_exit: bool = False
    ignore_violations_on_exit: bool = False
    strict: bool = False
    verbose: bool = False
    color: str = "auto"
    rules: _RuleSelectionState = dataclass_field(default_factory=_RuleSelectionState)
    show_help: bool = False
    show_version: bool = False


def _parse_arguments(arguments: Sequence[str]) -> ParsedArguments:
    state = _ArgumentParseState()
    index = 0
    argument_count = len(arguments)
    while index < argument_count:
        state, index = _consume_argument(state, arguments, index)
    if state.show_help or state.show_version:
        return _finish_help_or_version_parsing(state)
    return _finish_analysis_parsing(state)


def _consume_argument(
    state: _ArgumentParseState, arguments: Sequence[str], index: int
) -> tuple[_ArgumentParseState, int]:
    argument = arguments[index]
    if argument in {"-h", "--help"}:
        return replace(state, show_help=True), index + 1
    if argument in {"-v", "--version"}:
        return replace(state, show_version=True), index + 1
    if not argument.startswith("-"):
        return replace(state, positionals=(*state.positionals, argument)), index + 1
    option_name, option_value = _split_option(argument)
    if option_name in VALUE_OPTIONS:
        return _apply_value_option(state, arguments, index, option_name, option_value)
    if option_name in BOOLEAN_OPTIONS:
        return _apply_boolean_option(state, option_name, option_value), index + 1
    raise CliError(f"Unknown option: {option_name}", state.ignore_errors_on_exit)


def _apply_value_option(
    state: _ArgumentParseState, arguments: Sequence[str], index: int, option_name: str, option_value: str | None
) -> tuple[_ArgumentParseState, int]:
    if option_value is None:
        if index + 1 == len(arguments) or arguments[index + 1].startswith("-"):
            raise CliError(f"Missing value for option: {option_name}", state.ignore_errors_on_exit)
        option_value = arguments[index + 1]
        index += 1
    return _dispatch_value_option(state, option_name, option_value), index + 1


def _dispatch_value_option(state: _ArgumentParseState, option_name: str, option_value: str) -> _ArgumentParseState:
    if option_name in {"--report-file", "--reportfile"}:
        return replace(state, report_file=Path(option_value))
    if option_name == "--suffixes":
        return replace(
            state,
            suffixes=_merged_suffixes(state, option_value),
            suffixes_provided=True,
        )
    if option_name == "--exclude":
        return replace(state, exclusions=(*state.exclusions, *_split_nonempty(option_value)))
    if option_name == "--color":
        return replace(state, color=_parse_color(option_value, state.ignore_errors_on_exit))
    if option_name in {"--only", "--enable", "--disable"}:
        return _apply_rule_selection_option(state, option_name, option_value)
    if option_name in {"--minimum-priority", "--minimumpriority"}:
        priority = _parse_priority(option_name, option_value, state.ignore_errors_on_exit)
        return replace(state, rules=replace(state.rules, minimum_priority=priority))
    priority = _parse_priority(option_name, option_value, state.ignore_errors_on_exit)
    return replace(state, rules=replace(state.rules, maximum_priority=priority))


def _merged_suffixes(state: _ArgumentParseState, option_value: str) -> frozenset[str]:
    normalized_suffixes = frozenset(_normalized_suffixes(option_value))
    if not state.suffixes_provided:
        return normalized_suffixes
    return state.suffixes | normalized_suffixes


def _apply_rule_selection_option(
    state: _ArgumentParseState, option_name: str, option_value: str
) -> _ArgumentParseState:
    values = tuple(_split_nonempty(option_value))
    rules = state.rules
    if option_name == "--only":
        rules = replace(rules, only=(*rules.only, *values))
    elif option_name == "--enable":
        rules = replace(rules, enable=(*rules.enable, *values))
    else:
        rules = replace(rules, disable=(*rules.disable, *values))
    return replace(state, rules=rules)


def _apply_boolean_option(
    state: _ArgumentParseState, option_name: str, option_value: str | None
) -> _ArgumentParseState:
    if option_value is not None:
        raise CliError(f"Option does not accept a value: {option_name}", state.ignore_errors_on_exit)
    if option_name == "--ignore-tests":
        return replace(state, ignore_tests=True)
    if option_name == "--ignore-errors-on-exit":
        return replace(state, ignore_errors_on_exit=True)
    if option_name == "--verbose":
        return replace(state, verbose=True)
    if option_name == "--strict":
        return replace(state, strict=True)
    return replace(state, ignore_violations_on_exit=True)


def _finish_help_or_version_parsing(state: _ArgumentParseState) -> ParsedArguments:
    if state.positionals:
        raise CliError(f"Unexpected positional argument: {state.positionals[0]}", state.ignore_errors_on_exit)
    return ParsedArguments(
        paths=(),
        report_format="",
        suffixes=frozenset(state.suffixes),
        exclusions=tuple(state.exclusions),
        ignore_tests=state.ignore_tests,
        report_file=state.report_file,
        strict=state.strict,
        verbose=state.verbose,
        color=state.color,
        show_help=state.show_help,
        show_version=state.show_version,
        rule_selection=_rule_selection(state, rulesets=[]),
        exit_policy=_exit_policy(state),
    )


def _finish_analysis_parsing(state: _ArgumentParseState) -> ParsedArguments:
    if len(state.positionals) < 3:
        raise CliError(f"Missing required arguments: {REQUIRED_ARGUMENTS}", state.ignore_errors_on_exit)
    if len(state.positionals) > 3:
        raise CliError(f"Unexpected positional argument: {state.positionals[3]}", state.ignore_errors_on_exit)

    paths = _split_nonempty(state.positionals[0])
    if not paths:
        raise CliError("At least one input path is required", state.ignore_errors_on_exit)
    rulesets = _split_nonempty(state.positionals[2])
    if not rulesets:
        raise CliError("At least one ruleset is required", state.ignore_errors_on_exit)
    if state.rules.minimum_priority > state.rules.maximum_priority:
        raise CliError("Minimum priority must not exceed maximum priority.", state.ignore_errors_on_exit)
    return ParsedArguments(
        paths=tuple(paths),
        report_format=state.positionals[1],
        suffixes=frozenset(state.suffixes),
        exclusions=tuple(state.exclusions),
        ignore_tests=state.ignore_tests,
        report_file=state.report_file,
        strict=state.strict,
        verbose=state.verbose,
        color=state.color,
        show_help=False,
        show_version=False,
        rule_selection=_rule_selection(state, rulesets),
        exit_policy=_exit_policy(state),
    )


def _rule_selection(state: _ArgumentParseState, rulesets: list[str]) -> RuleSelection:
    return RuleSelection(
        rulesets=tuple(rulesets),
        only=tuple(state.rules.only),
        enable=tuple(state.rules.enable),
        disable=tuple(state.rules.disable),
        minimum_priority=state.rules.minimum_priority,
        maximum_priority=state.rules.maximum_priority,
    )


def _exit_policy(state: _ArgumentParseState) -> ExitPolicy:
    return ExitPolicy(
        ignore_errors_on_exit=state.ignore_errors_on_exit,
        ignore_violations_on_exit=state.ignore_violations_on_exit,
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


def _render_report(
    report_format: str,
    findings: Sequence[Finding],
    processing_errors: Sequence[ProcessingError],
    color: bool,
) -> str:
    renderer = {
        "text": lambda findings=findings, errors=processing_errors, color=color: _text_report_with_color(
            findings, errors, color
        ),
        "xml": lambda findings=findings, errors=processing_errors: _xml_report(findings, errors),
        "json": lambda findings=findings, errors=processing_errors: _json_report(findings, errors),
        "html": lambda findings=findings, errors=processing_errors: _html_report(findings, errors),
        "ansi": lambda findings=findings, errors=processing_errors: _text_report_with_color(findings, errors, True),
        "github": lambda findings=findings, errors=processing_errors: _github_report(findings, errors),
        "gitlab": lambda findings=findings, errors=processing_errors: _gitlab_report(findings, errors),
        "checkstyle": lambda findings=findings, errors=processing_errors: _checkstyle_report(findings, errors),
        "sarif": lambda findings=findings, errors=processing_errors: _sarif_report(findings, errors),
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


XML_ILLEGAL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _xml_safe_text(value: str) -> str:
    # XML does not allow most control characters, even when escaped.
    # Replace each one with a printable "\xHH" form.
    return XML_ILLEGAL_CHARACTERS.sub(lambda match: f"\\x{ord(match.group()):02x}", value)


def _xml_attribute_value(value: str | int | bool) -> str:
    return html_escape(_xml_safe_text(str(value)), quote=True)


def _xml_attributes(values: dict[str, str | int | bool]) -> str:
    return "".join(f' {name}="{_xml_attribute_value(value)}"' for name, value in values.items())


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


def _github_escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _github_escape_property(value: str) -> str:
    return _github_escape_data(value).replace(":", "%3A").replace(",", "%2C")


def _github_report(findings: Sequence[Finding], processing_errors: Sequence[ProcessingError]) -> str:
    lines = []
    for finding in _ordered_findings(findings):
        record = _finding_record(finding)
        title = _github_escape_property(f"{record['ruleName']} [priority {record['priority']}]")
        message = _github_escape_data(
            f"{record['message']} (context: {record['context']})"
            f"{' [suppressed]' if record['suppressed'] else ''}"
        )
        lines.append(
            f"::warning file={_github_escape_property(str(record['path']))},line={record['line']},col=1,title={title}::{message}"
        )
    for error in _ordered_errors(processing_errors):
        record = _error_record(error)
        lines.append(
            f"::error file={_github_escape_property(str(record['path']))},line={record['line']},col=1,title=ProcessingError::{_github_escape_data(str(record['message']))}"
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
        lines.append(f'  <file name="{_xml_attribute_value(path)}">')
        for record in by_path[path]:
            severity = "error" if int(record["priority"]) <= 2 else "warning"
            source = f"messpy.{record['ruleName']}"
            lines.append(
                "    <error"
                f' line="{record["line"]}" column="1" severity="{severity}"'
                f' message="{_xml_attribute_value(record["message"])}"'
                f' source="{_xml_attribute_value(source)}"'
                f' context="{_xml_attribute_value(record["context"])}"'
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


def _destination_file_mode(report_file: Path) -> int:
    try:
        return stat.S_IMODE(report_file.stat().st_mode)
    except OSError:
        current_umask = os.umask(0)
        try:
            return 0o666 & ~current_umask
        finally:
            os.umask(current_umask)


def _write_report(report_file: Path, report: str) -> None:
    temporary_file: Path | None = None
    try:
        target_mode = _destination_file_mode(report_file)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=report_file.parent,
            prefix=f".{report_file.name}.",
            delete=False,
        ) as output:
            temporary_file = Path(output.name)
            output.write(report)
        temporary_file.chmod(target_mode)
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


def _unsuppressed(findings: Sequence[Finding]) -> list[Finding]:
    return [finding for finding in findings if not finding.suppressed]


def _split_nonempty(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _normalized_suffixes(value: str) -> set[str]:
    return {
        suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
        for suffix in _split_nonempty(value)
    }


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
