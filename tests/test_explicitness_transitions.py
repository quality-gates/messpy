from __future__ import annotations

import ast
from collections import Counter
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from messpy.cli import run
from messpy.analyzer import _ScopeChain
from messpy.captures import _CaptureQuery
from messpy.ownership import Storage, _Seen, _State, _observations
from messpy.reachability import evaluated_children, live_statements


class DataflowTransitionTests(unittest.TestCase):
    def assert_findings(self, source: str, expected: list[tuple[str, str, int]]) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "example.py"
            path.write_text(source, encoding="utf-8")
            stdout, stderr = StringIO(), StringIO()
            status = run([str(path), "json", "explicitness", "--strict"], stdout, stderr)
        report = json.loads(stdout.getvalue())
        self.assertEqual("", stderr.getvalue())
        self.assertEqual([], report["errors"])
        self.assertEqual(2 if expected else 0, status)
        actual = Counter((finding["context"], finding["ruleName"], finding["line"]) for finding in report["findings"])
        self.assertEqual(Counter(expected), actual)

    def test_recursive_effects_reach_callers_and_keep_the_first_call_witness(self) -> None:
        self.assert_findings(
            "def first(value):\n"
            "    return second(value)\n"
            "def second(value):\n"
            "    if value:\n"
            "        return first(value)\n"
            "    print(value)\n"
            "def drive(value):\n"
            "    first(value)\n"
            "    second(value)\n",
            [("first", "ImplicitOutput", 2), ("second", "ImplicitOutput", 6), ("drive", "ImplicitOutput", 8)],
        )

    def test_returned_callable_alias_is_available_after_its_assignment(self) -> None:
        self.assert_findings(
            "def factory():\n"
            "    return lambda value: print(value)\n"
            "def drive(value):\n"
            "    callback = factory()\n"
            "    callback(value)\n",
            [("<lambda>", "ImplicitOutput", 2), ("drive", "ImplicitOutput", 5)],
        )

    def test_revisited_loop_read_uses_the_converged_alias(self) -> None:
        self.assert_findings(
            "def edit(shared, condition):\n"
            "    alias = []\n"
            "    while condition:\n"
            "        alias.append(1)\n"
            "        alias = shared\n",
            [("edit", "ImplicitOutput", 4)],
        )

    def test_joined_branch_preserves_a_possible_external_alias(self) -> None:
        self.assert_findings(
            "def edit(shared, choose):\n"
            "    alias = []\n"
            "    if choose:\n"
            "        alias = shared\n"
            "    alias.append(1)\n",
            [("edit", "ImplicitOutput", 5)],
        )

    def test_memoized_helper_replays_distinct_private_and_external_slots(self) -> None:
        self.assert_findings(
            "def pair(values):\n"
            "    return [values, []]\n"
            "def edit(shared):\n"
            "    first = pair(shared)\n"
            "    second = pair(shared)\n"
            "    second[1].append(1)\n"
            "    first[0].append(1)\n",
            [("edit", "ImplicitOutput", 7)],
        )

    def test_comprehension_restores_outer_bindings_and_skips_false_body(self) -> None:
        self.assert_findings(
            "def edit(shared):\n"
            "    private = []\n"
            "    [item.append(1) for item in [private] if False]\n"
            "    [shared for shared in [private]]\n"
            "    shared.append(1)\n",
            [("edit", "ImplicitOutput", 5)],
        )

    def test_comprehension_walrus_escapes_with_uncertain_storage(self) -> None:
        self.assert_findings(
            "def edit(shared):\n"
            "    [(saved := shared) for item in [1]]\n"
            "    saved.append(1)\n",
            [("edit", "UnknownEffect", 3)],
        )

    def test_known_deferred_and_unknown_await_values_remain_distinct(self) -> None:
        self.assert_findings(
            "async def drive(value):\n"
            "    await value\n"
            "async def known(value):\n"
            "    print(value)\n"
            "async def force(value):\n"
            "    saved = known(value)\n"
            "    await saved\n",
            [("drive", "UnknownEffect", 2), ("known", "ImplicitOutput", 4), ("force", "ImplicitOutput", 7)],
        )

    def test_capture_proof_stops_at_recursive_helper(self) -> None:
        self.assert_findings(
            "def build():\n"
            "    values = [1]\n"
            "    def recurse(items):\n"
            "        return recurse(items)\n"
            "    def read():\n"
            "        return recurse(values)\n"
            "    return read()\n",
            [("read", "ImplicitInput", 6)],
        )

    def test_statement_scan_includes_terminal_and_preserves_ast_identity(self) -> None:
        body = ast.parse("def calculate():\n    value = 1\n    return value\n    print(value)\n").body[0].body
        actual = live_statements(body)
        self.assertEqual(2, len(actual))
        self.assertIs(body[0], actual[0])
        self.assertIs(body[1], actual[1])

    def test_boolean_scan_includes_decisive_operand_and_stops(self) -> None:
        for source in ("value and False and print(value)", "value or True or print(value)"):
            with self.subTest(source=source):
                expression = ast.parse(source, mode="eval").body
                actual = evaluated_children(expression)
                self.assertEqual(2, len(actual))
                self.assertIs(expression.values[0], actual[0])
                self.assertIs(expression.values[1], actual[1])

    def test_comprehension_scan_preserves_result_order_and_false_filter_cutoff(self) -> None:
        expression = ast.parse("[emit(item) for item in values for other in values]", mode="eval").body
        actual = evaluated_children(expression)
        self.assertEqual([expression.elt, *expression.generators], actual)
        stopped = ast.parse("[emit(item) for item in values if False for other in values]", mode="eval").body
        self.assertEqual([stopped.generators[0]], evaluated_children(stopped))

    def test_capture_walk_preserves_identity_and_order_through_deep_pending_siblings(self) -> None:
        leaf = ast.Name(id="captured", ctx=ast.Load())
        nested = leaf
        siblings = []
        for value in range(4000):
            sibling = ast.Constant(value=value)
            siblings.append(sibling)
            nested = ast.BinOp(left=sibling, op=ast.Add(), right=nested)
        scope = ast.Expr(value=nested)
        query = _CaptureQuery("captured", scope, _ScopeChain((scope,), {}))
        nodes = list(query.nodes())
        self.assertEqual(12002, len(nodes))
        self.assertIs(nested, nodes[0])
        self.assertIs(leaf, nodes[4000])
        self.assertEqual(siblings, [node for node in nodes if isinstance(node, ast.Constant)])

    def test_observation_replay_preserves_chronological_last_write_in_deep_traces(self) -> None:
        early = _State(result=Storage(kinds=frozenset({"int"})))
        latest = _State(result=Storage(kinds=frozenset({"str"})))
        trace = (_Seen(0, early),)
        for node in range(1, 4001):
            trace = (trace, _Seen(node, early))
        trace = (trace, _Seen(0, latest))
        observed = _observations(trace)
        self.assertEqual(4001, len(observed))
        self.assertIs(latest, observed[0])
        self.assertIs(early, observed[4000])
