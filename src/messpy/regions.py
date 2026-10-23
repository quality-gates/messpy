"""Shared evaluated and lexical regions for callable analysis."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from functools import lru_cache
import importlib.util

from .reachability import evaluated_children, live_statements

CallableSyntax = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.Module | ast.GeneratorExp


def annotations_are_deferred(tree: ast.AST | None) -> bool:
    # annotationlib ships with the Python release that defers annotations.
    if importlib.util.find_spec("annotationlib") is not None:
        return True
    if not isinstance(tree, ast.Module):
        return False
    return any(
        isinstance(statement, ast.ImportFrom)
        and statement.module == "__future__"
        and any(alias.name == "annotations" for alias in statement.names)
        for statement in tree.body
    )


def _signature_annotations(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    annotations = [
        argument.annotation
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        if argument.annotation is not None
    ]
    if node.args.vararg is not None and node.args.vararg.annotation is not None:
        annotations.append(node.args.vararg.annotation)
    if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
        annotations.append(node.args.kwarg.annotation)
    if node.returns is not None:
        annotations.append(node.returns)
    return annotations


@lru_cache(maxsize=128)
def evaluated_nodes(node: CallableSyntax, deferred: bool = False) -> tuple[ast.AST, ...]:
    """Evaluated syntax, cached with bounded retention for synthetic execution owners too."""
    if isinstance(node, ast.GeneratorExp):
        generators = [node.generators[0].target, *node.generators[0].ifs, *node.generators[1:]]
        return tuple(_evaluated_present([*generators, node.elt], deferred))
    roots = [node.body] if isinstance(node, ast.Lambda) else live_statements(node.body)
    return tuple(_evaluated_present(roots, deferred))


def _evaluated_node_list(node: ast.AST, deferred: bool) -> list[ast.AST]:
    if isinstance(node, ast.AnnAssign):
        return [node, *_evaluated_present([node.target, node.value], deferred)]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        evaluated = [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults]
        if not deferred:
            evaluated.extend(_signature_annotations(node))
        return [node, *_evaluated_present(evaluated, deferred)]
    if isinstance(node, ast.Lambda):
        return _evaluated_present([*node.args.defaults, *node.args.kw_defaults], deferred)
    if isinstance(node, ast.GeneratorExp):
        return [node, *_evaluated_node_list(node.generators[0].iter, deferred)]
    if isinstance(node, ast.ClassDef):
        return [node, *_evaluated_present([*node.decorator_list, *node.bases, *node.keywords, *live_statements(node.body)], deferred)]
    found = [node]
    for child in evaluated_children(node):
        found.extend(_evaluated_node_list(child, deferred))
    return found


def _evaluated_present(nodes: Sequence[ast.AST | None], deferred: bool) -> list[ast.AST]:
    found: list[ast.AST] = []
    for node in nodes:
        if node is not None:
            found.extend(_evaluated_node_list(node, deferred))
    return found


@lru_cache(maxsize=128)
def lexical_nodes(node: CallableSyntax) -> tuple[ast.AST, ...]:
    """Syntax in the body, excluding nested definitions, without reachability pruning.

    ElseExpression examines even dead branches in this body's control flow.
    Symtable corrections must not count class-local reads as enclosing-local uses.
    Definition-time expressions belong to evaluated_nodes, not this region.
    """
    roots = [node.body] if isinstance(node, ast.Lambda) else node.body
    return tuple(child for root in roots for child in _lexical_node_list(root))


def _lexical_node_list(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
        return []
    found = [node]
    for child in ast.iter_child_nodes(node):
        found.extend(_lexical_node_list(child))
    return found
