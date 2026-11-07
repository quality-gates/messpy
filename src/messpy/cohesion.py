"""Class cohesion measurement over a shared parsed AST and call graph."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .callables import has_decorator, has_property_decorator, instance_receiver, is_contract_method, method_receiver
from .callgraph import CallGraph, _arguments
from .dependencies import ClassInfo


def measure_lcom4(class_info: ClassInfo, graph: CallGraph) -> int:
    """Count connected method components; inputs must share parsed AST nodes."""
    accessor_fields = _accessor_fields(class_info)
    methods = _method_relationships(class_info, accessor_fields, graph)
    active = _active_methods(methods)
    if not active:
        return 1
    return _relationship_component_count(methods, active)


def _method_relationships(
    class_info: ClassInfo, accessor_fields: dict[str, str], graph: CallGraph
) -> dict[str, _MethodRelationships]:
    methods: dict[str, _MethodRelationships] = {}
    for method in class_info.methods:
        if _excluded_from_cohesion(method, accessor_fields):
            continue
        receiver = instance_receiver(method)
        if receiver is None:
            continue
        fields: frozenset[str] = frozenset()
        for statement in method.body:
            fields = _method_fields(statement, receiver, accessor_fields, fields)
        methods[method.name] = _MethodRelationships(fields, _method_calls(class_info, method, accessor_fields, graph))
    return methods


def _method_calls(
    class_info: ClassInfo,
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    accessor_fields: dict[str, str],
    graph: CallGraph,
) -> frozenset[str]:
    return frozenset(
        site.callee.name
        for site in graph.callees(method)
        if graph.method_class(site.callee) is class_info.node and site.callee.name not in accessor_fields
    )


def _excluded_from_cohesion(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    accessor_fields: dict[str, str],
) -> bool:
    return (
        method.name.startswith("__")
        or has_property_decorator(method)
        or has_decorator(method, "staticmethod")
        or has_decorator(method, "classmethod")
        or is_contract_method(method)
        or has_decorator(method, "abstractmethod")
        or method.name in accessor_fields
    )


def _active_methods(methods: dict[str, _MethodRelationships]) -> set[str]:
    active = {
        name
        for name, relationships in methods.items()
        if relationships.fields or relationships.calls & methods.keys()
    }
    active.update(
        called
        for relationships in methods.values()
        for called in relationships.calls
        if called in methods
    )
    return active


def _relationship_component_count(
    methods: dict[str, _MethodRelationships], active: set[str]
) -> int:
    connected = {name: name for name in active}
    methods_by_field: dict[str, tuple[str, ...]] = {}
    for name in active:
        for field in methods[name].fields:
            methods_by_field[field] = (*methods_by_field.get(field, ()), name)
    for names in methods_by_field.values():
        first, *connected_names = names
        for name in connected_names:
            connected = _union_components(connected, first, name)
    names = sorted(active)
    for name in names:
        for called in methods[name].calls & active:
            connected = _union_components(connected, name, called)
    return len({_find_component(connected, name)[1] for name in active})


def _find_component(connected: dict[str, str], name: str) -> tuple[dict[str, str], str]:
    if connected[name] == name:
        return connected, name
    updated, root = _find_component(connected, connected[name])
    if updated[name] == root:
        return updated, root
    return {**updated, name: root}, root


def _union_components(connected: dict[str, str], left: str, right: str) -> dict[str, str]:
    connected, left_root = _find_component(connected, left)
    connected, right_root = _find_component(connected, right)
    if left_root == right_root:
        return connected
    return {**connected, left_root: right_root}


@dataclass(frozen=True)
class _MethodRelationships:
    fields: frozenset[str]
    calls: frozenset[str]


def _method_fields(
    node: ast.AST,
    receiver: str,
    accessor_fields: dict[str, str],
    fields: frozenset[str],
) -> frozenset[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return fields
    if isinstance(node, ast.Call) and _direct_receiver_attribute(node.func, receiver):
        return _receiver_call_fields(node, receiver, accessor_fields, fields)
    if _direct_receiver_attribute(node, receiver):
        return fields | {accessor_fields.get(node.attr, node.attr)}
    for child in ast.iter_child_nodes(node):
        fields = _method_fields(child, receiver, accessor_fields, fields)
    return fields


def _receiver_call_fields(
    node: ast.Call,
    receiver: str,
    accessor_fields: dict[str, str],
    fields: frozenset[str],
) -> frozenset[str]:
    attribute = node.func.attr
    if attribute in accessor_fields:
        fields = fields | {accessor_fields[attribute]}
    for argument in [*node.args, *node.keywords]:
        fields = _method_fields(_call_argument_value(argument), receiver, accessor_fields, fields)
    return fields


def _call_argument_value(argument: ast.expr | ast.keyword) -> ast.expr:
    if isinstance(argument, ast.keyword):
        return argument.value
    return argument


def _direct_receiver_attribute(node: ast.AST, receiver: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == receiver
    )


def _accessor_fields(class_info: ClassInfo) -> dict[str, str]:
    return {
        method.name: field
        for method in class_info.methods
        if (field := _trivial_accessor_field(method)) is not None
    }


def _trivial_accessor_field(method: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    if len(method.body) != 1:
        return None
    statement = method.body[0]
    target = _accessor_target(statement, method)
    # Keep class-state accessor classification unchanged.
    class_state = has_decorator(method, "classmethod") or method.name == "__new__"
    receiver = "self" if class_state else method_receiver(method)
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == receiver
    ):
        return target.attr
    return None


def _accessor_target(statement: ast.stmt, method: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    if isinstance(statement, ast.Return):
        return statement.value
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        return statement.targets[0] if _is_plain_accessor_value(statement.value, method) else None
    if isinstance(statement, ast.AnnAssign) and statement.value is not None:
        return statement.target if _is_plain_accessor_value(statement.value, method) else None
    return None


def _is_plain_accessor_value(value: ast.expr, method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    receiver = instance_receiver(method)
    return (
        isinstance(value, ast.Name)
        and value.id != receiver
        and value.id in {argument.arg for argument in _arguments(method.args)}
    )