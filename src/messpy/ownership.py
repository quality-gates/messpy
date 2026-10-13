from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass, field

from .reachability import constant_truth, evaluated_children, live_statements


@dataclass(frozen=True)
class Origin:
    scope: int
    name: str


@dataclass(frozen=True)
class Storage:
    outer: frozenset[Origin] = frozenset()
    reachable: frozenset[Origin] = frozenset()
    kinds: frozenset[str] = frozenset({"unknown"})

    def join(self, other: Storage) -> Storage:
        return Storage(self.outer | other.outer, self.reachable | other.reachable, self.kinds | other.kinds)


@dataclass(frozen=True)
class Ownership:
    observations: dict[int, dict[str, Storage]]
    external: dict[str, Storage]
    copies: dict[int, str]
    returned: dict[int, Storage] = field(default_factory=dict)

    def value(self, expression: ast.AST, node: ast.AST) -> Storage:
        return storage_value(expression, self.observations.get(id(node), {}), self.external, self.copies, self.returned)


def storage_value(
    expression: ast.AST,
    bindings: dict[str, Storage],
    external: dict[str, Storage],
    copies: dict[int, str],
    returned: dict[int, Storage] | None = None,
) -> Storage:
    returned = returned or {}
    if isinstance(expression, ast.Name):
        return bindings.get(expression.id, external.get(expression.id, Storage()))
    if isinstance(expression, ast.Constant):
        return Storage(kinds=frozenset({type(expression.value).__name__}))
    if isinstance(expression, ast.IfExp):
        return storage_value(expression.body, bindings, external, copies, returned).join(
            storage_value(expression.orelse, bindings, external, copies, returned)
        )
    if isinstance(expression, (ast.Attribute, ast.Subscript)):
        return _selected_storage(expression, bindings, external, copies, returned)
    if isinstance(expression, ast.Call):
        return returned.get(id(expression), _call_storage(expression, bindings, external, copies, returned))
    if isinstance(expression, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return _container_storage(expression, bindings, external, copies, returned)
    return Storage()


def _container_storage(expression: ast.AST, bindings, external, copies, returned) -> Storage:
    elements = [storage_value(child, bindings, external, copies, returned) for child in ast.iter_child_nodes(expression)]
    reachable = frozenset(origin for item in elements for origin in item.outer | item.reachable)
    return Storage(reachable=reachable, kinds=frozenset({type(expression).__name__.lower()}))


def _selected_storage(expression: ast.Attribute | ast.Subscript, bindings, external, copies, returned) -> Storage:
    base = storage_value(expression.value, bindings, external, copies, returned)
    if isinstance(expression, ast.Subscript) and isinstance(expression.slice, ast.Slice):
        return Storage(reachable=base.outer | base.reachable, kinds=base.kinds)
    return Storage(base.outer | base.reachable, base.outer | base.reachable)


def _call_storage(expression: ast.Call, bindings, external, copies, returned) -> Storage:
    copied = copies.get(id(expression))
    if copied:
        source = expression.args[0] if expression.args else ast.Constant(None)
        base = storage_value(source, bindings, external, copies, returned)
        return Storage(reachable=base.outer | base.reachable, kinds=frozenset({copied}))
    if isinstance(expression.func, ast.Attribute) and expression.func.attr == "copy":
        base = storage_value(expression.func.value, bindings, external, copies, returned)
        if base.kinds <= {"list", "dict", "set"}:
            return Storage(reachable=base.outer | base.reachable, kinds=base.kinds)
    return Storage()


def argument_ownership(
    callable_node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    parameters: set[str],
    external: dict[str, Storage],
    copies: dict[int, str],
) -> Ownership:
    observations: dict[int, dict[str, Storage]] = {}

    def visit(node: ast.AST, bindings: dict[str, Storage]) -> dict[str, Storage]:
        observations[id(node)] = bindings
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return bindings
        if isinstance(node, ast.If):
            return branches(node, visit(node.test, bindings))
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            return loop(node, bindings)
        if isinstance(node, (ast.Try, ast.TryStar)):
            return exceptions(node, bindings)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            return assignment(node, bindings)
        for child in evaluated_children(node):
            bindings = visit(child, bindings)
        return bindings

    def branches(node: ast.If, bindings: dict[str, Storage]) -> dict[str, Storage]:
        truth = constant_truth(node.test)
        if truth is None:
            return _join_bindings(block(node.body, bindings), block(node.orelse, bindings))
        return block(node.body if truth else node.orelse, bindings)

    def assignment(node: ast.Assign | ast.AnnAssign | ast.NamedExpr, bindings: dict[str, Storage]) -> dict[str, Storage]:
        value = node.value
        if value is not None:
            visit(value, bindings)
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        updated = dict(bindings)
        for target in targets:
            visit(target, bindings)
            bind(target, storage_value(value, bindings, external, copies), updated)
        return updated

    def exceptions(node: ast.Try | ast.TryStar, bindings: dict[str, Storage]) -> dict[str, Storage]:
        paths = _join_bindings(block(node.body, bindings), block(node.orelse, bindings))
        for handler in node.handlers:
            paths = _join_bindings(paths, block(handler.body, bindings))
        return block(node.finalbody, _join_bindings(bindings, paths))

    def bind(target: ast.AST, value: Storage, bindings: dict[str, Storage]) -> None:
        if isinstance(target, ast.Name):
            bindings[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            element = Storage(value.reachable, value.reachable)
            for child in target.elts:
                bind(child, element, bindings)

    def loop(node: ast.For | ast.AsyncFor | ast.While, bindings: dict[str, Storage]) -> dict[str, Storage]:
        truth = constant_truth(node.test) if isinstance(node, ast.While) else None
        if truth is False:
            return block(node.orelse, visit(node.test, bindings))
        current = bindings
        while True:
            entered = dict(current)
            if isinstance(node, (ast.For, ast.AsyncFor)):
                visit(node.iter, current)
                value = storage_value(node.iter, current, external, copies)
                bind(node.target, Storage(value.outer | value.reachable, value.outer | value.reachable), entered)
            else:
                entered = visit(node.test, current)
            updated = _join_bindings(current, block(node.body, entered))
            if updated == current:
                # A literal-true while loop leaves only through a jump, so its else clause never runs.
                return updated if truth else block(node.orelse, updated)
            current = updated

    def block(statements: Sequence[ast.stmt], bindings: dict[str, Storage]) -> dict[str, Storage]:
        for statement in live_statements(statements):
            bindings = visit(statement, bindings)
        return bindings

    initial = {
        name: Storage(frozenset({Origin(id(callable_node), name)}), frozenset({Origin(id(callable_node), name)}))
        for name in parameters
    }
    for argument, kind in ((callable_node.args.vararg, "tuple"), (callable_node.args.kwarg, "dict")):
        if argument is not None:
            initial[argument.arg] = Storage(reachable=frozenset({Origin(id(callable_node), argument.arg)}), kinds=frozenset({kind}))
    if isinstance(callable_node, ast.Lambda):
        visit(callable_node.body, initial)
    else:
        block(callable_node.body, initial)
    return Ownership(observations, external, copies)


def _join_bindings(left: dict[str, Storage], right: dict[str, Storage]) -> dict[str, Storage]:
    return {name: left.get(name, Storage()).join(right.get(name, Storage())) for name in left.keys() | right.keys()}
