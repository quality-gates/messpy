"""The callables of one module.

One place answers "what callables does this module define?" for every rule:
each function, method and lambda with its kind, the class that owns it, and the
scopes that enclose it.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache

__all__ = ["CallableNode", "module_callables"]

_CALLABLE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


@dataclass(frozen=True)
class CallableNode:
    """One function, method or lambda.

    A def in a class body, including one inside class-body control flow, is a
    method owned by that class. Every other def is a function, and a lambda has
    no owner. The enclosing scopes run from the innermost function or lambda
    that holds the node out to the module.
    """

    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    name: str
    kind: str
    owner: ast.ClassDef | None
    enclosing: tuple[ast.AST, ...]

    @property
    def owner_name(self) -> str | None:
        return self.owner.name if self.owner is not None else None

    @property
    def context(self) -> str:
        return f"{self.owner_name}.{self.name}" if self.owner_name else self.name

    @property
    def parameter_count(self) -> int:
        arguments = self.node.args
        return (
            len(arguments.posonlyargs)
            + len(arguments.args)
            + len(arguments.kwonlyargs)
            + int(arguments.vararg is not None)
            + int(arguments.kwarg is not None)
        )


@lru_cache(maxsize=1)
def module_callables(tree: ast.Module) -> tuple[CallableNode, ...]:
    """Every callable in the module in pre-order, the order symtable lists their tables in."""
    found: list[CallableNode] = []
    pending: list[tuple[ast.AST, ast.AST | None, tuple[ast.AST, ...]]] = [(tree, None, (tree,))]
    while pending:
        node, scope, enclosing = pending.pop()
        if isinstance(node, _CALLABLE_TYPES):
            found.append(_callable_node(node, scope, enclosing))
            enclosing = (node, *enclosing)
        if isinstance(node, (ast.ClassDef, *_CALLABLE_TYPES)):
            scope = node
        pending.extend((child, scope, enclosing) for child in reversed(list(ast.iter_child_nodes(node))))
    return tuple(found)


def _callable_node(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    scope: ast.AST | None,
    enclosing: tuple[ast.AST, ...],
) -> CallableNode:
    if isinstance(node, ast.Lambda):
        return CallableNode(node, "<lambda>", "lambda", None, enclosing)
    if isinstance(scope, ast.ClassDef):
        return CallableNode(node, node.name, "method", scope, enclosing)
    return CallableNode(node, node.name, "function", None, enclosing)
