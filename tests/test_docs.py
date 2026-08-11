from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

from messpy.rulesets import _CATALOG


ROOT = Path(__file__).parent.parent


class DocumentationAcceptanceTests(unittest.TestCase):
    def test_generated_rule_catalogue_is_current_and_escapes_property_tables(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_rule_docs.py"), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        rules = (ROOT / "docs" / "rules.md").read_text(encoding="utf-8")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(r"set\|get\|is\|has\|with", rules)
        self.assertEqual(
            len(_CATALOG),
            sum(line.startswith("| `") for line in rules.splitlines()),
        )


if __name__ == "__main__":
    unittest.main()
