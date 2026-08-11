from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.cli import run


FIXTURES = Path(__file__).parent / "fixtures"


class CommandAcceptanceTests(unittest.TestCase):
    def test_directory_scan_recurses_over_python_files_in_path_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            first = project / "a_first.py"
            second = project / "nested" / "z_second.pyi"
            first.write_text(_long_function("first"), encoding="utf-8")
            second.parent.mkdir()
            second.write_text(_long_function("second"), encoding="utf-8")

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(project), "text", "codesize"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual(
            "\n".join(
                [
                    _finding_for(first, "first"),
                    _finding_for(second, "second"),
                    "",
                ]
            ),
            stdout.getvalue(),
        )
        self.assertEqual("", stderr.getvalue())

    def test_overlapping_and_repeated_roots_do_not_duplicate_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            root_file = project / "root.py"
            nested_file = project / "package" / "nested.py"
            root_file.write_text(_long_function("root"), encoding="utf-8")
            nested_file.parent.mkdir()
            nested_file.write_text(_long_function("nested"), encoding="utf-8")

            stdout = StringIO()
            stderr = StringIO()
            status = run(
                [
                    f"{project},{project / 'package'},{root_file},{project}",
                    "text",
                    "codesize",
                ],
                stdout,
                stderr,
            )

        self.assertEqual(2, status)
        self.assertEqual(
            "\n".join(
                [
                    _finding_for(nested_file, "nested"),
                    _finding_for(root_file, "root"),
                    "",
                ]
            ),
            stdout.getvalue(),
        )
        self.assertEqual("", stderr.getvalue())

    def test_directory_scan_skips_dependency_cache_and_generated_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            included = project / "application.py"
            included.write_text(_long_function("application"), encoding="utf-8")
            for directory in [
                ".git",
                ".venv/lib/python/site-packages",
                "__pycache__",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                ".tox",
                "build",
                "coverage",
                "dist",
                "generated",
            ]:
                ignored = project / directory / "ignored.py"
                ignored.parent.mkdir(parents=True, exist_ok=True)
                ignored.write_text(_long_function("ignored"), encoding="utf-8")

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(project), "text", "codesize"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual(f"{_finding_for(included, 'application')}\n", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_suffixes_replaces_the_default_source_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            module = project / "module.py"
            stub = project / "interface.pyi"
            module.write_text(_long_function("module"), encoding="utf-8")
            stub.write_text(_long_function("interface"), encoding="utf-8")

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(project), "text", "codesize", "--suffixes", ".pyi"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual(f"{_finding_for(stub, 'interface')}\n", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_exclude_omits_matching_source_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            included = project / "application.py"
            excluded = project / "vendorized" / "schema.py"
            included.write_text(_long_function("application"), encoding="utf-8")
            excluded.parent.mkdir()
            excluded.write_text(_long_function("schema"), encoding="utf-8")

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(project), "text", "codesize", "--exclude", "vendorized"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual(f"{_finding_for(included, 'application')}\n", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_exclude_omits_a_matching_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            included = project / "application.py"
            excluded = project / "generated_client.py"
            included.write_text(_long_function("application"), encoding="utf-8")
            excluded.write_text(_long_function("generated_client"), encoding="utf-8")

            stdout = StringIO()
            stderr = StringIO()
            status = run(
                [str(project), "text", "codesize", "--exclude", "generated_client.py"], stdout, stderr
            )

        self.assertEqual(2, status)
        self.assertEqual(f"{_finding_for(included, 'application')}\n", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_ignore_tests_omits_conventional_test_files_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            application = project / "application.py"
            test_module = project / "test_application.py"
            suffix_test = project / "application_test.py"
            test_package = project / "tests" / "integration.py"
            for path, name in [
                (application, "application"),
                (test_module, "test_module"),
                (suffix_test, "suffix_test"),
                (test_package, "test_package"),
            ]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(_long_function(name), encoding="utf-8")

            included_stdout = StringIO()
            included_stderr = StringIO()
            included_status = run([str(project), "text", "codesize"], included_stdout, included_stderr)
            ignored_stdout = StringIO()
            ignored_stderr = StringIO()
            ignored_status = run(
                [str(project), "text", "codesize", "--ignore-tests"], ignored_stdout, ignored_stderr
            )

        self.assertEqual(2, included_status)
        self.assertEqual(
            "\n".join(
                [
                    _finding_for(application, "application"),
                    _finding_for(suffix_test, "suffix_test"),
                    _finding_for(test_module, "test_module"),
                    _finding_for(test_package, "test_package"),
                    "",
                ]
            ),
            included_stdout.getvalue(),
        )
        self.assertEqual("", included_stderr.getvalue())
        self.assertEqual(2, ignored_status)
        self.assertEqual(f"{_finding_for(application, 'application')}\n", ignored_stdout.getvalue())
        self.assertEqual("", ignored_stderr.getvalue())

    def test_directory_symlinks_are_not_followed_during_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            project = workspace / "project"
            source_directory = project / "source"
            source = source_directory / "module.py"
            external_directory = workspace / "external"
            external = external_directory / "external.py"
            source_directory.mkdir(parents=True)
            external_directory.mkdir()
            source.write_text(_long_function("module"), encoding="utf-8")
            external.write_text(_long_function("external"), encoding="utf-8")
            (project / "linked_source").symlink_to(external_directory, target_is_directory=True)

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(project), "text", "codesize"], stdout, stderr)
            linked_stdout = StringIO()
            linked_stderr = StringIO()
            linked_status = run([str(project / "linked_source"), "text", "codesize"], linked_stdout, linked_stderr)

        self.assertEqual(2, status)
        self.assertEqual(f"{_finding_for(source, 'module')}\n", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())
        self.assertEqual(2, linked_status)
        self.assertEqual(f"{_finding_for(external, 'external')}\n", linked_stdout.getvalue())
        self.assertEqual("", linked_stderr.getvalue())

    def test_clean_python_file_exits_zero_without_a_report(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        status = run([str(FIXTURES / "clean.py"), "text", "codesize"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_long_python_function_has_a_stable_codesize_finding(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        long_function = (FIXTURES / "long_function.py").resolve()
        status = run([str(long_function), "text", "codesize"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual(
            "tests/fixtures/long_function.py:1: ExcessiveMethodLength "
            "[priority 3] The function too_long() has 101 lines of code. "
            "Current threshold is set to 100. Avoid really long methods.\n",
            stdout.getvalue(),
        )
        self.assertEqual("", stderr.getvalue())

    def test_json_report_contains_the_normalized_finding_record(self) -> None:
        stdout = StringIO()
        stderr = StringIO()
        source = (FIXTURES / "long_function.py").resolve()

        status = run([str(source), "json", "codesize"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        self.assertEqual(
            {
                "tool": {"name": "messpy", "version": "0.1.0"},
                "findings": [
                    {
                        "path": "tests/fixtures/long_function.py",
                        "line": 1,
                        "column": 1,
                        "ruleName": "ExcessiveMethodLength",
                        "priority": 3,
                        "message": "The function too_long() has 101 lines of code. Current threshold is set to 100. Avoid really long methods.",
                        "context": "too_long",
                        "suppressed": False,
                    }
                ],
                "errors": [],
            },
            json.loads(stdout.getvalue()),
        )

    def test_public_reports_keep_one_finding_and_one_processing_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            finding_source = project / "finding&source.py"
            malformed_source = project / "malformed.py"
            finding_source.write_text(_long_function("too_long"), encoding="utf-8")
            malformed_source.write_text("def broken(:\n", encoding="utf-8")

            reports: dict[str, str] = {}
            for report_format in [
                "text",
                "xml",
                "json",
                "html",
                "ansi",
                "github",
                "gitlab",
                "checkstyle",
                "sarif",
            ]:
                stdout = StringIO()
                stderr = StringIO()
                status = run([str(project), report_format, "codesize"], stdout, stderr)

                self.assertEqual(1, status, report_format)
                self.assertEqual("", stderr.getvalue(), report_format)
                reports[report_format] = stdout.getvalue()

        for report_format in ["text", "html", "ansi", "github"]:
            self.assertIn("ExcessiveMethodLength", reports[report_format])
            self.assertIn("ProcessingError", reports[report_format])
        self.assertIn("finding&amp;source.py", reports["html"])
        self.assertIn("\x1b[", reports["ansi"])
        self.assertIn("::warning file=", reports["github"])
        self.assertIn("::error file=", reports["github"])

        xml = ElementTree.fromstring(reports["xml"])
        self.assertEqual("messpy", xml.tag)
        self.assertEqual("0.1.0", xml.get("version"))
        self.assertEqual("too_long", xml.find("./findings/finding").get("context"))
        self.assertEqual("ProcessingError", xml.find("./errors/error").get("ruleName"))

        json_report = json.loads(reports["json"])
        self.assertEqual("too_long", json_report["findings"][0]["context"])
        self.assertEqual("ProcessingError", json_report["errors"][0]["ruleName"])

        checkstyle = ElementTree.fromstring(reports["checkstyle"])
        self.assertEqual("checkstyle", checkstyle.tag)
        self.assertEqual(2, len(checkstyle.findall(".//error")))

        gitlab = json.loads(reports["gitlab"])
        self.assertEqual(["ExcessiveMethodLength", "ProcessingError"], [entry["check_name"] for entry in gitlab])
        self.assertEqual({"name": "messpy", "version": "0.1.0"}, gitlab[0]["tool"])
        self.assertEqual(
            (
                f"{finding_source.resolve().as_posix()}:1:1:ExcessiveMethodLength:"
                "The function too_long() has 101 lines of code. Current threshold is set to 100. Avoid really long methods."
            ).encode("utf-8").hex(),
            gitlab[0]["fingerprint"],
        )

        sarif = json.loads(reports["sarif"])
        run_record = sarif["runs"][0]
        self.assertEqual("2.1.0", sarif["version"])
        self.assertEqual("messpy", run_record["tool"]["driver"]["name"])
        self.assertEqual("ExcessiveMethodLength", run_record["results"][0]["ruleId"])
        self.assertFalse(run_record["invocations"][0]["executionSuccessful"])

    def test_text_color_controls_do_not_color_redirected_output_by_default(self) -> None:
        source = str((FIXTURES / "long_function.py").resolve())
        reports: dict[str, str] = {}
        for option in [[], ["--color", "always"], ["--color", "never"]]:
            stdout = StringIO()
            stderr = StringIO()
            status = run([source, "text", "codesize", *option], stdout, stderr)

            self.assertEqual(2, status)
            self.assertEqual("", stderr.getvalue())
            reports[option[-1] if option else "auto"] = stdout.getvalue()

        self.assertNotIn("\x1b[", reports["auto"])
        self.assertIn("\x1b[", reports["always"])
        self.assertNotIn("\x1b[", reports["never"])

    def test_every_format_keeps_clean_status_and_report_file_content(self) -> None:
        formats = ["text", "xml", "json", "html", "ansi", "github", "gitlab", "checkstyle", "sarif"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            finding_source = temporary / "finding.py"
            finding_source.write_text(_long_function("too_long"), encoding="utf-8")
            for report_format in formats:
                clean_stdout = StringIO()
                clean_stderr = StringIO()
                clean_status = run(
                    [str(FIXTURES / "clean.py"), report_format, "codesize"], clean_stdout, clean_stderr
                )
                stdout = StringIO()
                stderr = StringIO()
                status = run([str(finding_source), report_format, "codesize"], stdout, stderr)
                report_file = temporary / f"report.{report_format}"
                file_stdout = StringIO()
                file_stderr = StringIO()
                file_status = run(
                    [
                        str(finding_source),
                        report_format,
                        "codesize",
                        "--reportfile",
                        str(report_file),
                    ],
                    file_stdout,
                    file_stderr,
                )

                self.assertEqual(0, clean_status, report_format)
                self.assertEqual("", clean_stderr.getvalue(), report_format)
                self.assertEqual(2, status, report_format)
                self.assertEqual("", stderr.getvalue(), report_format)
                self.assertEqual(2, file_status, report_format)
                self.assertEqual("", file_stdout.getvalue(), report_format)
                self.assertEqual("", file_stderr.getvalue(), report_format)
                self.assertEqual(stdout.getvalue(), report_file.read_text(encoding="utf-8"), report_format)

    def test_disable_next_line_hides_only_the_named_finding_on_the_next_source_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "suppressed.py"
            source.write_text(
                "# messpy-disable-next-line ExcessiveMethodLength\n"
                + _long_function("waived")
                + "\n"
                + _long_function("still_reported"),
                encoding="utf-8",
            )

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(source), "text", "codesize"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual(f"{_finding_for(source, 'still_reported', 104)}\n", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_disable_next_line_does_not_skip_an_unsuitable_source_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "next_line.py"
            source.write_text(
                "# messpy-disable-next-line ExcessiveMethodLength\n"
                "marker = 1\n"
                + _long_function("still_reported"),
                encoding="utf-8",
            )

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(source), "text", "codesize"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual(f"{_finding_for(source, 'still_reported', 3)}\n", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_strict_includes_a_suppressed_finding_without_changing_its_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "strict.py"
            source.write_text(
                "# messpy-disable-next-line excessivemethodlength\n" + _long_function("waived"),
                encoding="utf-8",
            )

            normal_stdout = StringIO()
            normal_stderr = StringIO()
            normal_status = run([str(source), "text", "codesize"], normal_stdout, normal_stderr)
            strict_stdout = StringIO()
            strict_stderr = StringIO()
            strict_status = run([str(source), "text", "codesize", "--strict"], strict_stdout, strict_stderr)

        self.assertEqual(0, normal_status)
        self.assertEqual("", normal_stdout.getvalue())
        self.assertEqual("", normal_stderr.getvalue())
        self.assertEqual(2, strict_status)
        self.assertEqual(
            f"{_finding_for(source, 'waived', 2).replace('[priority 3]', '[priority 3] [suppressed]')}\n",
            strict_stdout.getvalue(),
        )
        self.assertEqual("", strict_stderr.getvalue())

    def test_regions_nest_and_malformed_or_other_tool_comments_do_not_hide_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "regions.py"
            ruleset = temporary / "policy.xml"
            source.write_text(
                "# messpy-disable ExcessiveMethodLength MissingRule\n"
                + _function_with_passes("outer", 3)
                + "# messpy-disable ExcessiveMethodLength\n"
                + _function_with_passes("nested", 3)
                + "# messpy-enable ExcessiveMethodLength\n"
                + _function_with_passes("outer_still_active", 3)
                + "# messpy-enable MissingRule\n"
                + _function_with_passes("partially_enabled", 3)
                + "# messpy-enable ExcessiveMethodLength\n"
                + _function_with_passes("released", 3)
                + "# messpy-enable ExcessiveMethodLength\n"
                + _function_with_passes("unbalanced_enable", 3)
                + "# noqa: E501\n"
                + _function_with_passes("noqa", 3)
                + "# type: ignore\n"
                + _function_with_passes("type_checker", 3)
                + "# fmt: off\n"
                + _function_with_passes("formatter", 3)
                + "# pragma: no cover\n"
                + _function_with_passes("coverage", 3)
                + "# messpy-disable\n"
                + _function_with_passes("malformed_region", 3)
                + "# messpy-disable-next-line ExcessiveMethodLength,\n"
                + _function_with_passes("malformed_next_line", 3),
                encoding="utf-8",
            )
            ruleset.write_text(
                """<ruleset name="team policy">
    <rule ref="codesize"><properties><property name="minimum" value="3" /></properties></rule>
</ruleset>
""",
                encoding="utf-8",
            )

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(source), "text", str(ruleset)], stdout, stderr)

        self.assertEqual(2, status)
        for name in [
            "released",
            "unbalanced_enable",
            "noqa",
            "type_checker",
            "formatter",
            "coverage",
            "malformed_region",
            "malformed_next_line",
        ]:
            self.assertIn(
                f"The function {name}() has 4 lines of code. Current threshold is set to 3. Avoid really long methods.",
                stdout.getvalue(),
            )
        for name in ["outer", "nested", "outer_still_active", "partially_enabled"]:
            self.assertNotIn(f"The function {name}() has 4 lines of code.", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_malformed_source_reports_an_error_without_hiding_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            violating = project / "violating.py"
            malformed = project / "malformed.py"
            violating.write_text(_long_function("violating"), encoding="utf-8")
            malformed.write_text("def broken(:\n", encoding="utf-8")

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(project), "text", "codesize"], stdout, stderr)

        self.assertEqual(1, status)
        self.assertIn(_finding_for(violating, "violating"), stdout.getvalue())
        self.assertIn(f"{malformed.resolve().as_posix()}:1: ProcessingError", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_invalid_source_encoding_reports_an_error_without_hiding_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            violating = project / "violating.py"
            malformed = project / "malformed.py"
            violating.write_text(_long_function("violating"), encoding="utf-8")
            malformed.write_bytes(b"\xff")

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(project), "text", "codesize"], stdout, stderr)

        self.assertEqual(1, status)
        self.assertIn(_finding_for(violating, "violating"), stdout.getvalue())
        self.assertIn(f"{malformed.resolve().as_posix()}:1: ProcessingError", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_exit_ignore_flags_change_status_without_changing_the_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            violating = project / "violating.py"
            malformed = project / "malformed.py"
            violating.write_text(_long_function("violating"), encoding="utf-8")
            malformed.write_text("def broken(:\n", encoding="utf-8")

            default_stdout = StringIO()
            default_stderr = StringIO()
            default_status = run([str(project), "text", "codesize"], default_stdout, default_stderr)
            errors_ignored_stdout = StringIO()
            errors_ignored_stderr = StringIO()
            errors_ignored_status = run(
                [str(project), "text", "codesize", "--ignore-errors-on-exit"],
                errors_ignored_stdout,
                errors_ignored_stderr,
            )
            violations_ignored_stdout = StringIO()
            violations_ignored_stderr = StringIO()
            violations_ignored_status = run(
                [str(violating), "text", "codesize", "--ignore-violations-on-exit"],
                violations_ignored_stdout,
                violations_ignored_stderr,
            )
            all_ignored_stdout = StringIO()
            all_ignored_stderr = StringIO()
            all_ignored_status = run(
                [
                    str(project),
                    "text",
                    "codesize",
                    "--ignore-errors-on-exit",
                    "--ignore-violations-on-exit",
                ],
                all_ignored_stdout,
                all_ignored_stderr,
            )

        self.assertEqual(1, default_status)
        self.assertEqual(2, errors_ignored_status)
        self.assertEqual(0, violations_ignored_status)
        self.assertEqual(0, all_ignored_status)
        self.assertEqual(default_stdout.getvalue(), errors_ignored_stdout.getvalue())
        self.assertEqual(default_stdout.getvalue(), all_ignored_stdout.getvalue())
        self.assertEqual(f"{_finding_for(violating, 'violating')}\n", violations_ignored_stdout.getvalue())
        self.assertEqual("", default_stderr.getvalue())
        self.assertEqual(default_stderr.getvalue(), errors_ignored_stderr.getvalue())
        self.assertEqual(default_stderr.getvalue(), all_ignored_stderr.getvalue())
        self.assertEqual("", violations_ignored_stderr.getvalue())

    def test_reportfile_replaces_the_complete_report_without_writing_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            report_file = temporary / "reports" / "messpy.txt"
            report_file.parent.mkdir()
            report_file.write_text("stale report", encoding="utf-8")
            source = temporary / "violating.py"
            source.write_text(_long_function("violating"), encoding="utf-8")

            stdout = StringIO()
            stderr = StringIO()
            status = run(
                [str(source), "text", "codesize", "--reportfile", str(report_file)], stdout, stderr
            )

            report = report_file.read_text(encoding="utf-8")

        self.assertEqual(2, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())
        self.assertEqual(f"{_finding_for(source, 'violating')}\n", report)

    def test_reportfile_write_failure_is_an_operational_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "violating.py"
            source.write_text(_long_function("violating"), encoding="utf-8")

            stdout = StringIO()
            stderr = StringIO()
            status = run(
                [
                    str(source),
                    "text",
                    "codesize",
                    "--reportfile",
                    str(temporary / "missing" / "messpy.txt"),
                ],
                stdout,
                stderr,
            )

        self.assertEqual(1, status)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("Unable to write report", stderr.getvalue())

    def test_command_errors_have_deterministic_diagnostics(self) -> None:
        cases = [
            ([], "Missing required arguments: <paths> <format> <ruleset[,ruleset...]>"),
            (["missing.py", "text", "codesize"], "Input path does not exist"),
            (["input.py", "text", "codesize", "--reportfile"], "Missing value for option: --reportfile"),
            (["input.py", "text", "codesize", "extra"], "Unexpected positional argument: extra"),
            (["input.py", "text", "codesize", "--unknown"], "Unknown option: --unknown"),
            (
                ["input.py", "text", "codesize", "--minimum-priority", "0"],
                "--minimum-priority expects a priority between 1 and 5, received '0'.",
            ),
            (["input.py", "unknown", "codesize"], "Unknown format: unknown"),
            (["input.py", "text", "unknown"], "Unknown ruleset 'unknown'."),
        ]

        for arguments, diagnostic in cases:
            with self.subTest(arguments=arguments):
                stdout = StringIO()
                stderr = StringIO()

                status = run(arguments, stdout, stderr)

                self.assertEqual(1, status)
                self.assertEqual("", stdout.getvalue())
                self.assertIn(diagnostic, stderr.getvalue())

    def test_custom_ruleset_composes_references_and_later_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "short.py"
            ruleset = temporary / "policy.xml"
            source.write_text(_function_with_passes("short", 3), encoding="utf-8")
            ruleset.write_text(
                """<ruleset name="team policy">
    <rule ref="rulesets/CoDeSiZe.xml"><exclude name="ExcessiveMethodLength" /></rule>
    <rule ref="excessivemethodlength">
        <priority>2</priority>
        <properties><property name="minimum" value="3" /></properties>
    </rule>
</ruleset>
""",
                encoding="utf-8",
            )

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(source), "text", f"CoDeSiZe,{ruleset}"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual(
            f"{source.resolve().as_posix()}:1: ExcessiveMethodLength "
            "[priority 2] The function short() has 4 lines of code. "
            "Current threshold is set to 3. Avoid really long methods.\n",
            stdout.getvalue(),
        )
        self.assertEqual("", stderr.getvalue())

    def test_nested_ruleset_and_filters_select_only_loaded_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "short.py"
            nested_ruleset = temporary / "base.xml"
            ruleset = temporary / "policy.xml"
            source.write_text(_function_with_passes("short", 3), encoding="utf-8")
            nested_ruleset.write_text(
                """<ruleset name="base">
    <rule ref="codesize">
        <properties><property name="minimum" value="3" /></properties>
    </rule>
</ruleset>
""",
                encoding="utf-8",
            )
            ruleset.write_text(
                """<ruleset name="team policy">
    <rule ref="base.xml" />
    <rule ref="ExcessiveMethodLength"><priority>2</priority></rule>
</ruleset>
""",
                encoding="utf-8",
            )

            enabled_stdout = StringIO()
            enabled_stderr = StringIO()
            enabled_status = run(
                [
                    str(source),
                    "text",
                    str(ruleset),
                    "--enable",
                    "EXCESSIVEMETHODLENGTH",
                    "--verbose",
                ],
                enabled_stdout,
                enabled_stderr,
            )
            disabled_stdout = StringIO()
            disabled_stderr = StringIO()
            disabled_status = run(
                [str(source), "text", str(ruleset), "--disable", "excessivemethodlength"],
                disabled_stdout,
                disabled_stderr,
            )
            priority_stdout = StringIO()
            priority_stderr = StringIO()
            priority_status = run(
                [
                    str(source),
                    "text",
                    str(ruleset),
                    "--only",
                    "ExcessiveMethodLength",
                    "--minimumpriority",
                    "3",
                ],
                priority_stdout,
                priority_stderr,
            )

        self.assertEqual(2, enabled_status)
        self.assertIn("ExcessiveMethodLength [priority 2]", enabled_stdout.getvalue())
        self.assertEqual("Loaded rules: ExcessiveMethodLength\n", enabled_stderr.getvalue())
        self.assertEqual(0, disabled_status)
        self.assertEqual("", disabled_stdout.getvalue())
        self.assertEqual("", disabled_stderr.getvalue())
        self.assertEqual(0, priority_status)
        self.assertEqual("", priority_stdout.getvalue())
        self.assertEqual("", priority_stderr.getvalue())

    def test_ruleset_loading_rejects_unknown_filter_and_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source.py"
            ruleset = temporary / "invalid.xml"
            unknown_rule_exclusion = temporary / "unknown-rule-exclusion.xml"
            unknown_ruleset_exclusion = temporary / "unknown-ruleset-exclusion.xml"
            source.write_text(_function_with_passes("source", 3), encoding="utf-8")
            ruleset.write_text(
                """<ruleset name="invalid">
    <rule ref="not-a-ruleset" />
</ruleset>
""",
                encoding="utf-8",
            )
            unknown_rule_exclusion.write_text(
                """<ruleset name="invalid">
    <rule ref="codesize"><exclude name="ExcessiveMethodLenght" /></rule>
</ruleset>
""",
                encoding="utf-8",
            )
            unknown_ruleset_exclusion.write_text(
                """<ruleset name="invalid">
    <rule ref="codesize" />
    <exclude name="ExcessiveMethodLenght" />
</ruleset>
""",
                encoding="utf-8",
            )

            unknown_filter_stdout = StringIO()
            unknown_filter_stderr = StringIO()
            unknown_filter_status = run(
                [str(source), "text", "codesize", "--only", "not-a-rule"],
                unknown_filter_stdout,
                unknown_filter_stderr,
            )
            unknown_reference_stdout = StringIO()
            unknown_reference_stderr = StringIO()
            unknown_reference_status = run(
                [str(source), "text", str(ruleset), "--verbose"],
                unknown_reference_stdout,
                unknown_reference_stderr,
            )
            unknown_rule_exclusion_stdout = StringIO()
            unknown_rule_exclusion_stderr = StringIO()
            unknown_rule_exclusion_status = run(
                [str(source), "text", str(unknown_rule_exclusion)],
                unknown_rule_exclusion_stdout,
                unknown_rule_exclusion_stderr,
            )
            unknown_ruleset_exclusion_stdout = StringIO()
            unknown_ruleset_exclusion_stderr = StringIO()
            unknown_ruleset_exclusion_status = run(
                [str(source), "text", str(unknown_ruleset_exclusion)],
                unknown_ruleset_exclusion_stdout,
                unknown_ruleset_exclusion_stderr,
            )

        self.assertEqual(1, unknown_filter_status)
        self.assertEqual("", unknown_filter_stdout.getvalue())
        self.assertEqual("Error: Unknown loaded rule 'not-a-rule'.\n", unknown_filter_stderr.getvalue())
        self.assertEqual(1, unknown_reference_status)
        self.assertEqual("", unknown_reference_stdout.getvalue())
        self.assertIn("Unknown ruleset reference 'not-a-ruleset'.", unknown_reference_stderr.getvalue())
        self.assertEqual(1, unknown_rule_exclusion_status)
        self.assertEqual("", unknown_rule_exclusion_stdout.getvalue())
        self.assertIn("Unknown rule exclusion 'ExcessiveMethodLenght'.", unknown_rule_exclusion_stderr.getvalue())
        self.assertEqual(1, unknown_ruleset_exclusion_status)
        self.assertEqual("", unknown_ruleset_exclusion_stdout.getvalue())
        self.assertIn("Unknown rule exclusion 'ExcessiveMethodLenght'.", unknown_ruleset_exclusion_stderr.getvalue())

    def test_callable_metrics_cover_python_callables_and_exact_configured_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "callables.py"
            ruleset = temporary / "callable-metrics.xml"
            parameter_ruleset = temporary / "parameter-forms.xml"
            lambda_ruleset = temporary / "lambda-metrics.xml"
            source.write_text(
                "def decision_flow(value: int | None) -> int:\n"
                "    if value and value > 0:\n        pass\n"
                "    for item in [value]:\n        pass\n"
                "    while value:\n        break\n"
                "    try:\n        raise RuntimeError\n"
                "    except RuntimeError:\n        pass\n"
                "    branch = max(1 if value else 0, 0)\n"
                "    values = [1 if item else 0 for item in range(2) if item]\n"
                "    match value:\n"
                "        case 1:\n            pass\n"
                "        case _:\n            pass\n"
                "    return branch\n\n"
                "def exact_length():\n    pass\n    pass\n\n"
                "def function(first, second, third, fourth, fifth, sixth, seventh, eighth, ninth, tenth):\n    pass\n\n"
                "async def async_function(first, second, third, fourth, fifth, sixth, seventh, eighth, ninth, tenth):\n    pass\n\n"
                "class Service:\n"
                "    def __init__(self, first, second, third, fourth, fifth, sixth, seventh, eighth, ninth, tenth):\n        pass\n\n"
                "    def method(self, first, second, third, fourth, fifth, sixth, seventh, eighth, ninth, tenth):\n        pass\n\n"
                "    async def async_method(self, first, second, third, fourth, fifth, sixth, seventh, eighth, ninth, tenth):\n        pass\n\n"
                "    @classmethod\n"
                "    def class_method(cls, first, second, third, fourth, fifth, sixth, seventh, eighth, ninth, tenth):\n        pass\n\n"
                "    def receiver_only(self, first, second, third, fourth, fifth, sixth, seventh, eighth, ninth):\n        pass\n\n"
                "    @staticmethod\n"
                "    def static_method(first, second, third, fourth, fifth, sixth, seventh, eighth, ninth, tenth):\n        pass\n\n"
                "    def parameter_forms(self, first, /, second, *rest, named, **extra):\n        pass\n\n"
                "lambda_value = lambda first, second, third, fourth, fifth, sixth, seventh, eighth, ninth, tenth: first\n"
                "lambda_decision = lambda value: 1 if value else 0\n\n"
                "def annotated(value: dict[str, list[int | None]]) -> tuple[int | None, ...]:\n    return (value,)[0]\n",
                encoding="utf-8",
            )
            ruleset.write_text(
                """<ruleset name="callable metrics">
    <rule ref="CyclomaticComplexity"><properties><property name="reportLevel" value="12" /></properties></rule>
    <rule ref="NPathComplexity"><properties><property name="minimum" value="1152" /></properties></rule>
    <rule ref="ExcessiveMethodLength"><properties><property name="minimum" value="3" /></properties></rule>
    <rule ref="ExcessiveParameterList"><properties><property name="minimum" value="10" /></properties></rule>
</ruleset>
""",
                encoding="utf-8",
            )
            parameter_ruleset.write_text(
                """<ruleset name="parameter forms">
    <rule ref="ExcessiveParameterList"><properties><property name="minimum" value="5" /></properties></rule>
</ruleset>
""",
                encoding="utf-8",
            )
            lambda_ruleset.write_text(
                """<ruleset name="lambda metrics">
    <rule ref="CyclomaticComplexity"><properties><property name="reportLevel" value="2" /></properties></rule>
    <rule ref="NPathComplexity"><properties><property name="minimum" value="3" /></properties></rule>
</ruleset>
""",
                encoding="utf-8",
            )

            stdout = StringIO()
            stderr = StringIO()
            status = run([str(source), "text", str(ruleset)], stdout, stderr)
            parameter_stdout = StringIO()
            parameter_stderr = StringIO()
            parameter_status = run(
                [str(source), "text", str(parameter_ruleset)],
                parameter_stdout,
                parameter_stderr,
            )
            lambda_stdout = StringIO()
            lambda_stderr = StringIO()
            lambda_status = run(
                [str(source), "text", str(lambda_ruleset)],
                lambda_stdout,
                lambda_stderr,
            )
            parameter_report = parameter_stdout.getvalue()
            lambda_report = lambda_stdout.getvalue()

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        self.assertIn(
            "CyclomaticComplexity [priority 3] The function decision_flow() has a Cyclomatic Complexity of 12. "
            "The configured cyclomatic complexity threshold is 12.",
            report,
        )
        self.assertIn(
            "NPathComplexity [priority 3] The function decision_flow() has an NPath complexity of 1152. "
            "The configured NPath complexity threshold is 1152.",
            report,
        )
        self.assertIn(
            "The function exact_length() has 3 lines of code. Current threshold is set to 3. Avoid really long methods.",
            report,
        )
        for kind, name, parameter_count in [
            ("function", "function", 10),
            ("function", "async_function", 10),
            ("method", "__init__", 11),
            ("method", "method", 11),
            ("method", "async_method", 11),
            ("method", "class_method", 11),
            ("method", "static_method", 10),
            ("lambda", "<lambda>", 10),
        ]:
            self.assertIn(
                f"ExcessiveParameterList [priority 3] The {kind} {name} has {parameter_count} parameters. "
                "Consider reducing the number of parameters to less than 10.",
                report,
            )
        self.assertIn(
            "The method receiver_only has 10 parameters. Consider reducing the number of parameters to less than 10.",
            report,
        )
        self.assertNotIn("annotated has", report)
        self.assertEqual(2, parameter_status)
        self.assertEqual("", parameter_stderr.getvalue())
        self.assertIn(
            "The method parameter_forms has 6 parameters. Consider reducing the number of parameters to less than 5.",
            parameter_report,
        )
        self.assertEqual(2, lambda_status)
        self.assertEqual("", lambda_stderr.getvalue())
        self.assertIn("The lambda <lambda>() has a Cyclomatic Complexity of 2.", lambda_report)
        self.assertIn("The lambda <lambda>() has an NPath complexity of 3.", lambda_report)

    def test_phpmd_2_15_0_codesize_reference_keeps_callable_messages_and_priorities_stable(self) -> None:
        reference = json.loads((FIXTURES / "phpmd_2_15_0_codesize.json").read_text(encoding="utf-8"))
        self.assertEqual("2.15.0", reference["version"])
        self.assertTrue((FIXTURES / reference["php_fixture"]).is_file())
        python_fixture = FIXTURES / reference["python_fixture"]
        self.assertTrue(python_fixture.is_file())
        self.assertEqual(
            "vendor/bin/phpmd tests/fixtures/phpmd_2_15_0_callable_metrics.php text codesize",
            reference["phpmd_command"],
        )
        self.assertEqual(
            [
                "CyclomaticComplexity    The function decisionFlow() has a Cyclomatic Complexity of 10. "
                "The configured cyclomatic complexity threshold is 10.",
                "NPathComplexity         The function decisionFlow() has an NPath complexity of 512. "
                "The configured NPath complexity threshold is 200.",
                "ExcessiveParameterList  The function decisionFlow has 10 parameters. "
                "Consider reducing the number of parameters to less than 10.",
            ],
            reference["phpmd_text_output"],
        )

        reports: dict[str, str] = {}
        for rule_name, source in [
            ("CyclomaticComplexity", python_fixture),
            ("NPathComplexity", python_fixture),
            ("ExcessiveParameterList", python_fixture),
            ("ExcessiveMethodLength", FIXTURES / "long_function.py"),
        ]:
            stdout = StringIO()
            stderr = StringIO()
            status = run([str(source), "text", rule_name], stdout, stderr)
            self.assertEqual(2, status, rule_name)
            self.assertEqual("", stderr.getvalue(), rule_name)
            reports[rule_name] = stdout.getvalue()

        expected_messages = {
            "CyclomaticComplexity": "The function decision_flow() has a Cyclomatic Complexity of 10. "
            "The configured cyclomatic complexity threshold is 10.",
            "NPathComplexity": "The function decision_flow() has an NPath complexity of 512. "
            "The configured NPath complexity threshold is 200.",
            "ExcessiveParameterList": "The function decision_flow has 10 parameters. "
            "Consider reducing the number of parameters to less than 10.",
            "ExcessiveMethodLength": "The function too_long() has 101 lines of code. "
            "Current threshold is set to 100. Avoid really long methods.",
        }
        for rule in reference["rules"]:
            self.assertIn(f"{rule['name']} [priority {rule['priority']}]", reports[rule["name"]])
            self.assertIn(expected_messages[rule["name"]], reports[rule["name"]])
            self.assertEqual(1, reports[rule["name"]].count(f"{rule['name']} [priority"))
            for other_rule in reference["rules"]:
                if other_rule["name"] != rule["name"]:
                    self.assertNotIn(other_rule["name"], reports[rule["name"]])

    def test_callable_metrics_below_each_default_threshold_are_clean(self) -> None:
        sources = {
            "CyclomaticComplexity": "def choose(value):\n" + "    if value:\n        return value\n" * 8,
            "NPathComplexity": "def choose(value):\n" + "    if value:\n        value += 1\n" * 7,
            "ExcessiveMethodLength": _function_with_passes("choose", 98),
            "ExcessiveParameterList": "def choose(first, second, third, fourth, fifth, sixth, seventh, eighth, ninth):\n    pass\n",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            for rule_name, source_text in sources.items():
                source = temporary / f"{rule_name}.py"
                source.write_text(source_text, encoding="utf-8")
                stdout = StringIO()
                stderr = StringIO()

                status = run([str(source), "text", rule_name], stdout, stderr)

                self.assertEqual(0, status, rule_name)
                self.assertEqual("", stdout.getvalue(), rule_name)
                self.assertEqual("", stderr.getvalue(), rule_name)

    def test_callable_metrics_leave_idiomatic_python_quiet(self) -> None:
        source_text = (
            "def normalized_labels(raw_labels: list[str]) -> list[str]:\n"
            "    labels = [label.strip().lower() for label in raw_labels if label.strip()]\n"
            "    return sorted(set(labels))\n"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "labels.py"
            source.write_text(source_text, encoding="utf-8")
            for rule_name in [
                "CyclomaticComplexity",
                "NPathComplexity",
                "ExcessiveMethodLength",
                "ExcessiveParameterList",
            ]:
                stdout = StringIO()
                stderr = StringIO()

                status = run([str(source), "text", rule_name], stdout, stderr)

                self.assertEqual(0, status, rule_name)
                self.assertEqual("", stdout.getvalue(), rule_name)
                self.assertEqual("", stderr.getvalue(), rule_name)

    def test_npath_counts_conditional_expression_in_comprehension_element(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "comprehension.py"
            ruleset = temporary / "npath.xml"
            source.write_text(
                "def choose(values):\n    return [1 if value else 0 for value in values]\n",
                encoding="utf-8",
            )
            ruleset.write_text(
                """<ruleset name="npath">
    <rule ref="NPathComplexity"><properties><property name="minimum" value="3" /></properties></rule>
</ruleset>
""",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", str(ruleset)], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        self.assertIn(
            "The function choose() has an NPath complexity of 3. The configured NPath complexity threshold is 3.",
            stdout.getvalue(),
        )

    def test_class_metrics_scan_real_python_classes_with_configured_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "service.py"
            ruleset = temporary / "class-metrics.xml"
            source.write_text(
                "class Service:\n"
                "    public_field: int = 1\n"
                "    another_field = 2\n"
                "    _private_field = 3\n"
                "\n"
                "    def get_value(self):\n"
                "        return self.public_field\n"
                "\n"
                "    def work_one(self, value):\n"
                "        if value:\n"
                "            return value\n"
                "        return 0\n"
                "\n"
                "    async def work_two(self, value):\n"
                "        if value:\n"
                "            return value\n"
                "        return 0\n"
                "\n"
                "    class Nested:\n"
                "        nested_field = 1\n"
                "        def nested_work(self):\n"
                "            return self.nested_field\n"
                "\n"
                "class ServiceProtocol(Protocol):\n"
                "    protocol_field: int\n"
                "    def contract(self) -> int: ...\n"
                "\n"
                "class AbstractService(ABC):\n"
                "    @abstractmethod\n"
                "    def contract(self) -> int:\n"
                "        raise NotImplementedError\n",
                encoding="utf-8",
            )
            ruleset.write_text(
                """<ruleset name="class metrics">
    <rule ref="ExcessiveClassLength"><properties><property name="minimum" value="22" /></properties></rule>
    <rule ref="ExcessivePublicCount"><properties><property name="minimum" value="5" /></properties></rule>
    <rule ref="TooManyFields"><properties><property name="maxfields" value="2" /></properties></rule>
    <rule ref="TooManyMethods"><properties><property name="maxmethods" value="1" /></properties></rule>
    <rule ref="TooManyPublicMethods"><properties><property name="maxmethods" value="1" /></properties></rule>
    <rule ref="ExcessiveClassComplexity"><properties><property name="maximum" value="5" /></properties></rule>
</ruleset>
""",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", str(ruleset)], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        self.assertIn(
            "ExcessiveClassLength [priority 3] The class Service has 22 lines of code. "
            "Current threshold is set to 22. Avoid really long classes.",
            report,
        )
        self.assertIn(
            "ExcessivePublicCount [priority 3] The class Service has 5 public methods and attributes. "
            "Consider reducing the number of public items to less than 5.",
            report,
        )
        self.assertIn(
            "TooManyFields [priority 3] The class Service has 3 fields. "
            "Consider redesigning Service to keep the number of fields under 2.",
            report,
        )
        self.assertIn(
            "TooManyMethods [priority 3] The class Service has 2 non-getter- and setter-methods. "
            "Consider refactoring Service to keep number of methods under 1.",
            report,
        )
        self.assertIn(
            "TooManyPublicMethods [priority 3] The class Service has 2 public methods. "
            "Consider refactoring Service to keep number of public methods under 1.",
            report,
        )
        self.assertIn(
            "ExcessiveClassComplexity [priority 3] The class Service has an overall complexity of 5 "
            "which is very high. The configured complexity threshold is 5.",
            report,
        )
        self.assertNotIn("Nested has", report)
        self.assertNotIn("ServiceProtocol has", report)
        self.assertNotIn("AbstractService has an overall complexity", report)

    def test_codesize_includes_all_ten_callable_and_class_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "clean.py"
            source.write_text("class Service:\n    pass\n", encoding="utf-8")
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "codesize", "--verbose"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual(
            "Loaded rules: CyclomaticComplexity, NPathComplexity, ExcessiveMethodLength, "
            "ExcessiveClassLength, ExcessiveParameterList, ExcessivePublicCount, TooManyFields, "
            "TooManyMethods, TooManyPublicMethods, ExcessiveClassComplexity\n",
            stderr.getvalue(),
        )

    def test_field_metrics_include_conventional_instance_attributes_without_static_noise(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "model.py"
            ruleset = temporary / "fields.xml"
            source.write_text(
                "class Model:\n"
                "    declared: str\n"
                "\n"
                "    def __init__(self):\n"
                "        self.active = True\n"
                "        self._cache = {}\n"
                "\n"
                "    @staticmethod\n"
                "    def configure(value):\n"
                "        value.not_a_model_field = True\n",
                encoding="utf-8",
            )
            ruleset.write_text(
                """<ruleset name="fields">
    <rule ref="TooManyFields"><properties><property name="maxfields" value="2" /></properties></rule>
    <rule ref="ExcessivePublicCount"><properties><property name="minimum" value="2" /></properties></rule>
</ruleset>
""",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", str(ruleset)], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        self.assertIn("The class Model has 3 fields.", stdout.getvalue())
        self.assertIn("The class Model has 3 public methods and attributes.", stdout.getvalue())

    def test_codesize_reports_every_callable_and_class_rule_in_one_real_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "all_codesize_rules.py"
            fields = "".join(f"    field_{index} = {index}\n" for index in range(45))
            complex_methods = "".join(
                f"    def work_{index}(self, first, second, third, fourth, fifth, sixth, seventh, eighth, ninth):\n"
                + "".join(f"        if value_{branch}:\n            pass\n" for branch in range(9))
                + ("        pass\n" * 90 if index == 0 else "")
                for index in range(11)
            )
            private_methods = "".join(
                f"    def _work_{index}(self):\n        return None\n" for index in range(15)
            )
            source.write_text(
                "class Everything:\n"
                + fields
                + complex_methods
                + private_methods
                + "".join(f"    _filler_{index} = None\n" for index in range(650)),
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "codesize"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        for rule_name in [
            "CyclomaticComplexity",
            "NPathComplexity",
            "ExcessiveMethodLength",
            "ExcessiveParameterList",
            "ExcessiveClassLength",
            "ExcessivePublicCount",
            "TooManyFields",
            "TooManyMethods",
            "TooManyPublicMethods",
            "ExcessiveClassComplexity",
        ]:
            self.assertIn(rule_name, stdout.getvalue())

    def test_class_rule_default_boundaries_and_conventional_interfaces_are_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "boundary.py"
            fields = "".join(f"    field_{index} = {index}\n" for index in range(15))
            methods = "".join(
                f"    def work_{index}(self):\n        return {index}\n" for index in range(10)
            ) + "".join(f"    def _work_{index}(self):\n        return {index}\n" for index in range(15))
            source.write_text(
                "class Boundary:\n"
                + fields
                + methods
                + "\nclass Interface(Protocol):\n"
                + "    value: int\n"
                + "    @overload\n"
                + "    def parse(self, value: int) -> int: ...\n"
                + "\nclass AbstractInterface(ABC):\n"
                + "    @abstractmethod\n"
                + "    def parse(self, value: int) -> int:\n"
                + "        raise NotImplementedError\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "codesize"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_dataclass_fields_are_real_without_inventing_generated_methods(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "generated.py"
            ruleset = temporary / "generated.xml"
            source.write_text(
                "from dataclasses import dataclass\n"
                "\n"
                "@dataclass\n"
                "class Generated:\n"
                "    first: int\n"
                "    second: int\n"
                "    third: int\n",
                encoding="utf-8",
            )
            ruleset.write_text(
                """<ruleset name="generated">
    <rule ref="TooManyFields"><properties><property name="maxfields" value="2" /></properties></rule>
    <rule ref="TooManyMethods"><properties><property name="maxmethods" value="0" /></properties></rule>
    <rule ref="TooManyPublicMethods"><properties><property name="maxmethods" value="0" /></properties></rule>
    <rule ref="ExcessivePublicCount"><properties><property name="minimum" value="4" /></properties></rule>
    <rule ref="ExcessiveClassComplexity"><properties><property name="maximum" value="1" /></properties></rule>
</ruleset>
""",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", str(ruleset)], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        self.assertIn("TooManyFields [priority 3] The class Generated has 3 fields.", stdout.getvalue())
        for rule_name in [
            "TooManyMethods",
            "TooManyPublicMethods",
            "ExcessivePublicCount",
            "ExcessiveClassComplexity",
        ]:
            self.assertNotIn(rule_name, stdout.getvalue())

    def test_naming_rules_find_unambiguous_python_roles_in_one_cli_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "names.py"
            source.write_text(
                "from typing import Final, TypeVar\n"
                "\n"
                "T = TypeVar(\"T\")\n"
                "\n"
                "def go():\n"
                "    return None\n"
                "\n"
                "class Ab:\n"
                "    pass\n"
                "\n"
                "class ThisClassNameIsLongerThanTheDefaultMaximum:\n"
                "    pass\n"
                "\n"
                "class Holder:\n"
                "    ab = 1\n"
                "\n"
                "    def ok(self, ab):\n"
                "        very_long_variable_name = ab\n"
                "        return very_long_variable_name\n"
                "\n"
                "    def get_ready(self) -> bool:\n"
                "        return True\n"
                "\n"
                "wrong_constant: Final = 1\n"
                "UPPER_CASE: Final = 2\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "naming"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        for rule_name in [
            "ShortClassName",
            "LongClassName",
            "ShortVariable",
            "LongVariable",
            "ShortMethodName",
            "ConstantNamingConventions",
            "BooleanGetMethodName",
        ]:
            self.assertIn(rule_name, report)
        self.assertNotIn("ConstructorWithNameAsEnclosingClass", report)

    def test_naming_rules_scope_exemptions_and_boolean_proof_to_python_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "role_scoped_names.py"
            source.write_text(
                "class e:\n"
                "    pass\n"
                "\n"
                "class Holder:\n"
                "    ab = 1\n"
                "    x = 1\n"
                "    y = 2\n"
                "\n"
                "    def i(self):\n"
                "        return None\n"
                "\n"
                "    def get_remote(self):\n"
                "        return service.bool()\n"
                "\n"
                "    def get_annotated(self) -> service.bool:\n"
                "        return object()\n"
                "\n"
                "    def get_partial(self):\n"
                "        if condition:\n"
                "            return True\n"
                "\n"
                "    @property\n"
                "    def p(self):\n"
                "        return 1\n"
                "\n"
                "    @p.setter\n"
                "    def p(self, value):\n"
                "        pass\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "naming"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        self.assertIn("ShortClassName [priority 3] Avoid using short class names like e.", report)
        self.assertIn("ShortVariable [priority 3] Avoid variables with short names like ab.", report)
        self.assertNotIn("ShortVariable [priority 3] Avoid variables with short names like x.", report)
        self.assertNotIn("ShortVariable [priority 3] Avoid variables with short names like y.", report)
        self.assertIn("ShortMethodName [priority 3] Avoid using short method names like i().", report)
        self.assertNotIn("ShortMethodName [priority 3] Avoid using short method names like p().", report)
        self.assertNotIn("BooleanGetMethodName", report)

    def test_naming_rules_honor_configured_lengths_at_the_cli_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "configured_names.py"
            ruleset = temporary / "configured-naming.xml"
            source.write_text(
                "class Four:\n"
                "    four = 1\n"
                "\n"
                "    def four(self, four):\n"
                "        longer = four\n"
                "        return longer\n"
                "\n"
                "class ExactlyFive:\n"
                "    pass\n",
                encoding="utf-8",
            )
            ruleset.write_text(
                """<ruleset name="configured naming">
    <rule ref="ShortClassName"><properties><property name="minimum" value="5" /></properties></rule>
    <rule ref="LongClassName"><properties><property name="maximum" value="10" /></properties></rule>
    <rule ref="ShortVariable"><properties><property name="minimum" value="5" /></properties></rule>
    <rule ref="LongVariable"><properties><property name="maximum" value="5" /></properties></rule>
    <rule ref="ShortMethodName"><properties><property name="minimum" value="5" /></properties></rule>
</ruleset>
""",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", str(ruleset)], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        self.assertIn("ShortClassName [priority 3] Avoid using short class names like Four. Configured minimum length is 5.", report)
        self.assertIn("LongClassName [priority 3] Avoid excessively long class names like ExactlyFive. Configured maximum length is 10.", report)
        self.assertIn("ShortVariable [priority 3] Avoid variables with short names like four. Configured minimum length is 5.", report)
        self.assertIn("LongVariable [priority 3] Avoid excessively long variable names like longer. Configured maximum length is 5.", report)
        self.assertIn("ShortMethodName [priority 3] Avoid using short method names like four(). Configured minimum length is 5.", report)

    def test_naming_rules_keep_python_idioms_and_default_boundaries_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "idiomatic_names.py"
            source_text = (
                "from typing import Final, TypeVar\n"
                "\n"
                "T = TypeVar(\"T\")\n"
                "\n"
                "class Cat:\n"
                "    age = 1\n"
                "\n"
                "    def run(self, value, /, *, option):\n"
                "        abc = value\n"
                "        very_long_variable_n = option\n"
                "        for i, x, y in enumerate((abc, very_long_variable_n)):\n"
                "            abc += i + x + y\n"
                "        try:\n"
                "            raise ValueError\n"
                "        except ValueError as exc:\n"
                "            return abc\n"
                "\n"
                "    def get_value(self):\n"
                "        return object()\n"
                "\n"
                "    def is_ready(self) -> bool:\n"
                "        return True\n"
                "\n"
                "    def _go(self):\n"
                "        __internal__ = 1\n"
                "        return __internal__\n"
                "\n"
                "MAXIMUM_VALUE: Final = 1\n"
                "__all__: Final = (\"Cat\",)\n"
                "THIS_IS_AN_UPPER_CASE_CONSTANT_LONGER_THAN_TWENTY = 1\n"
                + f"class {'C' * 40}:\n    pass\n"
            )
            source.write_text(
                source_text,
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "naming"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_unusedcode_reports_an_unused_function_local_through_the_command_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "unused_local.py"
            source.write_text(
                "def build():\n"
                "    discarded = 1\n"
                "    return 0\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        self.assertIn(
            "UnusedLocalVariable [priority 3] Avoid unused local variables such as 'discarded'.",
            stdout.getvalue(),
        )

    def test_unusedcode_reports_an_unused_parameter_through_the_command_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "unused_parameter.py"
            source.write_text(
                "def transform(value, unused):\n"
                "    return value\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        self.assertIn(
            "UnusedFormalParameter [priority 3] Avoid unused parameters such as 'unused'.",
            stdout.getvalue(),
        )

    def test_unusedcode_reports_an_unused_private_field_through_the_command_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "unused_field.py"
            source.write_text(
                "class Cache:\n"
                "    def __init__(self):\n"
                "        self._stale = 1\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        self.assertIn(
            "UnusedPrivateField [priority 3] Avoid unused private fields such as '_stale'.",
            stdout.getvalue(),
        )

    def test_unusedcode_reports_an_unused_private_method_through_the_command_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "unused_method.py"
            source.write_text(
                "class Service:\n"
                "    def _discarded(self):\n"
                "        return None\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        self.assertIn(
            "UnusedPrivateMethod [priority 3] Avoid unused private methods such as '_discarded'.",
            stdout.getvalue(),
        )

    def test_unusedcode_keeps_closure_and_comprehension_bindings_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "scopes.py"
            source.write_text(
                "def transform(values):\n"
                "    captured = 1\n"
                "    def read_capture():\n"
                "        return captured\n"
                "    return [item + read_capture() for item in values]\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_unusedcode_reports_unused_exception_and_pattern_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "bindings.py"
            source.write_text(
                "def parse(value):\n"
                "    try:\n"
                "        raise ValueError\n"
                "    except ValueError as error:\n"
                "        match value:\n"
                "            case {\"id\": item}:\n"
                "                return value\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        self.assertIn("UnusedLocalVariable [priority 3] Avoid unused local variables such as 'error'.", report)
        self.assertIn("UnusedLocalVariable [priority 3] Avoid unused local variables such as 'item'.", report)

    def test_unusedcode_honors_a_configured_rule_priority_at_the_command_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "configured_unused.py"
            ruleset = temporary / "unused.xml"
            source.write_text("def build():\n    discarded = 1\n", encoding="utf-8")
            ruleset.write_text(
                """<ruleset name="unused">
    <rule ref="UnusedLocalVariable"><priority>2</priority></rule>
</ruleset>
""",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", str(ruleset)], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        self.assertIn("UnusedLocalVariable [priority 2]", stdout.getvalue())

    def test_unusedcode_keeps_generated_and_dynamic_private_members_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "conservative_members.py"
            source.write_text(
                "from dataclasses import dataclass\n"
                "\n"
                "@dataclass\n"
                "class Record:\n"
                "    _stored: int\n"
                "\n"
                "class Dynamic:\n"
                "    def __init__(self):\n"
                "        self._cached = 1\n"
                "\n"
                "    def read(self, name):\n"
                "        return getattr(self, name)\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_unusedcode_keeps_global_and_nonlocal_bindings_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "global_nonlocal.py"
            source.write_text(
                "shared = 0\n"
                "\n"
                "def write_global():\n"
                "    global shared\n"
                "    shared = 1\n"
                "\n"
                "def outer():\n"
                "    captured = 0\n"
                "    def write_capture():\n"
                "        nonlocal captured\n"
                "        captured = 1\n"
                "    return write_capture\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_unusedcode_keeps_contracts_and_decorated_members_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "contracts.py"
            source.write_text(
                "from abc import ABC, abstractmethod\n"
                "from typing import Protocol, overload\n"
                "\n"
                "def decorator(function):\n"
                "    return function\n"
                "\n"
                "class Contract(Protocol):\n"
                "    @overload\n"
                "    def _convert(self, value): ...\n"
                "\n"
                "class Abstract(ABC):\n"
                "    @abstractmethod\n"
                "    def _hook(self, value):\n"
                "        raise NotImplementedError\n"
                "\n"
                "class Model:\n"
                "    @property\n"
                "    def _value(self):\n"
                "        return 1\n"
                "\n"
                "    @decorator\n"
                "    def _decorated(self, value):\n"
                "        pass\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_unusedcode_keeps_used_private_members_and_underscore_parameters_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "used_members.py"
            source.write_text(
                "class Cache:\n"
                "    def __init__(self):\n"
                "        self._value = 1\n"
                "\n"
                "    def read(self, _context):\n"
                "        return self._read_value()\n"
                "\n"
                "    def _read_value(self):\n"
                "        return self._value\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_unusedcode_keeps_externally_and_qualified_dynamically_used_members_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "external_members.py"
            source.write_text(
                "import builtins\n"
                "from dataclasses import dataclass\n"
                "\n"
                "@dataclass(frozen=True)\n"
                "class Record:\n"
                "    _stored: int\n"
                "\n"
                "class Cache:\n"
                "    def __init__(self):\n"
                "        self._value = 1\n"
                "\n"
                "    def _refresh(self):\n"
                "        return self._value\n"
                "\n"
                "cache = Cache()\n"
                "cache._value\n"
                "cache._refresh()\n"
                "builtins.getattr(cache, name)\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_unusedcode_honors_configured_priorities_for_every_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "configured_all_unused.py"
            ruleset = temporary / "unused.xml"
            source.write_text(
                "def build(unused):\n"
                "    discarded = 1\n"
                "\n"
                "class Cache:\n"
                "    _stale = 1\n"
                "\n"
                "    def _discarded(self):\n"
                "        return None\n",
                encoding="utf-8",
            )
            ruleset.write_text(
                """<ruleset name="unused">
    <rule ref="UnusedLocalVariable"><priority>1</priority></rule>
    <rule ref="UnusedFormalParameter"><priority>2</priority></rule>
    <rule ref="UnusedPrivateField"><priority>4</priority></rule>
    <rule ref="UnusedPrivateMethod"><priority>5</priority></rule>
</ruleset>
""",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", str(ruleset)], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        self.assertIn("UnusedLocalVariable [priority 1]", report)
        self.assertIn("UnusedFormalParameter [priority 2]", report)
        self.assertIn("UnusedPrivateField [priority 4]", report)
        self.assertIn("UnusedPrivateMethod [priority 5]", report)

    def test_unusedcode_reports_an_unused_comprehension_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "unused_comprehension.py"
            source.write_text(
                "def build(values):\n"
                "    return [0 for item in values]\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        self.assertIn(
            "UnusedLocalVariable [priority 3] Avoid unused local variables such as 'item'.",
            stdout.getvalue(),
        )

    def test_unusedcode_keeps_exported_private_members_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "exported_member.py"
            source.write_text(
                "__all__ = (\"_helper\",)\n"
                "\n"
                "class Service:\n"
                "    def _helper(self):\n"
                "        return None\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_unusedcode_handles_aliased_dataclasses_and_protocol_default_methods_conservatively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "generated_contracts.py"
            source.write_text(
                "from dataclasses import dataclass, dataclass as dc\n"
                "from typing import Protocol\n"
                "\n"
                "@dc\n"
                "class Record:\n"
                "    _stored: int\n"
                "\n"
                "@dataclass\n"
                "class Service:\n"
                "    def _dead(self):\n"
                "        return None\n"
                "\n"
                "class Contract(Protocol):\n"
                "    def transform(self, value):\n"
                "        return 0\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        self.assertIn("UnusedPrivateMethod [priority 3] Avoid unused private methods such as '_dead'.", report)
        self.assertNotIn("_stored", report)
        self.assertNotIn("UnusedFormalParameter", report)

    def test_unusedcode_reports_an_unused_lambda_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "expression_scopes.py"
            source.write_text(
                "transform = lambda unused: 0\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "unusedcode"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        self.assertIn("UnusedFormalParameter [priority 3] Avoid unused parameters such as 'unused'.", report)

    def test_cleancode_finds_each_honest_python_hazard_through_the_command_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "hazards.py"
            source.write_text(
                "class Logger:\n"
                "    @staticmethod\n"
                "    def write(value):\n"
                "        return value\n"
                "\n"
                "def choose(flag: bool):\n"
                "    if flag:\n"
                "        return 1\n"
                "    else:\n"
                "        return 0\n"
                "\n"
                "def inspect(values):\n"
                "    if current := values:\n"
                "        return Logger.write(current)\n"
                "    return {\"alpha\": 1, \"alpha\": 2}\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "cleancode"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        for rule_name in [
            "BooleanArgumentFlag",
            "ElseExpression",
            "StaticAccess",
            "IfStatementAssignment",
            "DuplicatedArrayKey",
        ]:
            self.assertIn(rule_name, report)

    def test_cleancode_keeps_clean_boundaries_and_dynamic_dictionary_keys_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "clean_hazards.py"
            source.write_text(
                "dynamic_key = object()\n"
                "\n"
                "class Worker:\n"
                "    def choose(self, value: object = None):\n"
                "        if value is None:\n"
                "            return Worker.default()\n"
                "        elif value:\n"
                "            return logger.write(value)\n"
                "        return {dynamic_key: 1, dynamic_key: 2, \"first\": 1, \"second\": 2}\n"
                "\n"
                "    @staticmethod\n"
                "    def default():\n"
                "        return 0\n"
                "\n"
                "def calculate(values):\n"
                "    current = values\n"
                "    return (stored := current)\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "cleancode"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_cleancode_uses_python_syntax_boundaries_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "boundaries.py"
            source.write_text(
                "from typing import Optional\n"
                "\n"
                "class Logger:\n"
                "    @staticmethod\n"
                "    def write():\n"
                "        return None\n"
                "\n"
                "    @staticmethod\n"
                "    def close():\n"
                "        return None\n"
                "\n"
                "if enabled:\n"
                "    Logger.write()\n"
                "else:\n"
                "    Logger.close()\n"
                "\n"
                "def inspect(option: bool | None = False, *, enabled: Optional[bool] = None, unknown: service.bool = None):\n"
                "    if (lambda: (hidden := option)):\n"
                "        pass\n"
                "    while current := enabled:\n"
                "        break\n"
                "    if \"é\" and (unicode_name := enabled):\n"
                "        pass\n"
                "    return {True: 1, 1: 2, -True: 3, -1: 4, (\"known\", 1): 5, (\"known\", True): 6, ...: 7, ...: 8, dynamic: 9, dynamic: 10, [1]: 11, [1]: 12}\n"
                "\n"
                "class Worker:\n"
                "    if enabled:\n"
                "        def run(self):\n"
                "            return Worker.build()\n"
                "\n"
                "    @staticmethod\n"
                "    def build():\n"
                "        return None\n",
                encoding="utf-8",
            )
            reports = {}
            for rule_name in [
                "BooleanArgumentFlag",
                "ElseExpression",
                "StaticAccess",
                "IfStatementAssignment",
                "DuplicatedArrayKey",
            ]:
                stdout = StringIO()
                stderr = StringIO()
                status = run(
                    [str(source), "text", "cleancode", "--only", rule_name],
                    stdout,
                    stderr,
                )
                reports[rule_name] = (status, stdout.getvalue(), stderr.getvalue())

        self.assertEqual(2, reports["BooleanArgumentFlag"][0])
        self.assertEqual(2, reports["BooleanArgumentFlag"][1].count("BooleanArgumentFlag"))
        self.assertNotIn("unknown", reports["BooleanArgumentFlag"][1])
        self.assertEqual((0, "", ""), reports["ElseExpression"])
        self.assertEqual((0, "", ""), reports["StaticAccess"])
        self.assertEqual(2, reports["IfStatementAssignment"][0])
        self.assertEqual(2, reports["IfStatementAssignment"][1].count("IfStatementAssignment"))
        self.assertIn("column '17'", reports["IfStatementAssignment"][1])
        self.assertNotIn("hidden", reports["IfStatementAssignment"][1])
        self.assertEqual(2, reports["DuplicatedArrayKey"][0])
        self.assertEqual(4, reports["DuplicatedArrayKey"][1].count("DuplicatedArrayKey"))
        self.assertEqual("", reports["DuplicatedArrayKey"][2])

    def test_cleancode_honors_boolean_and_static_access_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            source = directory / "configured_hazards.py"
            ruleset = directory / "configured.xml"
            source.write_text(
                "class Logger:\n"
                "    @staticmethod\n"
                "    def write(value):\n"
                "        return value\n"
                "\n"
                "class Gateway:\n"
                "    @staticmethod\n"
                "    def write(value):\n"
                "        return value\n"
                "\n"
                "class Service:\n"
                "    if enabled:\n"
                "        def choose(self, flag: bool):\n"
                "            return Logger.write(flag)\n"
                "\n"
                "def ignored_choice(flag: bool):\n"
                "    return Logger.write(flag)\n"
                "\n"
                "def active_choice(flag: bool):\n"
                "    return Gateway.write(flag)\n",
                encoding="utf-8",
            )
            ruleset.write_text(
                "<ruleset><rule ref=\"cleancode\"><properties>"
                "<property name=\"exceptions\" value=\"Service,Logger\"/>"
                "<property name=\"ignorepattern\" value=\"^ignored_\"/>"
                "</properties></rule></ruleset>",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", str(ruleset)], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        self.assertEqual(1, report.count("BooleanArgumentFlag"))
        self.assertEqual(1, report.count("StaticAccess"))
        self.assertIn("active_choice", report)
        self.assertIn("Gateway", report)
        self.assertNotIn("ignored_choice", report)

    def test_python_policy_permits_ordinary_idioms_and_opinionated_selects_every_clean_code_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            ordinary_source = directory / "ordinary_policy.py"
            hazard_source = directory / "opinionated_policy.py"
            logger = (
                "class Logger:\n"
                "    @staticmethod\n"
                "    def write(value):\n"
                "        return value\n"
                "\n"
            )
            ordinary_source.write_text(
                logger
                + "def choose(flag: bool):\n"
                "    if flag:\n"
                "        return Logger.write(flag)\n"
                "    else:\n"
                "        return 0\n",
                encoding="utf-8",
            )
            hazard_source.write_text(
                logger
                + "def choose(flag: bool):\n"
                "    if current := flag:\n"
                "        return Logger.write({\"same\": 1, \"same\": 2})\n"
                "    else:\n"
                "        return 0\n",
                encoding="utf-8",
            )
            python_stdout = StringIO()
            python_stderr = StringIO()
            python_status = run(
                [str(ordinary_source), "text", "python"], python_stdout, python_stderr
            )
            selected_reports = []
            for rule_name in [
                "BooleanArgumentFlag",
                "ElseExpression",
                "StaticAccess",
                "IfStatementAssignment",
                "DuplicatedArrayKey",
            ]:
                stdout = StringIO()
                stderr = StringIO()
                status = run(
                    [str(hazard_source), "text", "opinionated", "--only", rule_name],
                    stdout,
                    stderr,
                )
                selected_reports.append((rule_name, status, stdout.getvalue(), stderr.getvalue()))

        self.assertEqual(0, python_status)
        self.assertEqual("", python_stdout.getvalue())
        self.assertEqual("", python_stderr.getvalue())
        for rule_name, status, report, errors in selected_reports:
            self.assertEqual(2, status)
            self.assertEqual("", errors)
            self.assertIn(rule_name, report)

    def test_design_finds_direct_python_hazards_and_keeps_idioms_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "design_hazards.py"
            source.write_text(
                "import contextlib\n"
                "import sys\n"
                "\n"
                "# TODO: remove diagnostic path\n"
                "def stop(values):\n"
                "    while len(values):\n"
                "        breakpoint()\n"
                "        sys.exit(1)\n"
                "\n"
                "def placeholders():\n"
                "    try:\n"
                "        work()\n"
                "    except LookupError:\n"
                "        pass\n"
                "    try:\n"
                "        work()\n"
                "    except RuntimeError:\n"
                "        ...\n"
                "    try:\n"
                "        work()\n"
                "    except OSError:\n"
                "        logger.warning(\"ignored\")\n"
                "    with contextlib.suppress(FileNotFoundError):\n"
                "        work()\n"
                "\n"
                "import sys as platform\n"
                "from sys import exit as stop_alias\n"
                "\n"
                "def rebound_alias(platform):\n"
                "    platform.exit()\n"
                "\n"
                "def rebound_function_alias(stop_alias):\n"
                "    stop_alias()\n"
                "\n"
                "def shadowed(exit, breakpoint, len, values):\n"
                "    exit()\n"
                "    breakpoint()\n"
                "    while len(values):\n"
                "        break\n"
                "\n"
                "def idioms(values):\n"
                "    size = len(values)\n"
                "    while size:\n"
                "        size -= 1\n"
                "    for index in range(len(values)):\n"
                "        print(index)\n",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", "design"], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        self.assertEqual(1, report.count("ExitExpression"))
        self.assertEqual(1, report.count("CountInLoopExpression"))
        self.assertEqual(2, report.count("DevelopmentCodeFragment"))
        self.assertEqual(2, report.count("EmptyCatchBlock"))
        self.assertNotIn("GotoStatement", report)
        self.assertNotIn("logger.warning", report)

    def test_design_honors_custom_markers_calls_and_priorities_without_importing_target_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            source = directory / "configured_design.py"
            ruleset = directory / "configured-design.xml"
            source.write_text(
                "# REVIEW before release\n"
                "def inspect(items):\n"
                "    acme.trace(items)\n"
                "    ACME.TRACE(items)\n"
                "    while len(items):\n"
                "        sys.exit()\n"
                "    try:\n"
                "        consume(items)\n"
                "    except Exception:\n"
                "        pass\n",
                encoding="utf-8",
            )
            ruleset.write_text(
                "<ruleset><rule ref=\"design\"><priority>4</priority><properties>"
                "<property name=\"unwanted-functions\" value=\"acme.trace\"/>"
                "<property name=\"markers\" value=\"REVIEW\"/>"
                "</properties></rule></ruleset>",
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()

            status = run([str(source), "text", str(ruleset)], stdout, stderr)

        self.assertEqual(2, status)
        self.assertEqual("", stderr.getvalue())
        report = stdout.getvalue()
        for rule_name in [
            "ExitExpression",
            "CountInLoopExpression",
            "DevelopmentCodeFragment",
            "EmptyCatchBlock",
        ]:
            self.assertIn(f"{rule_name} [priority 4]", report)
        self.assertEqual(2, report.count("DevelopmentCodeFragment"))
        self.assertNotIn("TODO", report)

    def test_design_policies_keep_goto_loadable_and_strict_rules_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            source = directory / "policy_design.py"
            goto_ruleset = directory / "goto.xml"
            source.write_text(
                "def stop(items):\n"
                "    while len(items):\n"
                "        sys.exit()\n",
                encoding="utf-8",
            )
            goto_ruleset.write_text(
                "<ruleset><rule ref=\"GotoStatement\"/></ruleset>", encoding="utf-8"
            )
            python_stdout = StringIO()
            python_stderr = StringIO()
            python_status = run([str(source), "text", "python"], python_stdout, python_stderr)
            selected = []
            for rule_name in ["ExitExpression", "CountInLoopExpression"]:
                stdout = StringIO()
                stderr = StringIO()
                status = run(
                    [str(source), "text", "opinionated", "--only", rule_name], stdout, stderr
                )
                selected.append((rule_name, status, stdout.getvalue(), stderr.getvalue()))
            goto_stdout = StringIO()
            goto_stderr = StringIO()
            goto_status = run(
                [str(source), "text", str(goto_ruleset)], goto_stdout, goto_stderr
            )

        self.assertEqual((0, "", ""), (python_status, python_stdout.getvalue(), python_stderr.getvalue()))
        for rule_name, status, report, errors in selected:
            self.assertEqual(2, status)
            self.assertEqual("", errors)
            self.assertIn(rule_name, report)
        self.assertEqual((0, "", ""), (goto_status, goto_stdout.getvalue(), goto_stderr.getvalue()))

    def test_help_describes_command_shape_and_exit_codes(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        status = run(["--help"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertIn("messpy <paths> <format> <ruleset[,ruleset...]> [options]", stdout.getvalue())
        self.assertIn("text, xml, json, html, ansi, github, gitlab, checkstyle, sarif", stdout.getvalue())
        self.assertIn("--suffixes", stdout.getvalue())
        self.assertIn("--exclude", stdout.getvalue())
        self.assertIn("--ignore-tests", stdout.getvalue())
        self.assertIn("--reportfile", stdout.getvalue())
        self.assertIn("--strict", stdout.getvalue())
        self.assertIn("--color <auto|always|never>", stdout.getvalue())
        self.assertIn("--ignore-errors-on-exit", stdout.getvalue())
        self.assertIn("--ignore-violations-on-exit", stdout.getvalue())
        self.assertIn("Input directory symlinks are scanned; nested directory symlinks are skipped.", stdout.getvalue())
        self.assertIn("0 clean", stdout.getvalue())
        self.assertIn("2 findings", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())


def _long_function(name: str) -> str:
    return f"def {name}():\n" + "    pass\n" * 100


def _function_with_passes(name: str, count: int) -> str:
    return f"def {name}():\n" + "    pass\n" * count


def _finding_for(path: Path, name: str, line: int = 1) -> str:
    return (
        f"{path.resolve().as_posix()}:{line}: ExcessiveMethodLength "
        "[priority 3] "
        f"The function {name}() has 101 lines of code. Current threshold is set to 100. Avoid really long methods."
    )
