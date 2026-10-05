from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.callables import CallableNode, module_callables


def _definition(tree: ast.Module, name: str) -> ast.AST:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name
    )


def _callable(tree: ast.Module, name: str) -> CallableNode:
    return next(callable_node for callable_node in module_callables(tree) if callable_node.name == name)


class CallableModelTests(unittest.TestCase):
    def test_module_function_is_an_unowned_function_in_the_module_scope(self) -> None:
        tree = ast.parse("def load(path, *, mode='r'):\n    return path\n")

        load = _callable(tree, "load")

        self.assertIs(_definition(tree, "load"), load.node)
        self.assertEqual("function", load.kind)
        self.assertIsNone(load.owner)
        self.assertEqual((tree,), load.enclosing)
        self.assertEqual("load", load.context)
        self.assertEqual(2, load.parameter_count)

    def test_def_in_class_body_control_flow_is_a_method_owned_by_the_class(self) -> None:
        tree = ast.parse(
            "class Visitor:\n"
            "    if True:\n"
            "        def visit_Name(self, node):\n"
            "            return node\n"
            "    else:\n"
            "        def visit_Call(self, node):\n"
            "            return node\n"
        )
        visitor = _definition(tree, "Visitor")

        for name in ("visit_Name", "visit_Call"):
            method = _callable(tree, name)
            self.assertEqual("method", method.kind)
            self.assertIs(visitor, method.owner)
            self.assertEqual((tree,), method.enclosing)
            self.assertEqual(f"Visitor.{name}", method.context)

    def test_def_nested_in_a_method_is_an_unowned_function_enclosed_by_the_method(self) -> None:
        tree = ast.parse(
            "class Loader:\n"
            "    def load(self):\n"
            "        def helper():\n"
            "            return 1\n"
            "        return helper()\n"
        )

        helper = _callable(tree, "helper")

        self.assertEqual("function", helper.kind)
        self.assertIsNone(helper.owner)
        self.assertEqual((_definition(tree, "load"), tree), helper.enclosing)
        self.assertEqual("helper", helper.context)

    def test_defs_in_exception_handlers_and_match_cases_are_found(self) -> None:
        tree = ast.parse(
            "try:\n"
            "    import json\n"
            "except ImportError:\n"
            "    def fallback():\n"
            "        return None\n"
            "class Parser:\n"
            "    match 1:\n"
            "        case 1:\n"
            "            def parse(self):\n"
            "                return 1\n"
        )

        fallback, parse = _callable(tree, "fallback"), _callable(tree, "parse")

        self.assertEqual(("function", None, (tree,)), (fallback.kind, fallback.owner, fallback.enclosing))
        self.assertEqual(("method", (tree,)), (parse.kind, parse.enclosing))
        self.assertIs(_definition(tree, "Parser"), parse.owner)

    def test_class_nested_in_a_function_owns_its_methods_inside_the_function_scope(self) -> None:
        tree = ast.parse(
            "def build():\n"
            "    class Local:\n"
            "        def run(self):\n"
            "            return 1\n"
            "    return Local\n"
        )

        run = _callable(tree, "run")

        self.assertEqual("method", run.kind)
        self.assertIs(_definition(tree, "Local"), run.owner)
        self.assertEqual((_definition(tree, "build"), tree), run.enclosing)

    def test_lambda_in_class_body_has_no_owner_and_skips_the_class_scope(self) -> None:
        tree = ast.parse("class Sorter:\n    key = lambda item: item\n")

        key = _callable(tree, "<lambda>")

        self.assertEqual("lambda", key.kind)
        self.assertIsNone(key.owner)
        self.assertEqual((tree,), key.enclosing)
        self.assertEqual("<lambda>", key.context)
        self.assertEqual(1, key.parameter_count)

    def test_lambda_in_a_method_is_enclosed_by_the_method(self) -> None:
        tree = ast.parse("class Sorter:\n    def sort(self, items):\n        return sorted(items, key=lambda item: item)\n")

        self.assertEqual((_definition(tree, "sort"), tree), _callable(tree, "<lambda>").enclosing)

    def test_callables_come_back_in_pre_order(self) -> None:
        tree = ast.parse(
            "def outer(default=lambda: 0):\n"
            "    def inner():\n"
            "        return 1\n"
            "    return inner\n"
            "class Late:\n"
            "    def method(self):\n"
            "        return 2\n"
        )

        self.assertEqual(
            ["outer", "<lambda>", "inner", "method"],
            [callable_node.name for callable_node in module_callables(tree)],
        )


if __name__ == "__main__":
    unittest.main()
