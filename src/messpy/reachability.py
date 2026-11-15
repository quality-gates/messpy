from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto

__all__ = ["constant_truth", "evaluated_children", "live_statements"]

_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


class _ScanPhase(Enum):
    LIVE = auto()
    STOPPED = auto()


@dataclass(frozen=True)
class _EvaluatedNode:
    node: ast.AST
    previous: _EvaluatedNode | None


@dataclass(frozen=True)
class _EvaluationPrefix:
    last: _EvaluatedNode | None = None
    phase: _ScanPhase = _ScanPhase.LIVE

    def statement(self, node: ast.AST) -> _EvaluationPrefix:
        return self._include(node, _never_completes(node))

    def condition(self, node: ast.expr, decisive: bool) -> _EvaluationPrefix:
        return self._include(node, constant_truth(node) is decisive)

    def generator(self, node: ast.comprehension) -> _EvaluationPrefix:
        return self._include(node, any(constant_truth(test) is False for test in node.ifs))

    def _include(self, node: ast.AST, stops: bool) -> _EvaluationPrefix:
        if self.phase is _ScanPhase.STOPPED:
            return self
        phase = _ScanPhase.STOPPED if stops else _ScanPhase.LIVE
        return _EvaluationPrefix(_EvaluatedNode(node, self.last), phase)

    def nodes(self) -> list[ast.AST]:
        nodes = []
        current = self.last
        while current is not None:
            nodes.append(current.node)
            current = current.previous
        nodes.reverse()
        return nodes


def constant_truth(test: ast.expr) -> bool | None:
    """The truth Python gives a literal test, or None when the test needs a runtime value."""
    if isinstance(test, ast.Constant):
        return bool(test.value)
    return None


def evaluated_children(node: ast.AST) -> list[ast.AST]:
    """The child nodes Python can evaluate while it evaluates the node."""
    if isinstance(node, (ast.If, ast.While, ast.IfExp)):
        truth = constant_truth(node.test)
        if truth is not None:
            branch = node.body if truth else node.orelse
            return [node.test, *(live_statements(branch) if isinstance(branch, list) else [branch])]
    if isinstance(node, ast.BoolOp):
        return _short_circuit(node)
    if isinstance(node, _COMPREHENSIONS):
        return _comprehension_children(node)
    if isinstance(node, ast.comprehension):
        return [node.target, node.iter, *_until_false(node.ifs)]
    return _ordinary_children(node)


def _ordinary_children(node: ast.AST) -> list[ast.AST]:
    children: list[ast.AST] = []
    for _field, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            children.append(value)
        elif isinstance(value, list):
            items = [item for item in value if isinstance(item, ast.AST)]
            children.extend(live_statements(items) if items and isinstance(items[0], ast.stmt) else items)
    return children


def live_statements(statements: Sequence[ast.AST]) -> list[ast.AST]:
    """The statements up to and including the first one that never completes normally."""
    scan = _EvaluationPrefix()
    for statement in statements:
        scan = scan.statement(statement)
        if scan.phase is _ScanPhase.STOPPED:
            break
    return scan.nodes()


def _never_completes(statement: ast.AST) -> bool:
    if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
        return True
    if isinstance(statement, ast.If):
        truth = constant_truth(statement.test)
        branches = [statement.body, statement.orelse] if truth is None else [statement.body if truth else statement.orelse]
        return all(any(_never_completes(inner) for inner in branch) for branch in branches)
    if isinstance(statement, ast.While):
        return constant_truth(statement.test) is True and not _breaks(statement.body)
    return False


def _breaks(nodes: Sequence[ast.AST]) -> bool:
    for node in nodes:
        if isinstance(node, ast.Break):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.expr)):
            continue
        inner = node.orelse if isinstance(node, (ast.For, ast.AsyncFor, ast.While)) else list(ast.iter_child_nodes(node))
        if _breaks(inner):
            return True
    return False


def _short_circuit(node: ast.BoolOp) -> list[ast.AST]:
    decisive = isinstance(node.op, ast.Or)
    scan = _EvaluationPrefix()
    for value in node.values:
        scan = scan.condition(value, decisive)
        if scan.phase is _ScanPhase.STOPPED:
            break
    return scan.nodes()


def _comprehension_children(node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp) -> list[ast.AST]:
    scan = _EvaluationPrefix()
    for generator in node.generators:
        scan = scan.generator(generator)
        if scan.phase is _ScanPhase.STOPPED:
            return scan.nodes()
    results = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
    return [*results, *scan.nodes()]


def _until_false(tests: Sequence[ast.expr]) -> list[ast.AST]:
    scan = _EvaluationPrefix()
    for test in tests:
        scan = scan.condition(test, False)
        if scan.phase is _ScanPhase.STOPPED:
            break
    return scan.nodes()
