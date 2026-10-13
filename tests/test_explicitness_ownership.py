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
            return status, out.getvalue().replace(path.resolve().as_posix(), "probe.py")

    def test_alias_retains_caller_ownership(self):
        self.assertEqual((2, "probe.py:3: ImplicitOutput [priority 3] The function change() writes the implicit output alias. Return it instead.\n"), self.analyze("def change(values):\n    alias = values\n    alias.append(1)\n"))

    def test_receiver_alias_retains_instance_ownership(self):
        status, report = self.analyze("class Box:\n    def change(self):\n        alias = self\n        alias.items.append(1)\n")
        self.assertEqual(2, status)
        self.assertIn("probe.py:4: ImplicitOutput", report)
        self.assertNotIn("UnknownEffect", report)

    def test_known_pure_helper_does_not_link_unrelated_arguments(self):
        source = (
            "def ignore(first, second):\n    return 1\n"
            "def check(shared):\n    private = []\n    ignore(private, shared)\n    private.append(1)\n"
        )
        self.assertEqual((0, ""), self.analyze(source))

    def test_selected_private_and_shared_children_keep_distinct_ownership(self):
        cases = (
            ("pair = [shared, []]\n    pair[1].append(1)\n    pair[0].append(1)\n", 4),
            ("pair = {'left': shared, 'right': []}\n    pair['right'].append(1)\n    pair['left'].append(1)\n", 4),
            ("pair = []\n    pair.append(shared)\n    pair.append([])\n    pair[1].append(1)\n    pair[0].append(1)\n", 6),
        )
        for body, line in cases:
            with self.subTest(body=body):
                status, report = self.analyze("def edit(shared):\n    " + body)
                self.assertEqual(2, status)
                self.assertEqual(1, report.count("ImplicitOutput"))
                self.assertIn(f"probe.py:{line}: ImplicitOutput", report)

    def test_replacing_one_child_removes_its_old_reachability(self):
        for body in (
            "pair = [shared]\n    pair[0] = []\n    pair[0].append(1)\n",
            "pair = {'left': shared}\n    pair['left'] = []\n    pair['left'].append(1)\n",
            "pair = [shared]\n    alias = pair\n    pair[0] = []\n    alias[0].append(1)\n",
        ):
            with self.subTest(body=body):
                self.assertEqual((0, ""), self.analyze("def edit(shared):\n    " + body))

    def test_reordered_slots_do_not_claim_a_private_child(self):
        status, report = self.analyze(
            "def edit(shared):\n"
            "    pair = [[], shared]\n"
            "    pair.reverse()\n"
            "    pair[0].append(1)\n"
        )
        self.assertEqual(2, status)
        self.assertIn("probe.py:4: UnknownEffect", report)
        self.assertNotIn("ImplicitOutput", report)

    def test_branch_added_sibling_keeps_existing_slot_precise(self):
        status, report = self.analyze(
            "def edit(shared, choose):\n"
            "    pair = [shared]\n"
            "    if choose:\n"
            "        pair.append([])\n"
            "    pair[0].append(1)\n"
        )
        self.assertEqual(2, status)
        self.assertIn("probe.py:5: ImplicitOutput", report)
        self.assertNotIn("UnknownEffect", report)

    def test_helper_can_replace_a_private_holder_child(self):
        status, report = self.analyze(
            "def put(holder, value):\n"
            "    holder[0] = value\n"
            "def edit(shared):\n"
            "    pair = [[]]\n"
            "    put(pair, shared)\n"
            "    pair[0].append(1)\n"
        )
        self.assertEqual(2, status)
        self.assertIn("probe.py:6: UnknownEffect", report)

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
