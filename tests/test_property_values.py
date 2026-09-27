from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.analyzer import analyze
from messpy.cli import run
from messpy.rulesets import RulesetError, load_rulesets


FUNCTION_SOURCE = "def function_name():\n    return 1\n"
CLASS_SOURCE = "class Sample:\n    def method_name(self):\n        return 1\n"


def _ruleset(*rules: tuple[str, str, str]) -> str:
    body = "".join(
        f'    <rule ref="{ref}"><properties><property name="{name}" value="{value}" /></properties></rule>\n'
        for ref, name, value in rules
    )
    return f'<ruleset name="values">\n{body}</ruleset>\n'


def _run_against_inputs(ruleset_text: str) -> dict[str, tuple[int, str, str]]:
    """Run one ruleset against an empty directory, a file that never reaches
    class rules, and a directory that reaches every rule."""
    results = {}
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary = Path(temporary_directory)
        ruleset = temporary / "ruleset.xml"
        ruleset.write_text(ruleset_text, encoding="utf-8")
        empty = temporary / "empty"
        empty.mkdir()
        project = temporary / "project"
        project.mkdir()
        (project / "function_only.py").write_text(FUNCTION_SOURCE, encoding="utf-8")
        (project / "with_class.py").write_text(CLASS_SOURCE, encoding="utf-8")
        inputs = {
            "empty directory": empty,
            "file that does not exercise the rule": project / "function_only.py",
            "directory that exercises the rule": project,
        }
        for label, path in inputs.items():
            stdout = StringIO()
            stderr = StringIO()
            status = run([str(path), "text", str(ruleset)], stdout, stderr)
            results[label] = (status, stdout.getvalue(), stderr.getvalue())
    return results


class PropertyValueValidationTests(unittest.TestCase):
    def assert_fails_for_every_input(self, ruleset_text: str, message: str) -> None:
        for label, result in _run_against_inputs(ruleset_text).items():
            with self.subTest(input=label):
                self.assertEqual((1, "", f"Error: {message}\n"), result)

    def test_invalid_regular_expression_fails_at_load_for_every_input(self) -> None:
        self.assert_fails_for_every_input(
            _ruleset(
                ("TooManyMethods", "ignorepattern", "(["),
                ("CyclomaticComplexity", "reportLevel", "1"),
            ),
            "TooManyMethods property 'ignorepattern' must be a valid regular expression.",
        )

    def test_invalid_integer_fails_at_load_for_every_input(self) -> None:
        self.assert_fails_for_every_input(
            _ruleset(
                ("CyclomaticComplexity", "reportLevel", "abc"),
                ("ShortMethodName", "minimum", "3"),
            ),
            "CyclomaticComplexity property 'reportlevel' must be an integer.",
        )

    def test_invalid_boolean_fails_at_load_for_every_input(self) -> None:
        self.assert_fails_for_every_input(
            _ruleset(
                ("ExcessiveClassLength", "ignore-whitespace", "maybe"),
                ("CyclomaticComplexity", "reportLevel", "1"),
            ),
            "ExcessiveClassLength property 'ignore-whitespace' must be true or false.",
        )

    def test_empty_onion_domain_fails_at_load_for_every_input(self) -> None:
        self.assert_fails_for_every_input(
            _ruleset(("onion", "domain", " , "), ("CyclomaticComplexity", "reportLevel", "1")),
            "DomainAction property 'domain' must name at least one path pattern.",
        )

    def test_empty_onion_outer_layers_fails_at_load(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            ruleset = Path(temporary_directory) / "ruleset.xml"
            ruleset.write_text(
                _ruleset(("DomainOuterImport", "domain", "*/domain/*"), ("DomainOuterImport", "outer-layers", "")),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                RulesetError, r"^DomainOuterImport property 'outer-layers' must name at least one module\.$"
            ):
                load_rulesets([str(ruleset)])

    def test_empty_ignore_pattern_excludes_nothing(self) -> None:
        source = "class Sample:\n" + "".join(f"    def get_{index}(self):\n        return 1\n" for index in range(3))
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            ruleset = temporary / "ruleset.xml"
            ruleset.write_text(
                _ruleset(("TooManyMethods", "ignorepattern", " "), ("TooManyMethods", "maxmethods", "2")),
                encoding="utf-8",
            )
            path = temporary / "sample.py"
            path.write_text(source, encoding="utf-8")

            analysis = analyze([path], rules=load_rulesets([str(ruleset)]))

        self.assertEqual(["TooManyMethods"], [finding.rule_name for finding in analysis.findings])

    def test_built_in_onion_ruleset_without_domain_fails_at_load(self) -> None:
        with self.assertRaisesRegex(
            RulesetError, r"^DomainAction property 'domain' must name at least one path pattern\.$"
        ):
            load_rulesets(["onion"])

    def test_built_in_rulesets_load(self) -> None:
        for name in ("naming", "unusedcode", "cleancode", "design", "python", "controversial", "opinionated"):
            with self.subTest(ruleset=name):
                self.assertTrue(load_rulesets([name]))


if __name__ == "__main__":
    unittest.main()
