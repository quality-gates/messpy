from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass

from .callgraph import CallGraph, _dotted_name, _module_nodes
from .execution import effect_site
from .ownership import Ownership


@dataclass(frozen=True)
class Protocols:
    methods: frozenset[str]
    properties: frozenset[str]
    overrides: frozenset[tuple[str, str]]

    @classmethod
    def collect(cls, tree: ast.Module) -> Protocols:
        classes = [node for node in _module_nodes(tree) if isinstance(node, ast.ClassDef)]
        methods = _class_methods(classes)
        properties = frozenset(node.name for _, node in methods if _property(node))
        overrides = frozenset((ancestor, node.name) for owner, node in methods for ancestor in _ancestors(owner, classes, frozenset()))
        return cls(frozenset(node.name for _, node in methods), properties, overrides)


def _class_methods(classes: Sequence[ast.ClassDef]):
    return [(owner, node) for owner in classes for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _property(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_dotted_name(decorator).split(".")[-1] == "property" for decorator in node.decorator_list)


def _ancestors(owner: ast.ClassDef, classes: Sequence[ast.ClassDef], visited: frozenset[str]) -> frozenset[str]:
    direct = frozenset(_dotted_name(base) for base in owner.bases) - visited
    parents = [node for node in classes if node.name in direct]
    return direct | frozenset(ancestor for parent in parents for ancestor in _ancestors(parent, classes, visited | direct))


def uncertainties(nodes: Sequence[ast.AST], ownership: Ownership, qualified, graph: CallGraph, protocols: Protocols) -> tuple[tuple[str, ast.AST], ...]:
    found = []
    for node in nodes:
        if _descriptor(node, ownership, protocols):
            found.append((f"descriptor {node.attr}", node))
        if _protocol(node, ownership, qualified, protocols):
            found.append(("user-defined protocol", effect_site(node)))
        if _context_manager(node, qualified):
            found.append(("context manager", node))
        if _virtual(node, graph, protocols):
            found.append(("virtual method dispatch", node))
    return tuple(found)


def _ordinary(value: ast.expr, node: ast.AST, ownership: Ownership) -> bool:
    storage = ownership.value(value, node)
    return not storage.opaque and bool(storage.kinds) and "unknown" not in storage.kinds


def _descriptor(node: ast.AST, ownership: Ownership, protocols: Protocols) -> bool:
    return isinstance(node, ast.Attribute) and node.attr in protocols.properties and not _ordinary(node.value, node, ownership)


def _protocol(node: ast.AST, ownership: Ownership, qualified, protocols: Protocols) -> bool:
    methods, values = _dispatch(node, qualified)
    return bool(methods & protocols.methods) and any(not _ordinary(value, node, ownership) for value in values)


def _dispatch(node: ast.AST, qualified) -> tuple[frozenset[str], tuple[ast.expr, ...]]:
    if isinstance(node, ast.Subscript):
        return frozenset({"__getitem__", "__setitem__", "__delitem__"}), (node.value,)
    if isinstance(node, (ast.BinOp, ast.AugAssign)):
        operands = (node.left, node.right) if isinstance(node, ast.BinOp) else (node.target, node.value)
        return _operator_methods(node.op), operands
    if isinstance(node, ast.UnaryOp):
        return _operator_methods(node.op), (node.operand,)
    if isinstance(node, ast.Compare):
        return frozenset({"__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__", "__contains__"}), (node.left, *node.comparators)
    if isinstance(node, ast.FormattedValue):
        return frozenset({"__str__", "__repr__", "__format__"}), (node.value,)
    return _iteration_dispatch(node, qualified)


def _operator_methods(operator: ast.AST) -> frozenset[str]:
    names = {
        ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "truediv", ast.FloorDiv: "floordiv",
        ast.Mod: "mod", ast.Pow: "pow", ast.MatMult: "matmul", ast.BitAnd: "and", ast.BitOr: "or",
        ast.BitXor: "xor", ast.LShift: "lshift", ast.RShift: "rshift", ast.UAdd: "pos", ast.USub: "neg", ast.Invert: "invert", ast.Not: "bool",
    }
    name = names.get(type(operator))
    return frozenset({f"__{name}__", f"__r{name}__", f"__i{name}__"}) if name else frozenset()


def _iteration_dispatch(node: ast.AST, qualified) -> tuple[frozenset[str], tuple[ast.expr, ...]]:
    if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        return frozenset({"__iter__", "__next__", "__aiter__", "__anext__"}), (node.iter,)
    if isinstance(node, (ast.YieldFrom, ast.Starred)):
        return frozenset({"__iter__", "__next__"}), (node.value,)
    if isinstance(node, ast.Call):
        name = qualified(node.func)
        if name in {"builtins.str", "builtins.repr", "builtins.format"}:
            return frozenset({"__str__", "__repr__", "__format__"}), tuple(node.args[:1])
        if name in {"builtins.all", "builtins.any", "builtins.dict", "builtins.frozenset", "builtins.iter", "builtins.list", "builtins.max", "builtins.min", "builtins.next", "builtins.set", "builtins.sorted", "builtins.sum", "builtins.tuple"}:
            return frozenset({"__iter__", "__next__"}), tuple(node.args[:1])
    return frozenset(), ()


def _context_manager(node: ast.AST, qualified) -> bool:
    if not isinstance(node, (ast.With, ast.AsyncWith)):
        return False
    return any(not isinstance(item.context_expr, ast.Call) or qualified(item.context_expr.func) not in {"builtins.open", "io.open"} for item in node.items)


def _virtual(node: ast.AST, graph: CallGraph, protocols: Protocols) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    target = graph.resolve_target(node)
    owner = graph.method_class(target) if target is not None else None
    return owner is not None and (owner.name, node.func.attr) in protocols.overrides
