"""Scope names whose value cannot change after their single binding.

A name is a constant when one live statement binds it, no other live code
binds or deletes it, and its value is immutable: a literal, a tuple, a
frozenset, a string, a compiled pattern, a read-only mapping, a class or a
function. A read of a constant is not an implicit input, because no code can
change what it reads.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from types import NoneType, EllipsisType

from .reachability import evaluated_children, live_statements

__all__ = ["scope_constants"]

_STATIC_TYPES = (str, bytes, int, float, complex, bool, NoneType, EllipsisType)
_NUMERIC = frozenset({"int", "float", "complex", "bool"})
_SAME_KIND_OPERANDS = frozenset({"str", "bytes", "tuple", "frozenset"}) | _NUMERIC
_CONTAINER_CALLS = frozenset({"builtins.frozenset", "builtins.tuple"})
_IMMUTABLE_BUILTINS = frozenset({"builtins.str", "builtins.bytes", "builtins.int", "builtins.float", "builtins.complex", "builtins.bool"})
_ITERABLE_KINDS = frozenset({"str", "bytes", "tuple", "frozenset"})
# These standard modules expose classes, functions and immutable values as attributes.
_IMMUTABLE_MODULES = frozenset({"abc", "ast", "collections.abc", "math", "numbers", "operator", "re", "string", "types", "typing"})
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def scope_constants(statements: Sequence[ast.AST], candidates: set[str]) -> dict[str, str]:
    """Map each candidate name that is a constant to the kind of its value."""
    live = list(_live_nodes(statements))
    writes = Counter(name for node in live for name in _written_names(node))
    imports = _imports(live)
    known = _fixed_definitions(statements, writes)
    for target, value in _assignments(statements):
        if target not in candidates or writes[target] != 1:
            continue
        known.update(_constant_assignment(target, value, known, imports, writes))
    return {name: kind for name, kind in known.items() if name in candidates}


def _fixed_definitions(statements, writes) -> dict[str, str]:
    return {name: "definition" for name in _definitions(statements) if writes[name] == 1}


def _constant_assignment(target, value, known, imports, writes) -> dict[str, str]:
    kind = _kind(value, known, imports, writes)
    return {target: kind} if kind else {}


def _live_nodes(statements: Sequence[ast.AST]) -> Iterator[ast.AST]:
    pending = list(reversed(live_statements(statements)))
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(evaluated_children(node)))


def _written_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return (node.id,)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return tuple(_binding(alias, node) for alias in node.names)
    return _pattern_names(node)


def _pattern_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
        return (node.name,) if node.name is not None else ()
    if isinstance(node, ast.MatchMapping):
        return (node.rest,) if node.rest is not None else ()
    return ()


def _binding(alias: ast.alias, node: ast.Import | ast.ImportFrom) -> str:
    if alias.asname:
        return alias.asname
    return alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name


def _imports(nodes: Sequence[ast.AST]) -> dict[str, str]:
    """Map each name that an import binds to the qualified name it refers to."""
    imports = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            imports.update((_binding(alias, node), alias.name if alias.asname else alias.name.split(".")[0]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            imports.update((_binding(alias, node), f"{node.module}.{alias.name}") for alias in node.names)
    return imports


def _definitions(statements: Sequence[ast.AST]) -> Iterator[str]:
    for statement in live_statements(statements):
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not statement.decorator_list:
            yield statement.name


def _assignments(statements: Sequence[ast.AST]) -> Iterator[tuple[str, ast.expr]]:
    """Each name and value that a live assignment of the scope binds, in source order."""
    for node in _scope_nodes(statements):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            yield from _pairs(node.targets[0], node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            yield from _pairs(node.target, node.value)


def _scope_nodes(statements: Sequence[ast.AST]) -> Iterator[ast.AST]:
    pending = list(reversed(live_statements(statements)))
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, _SCOPES):
            pending.extend(reversed(evaluated_children(node)))


def _pairs(target: ast.expr, value: ast.expr) -> Iterator[tuple[str, ast.expr]]:
    if isinstance(target, ast.Name):
        yield target.id, value
    elif isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple) and len(target.elts) == len(value.elts):
        if not any(isinstance(element, ast.Starred) for element in (*target.elts, *value.elts)):
            for inner_target, inner_value in zip(target.elts, value.elts):
                yield from _pairs(inner_target, inner_value)


def _kind(value: ast.expr, known: Mapping[str, str], imports: Mapping[str, str], writes: Counter[str]) -> str:
    """The kind of an immutable value, or an empty string when the value can change or is not known."""
    if isinstance(value, ast.Constant):
        return type(value.value).__name__ if isinstance(value.value, _STATIC_TYPES) else ""
    if isinstance(value, ast.Name):
        return known.get(value.id, "") or _definition_kind(value, imports, writes)
    if isinstance(value, ast.Attribute):
        return "definition" if _module_attribute(value, imports, writes) else ""
    return _constructed_kind(value, known, imports, writes)


def _definition_kind(value: ast.Name, imports, writes) -> str:
    name = _qualified(value, imports, writes)
    return "definition" if name in _IMMUTABLE_BUILTINS or name.rpartition(".")[0] in _IMMUTABLE_MODULES else ""


def _constructed_kind(value: ast.expr, known: Mapping[str, str], imports: Mapping[str, str], writes: Counter[str]) -> str:
    if isinstance(value, ast.Tuple):
        return "tuple" if all(_kind(element, known, imports, writes) for element in value.elts) else ""
    if isinstance(value, ast.JoinedStr):
        return "str" if all(_formatted_kind(part, known, imports, writes) for part in value.values) else ""
    return _operation_kind(value, known, imports, writes)


def _operation_kind(value: ast.expr, known: Mapping[str, str], imports: Mapping[str, str], writes: Counter[str]) -> str:
    if isinstance(value, ast.UnaryOp):
        return _unary_kind(value, _kind(value.operand, known, imports, writes))
    if isinstance(value, ast.BinOp):
        return _binary_kind(_kind(value.left, known, imports, writes), _kind(value.right, known, imports, writes))
    if isinstance(value, ast.Call):
        return _call_kind(value, known, imports, writes)
    return ""


def _formatted_kind(part: ast.expr, known: Mapping[str, str], imports: Mapping[str, str], writes: Counter[str]) -> bool:
    if isinstance(part, ast.Constant):
        return True
    if not isinstance(part, ast.FormattedValue) or part.format_spec is not None:
        return False
    return _kind(part.value, known, imports, writes) in {"str", "bytes"} | _NUMERIC


def _unary_kind(node: ast.UnaryOp, operand: str) -> str:
    if isinstance(node.op, ast.Not):
        return "bool" if operand in _NUMERIC | {"str", "bytes", "tuple", "frozenset"} else ""
    return operand if operand in _NUMERIC else ""


def _binary_kind(left: str, right: str) -> str:
    # Builtin immutable operands have no overloaded operators, so the result is a new immutable value.
    if left in _NUMERIC and right in _NUMERIC:
        return left if left == right else "float"
    return left if left == right and left in _SAME_KIND_OPERANDS else ""


def _call_kind(call: ast.Call, known: Mapping[str, str], imports: Mapping[str, str], writes: Counter[str]) -> str:
    name = _qualified(call.func, imports, writes)
    if call.keywords or any(isinstance(argument, ast.Starred) for argument in call.args):
        return ""
    if name in _CONTAINER_CALLS and len(call.args) <= 1:
        return _container_call_kind(call, name, known, imports, writes)
    return _standard_object_kind(call, name, known, imports, writes)


def _standard_object_kind(call, name, known, imports, writes) -> str:
    if name == "re.compile" and _pattern_arguments(call.args, imports, writes):
        return "pattern"
    if name == "types.MappingProxyType" and len(call.args) == 1:
        return "mapping" if _mapping_is_fixed(call.args[0], known, imports, writes) else ""
    return ""


def _container_call_kind(call, name, known, imports, writes) -> str:
    immutable = not call.args or _iterable_is_fixed(call.args[0], known, imports, writes)
    return name.removeprefix("builtins.") if immutable else ""


def _mapping_is_fixed(items: ast.expr, known: Mapping[str, str], imports: Mapping[str, str], writes: Counter[str]) -> bool:
    if not isinstance(items, ast.Dict) or None in items.keys:
        return False
    return all(_kind(item, known, imports, writes) for item in (*items.keys, *items.values))


def _iterable_is_fixed(node: ast.expr, known: Mapping[str, str], imports: Mapping[str, str], writes: Counter[str]) -> bool:
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return all(_kind(element, known, imports, writes) for element in node.elts)
    return _kind(node, known, imports, writes) in _ITERABLE_KINDS


def _pattern_arguments(arguments: Sequence[ast.expr], imports: Mapping[str, str], writes: Counter[str]) -> bool:
    if not arguments or len(arguments) > 2:
        return False
    pattern = arguments[0]
    if not isinstance(pattern, ast.Constant) or not isinstance(pattern.value, (str, bytes)):
        return False
    return len(arguments) == 1 or _flags(arguments[1], imports, writes)


def _flags(node: ast.expr, imports: Mapping[str, str], writes: Counter[str]) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _flags(node.left, imports, writes) and _flags(node.right, imports, writes)
    if isinstance(node, ast.Constant):
        return type(node.value) is int
    return isinstance(node, ast.Attribute) and _qualified(node, imports, writes).startswith("re.")


def _module_attribute(node: ast.Attribute, imports: Mapping[str, str], writes: Counter[str]) -> bool:
    qualified = _qualified(node, imports, writes)
    module = qualified.rpartition(".")[0]
    return module in _IMMUTABLE_MODULES


def _qualified(node: ast.expr, imports: Mapping[str, str], writes: Counter[str]) -> str:
    if isinstance(node, ast.Name):
        if node.id in imports:
            return imports[node.id] if writes[node.id] == 1 else ""
        return "" if writes[node.id] else f"builtins.{node.id}"
    if isinstance(node, ast.Attribute):
        base = _qualified(node.value, imports, writes)
        return f"{base}.{node.attr}" if base and not base.startswith("builtins.") else ""
    return ""
