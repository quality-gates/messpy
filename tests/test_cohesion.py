from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.callgraph import build_call_graph
from messpy.cohesion import measure_lcom4
from messpy.dependencies import ClassInfo


def measure(source: str) -> int:
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.ClassDef))
    methods = tuple(item for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return measure_lcom4(ClassInfo(node, node.name, methods=methods), build_call_graph(tree))


class CohesionTests(unittest.TestCase):
    def test_fields_and_calls_connect_components(self) -> None:
        self.assertEqual(1, measure('''
class Example:
    def first(self): self.x += 1
    def second(self): self.x += 2; self.third()
    def third(self): self.y += 1
'''))
        self.assertEqual(3, measure('''
class Example:
    def first(self): self.x += 1
    def second(self): self.y += 1
    def third(self): self.z += 1
'''))

    def test_accessors_bridge_fields(self) -> None:
        self.assertEqual(1, measure('''
class Example:
    @property
    def value(self): return self._value
    def get_other(self): return self._other
    def set_other(self, value): self._other = value
    def first(self): self.value += 1; self.get_other()
    def second(self): self._other += 1; self.set_other(3)
    def third(self): self._value += 1
'''))

    def test_excluded_methods_do_not_connect_active_methods(self) -> None:
        self.assertEqual(2, measure('''
class Example:
    def first(self): self.x += 1
    def second(self): self.y += 1
    def __init__(self): self.x += 1; self.y += 1
    @property
    def value(self): return self.x + self.y
    @value.setter
    def value(self, value): self.x += value; self.y += value
    @staticmethod
    def static(self): self.x += 1; self.y += 1
    @classmethod
    def class_method(cls): cls.x += 1; cls.y += 1
    @abstractmethod
    def abstract(self): self.x += 1; self.y += 1
    @overload
    def contract(self): self.x += 1; self.y += 1
    def stub(self): raise NotImplementedError
'''))

    def test_no_active_methods_returns_one(self) -> None:
        self.assertEqual(1, measure('''
class Example:
    def stub(self): ...
    def idle(self): return 42
    def getter(self): return self.value
'''))

    def test_renamed_receiver_and_nested_functions(self) -> None:
        self.assertEqual(2, measure('''
class Example:
    def first(this, /):
        this.x += 1
        def nested(): this.y += 1
        return nested
    async def second(that):
        that.y += 1
    def third(other):
        other.x += 1
'''))


if __name__ == "__main__":
    unittest.main()
