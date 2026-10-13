"""Captured variable reads.

A closure reads a captured name when it runs, not when it is made. The read is a calculation only when
the binding is fixed and no other code can change the captured contents between two runs. This module
decides that from the live syntax of the scope that binds the name, including binders in nested
scopes that declare the name nonlocal.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .reachability import evaluated_children

if TYPE_CHECKING:
    from .analyzer import _ScopeChain

__all__ = ["captured_read_is_fixed", "write_only_receiver"]

_FUNCTION_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_WRITE_ONLY_METHODS = frozenset({"append", "extend", "insert", "add", "clear", "update", "discard"})
_ELEMENT_READERS = frozenset({
    "builtins.sum", "builtins.min", "builtins.max", "builtins.any", "builtins.all",
    "builtins.sorted", "builtins.list", "builtins.tuple", "builtins.set", "builtins.frozenset",
})
_CONTAINER_READERS = _ELEMENT_READERS | frozenset({
    "builtins.len", "builtins.dict", "builtins.iter", "builtins.next", "builtins.enumerate", "builtins.zip",
    "builtins.reversed", "builtins.map", "builtins.filter",
})
_IMMUTABLE, _FRESH_IMMUTABLE, _FRESH_SHARED, _SHARED = "immutable", "fresh immutable", "fresh shared", "shared"


@dataclass(frozen=True)
class _Capture:
    name: str
    scope: ast.AST
    value: str


def write_only_receiver(node: ast.Name, parents: dict[int, ast.AST]) -> bool:
    """True when the name only receives a write, for example CACHE.append(value) or CACHE[key] = value."""
    parent = parents.get(id(node))
    if isinstance(parent, (ast.Subscript, ast.Attribute)) and parent.value is node and isinstance(parent.ctx, ast.Store):
        return not isinstance(parents.get(id(parent)), ast.AugAssign)
    if not isinstance(parent, ast.Attribute) or parent.value is not node or parent.attr not in _WRITE_ONLY_METHODS:
        return False
    call = parents.get(id(parent))
    return isinstance(call, ast.Call) and call.func is parent and isinstance(parents.get(id(call)), ast.Expr)


def captured_read_is_fixed(node: ast.Name, scope: ast.AST, chain: _ScopeChain) -> bool:
    """True when a closure read of a name that an enclosing function binds is a calculation."""
    parents = chain.parents or {}
    if _invoked_at_definition(chain.callable_node, scope, parents):
        return True
    value = _fixed_value(node.id, scope, list(_binders(node.id, scope, chain)), node, parents)
    if value is None:
        return False
    if _use(node, parents) in {"identity", "arithmetic"} or value == _IMMUTABLE:
        return True
    return _fixed_contents(node, _Capture(node.id, scope, value), chain)


def _fixed_contents(node: ast.Name, capture: _Capture, chain: _ScopeChain) -> bool:
    others = [other for other in _occurrences(node.id, capture.scope, chain) if other is not node]
    if capture.value == _SHARED:
        return not _container_use(node, chain) and not any(_mutating_use(other, chain.parents or {}) for other in others)
    return _safe_read(node, capture, chain) and all(_safe_read(other, capture, chain) for other in others)


def _container_use(node: ast.Name, chain: _ScopeChain) -> bool:
    parent = (chain.parents or {}).get(id(node))
    if isinstance(parent, (ast.Subscript, ast.Attribute, ast.Starred)):
        return parent.value is node
    if isinstance(parent, ast.Compare):
        return node in parent.comparators and any(isinstance(op, (ast.In, ast.NotIn)) for op in parent.ops)
    if isinstance(parent, (ast.For, ast.AsyncFor, ast.comprehension)):
        return parent.iter is node
    return _container_transfer(node, parent, chain)


def _container_transfer(node: ast.Name, parent: ast.AST | None, chain: _ScopeChain) -> bool:
    if isinstance(parent, ast.YieldFrom):
        return True
    if isinstance(parent, ast.keyword) and parent.arg is None:
        return True
    call = _argument_call(node, chain.parents or {})
    if call is None:
        return False
    if chain.qualified_name(call.func) in _CONTAINER_READERS:
        return True
    helper = _helper_parameter(node, chain)
    if helper is None:
        return False
    parameter, scope = helper
    local = replace(chain, scopes=(scope, *chain.scopes), callable_node=scope)
    return any(_container_use(read, local) for read in _occurrences(parameter, scope, local))


def _mutating_use(node: ast.Name, parents) -> bool:
    from .analyzer import MUTATOR_METHOD_NAMES

    parent = parents.get(id(node))
    if not isinstance(parent, (ast.Subscript, ast.Attribute)) or parent.value is not node:
        return False
    return isinstance(parent.ctx, (ast.Store, ast.Del)) or isinstance(parent, ast.Attribute) and parent.attr in MUTATOR_METHOD_NAMES


def _invoked_at_definition(closure: ast.AST | None, scope: ast.AST, parents) -> bool:
    # A lambda that is called where it is made, for example (lambda: total)(), reads the name at that point.
    call = parents.get(id(closure))
    if not isinstance(closure, ast.Lambda) or not isinstance(call, ast.Call) or call.func is not closure:
        return False
    current = call
    while id(current) in parents and not isinstance(current, _NESTED_SCOPES):
        current = parents[id(current)]
    return current is scope


def _fixed_value(name: str, scope: ast.AST, binders: list[ast.AST], read: ast.AST, parents) -> str | None:
    if name in {argument.arg for argument in _parameters(scope)}:
        return _SHARED if not binders else None
    if len(binders) != 1 or not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    statement = _fixed_assignment(binders[0], scope, parents)
    if statement is None:
        return None
    reader = _top_statement(read, scope, parents)
    if reader is None or scope.body.index(statement) >= scope.body.index(reader):
        return None
    return _value_class(statement.value)


def _fixed_assignment(binder: ast.AST, scope: ast.FunctionDef | ast.AsyncFunctionDef, parents):
    statement = _top_statement(binder, scope, parents)
    if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or statement.value is None:
        return None
    return statement if any(target is binder for target in _assigned_names(statement)) else None


def _assigned_names(statement: ast.Assign | ast.AnnAssign) -> list[ast.AST]:
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    return [target for target in targets if isinstance(target, ast.Name)]


def _top_statement(node: ast.AST, scope: ast.FunctionDef | ast.AsyncFunctionDef, parents) -> ast.AST | None:
    current = node
    while id(current) in parents:
        parent = parents[id(current)]
        if parent is scope:
            return current if current in scope.body else None
        current = parent
    return None


def _value_class(value: ast.expr) -> str:
    if isinstance(value, (ast.Constant, ast.JoinedStr, ast.Compare)):
        return _IMMUTABLE
    if isinstance(value, ast.Tuple):
        return _IMMUTABLE if all(_value_class(item) == _IMMUTABLE for item in value.elts) else _FRESH_SHARED
    if isinstance(value, (ast.BinOp, ast.UnaryOp)):
        operands = [value.left, value.right] if isinstance(value, ast.BinOp) else [value.operand]
        return _SHARED if any(_display(operand) for operand in operands) else _IMMUTABLE
    return _container_class(value)


def _container_class(value: ast.expr) -> str:
    if isinstance(value, (ast.List, ast.Set)):
        return _fresh_class(value.elts)
    if isinstance(value, ast.Dict):
        return _fresh_class([*(key for key in value.keys if key is not None), *value.values], all(value.keys))
    return _SHARED


def _display(expression: ast.expr) -> bool:
    return isinstance(expression, (ast.List, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp))


def _fresh_class(elements: list[ast.expr], complete: bool = True) -> str:
    immutable = complete and all(_value_class(item) == _IMMUTABLE for item in elements)
    return _FRESH_IMMUTABLE if immutable else _FRESH_SHARED


def _use(node: ast.expr, parents) -> str:
    parent = parents.get(id(node))
    if isinstance(parent, ast.Return):
        return "identity"
    if isinstance(parent, ast.Lambda) and parent.body is node:
        return "identity"
    if isinstance(parent, ast.Compare):
        return _comparison_use(parent)
    if isinstance(parent, ast.BinOp) or isinstance(parent, ast.UnaryOp) and not isinstance(parent.op, ast.Not):
        return "arithmetic"
    return "contents"


def _comparison_use(parent: ast.Compare) -> str:
    if all(isinstance(op, (ast.Is, ast.IsNot)) for op in parent.ops):
        return "identity"
    return "contents" if any(isinstance(op, (ast.In, ast.NotIn)) for op in parent.ops) else "arithmetic"


def _safe_read(node: ast.Name, capture: _Capture, chain: _ScopeChain) -> bool:
    parents = chain.parents or {}
    parent = parents.get(id(node))
    immutable = capture.value == _FRESH_IMMUTABLE
    if isinstance(parent, ast.Subscript):
        return _private_element_read(node, parent, immutable, parents)
    if isinstance(parent, ast.Compare):
        return len(parent.ops) == 1 and parent.comparators[0] is node and isinstance(parent.ops[0], (ast.In, ast.NotIn))
    if _argument_call(node, parents) is not None:
        return _private_call_read(node, capture, chain)
    return immutable and isinstance(parent, (ast.For, ast.comprehension)) and parent.iter is node


def _private_element_read(node: ast.Name, parent: ast.Subscript, immutable: bool, parents) -> bool:
    if parent.value is not node or not isinstance(parent.ctx, ast.Load) or isinstance(parent.slice, ast.Slice):
        return False
    return immutable or _use(parent, parents) != "contents"


def _private_call_read(node: ast.Name, capture: _Capture, chain: _ScopeChain) -> bool:
    call = _argument_call(node, chain.parents or {})
    qualified = chain.qualified_name(call.func)
    if call.args == [node] and not call.keywords:
        if qualified == "builtins.len" or capture.value == _FRESH_IMMUTABLE and qualified in _ELEMENT_READERS:
            return True
    helper = _helper_parameter(node, chain)
    if helper is None:
        return False
    parameter, scope = helper
    local = replace(chain, scopes=(scope, *chain.scopes), callable_node=scope)
    return all(_safe_read(read, capture, local) for read in _occurrences(parameter, scope, local))


def _helper_parameter(node: ast.Name, chain: _ScopeChain) -> tuple[str, ast.AST] | None:
    call = _argument_call(node, chain.parents or {})
    if call is None or chain.graph is None or chain.callable_node is None:
        return None
    site = chain.graph.call_site(chain.callable_node, call)
    if site is None or site.callee in chain.scopes or not isinstance(site.callee, _FUNCTION_SCOPES):
        return None
    return _parameter_for_value(node, call, site.callee)


def _parameter_for_value(node: ast.Name, call: ast.Call, target) -> tuple[str, ast.AST] | None:
    parameters = [*target.args.posonlyargs, *target.args.args]
    arguments = {parameter.arg: value for parameter, value in zip(parameters, call.args)}
    arguments.update((keyword.arg, keyword.value) for keyword in call.keywords if keyword.arg is not None)
    return next(((name, target) for name, value in arguments.items() if value is node), None)


def _argument_call(node: ast.Name, parents) -> ast.Call | None:
    parent = parents.get(id(node))
    if isinstance(parent, ast.keyword):
        parent = parents.get(id(parent))
    if not isinstance(parent, ast.Call):
        return None
    return parent if node in parent.args or any(keyword.value is node for keyword in parent.keywords) else None


def _binders(name: str, scope: ast.AST, chain: _ScopeChain) -> Iterator[ast.AST]:
    for node in _scope_nodes(name, scope, chain):
        if _binds(node, name):
            yield node


def _occurrences(name: str, scope: ast.AST, chain: _ScopeChain) -> Iterator[ast.Name]:
    for node in _scope_nodes(name, scope, chain):
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
            yield node


def _binds(node: ast.AST, name: str) -> bool:
    if isinstance(node, ast.Name):
        return node.id == name and isinstance(node.ctx, (ast.Store, ast.Del))
    if isinstance(node, ast.ExceptHandler) or isinstance(node, (ast.MatchAs, ast.MatchStar)):
        return node.name == name
    if isinstance(node, ast.MatchMapping):
        return node.rest == name
    if isinstance(node, ast.alias):
        return (node.asname or node.name.partition(".")[0]) == name
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name == name
    return False


def _scope_nodes(name: str, scope: ast.AST, chain: _ScopeChain) -> Iterator[ast.AST]:
    # A nested scope that binds the name without a nonlocal declaration has its own variable.
    pending = list(evaluated_children(scope))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, _NESTED_SCOPES) and _binds_locally(node, name, chain):
            pending.extend(_definition_time_nodes(node))
            continue
        pending.extend(evaluated_children(node))


def _binds_locally(node: ast.AST, name: str, chain: _ScopeChain) -> bool:
    record = chain.name_scopes.get(id(node))
    if record is None:
        return False
    if name in record.nonlocal_names:
        return False
    return name in record.global_names or name in record.variables or name in record.definitions


def _definition_time_nodes(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *node.keywords]
    arguments = node.args
    defaults = [*arguments.defaults, *(item for item in arguments.kw_defaults if item is not None)]
    decorators = [] if isinstance(node, ast.Lambda) else node.decorator_list
    return [*decorators, *defaults]


def _parameters(scope: ast.AST) -> list[ast.arg]:
    if not isinstance(scope, _FUNCTION_SCOPES):
        return []
    arguments = scope.args
    packed = [item for item in (arguments.vararg, arguments.kwarg) if item is not None]
    return [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *packed]
