from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.cli import run


FIXTURES = Path(__file__).parent / "fixtures"


class CommandAcceptanceTests(unittest.TestCase):
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
        self.assertIn("messpy <path> text codesize", stdout.getvalue())
        self.assertIn("0 clean", stdout.getvalue())
        self.assertIn("2 findings", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())
