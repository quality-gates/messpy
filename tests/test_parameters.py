from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.parameters import bind_arguments, bind_call


def _bind(definition: str, call: str, receiver: bool = False) -> dict[str, str] | None:
    function = ast.parse(definition).body[0]
    bound = bind_call(function, ast.parse(call, mode="eval").body, receiver)
    if bound is None:
        return None
    return {name: _source(parameter) for name, parameter in bound.items()}


def _source(parameter) -> str:
    if parameter.pack:
        items = ", ".join(f"{key[1]}={ast.unparse(item)}" for key, item in parameter.items)
        return f"{parameter.pack}({items})"
    if parameter.default is not None:
        return f"default {ast.unparse(parameter.default)}"
    return ast.unparse(parameter.argument)


class ParameterBindingTests(unittest.TestCase):
    def test_binds_positional_keyword_default_and_packed_parameters(self) -> None:
        self.assertEqual(
            {"a": "x", "b": "default 2", "c": "z", "rest": "tuple()", "extra": "dict(d=w)"},
            _bind("def f(a, b=2, *rest, c, **extra): pass", "f(x, c=z, d=w)"),
        )
        self.assertEqual(
            {"items": "tuple(0=x, 1=y)"},
            _bind("def f(*items): pass", "f(x, y)"),
        )

    def test_bound_method_receives_the_attribute_object_whatever_its_spelling(self) -> None:
        self.assertEqual({"this": "box", "values": "x"}, _bind("def fill(this, values): pass", "box.fill(x)", receiver=True))
        self.assertEqual({"self": "x"}, _bind("def stuff(self): pass", "box.stuff(x)", receiver=False))
        self.assertEqual({"values": "x"}, _bind("def fill(values): pass", "fill(x)", receiver=True))

    def test_calls_python_would_reject_or_cannot_be_read_are_unbound(self) -> None:
        cases = {
            "star expansion": ("def f(*items): pass", "f(*xs)"),
            "keyword expansion": ("def f(**named): pass", "f(**xs)"),
            "missing argument": ("def f(a, b): pass", "f(x)"),
            "too many positionals": ("def f(a): pass", "f(x, y)"),
            "duplicate binding": ("def f(a): pass", "f(x, a=y)"),
            "unknown keyword": ("def f(a): pass", "f(x, b=y)"),
            "positional-only keyword": ("def f(a, /): pass", "f(a=x)"),
            "not a function": ("class F: pass", "F(x)"),
        }
        for label, (definition, call) in cases.items():
            with self.subTest(label):
                self.assertIsNone(_bind(definition, call))

    def test_positional_only_name_passed_by_keyword_joins_the_keyword_pack(self) -> None:
        self.assertEqual({"a": "x", "named": "dict(a=y)"}, _bind("def f(a, /, **named): pass", "f(x, a=y)"))

    def test_binds_abstract_argument_values(self) -> None:
        arguments = ast.parse("def f(a, *rest, b=None): pass").body[0].args
        bound = bind_arguments(arguments, ["first", "second"], [])
        self.assertEqual("first", bound["a"].argument)
        self.assertEqual(((("item", 0), "second"),), bound["rest"].items)
        self.assertIsInstance(bound["b"].default, ast.Constant)


if __name__ == "__main__":
    unittest.main()
