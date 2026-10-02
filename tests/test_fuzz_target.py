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
sys.path.insert(0, str(ROOT / "fuzz"))

from messpy.cli import run
from messpy.rulesets import load_rulesets
from scan_profile import RULESETS, run_scan
from source_analysis_target import run_source_analysis


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


class FuzzScanProfileAcceptanceTests(unittest.TestCase):
    def test_every_profile_ruleset_loads_and_together_they_reach_explicitness_and_onion(self) -> None:
        loaded_names = {
            rule.name for ruleset in RULESETS for rule in load_rulesets(ruleset.split(","))
        }

        self.assertLessEqual(
            {
                "ImplicitInput",
                "ImplicitOutput",
                "ImplicitInstanceInput",
                "ImplicitInstanceOutput",
                "DomainAction",
                "DomainOuterImport",
            },
            loaded_names,
        )

    def test_profile_includes_one_combined_scan_of_every_ruleset(self) -> None:
        single_rulesets = [ruleset for ruleset in RULESETS if "," not in ruleset]
        combined_rulesets = [ruleset for ruleset in RULESETS if "," in ruleset]

        self.assertEqual([",".join(single_rulesets)], combined_rulesets)

    def test_configured_onion_reports_an_outer_layer_import_in_a_scanned_source(self) -> None:
        onion_rulesets = [
            ruleset for ruleset in RULESETS if ruleset.endswith(".xml") and "," not in ruleset
        ]

        statuses = [run_scan(b"import subprocess\n", ruleset) for ruleset in onion_rulesets]

        self.assertEqual([2], statuses)

    def test_scan_reports_the_documented_status_for_clean_and_malformed_source(self) -> None:
        self.assertEqual(0, run_scan(b"VALUE = 1\n", "codesize", "json"))
        self.assertEqual(1, run_scan(b"def broken(:\n", "codesize", "sarif"))


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

    def test_duplicate_argument_regression_replays_into_the_symbol_table_analysis(self) -> None:
        regression = ROOT / "fuzz" / "regressions" / "source-analysis" / "duplicate_function_arguments.py"

        statuses = run_source_analysis(regression.read_bytes())

        self.assertEqual(0, statuses["codesize"])
        self.assertEqual(1, statuses["unusedcode"])
        self.assertEqual(1, statuses["python"])

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
