from __future__ import annotations

from collections import Counter
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.cli import run


class ExplicitnessLifecycleTests(unittest.TestCase):
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

    def test_cold_coroutine_effects_transfer_at_await(self) -> None:
        self.assert_findings(
            "async def send(value):\n"
            "    print(value)\n"
            "def factory(value):\n"
            "    return send(value)\n"
            "async def drive(value):\n"
            "    work = send(value)\n"
            "    await work\n",
            [("send", "ImplicitOutput", 2), ("drive", "ImplicitOutput", 7)],
        )

    def test_generator_is_owned_by_its_body_and_forced_by_iteration(self) -> None:
        self.assert_findings(
            "def values():\n"
            "    yield print('item')\n"
            "def create():\n"
            "    return values()\n"
            "def consume():\n"
            "    return list(values())\n",
            [("values", "ImplicitOutput", 2), ("consume", "ImplicitOutput", 6)],
        )

    def test_rebound_deferred_value_retains_uncertainty_when_forced(self) -> None:
        self.assert_findings(
            "def values():\n"
            "    yield print('item')\n"
            "def consume():\n"
            "    work = values()\n"
            "    work = values()\n"
            "    return list(work)\n"
            "def quiet():\n"
            "    work = values()\n"
            "    work = [1]\n"
            "    return list(work)\n",
            [("values", "ImplicitOutput", 2), ("consume", "UnknownEffect", 6)],
        )

    def test_generator_expression_has_its_own_owner(self) -> None:
        self.assert_findings(
            "def build(values):\n"
            "    return (print(value) for value in values)\n"
            "def consume(values):\n"
            "    return list(build(values))\n",
            [("<genexpr>", "ImplicitOutput", 2), ("consume", "ImplicitOutput", 4)],
        )

    def test_nested_generator_scopes_are_registered_before_effect_analysis(self) -> None:
        self.assert_findings(
            "def calculate(values):\n"
            "    return sum(sum(item for item in row) for row in values)\n",
            [],
        )

    def test_comprehension_protocol_effect_uses_the_iterable_source_line(self) -> None:
        self.assert_findings(
            "class Rows:\n"
            "    def __iter__(self):\n"
            "        print('iterate')\n"
            "        yield 1\n"
            "def calculate(rows):\n"
            "    return [row for row in rows]\n",
            [("Rows.__iter__", "ImplicitOutput", 3), ("calculate", "UnknownEffect", 6)],
        )

    def test_sort_key_executes_its_callback(self) -> None:
        self.assert_findings(
            "def sort(values):\n"
            "    return sorted(values, key=lambda value: print(value))\n"
            "def quiet(values):\n"
            "    return sorted(values, key=lambda value: value + 1)\n",
            [("<lambda>", "ImplicitOutput", 2), ("sort", "ImplicitOutput", 2)],
        )

    def test_helper_keyword_reads_shared_capture_but_keeps_private_capture_fixed(self) -> None:
        self.assert_findings(
            "def size(items):\n"
            "    return len(items)\n"
            "def make(values):\n"
            "    def read():\n"
            "        return size(items=values)\n"
            "    return read\n"
            "def private():\n"
            "    values = [1, 2]\n"
            "    def fixed():\n"
            "        return size(items=values)\n"
            "    return fixed\n",
            [("read", "ImplicitInput", 5)],
        )

    def test_decorator_runs_at_definition_and_transformed_call_remains_unknown(self) -> None:
        self.assert_findings(
            "def decorate(function):\n"
            "    print('decorate')\n"
            "    return function\n"
            "@decorate\n"
            "def quiet():\n"
            "    return 1\n"
            "def call():\n"
            "    return quiet()\n",
            [("decorate", "ImplicitOutput", 2), ("<module>", "ImplicitOutput", 4), ("call", "UnknownEffect", 8)],
        )

    def test_local_descriptor_dispatch_remains_unknown(self) -> None:
        self.assert_findings(
            "class Box:\n"
            "    @property\n"
            "    def value(self):\n"
            "        print('read')\n"
            "        return 1\n"
            "def read(box):\n"
            "    return box.value\n"
            "def quiet():\n"
            "    return [1][0]\n",
            [("Box.value", "ImplicitOutput", 4), ("read", "UnknownEffect", 7)],
        )

    def test_returning_ambient_callable_does_not_execute_it(self) -> None:
        self.assert_findings("def factory():\n    return print\n", [])

    def test_reading_ambient_stream_is_input_without_writing_to_it(self) -> None:
        self.assert_findings(
            "import sys\n"
            "def factory():\n"
            "    return sys.stdout\n",
            [("factory", "ImplicitInput", 3)],
        )

    def test_frozen_plain_record_constructor_is_a_calculation(self) -> None:
        self.assert_findings(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Point:\n"
            "    x: int\n"
            "def make(value):\n"
            "    return Point(value)\n",
            [("<module>", "UnknownEffect", 2), ("<module>", "UnknownEffect", 2)],
        )

    def test_literal_false_is_pruned_without_evaluating_constant_expressions(self) -> None:
        self.assert_findings(
            "def literal():\n"
            "    if False:\n"
            "        print('dead')\n"
            "def expression():\n"
            "    if not True:\n"
            "        print('retained')\n",
            [("expression", "ImplicitOutput", 6)],
        )
