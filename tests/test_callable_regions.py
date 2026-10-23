from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.cli import run


def _findings(source: str, selected: str) -> list[dict]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "regions.py"
        path.write_text(source, encoding="utf-8")
        stdout, stderr = StringIO(), StringIO()
        status = run(
            [str(path), "json", "design,explicitness,cleancode,unusedcode", "--only", selected],
            stdout, stderr,
        )
    if stderr.getvalue() or status not in (0, 2):
        raise AssertionError((status, stderr.getvalue(), stdout.getvalue()))
    return json.loads(stdout.getvalue())["findings"]


class CallableRegionAcceptanceTests(unittest.TestCase):
    def test_nested_definition_calls_belong_to_the_enclosing_callable(self) -> None:
        findings = _findings(
            "import time\n"
            "class Foo:\n"
            "    @staticmethod\n"
            "    def create():\n"
            "        return time.time()\n"
            "def outer():\n"
            "    def inner(value=Foo.create(), stamp=time.time()):\n"
            "        return value, stamp\n"
            "    @decorate(Foo.create(), time.time())\n"
            "    async def decorated():\n"
            "        pass\n"
            "    class Local(Foo.create(), metaclass=Foo.create()):\n"
            "        made = Foo.create()\n"
            "        stamp = time.time()\n"
            "    return inner, decorated, Local\n",
            "StaticAccess,ImplicitInput",
        )
        self.assertEqual(
            [(7, "outer"), (9, "outer"), (12, "outer"), (12, "outer"), (13, "outer")],
            [(f["line"], f["context"]) for f in findings if f["ruleName"] == "StaticAccess"],
        )
        self.assertTrue(any(
            f["ruleName"] == "ImplicitInput" and f["line"] == 7 and f["context"] == "outer"
            and "time.time" in f["message"] for f in findings
        ))

    def test_nested_bodies_and_local_annotations_are_not_enclosing_calls(self) -> None:
        findings = _findings(
            "def outer():\n"
            "    pending: Foo.annotation()\n"
            "    def inner():\n"
            "        return Foo.function_body()\n"
            "    callback = lambda value=Foo.default(): Foo.lambda_body()\n"
            "    return inner, callback\n",
            "StaticAccess",
        )
        self.assertEqual(
            [(4, "inner"), (5, "<lambda>"), (5, "outer")],
            sorted((f["line"], f["context"]) for f in findings),
        )

    def test_else_checks_stay_in_the_callable_control_flow(self) -> None:
        findings = _findings(
            "def outer(flag):\n"
            "    class Local:\n"
            "        if flag:\n"
            "            raise ValueError()\n"
            "        else:\n"
            "            value = 1\n"
            "    def inner(test):\n"
            "        if test:\n"
            "            return 1\n"
            "        else:\n"
            "            return 2\n"
            "    return Local, inner\n",
            "ElseExpression",
        )
        self.assertEqual([(11, "inner")], [(f["line"], f["context"]) for f in findings])

    def test_nested_definition_defaults_still_use_enclosing_locals(self) -> None:
        findings = _findings(
            "def outer():\n"
            "    values = [1]\n"
            "    def inner(copied=[value for value in values]):\n"
            "        return copied\n"
            "    callback = lambda value=values: value\n"
            "    return inner, callback\n",
            "UnusedLocalVariable",
        )
        self.assertEqual([], findings)

    def test_nested_class_local_reads_do_not_use_enclosing_locals(self) -> None:
        findings = _findings(
            "def outer():\n"
            "    total = 10\n"
            "    values = [1]\n"
            "    class Local:\n"
            "        total = 0\n"
            "        total += 1\n"
            "        values = [2]\n"
            "        copied = [value for value in values]\n"
            "    def inner():\n"
            "        total = 0\n"
            "        total += 1\n"
            "        return total\n"
            "    return Local, inner\n",
            "UnusedLocalVariable",
        )
        self.assertEqual([2, 3], [f["line"] for f in findings])
        self.assertEqual(
            ["Avoid unused local variables such as 'total'.", "Avoid unused local variables such as 'values'."],
            [f["message"] for f in findings],
        )


if __name__ == "__main__":
    unittest.main()
