from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.callgraph import CallSite, build_call_graph


def _graph(source: str):
    tree = ast.parse(source)
    return tree, build_call_graph(tree)


def _definition(tree: ast.Module, name: str) -> ast.AST:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name
    )


def _lambda(tree: ast.Module) -> ast.Lambda:
    return next(node for node in ast.walk(tree) if isinstance(node, ast.Lambda))


def _calls(tree: ast.Module) -> list[ast.Call]:
    return sorted(
        (node for node in ast.walk(tree) if isinstance(node, ast.Call)),
        key=lambda call: (call.lineno, call.col_offset),
    )


class CallGraphTests(unittest.TestCase):
    def test_bare_call_resolves_to_module_function(self) -> None:
        tree, graph = _graph("def load():\n    return save()\n\ndef save():\n    return 1\n")
        load, save = _definition(tree, "load"), _definition(tree, "save")

        self.assertEqual((CallSite(load, save, "save", 2),), graph.callees(load))
        self.assertEqual((CallSite(load, save, "save", 2),), graph.callers(save))
        self.assertEqual((), graph.callees(save))

    def test_each_callee_is_one_call_site_at_its_first_call(self) -> None:
        tree, graph = _graph("def load():\n    save()\n    save()\n\ndef save():\n    return 1\n")

        self.assertEqual(
            (CallSite(_definition(tree, "load"), _definition(tree, "save"), "save", 2),),
            graph.callees(_definition(tree, "load")),
        )

    def test_nested_function_resolves_through_enclosing_scope(self) -> None:
        tree, graph = _graph(
            "def outer():\n"
            "    def helper():\n"
            "        return 1\n"
            "    def inner():\n"
            "        return helper()\n"
            "    return inner()\n"
        )
        inner, helper = _definition(tree, "inner"), _definition(tree, "helper")

        self.assertEqual((CallSite(inner, helper, "helper", 5),), graph.callees(inner))
        self.assertEqual(
            (CallSite(_definition(tree, "outer"), inner, "inner", 6),),
            graph.callees(_definition(tree, "outer")),
        )

    def test_parameter_shadows_module_function(self) -> None:
        tree, graph = _graph("def save():\n    return 1\n\ndef load(save):\n    return save()\n")

        self.assertEqual((), graph.callees(_definition(tree, "load")))

    def test_global_declaration_skips_local_binding(self) -> None:
        tree, graph = _graph(
            "def save():\n"
            "    return 1\n"
            "def load():\n"
            "    global save\n"
            "    def save():\n"
            "        return 2\n"
            "    return save()\n"
        )
        saves = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "save"]

        self.assertEqual(saves[0], graph.callees(_definition(tree, "load"))[0].callee)

    def test_lambda_bound_to_name_is_a_callable(self) -> None:
        tree, graph = _graph("save = lambda: store()\n\ndef store():\n    return 1\n\ndef load():\n    return save()\n")
        lambda_node = _lambda(tree)

        self.assertEqual(
            (CallSite(_definition(tree, "load"), lambda_node, "save", 7),),
            graph.callees(_definition(tree, "load")),
        )
        self.assertEqual((CallSite(lambda_node, _definition(tree, "store"), "store", 1),), graph.callees(lambda_node))

    def test_receiver_calls_resolve_to_methods_of_the_class(self) -> None:
        tree, graph = _graph(
            "class Cart:\n"
            "    def total(self):\n"
            "        return self.subtotal()\n"
            "    def subtotal(self):\n"
            "        return 1\n"
            "    @classmethod\n"
            "    def empty(cls):\n"
            "        return cls.build()\n"
            "    @classmethod\n"
            "    def build(cls):\n"
            "        return cls()\n"
        )
        cart = _definition(tree, "Cart")

        self.assertEqual(
            (CallSite(_definition(tree, "total"), _definition(tree, "subtotal"), "subtotal", 3),),
            graph.callees(_definition(tree, "total")),
        )
        self.assertEqual(
            (CallSite(_definition(tree, "empty"), _definition(tree, "build"), "build", 8),),
            graph.callees(_definition(tree, "empty")),
        )
        self.assertIs(cart, graph.method_class(_definition(tree, "total")))
        self.assertIsNone(graph.method_class(cart))

    def test_nested_function_reaches_the_method_receiver(self) -> None:
        tree, graph = _graph(
            "class Cart:\n"
            "    def total(self):\n"
            "        def later():\n"
            "            return self.subtotal()\n"
            "        return later\n"
            "    def subtotal(self):\n"
            "        return 1\n"
        )

        self.assertEqual(
            _definition(tree, "subtotal"),
            graph.callees(_definition(tree, "later"))[0].callee,
        )
        self.assertEqual((), graph.callees(_definition(tree, "total")))

    def test_staticmethod_has_no_receiver(self) -> None:
        tree, graph = _graph(
            "class Cart:\n"
            "    @staticmethod\n"
            "    def total(self):\n"
            "        return self.subtotal()\n"
            "    def subtotal(self):\n"
            "        return 1\n"
        )

        self.assertEqual((), graph.callees(_definition(tree, "total")))

    def test_comprehension_target_masks_outer_callable(self) -> None:
        tree, graph = _graph(
            "def save():\n"
            "    return 1\n"
            "def load(items):\n"
            "    return [save() for save in items]\n"
        )

        self.assertEqual((), graph.callees(_definition(tree, "load")))

    def test_outermost_comprehension_iterable_sees_the_outer_callable(self) -> None:
        tree, graph = _graph(
            "def save():\n"
            "    return []\n"
            "def load():\n"
            "    return [save for save in save()]\n"
        )

        self.assertEqual(_definition(tree, "save"), graph.callees(_definition(tree, "load"))[0].callee)

    def test_comprehension_target_masks_calls_in_lambdas_and_inner_iterables(self) -> None:
        tree, graph = _graph(
            "def save():\n"
            "    return []\n"
            "def load(items):\n"
            "    return [lambda: save() for save in items]\n"
            "def store(items):\n"
            "    return [x for save in items for x in save()]\n"
        )

        self.assertEqual((), graph.callees(_definition(tree, "load")))
        self.assertEqual((), graph.callees(_definition(tree, "store")))

    def test_comprehension_target_does_not_reach_nested_definitions(self) -> None:
        tree, graph = _graph(
            "def save():\n"
            "    return 1\n"
            "def load(items):\n"
            "    return [save for save in items if [save() for _ in items]]\n"
            "class Store:\n"
            "    items = [save() for save in range(3)]\n"
        )

        self.assertEqual((), graph.callees(_definition(tree, "load")))

    def test_reachable_from_follows_mutual_recursion(self) -> None:
        tree, graph = _graph(
            "def ping():\n"
            "    return pong()\n"
            "def pong():\n"
            "    ping()\n"
            "    return leaf()\n"
            "def leaf():\n"
            "    return 1\n"
        )
        ping, pong, leaf = (_definition(tree, name) for name in ("ping", "pong", "leaf"))

        self.assertEqual({ping, pong, leaf}, graph.reachable_from(ping))
        self.assertEqual(set(), graph.reachable_from(leaf))

    def test_reachable_from_excludes_the_caller_without_a_cycle(self) -> None:
        tree, graph = _graph("def a():\n    return b()\ndef b():\n    return 1\n")

        self.assertEqual({_definition(tree, "b")}, graph.reachable_from(_definition(tree, "a")))

    def test_callables_lists_functions_and_lambdas_in_source_order(self) -> None:
        tree, graph = _graph("def a():\n    return 1\nb = lambda: 2\nclass C:\n    def c(self):\n        return 3\n")

        self.assertEqual(
            (_definition(tree, "a"), _lambda(tree), _definition(tree, "c")),
            graph.callables,
        )

    def test_resolve_target_finds_intra_module_definitions(self) -> None:
        tree, graph = _graph(
            "import sys\n"
            "def save():\n"
            "    return 1\n"
            "def load():\n"
            "    sys.exit()\n"
            "    return save()\n"
            "load()\n"
        )
        exit_call, save_call, load_call = _calls(tree)

        self.assertIs(_definition(tree, "load"), graph.resolve_target(load_call))
        self.assertIsNone(graph.resolve_target(exit_call))
        self.assertIs(_definition(tree, "save"), graph.resolve_target(save_call))

    def test_qualified_name_follows_import_aliases(self) -> None:
        tree, graph = _graph(
            "import sys as system\n"
            "from os import _exit as stop\n"
            "system.exit(1)\n"
            "stop(1)\n"
            "exit()\n"
            "helper.run()\n"
        )

        self.assertEqual(
            ["sys.exit", "os._exit", "exit", "helper.run"],
            [graph.qualified_name(call) for call in _calls(tree)],
        )

    def test_qualified_name_is_empty_for_locally_rebound_names(self) -> None:
        tree, graph = _graph(
            "import sys\n"
            "def run(sys):\n"
            "    sys.exit()\n"
            "def stop():\n"
            "    exit = print\n"
            "    exit()\n"
        )

        self.assertEqual(["", ""], [graph.qualified_name(call) for call in _calls(tree)])

    def test_qualified_name_is_empty_for_comprehension_targets(self) -> None:
        tree, graph = _graph(
            "import sys\n"
            "def run(modules):\n"
            "    return [sys.exit() for sys in modules]\n"
            "def outer():\n"
            "    return [item for item in sys.exit()]\n"
        )

        self.assertEqual(["", "sys.exit"], [graph.qualified_name(call) for call in _calls(tree)])


if __name__ == "__main__":
    unittest.main()
