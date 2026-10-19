from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.cli import run


class MethodReceiverTests(unittest.TestCase):
    def scan(self, source_text: str, rules: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.py"
            ruleset = Path(directory) / "rules.xml"
            source.write_text(source_text, encoding="utf-8")
            ruleset.write_text(f'<ruleset name="receivers">{rules}</ruleset>', encoding="utf-8")
            stdout, stderr = StringIO(), StringIO()
            status = run([str(source), "text", str(ruleset)], stdout, stderr)
        self.assertEqual("", stderr.getvalue())
        return status, stdout.getvalue()

    def test_field_count_and_implicit_output_agree(self) -> None:
        for receiver in ("self", "this"):
            for positional_only in ("", ", /"):
                with self.subTest(receiver=receiver, positional_only=positional_only):
                    status, report = self.scan(
                        "class Counter:\n"
                        f"    def __init__({receiver}{positional_only}):\n"
                        f"        {receiver}.first = 0\n"
                        f"        {receiver}.second = 0\n"
                        f"        {receiver}.third = 0\n"
                        f"    def bump({receiver}{positional_only}):\n"
                        f"        {receiver}.first += 1\n",
                        '<rule ref="TooManyFields"><properties>'
                        '<property name="maxfields" value="2" />'
                        '</properties></rule><rule ref="ImplicitInstanceOutput" />',
                    )
                    self.assertEqual(2, status)
                    self.assertIn("TooManyFields [priority 3] The class Counter has 3 fields.", report)
                    self.assertIn(
                        f"ImplicitInstanceOutput [priority 3] The method Counter.bump() writes the implicit output {receiver}.first.",
                        report,
                    )
                    self.assertEqual(2, len(report.splitlines()))

    def test_state_consumers_recognize_any_instance_receiver(self) -> None:
        for receiver in ("self", "this", "this, /"):
            for definition in ("def", "async def"):
                with self.subTest(receiver=receiver, definition=definition):
                    name = receiver.split(",")[0]
                    status, report = self.scan(
                        "class Counter:\n"
                        f"    def __init__({receiver}):\n"
                        f"        {name}._unused = 0\n"
                        f"        {name}._used = 0\n"
                        f"        {name}.BadName = 0\n"
                        f"    {definition} first({receiver}):\n"
                        f"        {name}._used += 1\n"
                        f"        return {name}._used + 1\n"
                        f"    {definition} second({receiver}):\n"
                        f"        {name}.BadName += 1\n"
                        f"        return {name}.BadName + 1\n"
                        f"    def getter({receiver}):\n"
                        f"        return {name}._getter_only\n",
                        '<rule ref="UnusedPrivateField" />'
                        '<rule ref="CamelCasePropertyName" />'
                        '<rule ref="LackOfCohesionOfMethods"><properties>'
                        '<property name="maximum" value="1" />'
                        '</properties></rule>',
                    )
                    self.assertEqual(2, status)
                    self.assertIn("UnusedPrivateField [priority 3] Avoid unused private fields such as '_unused'.", report)
                    self.assertNotIn("such as '_used'", report)
                    self.assertIn("CamelCasePropertyName [priority 1] The property BadName", report)
                    self.assertIn("Lack of Cohesion Of Methods (LCOM4) value of 2.", report)

    def test_static_methods_have_no_receiver_state(self) -> None:
        for decorator in ("staticmethod", "builtins.staticmethod"):
            for receiver in ("self", "this", "this, /"):
                with self.subTest(decorator=decorator, receiver=receiver):
                    name = receiver.split(",")[0]
                    status, report = self.scan(
                        "import builtins\n"
                        "class Counter:\n"
                        f"    @{decorator}\n"
                        f"    def change({receiver}):\n"
                        f"        {name}._unused = 1\n"
                        f"        {name}.BadName = 1\n",
                        '<rule ref="TooManyFields"><properties>'
                        '<property name="maxfields" value="0" />'
                        '</properties></rule>'
                        '<rule ref="ImplicitInstanceOutput" />'
                        '<rule ref="UnusedPrivateField" />'
                        '<rule ref="CamelCasePropertyName" />',
                    )
                    self.assertEqual((0, ""), (status, report))

    def test_class_state_policy_is_unchanged(self) -> None:
        for method, decorator, receiver, counted in (
            ("create", "@classmethod", "self", True),
            ("create", "@classmethod", "cls", True),
            ("create", "@classmethod", "mcls", False),
            ("__new__", "", "self", True),
            ("__new__", "", "cls", False),
            ("__new__", "", "mcls", False),
            ("__new__", "@classmethod", "cls", True),
        ):
            with self.subTest(method=method, decorator=decorator, receiver=receiver):
                status, report = self.scan(
                    "class Counter:\n"
                    f"    {decorator}\n"
                    f"    def {method}({receiver}):\n"
                    f"        {receiver}.field = 0\n",
                    '<rule ref="TooManyFields"><properties>'
                    '<property name="maxfields" value="0" />'
                    '</properties></rule><rule ref="ImplicitInstanceOutput" />',
                )
                self.assertEqual(counted, "TooManyFields" in report)
                self.assertIn("ImplicitInstanceOutput", report)
                self.assertEqual(2, status)
