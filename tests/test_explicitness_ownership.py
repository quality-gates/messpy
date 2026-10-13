from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from messpy.cli import run


class OwnershipTests(unittest.TestCase):
    def analyze(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.py"
            path.write_text(source)
            out, err = StringIO(), StringIO()
            status = run([str(path), "text", "explicitness"], out, err)
            self.assertEqual("", err.getvalue())
            return status, out.getvalue().replace(str(path.resolve()), "probe.py")

    def test_alias_retains_caller_ownership(self):
        self.assertEqual((2, "probe.py:3: ImplicitOutput [priority 3] The function change() writes the implicit output alias. Return it instead.\n"), self.analyze("def change(values):\n    alias = values\n    alias.append(1)\n"))

    def test_later_rebinding_does_not_erase_earlier_mutation(self):
        self.assertEqual((2, "probe.py:2: ImplicitOutput [priority 3] The function change() writes the implicit output values. Return it instead.\n"), self.analyze("def change(values):\n    values.append(1)\n    values = []\n"))

    def test_copy_is_private_but_conditional_copy_is_not_proof(self):
        self.assertEqual((0, ""), self.analyze("def change(values):\n    values = list(values)\n    values.append(1)\n    return values\n"))
        status, report = self.analyze("def change(values, copy):\n    if copy:\n        values = list(values)\n    values.append(1)\n")
        self.assertEqual(2, status)
        self.assertIn("probe.py:4: ImplicitOutput", report)

    def test_uppercase_mutable_contents_are_an_input(self):
        status, report = self.analyze("CACHE = []\ndef read():\n    return len(CACHE)\n")
        self.assertEqual((2, "probe.py:3: ImplicitInput [priority 3] The function read() reads the implicit input CACHE. Pass it as an argument instead.\n"), (status, report))

    def test_fixed_capture_is_not_a_time_dependency(self):
        self.assertEqual((0, ""), self.analyze("def make_adder(start):\n    return lambda value: start + value\n"))
        self.assertEqual((0, ""), self.analyze("def make_reader():\n    prefix = 'fixed'\n    return lambda: len(prefix)\n"))
        self.assertEqual((0, ""), self.analyze("def make_reader(value):\n    box = [value]\n    return lambda: box[0]\n"))
        self.assertEqual((2, "probe.py:3: ImplicitInput [priority 3] The function read() reads the implicit input box. Pass it as an argument instead.\n"), self.analyze("def make_reader(box):\n    def read():\n        return len(box)\n    return read\n"))

    def test_returned_alias_mutation_is_caller_owned(self):
        status, report = self.analyze(
            "def alias(values):\n"
            "    return values\n"
            "def change(values):\n"
            "    alias(values).append(1)\n"
        )
        self.assertEqual(2, status)
        self.assertEqual(
            "probe.py:4: ImplicitOutput [priority 3] The function change() writes the implicit output values. Return it instead.\n",
            report,
        )

    def test_known_effects_propagate_transitively_and_through_recursive_cycles(self):
        status, report = self.analyze(
            "def leaf(value):\n"
            "    print(value)\n"
            "def mid(value):\n"
            "    leaf(value)\n"
            "def top(value):\n"
            "    mid(value)\n"
        )
        self.assertEqual(2, status)
        self.assertIn(
            "probe.py:6: ImplicitOutput [priority 3] The function top() writes the implicit output print. Return it instead.\n",
            report,
        )
        self.assertNotIn("UnknownEffect", report)

        status, report = self.analyze(
            "def first(value):\n"
            "    second(value)\n"
            "def second(value):\n"
            "    print(value)\n"
            "    first(value)\n"
        )
        self.assertEqual(2, status)
        self.assertIn(
            "probe.py:2: ImplicitOutput [priority 3] The function first() writes the implicit output print. Return it instead.\n",
            report,
        )
        self.assertIn(
            "probe.py:4: ImplicitOutput [priority 3] The function second() writes the implicit output print. Return it instead.\n",
            report,
        )

    def test_unknown_effects_propagate_without_fabricating_inputs_or_outputs(self):
        status, report = self.analyze(
            "def leaf(value, notify):\n"
            "    return notify(value)\n"
            "def wrapper(value, notify):\n"
            "    return leaf(value, notify)\n"
        )
        self.assertEqual(2, status)
        self.assertIn(
            "probe.py:2: UnknownEffect [priority 3] The function leaf() has an unknown effect from notify. "
            "Establish the callable's effects before treating it as a calculation.\n",
            report,
        )
        self.assertIn(
            "probe.py:4: UnknownEffect [priority 3] The function wrapper() has an unknown effect from notify. "
            "Establish the callable's effects before treating it as a calculation.\n",
            report,
        )
        self.assertNotIn("ImplicitInput", report)
        self.assertNotIn("ImplicitOutput", report)

    def test_shadowed_callable_parameter_is_unknown_but_same_file_helper_is_resolved(self):
        self.assertEqual(
            (0, ""),
            self.analyze("def helper(value):\n    return value + 1\ndef wrapper(value):\n    return helper(value)\n"),
        )
        status, report = self.analyze(
            "def helper(value):\n"
            "    return value + 1\n"
            "def send(value, helper):\n"
            "    return helper(value)\n"
        )
        self.assertEqual(2, status)
        self.assertEqual(
            "probe.py:4: UnknownEffect [priority 3] The function send() has an unknown effect from helper. "
            "Establish the callable's effects before treating it as a calculation.\n",
            report,
        )

    def test_deferred_callback_creation_and_immediate_invocation_have_distinct_owners(self):
        status, report = self.analyze("def build():\n    return lambda: print(1)\n")
        self.assertEqual(2, status)
        self.assertEqual(
            "probe.py:2: ImplicitOutput [priority 3] The function <lambda>() writes the implicit output print. "
            "Return it instead.\n",
            report,
        )
        self.assertNotIn("build()", report)

        status, report = self.analyze(
            "def build():\n"
            "    return lambda: print(1)\n"
            "def run():\n"
            "    callback = build()\n"
            "    callback()\n"
        )
        self.assertEqual(2, status)
        self.assertIn(
            "probe.py:5: ImplicitOutput [priority 3] The function run() writes the implicit output print. Return it instead.\n",
            report,
        )
        self.assertNotIn("UnknownEffect", report)

    def test_top_level_private_mutation_does_not_make_later_calculations_actions(self):
        self.assertEqual((0, ""), self.analyze("cache = []\ncache.append(1)\ndef add(value):\n    return value + 1\n"))

    def test_helper_mutation_distinguishes_private_and_caller_owned_arguments(self):
        status, report = self.analyze(
            "def mutate(values):\n"
            "    values.append(1)\n"
            "def build():\n"
            "    values = []\n"
            "    mutate(values)\n"
            "    return values\n"
        )
        self.assertEqual(2, status)
        self.assertIn(
            "probe.py:2: ImplicitOutput [priority 3] The function mutate() writes the implicit output values. Return it instead.\n",
            report,
        )
        self.assertNotIn("build()", report)

        status, report = self.analyze(
            "def mutate(values):\n"
            "    values.append(1)\n"
            "def change(values):\n"
            "    mutate(values)\n"
        )
        self.assertEqual(2, status)
        self.assertIn(
            "probe.py:4: ImplicitOutput [priority 3] The function change() writes the implicit output values. Return it instead.\n",
            report,
        )
