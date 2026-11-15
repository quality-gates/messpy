from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum, auto

from .regions import evaluated_nodes
from .ownership import Ownership, Storage


@dataclass(frozen=True)
class Execution:
    target: ast.AST
    creation: ast.Call
    site: ast.AST


class _DeferredStatus(Enum):
    ORDINARY = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class _DeferredCall:
    target: ast.AST
    creation: ast.Call


_DeferredValue = _DeferredStatus | _DeferredCall


def _deferred_assignment(previous: _DeferredValue, assigned: _DeferredValue, writes: int) -> _DeferredValue:
    if writes == 1:
        return assigned
    return _DeferredStatus.UNKNOWN if assigned is not _DeferredStatus.ORDINARY else previous


def effect_site(node: ast.AST) -> ast.AST:
    return node.iter if isinstance(node, ast.comprehension) else node


_ITERATORS = frozenset({
    "builtins.all", "builtins.any", "builtins.dict", "builtins.frozenset", "builtins.list",
    "builtins.max", "builtins.min", "builtins.next", "builtins.set", "builtins.sorted", "builtins.sum", "builtins.tuple",
})
_SCHEDULERS = frozenset({"asyncio.run", "asyncio.create_task", "asyncio.ensure_future"})
_TRUSTED_DECORATORS = frozenset({"builtins.staticmethod", "builtins.classmethod", "builtins.property"})


def cold_body(node: ast.AST) -> bool:
    if isinstance(node, (ast.AsyncFunctionDef, ast.GeneratorExp)):
        return True
    return isinstance(node, ast.FunctionDef) and any(isinstance(child, (ast.Yield, ast.YieldFrom)) for child in evaluated_nodes(node))


def executions(
    nodes: Sequence[ast.AST], resolve: Callable[[ast.Call], ast.AST | None], qualified: Callable[[ast.expr], str],
    ownership: Ownership,
) -> tuple[tuple[Execution, ...], tuple[ast.AST, ...]]:
    values = _deferred_bindings(nodes, resolve)
    found = []
    unknown = []
    for node in nodes:
        for value in _forced_values(node, qualified):
            deferred = _deferred_value(value, values, resolve)
            if isinstance(deferred, _DeferredCall):
                found.append(Execution(deferred.target, deferred.creation, effect_site(node)))
            elif isinstance(node, ast.Await) or deferred is _DeferredStatus.UNKNOWN and not _ordinary_iterable(ownership.value(value, node)):
                unknown.append(effect_site(node))
    return tuple(found), tuple(unknown)


def _ordinary_iterable(storage: Storage) -> bool:
    return not storage.opaque and bool(storage.kinds) and "unknown" not in storage.kinds


def _forced_values(node: ast.AST, qualified) -> tuple[ast.expr, ...]:
    if isinstance(node, (ast.Await, ast.YieldFrom)):
        return (node.value,)
    if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        return (node.iter,)
    if isinstance(node, ast.Call) and qualified(node.func) in _ITERATORS | _SCHEDULERS:
        return tuple(node.args[:1])
    return ()


def _deferred_bindings(nodes: Sequence[ast.AST], resolve) -> dict[str, _DeferredValue]:
    writes = Counter(node.id for node in nodes if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)))
    values: dict[str, _DeferredValue] = {}
    for node in nodes:
        pair = _assignment(node)
        if pair is not None:
            name, expression = pair
            previous = values.get(name, _DeferredStatus.ORDINARY)
            values[name] = _deferred_assignment(previous, _deferred_value(expression, values, resolve), writes[name])
    return values


def _assignment(node: ast.AST) -> tuple[str, ast.expr] | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id, node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return node.target.id, node.value
    return None


def _deferred_value(expression: ast.expr, values: dict[str, _DeferredValue], resolve) -> _DeferredValue:
    if isinstance(expression, ast.Name):
        return values.get(expression.id, _DeferredStatus.ORDINARY)
    if isinstance(expression, ast.GeneratorExp):
        call = ast.copy_location(ast.Call(func=expression, args=[], keywords=[]), expression)
        return _DeferredCall(expression, call)
    if isinstance(expression, ast.Call):
        return _deferred_call(expression, resolve(expression))
    return _DeferredStatus.ORDINARY


def _deferred_call(expression: ast.Call, target: ast.AST | None) -> _DeferredValue:
    if target is not None and cold_body(target):
        return _DeferredCall(target, expression)
    if isinstance(target, (ast.FunctionDef, ast.Lambda)):
        returned = [target.body] if isinstance(target, ast.Lambda) else [node.value for node in evaluated_nodes(target) if isinstance(node, ast.Return)]
        if len(returned) == 1 and isinstance(returned[0], ast.GeneratorExp):
            return _DeferredCall(returned[0], expression)
    return _DeferredStatus.ORDINARY


def decorator_calls(nodes: Sequence[ast.AST], qualified) -> tuple[ast.Call, ...]:
    calls = []
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                if qualified(decorator) not in _TRUSTED_DECORATORS:
                    calls.append(ast.copy_location(ast.Call(func=decorator, args=[ast.Name(node.name, ast.Load())], keywords=[]), decorator))
    return tuple(calls)


def key_calls(nodes: Sequence[ast.AST], qualified) -> tuple[tuple[ast.Call, ast.Call], ...]:
    calls = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        source = _key_source(node, qualified)
        if source is None:
            continue
        for keyword in node.keywords:
            if keyword.arg != "key" or isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                continue
            element = ast.Subscript(value=source, slice=ast.Constant(0), ctx=ast.Load())
            call = ast.copy_location(ast.Call(func=keyword.value, args=[element], keywords=[]), node)
            calls.append((node, call))
    return tuple(calls)


def _key_source(call: ast.Call, qualified) -> ast.expr | None:
    if qualified(call.func) in {"builtins.sorted", "builtins.min", "builtins.max"}:
        return call.args[0] if call.args else None
    if isinstance(call.func, ast.Attribute) and call.func.attr == "sort":
        return call.func.value
    return None


def transformed_callable(target: ast.AST, qualified) -> bool:
    decorators = getattr(target, "decorator_list", ())
    return any(qualified(decorator) not in _TRUSTED_DECORATORS for decorator in decorators)
