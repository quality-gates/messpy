from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest

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
            f"{long_function.as_posix()}:1: ExcessiveMethodLength "
            "[priority 3] The method too_long has 101 lines of code. "
            "The configured limit is 100.\n",
            stdout.getvalue(),
        )
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

    def test_help_describes_command_shape_and_exit_codes(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        status = run(["--help"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertIn("messpy <paths> text codesize", stdout.getvalue())
        self.assertIn("--suffixes", stdout.getvalue())
        self.assertIn("--exclude", stdout.getvalue())
        self.assertIn("--ignore-tests", stdout.getvalue())
        self.assertIn("--reportfile", stdout.getvalue())
        self.assertIn("--ignore-errors-on-exit", stdout.getvalue())
        self.assertIn("--ignore-violations-on-exit", stdout.getvalue())
        self.assertIn("Input directory symlinks are scanned; nested directory symlinks are skipped.", stdout.getvalue())
        self.assertIn("0 clean", stdout.getvalue())
        self.assertIn("2 findings", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())


def _long_function(name: str) -> str:
    return f"def {name}():\n" + "    pass\n" * 100


def _finding_for(path: Path, name: str) -> str:
    return (
        f"{path.resolve().as_posix()}:1: ExcessiveMethodLength "
        "[priority 3] "
        f"The method {name} has 101 lines of code. The configured limit is 100."
    )
