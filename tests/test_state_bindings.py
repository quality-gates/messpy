from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.analyzer import analyze_source
from messpy.constants import scope_constants
from messpy.names import Names
from messpy.protocols import Protocols
from messpy.rulesets import LoadedRule


class BindingStateBehaviorTests(unittest.TestCase):
    def test_name_lookup_distinguishes_global_nonlocal_and_class_bindings(self) -> None:
        tree = ast.parse('''
import sys as selected
class Container:
    selected = object()
    body = selected
    def method(self):
        return selected

def outer():
    import os as selected
    def inner():
        nonlocal selected
        return selected
    def module_value():
        global selected
        return selected
    return inner, module_value
''')
        names = Names.build(tree, module=None, path=Path("example.py"))
        uses = sorted(
            (node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == "selected" and isinstance(node.ctx, ast.Load)),
            key=lambda node: node.lineno,
        )

        self.assertEqual(["", "sys", "os", "sys"], [names.qualified(node) for node in uses])
        self.assertEqual([None, ("sys", False), ("os", False), ("sys", False)], [names.imported(node) for node in uses])

    def test_constants_advance_once_in_source_order_and_reject_rebinding(self) -> None:
        tree = ast.parse('''
earlier = later
later = 3
forward = later
changing = 1
changing = 2
def definition(): pass
reference = definition
''')

        self.assertEqual(
            {"later": "int", "forward": "int", "definition": "definition", "reference": "definition"},
            scope_constants(tree.body, {"earlier", "later", "forward", "changing", "definition", "reference"}),
        )

    def test_cyclic_ancestors_preserve_each_method_override_set(self) -> None:
        tree = ast.parse('''
class First(Second):
    def first(self): pass
class Second(First):
    def second(self): pass
class Leaf(First, external.Base):
    def leaf(self): pass
''')

        self.assertEqual(
            frozenset({("First", "first"), ("Second", "first"), ("First", "second"), ("Second", "second"),
                       ("First", "leaf"), ("Second", "leaf"), ("external.Base", "leaf")}),
            Protocols.collect(tree).overrides,
        )

    def test_action_cycle_keeps_first_explanation_and_first_module_call(self) -> None:
        analysis = analyze_source(
            "def first():\n"
            "    second()\n"
            "    print('first')\n"
            "def second():\n"
            "    first()\n"
            "def entry():\n"
            "    second()\n"
            "entry()\n"
            "entry()\n",
            filename="/app/domain/core.py",
            rules=[LoadedRule("DomainAction", 2, {"domain": "*/domain/*"})],
        )

        self.assertEqual((), analysis.errors)
        spread = [finding for finding in analysis.findings if "which" in finding.message]
        self.assertEqual(
            [(2, "The function first() calls second(), which calls first(), which writes the implicit output print. Move the action to the interaction layer."),
             (5, "The function second() calls first(), which writes the implicit output print. Move the action to the interaction layer."),
             (7, "The function entry() calls second(), which calls first(), which writes the implicit output print. Move the action to the interaction layer."),
             (8, "The module calls entry(), which calls second(), which calls first(), which writes the implicit output print, at import time. Move the action to the interaction layer.")],
            [(finding.line, finding.message) for finding in spread],
        )


if __name__ == "__main__":
    unittest.main()
