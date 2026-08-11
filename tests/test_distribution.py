from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


class DistributionAcceptanceTests(unittest.TestCase):
    def test_built_wheel_installs_and_runs_the_messpy_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            wheel_directory = temporary / "wheels"
            environment = temporary / "environment"
            project = temporary / "project"
            application = project / "application.py"
            metrics = project / "metrics.py"
            unused_module = project / "unused.py"
            empty_module = project / "empty.py"
            test_module = project / "tests" / "test_application.py"
            ruleset = project / "team-policy.xml"
            test_module.parent.mkdir(parents=True)
            source = (FIXTURES / "long_function.py").read_text(encoding="utf-8")
            application.write_text(source, encoding="utf-8")
            metrics.write_text(
                "def branching(first, second, third, fourth, fifth, sixth, seventh, eighth, ninth, tenth):\n"
                "    if first:\n        pass\n"
                "    if second:\n        pass\n"
                "    if third:\n        pass\n"
                "    if fourth:\n        pass\n"
                "    if fifth:\n        pass\n"
                "    if sixth:\n        pass\n"
                "    if seventh:\n        pass\n"
                "    if eighth:\n        pass\n"
                "    if ninth:\n        pass\n",
                encoding="utf-8",
            )
            test_module.write_text(source, encoding="utf-8")
            unused_module.write_text("def build():\n    discarded = 1\n", encoding="utf-8")
            empty_module.write_text("", encoding="utf-8")
            ruleset.write_text(
                """<ruleset name="team policy">
    <rule ref="rulesets/codesize.xml">
        <priority>2</priority>
        <properties><property name="minimum" value="3" /></properties>
    </rule>
</ruleset>
""",
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, "-m", "pip", "wheel", str(ROOT), "--wheel-dir", str(wheel_directory)],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [sys.executable, "-m", "venv", str(environment)],
                check=True,
                capture_output=True,
                text=True,
            )
            scripts_directory = environment / ("Scripts" if sys.platform == "win32" else "bin")
            executable = scripts_directory / ("messpy.exe" if sys.platform == "win32" else "messpy")
            environment_python = scripts_directory / ("python.exe" if sys.platform == "win32" else "python")
            subprocess.run(
                [
                    environment_python,
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--find-links",
                    str(wheel_directory),
                    "messpy",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            help_result = subprocess.run(
                [executable, "--help"], capture_output=True, text=True, check=False
            )
            version_result = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, check=False
            )
            clean_result = subprocess.run(
                [executable, str(FIXTURES / "clean.py"), "text", "codesize"],
                capture_output=True,
                text=True,
                check=False,
            )
            finding_result = subprocess.run(
                [executable, str(FIXTURES / "long_function.py"), "text", "codesize"],
                capture_output=True,
                text=True,
                check=False,
            )
            metrics_result = subprocess.run(
                [executable, str(metrics), "text", "codesize"],
                capture_output=True,
                text=True,
                check=False,
            )
            unused_result = subprocess.run(
                [executable, str(unused_module), "text", "unusedcode"],
                capture_output=True,
                text=True,
                check=False,
            )
            ignore_tests_result = subprocess.run(
                [executable, str(project), "text", "codesize", "--ignore-tests"],
                capture_output=True,
                text=True,
                check=False,
            )
            bundled_rule_counts = {
                "codesize": 10,
                "naming": 8,
                "unusedcode": 4,
                "cleancode": 5,
                "design": 8,
                "controversial": 5,
                "python": 31,
                "opinionated": 7,
            }
            bundled_ruleset_results = {
                ruleset_name: subprocess.run(
                    [executable, str(empty_module), "text", ruleset_name, "--verbose"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                for ruleset_name in bundled_rule_counts
            }
            custom_ruleset_result = subprocess.run(
                [
                    executable,
                    str(application),
                    "text",
                    str(ruleset),
                    "--only",
                    "ExcessiveMethodLength",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            malformed = project / "malformed.py"
            malformed.write_text("def broken(:\n", encoding="utf-8")
            public_report_results = {
                report_format: subprocess.run(
                    [
                        executable,
                        f"{application},{malformed}",
                        report_format,
                        "codesize",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
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
                ]
            }

        self.assertEqual(0, help_result.returncode)
        self.assertIn("messpy <paths> <format> <ruleset[,ruleset...]> [options]", help_result.stdout)
        self.assertEqual(0, version_result.returncode)
        self.assertEqual("0.1.0\n", version_result.stdout)
        self.assertEqual(0, clean_result.returncode)
        self.assertEqual("", clean_result.stdout)
        self.assertEqual(2, finding_result.returncode)
        self.assertIn("ExcessiveMethodLength", finding_result.stdout)
        self.assertEqual(2, metrics_result.returncode)
        self.assertIn("CyclomaticComplexity", metrics_result.stdout)
        self.assertEqual(2, unused_result.returncode)
        self.assertIn("UnusedLocalVariable", unused_result.stdout)
        self.assertIn("NPathComplexity", metrics_result.stdout)
        self.assertIn("ExcessiveParameterList", metrics_result.stdout)
        self.assertEqual(2, ignore_tests_result.returncode)
        self.assertIn(application.resolve().as_posix(), ignore_tests_result.stdout)
        self.assertNotIn(test_module.resolve().as_posix(), ignore_tests_result.stdout)
        for ruleset_name, result in bundled_ruleset_results.items():
            with self.subTest(ruleset_name=ruleset_name):
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stdout)
                prefix = "Loaded rules: "
                self.assertTrue(result.stderr.startswith(prefix))
                loaded_names = result.stderr.removeprefix(prefix).strip().split(", ")
                self.assertEqual(bundled_rule_counts[ruleset_name], len(loaded_names))
        self.assertEqual(2, custom_ruleset_result.returncode)
        self.assertIn("ExcessiveMethodLength [priority 2]", custom_ruleset_result.stdout)
        self.assertIn("Current threshold is set to 3. Avoid really long methods.", custom_ruleset_result.stdout)
        for report_format, result in public_report_results.items():
            with self.subTest(report_format=report_format):
                self.assertEqual(1, result.returncode)
                self.assertEqual("", result.stderr)
                self.assertIn("ExcessiveMethodLength", result.stdout)
                self.assertIn("malformed.py", result.stdout)
