from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.analyzer import analyze
from messpy.rulesets import (
    RuleSelection,
    RulesetError,
    built_in_ruleset_names,
    load_rulesets,
    select_rules,
)


class RuleSelectionTests(unittest.TestCase):
    def test_default_selection_loads_every_codesize_rule(self) -> None:
        rules = select_rules(RuleSelection(rulesets=("codesize",)))

        self.assertEqual(
            [
                "CyclomaticComplexity",
                "NPathComplexity",
                "ExcessiveMethodLength",
                "ExcessiveClassLength",
                "ExcessiveParameterList",
                "ExcessivePublicCount",
                "TooManyFields",
                "TooManyMethods",
                "TooManyPublicMethods",
                "ExcessiveClassComplexity",
            ],
            [rule.name for rule in rules],
        )

    def test_default_selection_preserves_codesize_analysis_findings(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "many_parameters.py"
            source.write_text(
                "def accepts_many(argument_one, argument_two, argument_three, argument_four, "
                "argument_five, argument_six, argument_seven, argument_eight, argument_nine, "
                "argument_ten, argument_eleven):\n"
                "    return argument_one\n",
                encoding="utf-8",
            )

            selected_analysis = analyze(
                [source], rules=select_rules(RuleSelection(rulesets=("codesize",)))
            )
            all_codesize_analysis = analyze([source], rules=load_rulesets(["codesize"]))

        self.assertEqual(all_codesize_analysis.findings, selected_analysis.findings)
        self.assertEqual(
            ["ExcessiveParameterList"],
            [finding.rule_name for finding in selected_analysis.findings],
        )

    def test_rejects_an_inverted_priority_range(self) -> None:
        with self.assertRaisesRegex(
            RulesetError, r"Minimum priority must not exceed maximum priority\."
        ):
            RuleSelection(rulesets=("codesize",), minimum_priority=5, maximum_priority=1)

    def test_rejects_priorities_outside_the_supported_range(self) -> None:
        for field in ("minimum_priority", "maximum_priority"):
            for priority in (0, 6):
                with self.subTest(field=field, priority=priority):
                    with self.assertRaisesRegex(RulesetError, "between 1 and 5"):
                        RuleSelection(rulesets=("codesize",), **{field: priority})


class BuiltInRulesetNamesTests(unittest.TestCase):
    def test_lists_every_documented_built_in_ruleset(self) -> None:
        self.assertEqual(
            [
                "cleancode",
                "codesize",
                "controversial",
                "design",
                "explicitness",
                "naming",
                "onion",
                "opinionated",
                "python",
                "strictexplicitness",
                "unusedcode",
            ],
            sorted(built_in_ruleset_names()),
        )
