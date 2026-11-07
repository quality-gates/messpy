"""The callables of one module.

One place answers "what callables does this module define?" for every rule:
each function, method and lambda with its kind, the class that owns it, and the
scopes that enclose it.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from .regions import annotations_are_deferred, evaluated_nodes, lexical_nodes

__all__ = [
    "CallableNode", "has_decorator", "has_property_decorator", "instance_receiver",
    "is_contract_method", "method_receiver", "module_callables",
]

_CALLABLE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


@dataclass(frozen=True)
class CallableNode:
    """One function, method or lambda.

    A def in a class body, including one inside class-body control flow, is a
    method owned by that class. Every other def is a function, and a lambda has
    no owner. The enclosing scopes run from the innermost function or lambda
    that holds the node out to the module.
    """

    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.Module | ast.GeneratorExp
    name: str
    kind: str
    owner: ast.ClassDef | None
    enclosing: tuple[ast.AST, ...]

    def evaluated_nodes(self) -> tuple[ast.AST, ...]:
        """Nodes evaluated by this callable, in analysis traversal order.

        Include nested defaults, decorators, class bases, keywords and bodies.
        Exclude nested callable bodies and local annotations. Signature
        annotations follow the enclosing module's annotation policy.
        """
        module = self.enclosing[-1] if self.enclosing else self.node
        return evaluated_nodes(self.node, annotations_are_deferred(module))

    def lexical_nodes(self) -> tuple[ast.AST, ...]:
        """Body syntax for control-flow checks and local symtable corrections.

        Exclude nested definitions in full: class bodies have separate locals,
        and their control flow does not belong to the enclosing callable.
        Do not prune unreachable branches, which can contain misleading else clauses.
        """
        return lexical_nodes(self.node)

    @property
    def owner_name(self) -> str | None:
        return self.owner.name if self.owner is not None else None

    @property
    def context(self) -> str:
        return f"{self.owner_name}.{self.name}" if self.owner_name else self.name

    @property
    def receiver(self) -> str | None:
        """The parameter bound to the instance or class, if this is a method."""
        if self.owner is None or not isinstance(self.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return None
        return method_receiver(self.node)

    @property
    def parameter_count(self) -> int:
        if not isinstance(self.node, _CALLABLE_TYPES):
            return 0
        arguments = self.node.args
        return (
            len(arguments.posonlyargs)
            + len(arguments.args)
            + len(arguments.kwonlyargs)
            + int(arguments.vararg is not None)
            + int(arguments.kwarg is not None)
        )


def method_receiver(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Return the bound parameter of a known method, or None for a static method.

    Callers with an unclassified callable must use CallableNode.receiver.
    Receiver identity does not distinguish instance state from class state.
    """
    if any(
        (isinstance(decorator, ast.Name) and decorator.id == "staticmethod")
        or (isinstance(decorator, ast.Attribute) and decorator.attr == "staticmethod")
        for decorator in node.decorator_list
    ):
        return None
    positional = [*node.args.posonlyargs, *node.args.args]
    return positional[0].arg if positional else None


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


def instance_receiver(method: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Select state tracked by class rules from the shared receiver identity.

    Keep the existing class-state policy for classmethods and __new__:
    track self, and track cls only with an explicit classmethod decorator.
    Ordinary instance methods have no receiver-name restriction.
    """
    receiver = method_receiver(method)
    classmethod = has_decorator(method, "classmethod")
    if classmethod or method.name == "__new__":
        return receiver if receiver == "self" or (classmethod and receiver == "cls") else None
    return receiver


def is_contract_method(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    return has_decorator(method, "overload") or _is_stub_body(method.body)


def has_property_decorator(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return has_decorator(method, "property") or any(
        isinstance(decorator, ast.Attribute) and decorator.attr in {"getter", "setter", "deleter"}
        for decorator in method.decorator_list
    )


def has_decorator(method: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == name)
        or (isinstance(decorator, ast.Attribute) and decorator.attr == name)
        for decorator in method.decorator_list
    )


def _is_stub_body(statements: Sequence[ast.stmt]) -> bool:
    body = _body_without_docstring(statements)
    if not body:
        return True
    if all(isinstance(statement, ast.Pass) for statement in body):
        return True
    return len(body) == 1 and (_is_ellipsis_statement(body[0]) or (
        isinstance(body[0], ast.Raise) and _raises_not_implemented(body[0])
    ))


def _body_without_docstring(statements: Sequence[ast.stmt]) -> list[ast.stmt]:
    body = list(statements)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def _is_ellipsis_statement(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )


def _raises_not_implemented(statement: ast.Raise) -> bool:
    exception = statement.exc
    if isinstance(exception, ast.Name):
        return exception.id == "NotImplementedError"
    return isinstance(exception, ast.Call) and isinstance(exception.func, ast.Name) and exception.func.id == "NotImplementedError"
