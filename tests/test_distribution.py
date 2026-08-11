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
            test_module = project / "tests" / "test_application.py"
            ruleset = project / "team-policy.xml"
            test_module.parent.mkdir(parents=True)
            source = (FIXTURES / "long_function.py").read_text(encoding="utf-8")
            application.write_text(source, encoding="utf-8")
            test_module.write_text(source, encoding="utf-8")
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
            executable = environment / "bin" / "messpy"
            subprocess.run(
                [
                    environment / "bin" / "python",
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
            ignore_tests_result = subprocess.run(
                [executable, str(project), "text", "codesize", "--ignore-tests"],
                capture_output=True,
                text=True,
                check=False,
            )
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
        self.assertEqual(2, ignore_tests_result.returncode)
        self.assertIn(application.as_posix(), ignore_tests_result.stdout)
        self.assertNotIn(test_module.as_posix(), ignore_tests_result.stdout)
        self.assertEqual(2, custom_ruleset_result.returncode)
        self.assertIn("ExcessiveMethodLength [priority 2]", custom_ruleset_result.stdout)
        self.assertIn("The configured limit is 3.", custom_ruleset_result.stdout)
        for report_format, result in public_report_results.items():
            with self.subTest(report_format=report_format):
                self.assertEqual(1, result.returncode)
                self.assertEqual("", result.stderr)
                self.assertIn("ExcessiveMethodLength", result.stdout)
                self.assertIn("malformed.py", result.stdout)
