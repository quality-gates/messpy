from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


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
        table_rows = [
            line
            for line in rules.splitlines()
            if line.startswith("| `") and " | `" in line
        ]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(r"set\|get\|is\|has\|with", rules)
        self.assertGreaterEqual(len(table_rows), 1)
        self.assertNotIn("**Applicable.**", rules)
        self.assertNotIn("**Not applicable.**", rules)
        self.assertNotIn("**Adapted.**", rules)


if __name__ == "__main__":
    unittest.main()
