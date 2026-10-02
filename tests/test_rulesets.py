from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.rulesets import built_in_ruleset_names


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
