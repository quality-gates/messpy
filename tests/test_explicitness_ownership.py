from io import StringIO
from pathlib import Path
import sys
import tempfile
import time
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
        self.assertIn("probe.py:6: ImplicitOutput", report)
        self.assertNotIn("UnknownEffect", report)

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
            "probe.py:6: ImplicitOutput [priority 3] The function top() writes the implicit output print. Move this effect to the caller.\n",
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
            "probe.py:2: ImplicitOutput [priority 3] The function first() writes the implicit output print. Move this effect to the caller.\n",
            report,
        )
        self.assertIn(
            "probe.py:4: ImplicitOutput [priority 3] The function second() writes the implicit output print. Move this effect to the caller.\n",
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
            "Move this effect to the caller.\n",
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
            "probe.py:5: ImplicitOutput [priority 3] The function run() writes the implicit output print. Move this effect to the caller.\n",
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

    def assert_helper_mutation_binds_through(self, helper, private_call, forwarded_call):
        status, report = self.analyze(
            f"{helper}"
            "def build():\n"
            "    values = []\n"
            f"    {private_call}\n"
            "    return values\n"
            "def change(values):\n"
            f"    {forwarded_call}\n"
        )
        self.assertEqual(2, status)
        self.assertIn("ImplicitOutput [priority 3] The function mutate() writes the implicit output", report)
        self.assertNotIn("build()", report)
        self.assertNotIn("UnknownEffect", report)
        self.assertRegex(report, r"probe\.py:\d+: ImplicitOutput \[priority 3\] The function change\(\) writes the implicit output \w+\.")

    def test_helper_mutation_binds_every_parameter_kind_to_the_caller_argument(self):
        cases = {
            "positional": ("def mutate(values):\n    values.append(1)\n", "mutate(values)"),
            "keyword-only": ("def mutate(*, values):\n    values.append(1)\n", "mutate(values=values)"),
            "variadic positional": ("def mutate(*items):\n    items[0].append(1)\n", "mutate(values)"),
            "variadic keyword": ('def mutate(**named):\n    named["v"].append(1)\n', "mutate(v=values)"),
            "variadic element": ("def mutate(*items):\n    for item in items:\n        item.append(1)\n", "mutate(values)"),
        }
        for kind, (helper, call) in cases.items():
            with self.subTest(kind):
                self.assert_helper_mutation_binds_through(helper, call, call)

    def test_omitted_constant_default_does_not_bind_caller_storage(self):
        status, report = self.analyze(
            "def mutate(values=None):\n"
            "    if values is not None:\n"
            "        values.append(1)\n"
            "def build():\n"
            "    mutate()\n"
            "    return 1\n"
            "def change(values):\n"
            "    mutate(values)\n"
        )
        self.assertEqual(2, status)
        self.assertIn("probe.py:3: ImplicitOutput [priority 3] The function mutate() writes the implicit output values.", report)
        self.assertIn("probe.py:8: ImplicitOutput [priority 3] The function change() writes the implicit output values.", report)
        self.assertNotIn("build()", report)
        self.assertNotIn("UnknownEffect", report)

    def test_omitted_non_constant_default_keeps_uncertainty(self):
        status, report = self.analyze(
            "SHARED = []\n"
            "def mutate(values=SHARED):\n"
            "    values.append(1)\n"
            "def build():\n"
            "    mutate()\n"
            "    return 1\n"
        )
        self.assertEqual(2, status)
        self.assertIn("probe.py:5: UnknownEffect [priority 3] The function build()", report)

    def test_star_expansion_keeps_argument_binding_uncertain(self):
        status, report = self.analyze(
            "def mutate(*items):\n"
            "    items[0].append(1)\n"
            "def build(pending):\n"
            "    mutate(*pending)\n"
            "    return pending\n"
        )
        self.assertEqual(2, status)
        self.assertIn("probe.py:4: UnknownEffect [priority 3] The function build() has an unknown effect from <argument binding>.", report)

    def test_method_call_binds_the_declared_receiver_whatever_its_spelling(self):
        status, report = self.analyze(
            "class Box:\n"
            "    def fill(this, values):\n"
            "        values.append(1)\n"
            "    def build(this):\n"
            "        values = []\n"
            "        this.fill(values)\n"
            "        return values\n"
            "    def change(this, values):\n"
            "        this.fill(values)\n"
            "    @staticmethod\n"
            "    def stuff(self):\n"
            "        self.append(1)\n"
            "    def restock(this, values):\n"
            "        this.stuff(values)\n"
        )
        self.assertEqual(2, status)
        self.assertNotIn("Box.build()", report)
        self.assertNotIn("UnknownEffect", report)
        self.assertIn("probe.py:9: ImplicitOutput [priority 3] The method Box.change() writes the implicit output values.", report)
        self.assertIn("probe.py:14: ImplicitOutput [priority 3] The method Box.restock() writes the implicit output self.", report)

    def test_callback_substitution_binds_receiver_and_packed_parameters(self):
        status, report = self.analyze(
            "def record(*items):\n"
            "    items[0].append(1)\n"
            "def apply(callback, values):\n"
            "    callback(values)\n"
            "class Box:\n"
            "    def run(this, callback, values):\n"
            "        callback(values)\n"
            "    def build(this):\n"
            "        values = []\n"
            "        this.run(record, values)\n"
            "        return values\n"
            "def build():\n"
            "    values = []\n"
            "    apply(record, values)\n"
            "    return values\n"
            "def change(values):\n"
            "    apply(record, values)\n"
        )
        self.assertEqual(2, status)
        self.assertIn("probe.py:4: UnknownEffect [priority 3] The function apply() has an unknown effect from callback.", report)
        self.assertNotIn("The function build()", report)
        self.assertNotIn("Box.build()", report)
        self.assertNotIn("<callback", report)
        self.assertIn("probe.py:17: ImplicitOutput [priority 3] The function change() writes the implicit output items.", report)

    def test_variadic_returned_alias_keeps_caller_provenance(self):
        status, report = self.analyze(
            "def pick(*items, **named):\n"
            "    return items[0] if items else named['v']\n"
            "def build():\n"
            "    values = []\n"
            "    alias = pick(values)\n"
            "    alias.append(1)\n"
            "    return values\n"
            "def change(values):\n"
            "    alias = pick(v=values)\n"
            "    alias.append(1)\n"
        )
        self.assertEqual(2, status)
        self.assertNotIn("build()", report)
        self.assertIn("probe.py:10: ImplicitOutput [priority 3] The function change() writes the implicit output alias.", report)

    def test_recursive_call_ring_and_repeated_helpers_scale_without_superlinear_overhead(self):
        def ring_source(functions, calls):
            parts = []
            for i in range(functions):
                parts.append(f"def g{i}(tokens, pos):\n    out = []\n    while pos < len(tokens):\n")
                for c in range(calls):
                    target = (i + 1 + c) % functions
                    parts.append(
                        f"        if tokens[pos] == {c}:\n"
                        f"            node, pos = g{target}(tokens, pos + 1)\n"
                        f"            out.append(node)\n"
                    )
                parts.append("        pos += 1\n    return out, pos\n\n")
            return "".join(parts)

        started = time.perf_counter()
        status, report = self.analyze(ring_source(6, 2))
        elapsed = time.perf_counter() - started
        self.assertEqual(2, status)
        self.assertEqual(6, report.count("ImplicitOutput"))
        self.assertLess(elapsed, 2.0)

        seq_parts = [
            "def testformat(fmt, arg):\n"
            "    try:\n"
            "        r = fmt % arg\n"
            "    except OverflowError:\n"
            "        pass\n"
            "    else:\n"
            "        if r != '':\n"
            "            pass\n"
            "def testcommon(fmt, arg):\n"
            "    testformat(fmt, arg)\n"
            "    testformat(fmt, arg)\n"
            "    testformat(fmt, arg)\n"
            "def main():\n"
        ]
        for c in range(100):
            seq_parts.append(f"    testcommon('%d', {c})\n")
        started = time.perf_counter()
        status, report = self.analyze("".join(seq_parts))
        elapsed = time.perf_counter() - started
        self.assertEqual(0, status)
        self.assertLess(elapsed, 0.5)

    def test_container_literal_memory_scaling(self):
        import tracemalloc

        def measure(n: int) -> int:
            source = "TABLE = [\n" + "".join(f"    ({i}, {i}),\n" for i in range(n)) + "]\n"
            tracemalloc.start()
            try:
                status, _report = self.analyze(source)
                self.assertEqual(0, status)
                _curr, peak = tracemalloc.get_traced_memory()
                return peak
            finally:
                tracemalloc.stop()

        peak_500 = measure(500)
        peak_1000 = measure(1000)
        self.assertLess(peak_1000, 15 * 1024 * 1024)
        self.assertLess(peak_1000 / peak_500, 2.5)

