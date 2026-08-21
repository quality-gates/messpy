from __future__ import annotations

import importlib.util
import os
from io import StringIO
from pathlib import Path
from shutil import copytree
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.cli import run


SEED_CORPUS = ROOT / "fuzz" / "corpus" / "source-analysis"


class SourceAnalysisSeedCorpusAcceptanceTests(unittest.TestCase):
    def test_seed_sources_produce_the_documented_command_results(self) -> None:
        expected_statuses = {
            "clean.py": 0,
            "excessive_method_length.py": 2,
            "malformed.py": 1,
            "non_utf8.py": 1,
        }

        actual_statuses = {
            name: run([str(SEED_CORPUS / name), "text", "codesize"], StringIO(), StringIO())
            for name in expected_statuses
        }

        self.assertEqual(expected_statuses, actual_statuses)


class SourceAnalysisReplayAcceptanceTests(unittest.TestCase):
    def test_stored_source_inputs_replay_without_atheris_or_fuzz_state(self) -> None:
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

        result = subprocess.run(
            [sys.executable, "fuzz/replay_source_file.py", str(SEED_CORPUS)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "".join(
                f"Replayed source-analysis input: {SEED_CORPUS / name}\n"
                for name in [
                    "clean.py",
                    "excessive_method_length.py",
                    "malformed.py",
                    "non_utf8.py",
                ]
            ),
            result.stdout,
        )

    def test_stored_regression_inputs_replay_without_atheris(self) -> None:
        regressions_dir = ROOT / "fuzz" / "regressions" / "source-analysis"
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

        result = subprocess.run(
            [sys.executable, "fuzz/replay_source_file.py", str(regressions_dir)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("duplicate_function_arguments.py", result.stdout)



@unittest.skipUnless(importlib.util.find_spec("atheris"), "Atheris is not installed")
class SourceAnalysisFuzzTargetAcceptanceTests(unittest.TestCase):
    def test_bounded_source_analysis_fuzz_command_completes(self) -> None:
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

        with TemporaryDirectory() as temporary_directory:
            copied_corpus = Path(temporary_directory) / "source-analysis"
            copytree(SEED_CORPUS, copied_corpus)
            result = subprocess.run(
                [
                    sys.executable,
                    "fuzz/fuzz_source_file.py",
                    "-runs=1000",
                    str(copied_corpus),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
