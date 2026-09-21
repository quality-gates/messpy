from __future__ import annotations

from io import StringIO
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.analyzer import DEFAULT_SUFFIXES, Analysis, Finding, ProcessingError, analyze
from messpy.cli import run
from messpy.rulesets import load_rulesets


FINDING_LINE_PATTERN = re.compile(
    r"^(?P<path>.+):(?P<line>\d+): (?P<rule>[A-Za-z_][A-Za-z0-9_]*)"
    r" \[priority (?P<priority>\d+)\](?: \[suppressed\])? (?P<message>.+)$"
)
ERROR_LINE_PATTERN = re.compile(
    r"^(?P<path>.+):(?P<line>\d+): (?P<rule>ProcessingError) (?P<message>.+)$"
)


def _long_function(name: str) -> str:
    return f"def {name}():\n" + "    pass\n" * 100


def _parse_text_report(report: str) -> set[tuple[str, int, str, int, str]]:
    entries = set()
    for line in report.splitlines():
        matched = FINDING_LINE_PATTERN.fullmatch(line) or ERROR_LINE_PATTERN.fullmatch(line)
        assert matched is not None, f"Unrecognized report line: {line!r}"
        entries.add(
            (
                matched.group("path"),
                int(matched.group("line")),
                matched.group("rule"),
                int(matched.groupdict().get("priority") or 1),
                matched.group("message"),
            )
        )
    return entries


def _analysis_entries(analysis: Analysis, include_suppressed: bool = False) -> set[tuple[str, int, str, int, str]]:
    return {
        (finding.path.as_posix(), finding.line, finding.rule_name, finding.priority, finding.message)
        for finding in analysis.findings
        if include_suppressed or not finding.suppressed
    } | {
        (error.path.as_posix(), error.line, "ProcessingError", 1, error.message)
        for error in analysis.errors
    }


class FacadeAcceptanceTests(unittest.TestCase):
    def test_analyze_matches_the_rendered_text_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            (project / "long_function.py").write_text(_long_function("first"), encoding="utf-8")
            (project / "naming.py").write_text(
                "def run_this():\n"
                "    temporary_computation_result_holder = 1\n"
                "    return temporary_computation_result_holder\n",
                encoding="utf-8",
            )
            rules = load_rulesets(["codesize", "naming"])

            analysis = analyze([project], rules=rules)

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(project), "text", "codesize,naming"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        self.assertEqual(_parse_text_report(stdout.getvalue()), _analysis_entries(analysis))
        self.assertTrue(analysis.findings)
        self.assertEqual((), analysis.errors)

    def test_analyze_marks_suppressed_findings_and_collects_processing_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            suppressed = project / "waived.py"
            suppressed.write_text(
                "# messpy-disable-next-line ExcessiveMethodLength\n"
                + _long_function("waived_run"),
                encoding="utf-8",
            )
            broken = project / "broken.py"
            broken.write_text("def truncated(:\n", encoding="utf-8")
            rules = load_rulesets(["codesize"])

            analysis = analyze([project], rules=rules)

            plain_stdout = StringIO()
            strict_stdout = StringIO()
            plain_status = run([str(project), "text", "codesize"], plain_stdout, StringIO())
            strict_status = run(
                [str(project), "text", "codesize", "--strict"], strict_stdout, StringIO()
            )

        self.assertEqual(1, plain_status)
        self.assertEqual(1, strict_status)
        suppressed_findings = [finding for finding in analysis.findings if finding.suppressed]
        self.assertEqual(1, len(suppressed_findings))
        self.assertEqual("ExcessiveMethodLength", suppressed_findings[0].rule_name)
        self.assertEqual(suppressed.resolve(), suppressed_findings[0].path)
        self.assertEqual(1, len(analysis.errors))
        self.assertEqual(broken.resolve(), analysis.errors[0].path)
        self.assertIn("Could not parse", analysis.errors[0].message)
        self.assertEqual(
            _analysis_entries(analysis, include_suppressed=True),
            _parse_text_report(strict_stdout.getvalue()),
        )
        self.assertEqual(
            _analysis_entries(analysis, include_suppressed=False),
            _parse_text_report(plain_stdout.getvalue()),
        )

    def test_analyze_honors_suffixes_exclusions_and_ignore_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            (project / "main_app.py").write_text(_long_function("main_run"), encoding="utf-8")
            third_party = project / "third_party"
            third_party.mkdir()
            (third_party / "produced.py").write_text(_long_function("produced_run"), encoding="utf-8")
            tests = project / "tests"
            tests.mkdir()
            (tests / "test_main_app.py").write_text(_long_function("test_run"), encoding="utf-8")
            (project / "notes.pyz").write_text(_long_function("other_run"), encoding="utf-8")
            rules = load_rulesets(["codesize"])

            default_analysis = analyze([project], rules=rules)
            quiet_analysis = analyze(
                [project], rules=rules, exclusions=("third_party",), ignore_tests=True
            )
            custom_suffix_analysis = analyze([project], rules=rules, suffixes={".pyz"})

        self.assertEqual(
            {"main_app.py", "produced.py", "test_main_app.py"},
            {finding.path.name for finding in default_analysis.findings},
        )
        self.assertEqual({"main_app.py"}, {finding.path.name for finding in quiet_analysis.findings})
        self.assertEqual((), quiet_analysis.errors)
        self.assertEqual({"notes.pyz"}, {finding.path.name for finding in custom_suffix_analysis.findings})

    def test_analyze_accepts_string_and_path_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            (project / "long_function.py").write_text(_long_function("string_run"), encoding="utf-8")
            rules = load_rulesets(["codesize"])

            from_strings = analyze([str(project)], rules=rules)
            from_paths = analyze([project], rules=rules)

        self.assertEqual(_analysis_entries(from_strings), _analysis_entries(from_paths))
        self.assertTrue(from_strings.findings)

    def test_facade_exports_the_findings_level_value_types(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "long_function.py"
            source.write_text(_long_function("typed_run"), encoding="utf-8")

            analysis = analyze([source], rules=load_rulesets(["codesize"]))

        self.assertIsInstance(analysis, Analysis)
        self.assertTrue(analysis.findings)
        self.assertIsInstance(analysis.findings[0], Finding)
        self.assertEqual((), analysis.errors)
        self.assertEqual({".py", ".pyi"}, set(DEFAULT_SUFFIXES))
        self.assertFalse(isinstance(ProcessingError(source, 1, "unused"), Finding))


if __name__ == "__main__":
    unittest.main()
