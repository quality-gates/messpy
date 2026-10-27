from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.callgraph import build_call_graph
from messpy.names import Names


class SyntaxResolutionTests(unittest.TestCase):
    def test_names_and_calls_preserve_comprehension_scopes(self) -> None:
        tree = ast.parse(
            "import sys as system\n"
            "def finish():\n    pass\n"
            "def check(functions, groups):\n"
            "    [finish() for finish in functions]\n"
            "    [item for finish in finish() for item in ()]\n"
            "    [[finish() for finish in group] for group in groups]\n"
            "    [(lambda: finish())() for finish in functions]\n"
            "    [system.exit() for system in functions]\n"
            "    [system for system in system.exit()]\n"
            "    return finish()\n"
        )
        names = Names.build(tree, module=None, path=Path("example.py"))
        graph = build_call_graph(tree, names)
        resolved = []
        calls = sorted(
            (node for node in ast.walk(tree) if isinstance(node, ast.Call)),
            key=lambda node: (node.lineno, node.col_offset),
        )
        for call in calls:
            target = graph.resolve_target(call)
            target_name = "<lambda>" if isinstance(target, ast.Lambda) else getattr(target, "name", None)
            resolved.append((call.lineno, target_name, names.qualified(call.func)))

        self.assertEqual(
            [
                (5, None, ""),
                (6, "finish", ""),
                (7, None, ""),
                (8, "<lambda>", ""),
                (8, None, ""),
                (9, None, ""),
                (10, None, "sys.exit"),
                (11, "finish", ""),
            ],
            resolved,
        )

    def test_import_roots_do_not_treat_subscripts_as_dotted_names(self) -> None:
        tree = ast.parse("import sys as system\nsystem.modules\nsystem.modules['example']\n")
        names = Names.build(tree, module=None, path=Path("example.py"))

        self.assertEqual(("sys", False), names.imported(tree.body[1].value))
        self.assertEqual("sys.modules", names.qualified(tree.body[1].value))
        self.assertIsNone(names.imported(tree.body[2].value))
        self.assertEqual("", names.qualified(tree.body[2].value))
