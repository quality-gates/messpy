from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.analyzer import analyze_source
from messpy.constants import scope_constants
from messpy.names import Names
from messpy.protocols import Protocols
from messpy.rulesets import LoadedRule
from messpy.syntax import dotted_name


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

    def test_layered_diamond_ancestry_work_is_polynomial(self) -> None:
        depth = 12
        source = 'class Root: pass\n'
        previous = ['Root']
        for level in range(depth):
            current = [f'C{level}a', f'C{level}b']
            source += ''.join(
                f'class {name}({", ".join(previous)}):\n'
                + ''.join(f' def method{index}(self): pass\n' for index in range(5))
                for name in current
            )
            previous = current
        # Each base expansion resolves its bases with dotted_name, so its
        # call count is the deterministic ancestry work for this traversal.
        with mock.patch('messpy.protocols.dotted_name', wraps=dotted_name) as resolve:
            protocols = Protocols.collect(ast.parse(source))
        # Ceiling, not target: the path-local traversal re-expanded convergent
        # ancestors and made >100k resolutions at this depth. A shared
        # traversal resolves each inheritance edge a bounded number of times.
        self.assertLessEqual(resolve.call_count, 50 * (2 * depth + 1))
        expected = frozenset(
            (ancestor, f'method{index}')
            for level in range(depth)
            for ancestor in ['Root'] + [f'C{earlier}{side}' for earlier in range(level) for side in 'ab']
            for index in range(5)
        )
        self.assertEqual(expected, protocols.overrides)

    def test_duplicate_class_names_expand_every_matching_class(self) -> None:
        tree = ast.parse('''
class Base(First):
    def first(self): pass
class Base(Second):
    def second(self): pass
class Leaf(Base):
    def leaf(self): pass
''')
        self.assertEqual(
            frozenset({('First', 'first'), ('Second', 'second'),
                       ('Base', 'leaf'), ('First', 'leaf'), ('Second', 'leaf')}),
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
