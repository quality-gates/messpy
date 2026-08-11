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

    def test_help_describes_command_shape_and_exit_codes(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        status = run(["--help"], stdout, stderr)

        self.assertEqual(0, status)
        self.assertIn("messpy <paths> text codesize", stdout.getvalue())
        self.assertIn("--suffixes", stdout.getvalue())
        self.assertIn("--exclude", stdout.getvalue())
        self.assertIn("--ignore-tests", stdout.getvalue())
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
