from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).parent.parent


@unittest.skipUnless(importlib.util.find_spec("atheris"), "Atheris is not installed")
class SourceAnalysisFuzzTargetAcceptanceTests(unittest.TestCase):
    def test_bounded_source_analysis_fuzz_command_completes(self) -> None:
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

        result = subprocess.run(
            [sys.executable, "fuzz/fuzz_source_file.py", "-runs=1000"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
