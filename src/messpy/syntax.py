"""Shared syntax-tree queries for a module that stays unchanged during analysis."""

from __future__ import annotations

import ast
from functools import lru_cache

__all__ = ["module_nodes", "parent_map", "dotted_name", "root_name", "stored_names", "comprehension_masks"]


@lru_cache(maxsize=2)
def module_nodes(tree: ast.Module) -> tuple[ast.AST, ...]:
    """Return nodes in ``ast.walk`` order, retaining at most two module trees."""
    return tuple(ast.walk(tree))


@lru_cache(maxsize=2)
def parent_map(tree: ast.Module) -> dict[int, ast.AST]:
    """Return shared, read-only parent links keyed by child identity."""
    return {id(child): parent for parent in module_nodes(tree) for child in ast.iter_child_nodes(parent)}


def dotted_name(node: ast.expr) -> str:
    """Return a name and its attributes, or an empty string for other expressions."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else ""
    return ""


def root_name(node: ast.AST) -> str:
    """Return the name beneath attributes and subscripts, or an empty string."""
    current = node
    while isinstance(current, (ast.Attribute, ast.Subscript)):
        current = current.value
    return current.id if isinstance(current, ast.Name) else ""


def stored_names(node: ast.AST) -> list[str]:
    """Return names in an assignment target, including starred and unpacked targets."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Starred):
        return stored_names(node.value)
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for element in node.elts for name in stored_names(element)]
    return []


@lru_cache(maxsize=2)
def comprehension_masks(tree: ast.Module) -> dict[int, frozenset[str]]:
    """Return shared, read-only masks for names, attributes, and calls.

    Targets apply through lambdas but not definitions, and never to the
    outermost iterable, which is evaluated in the enclosing scope.
    """
    masks: dict[int, frozenset[str]] = {}
    pending: list[tuple[ast.AST, frozenset[str]]] = [(tree, frozenset())]
    while pending:
        node, masked = pending.pop()
        if masked and isinstance(node, (ast.Name, ast.Attribute, ast.Call)):
            masks[id(node)] = masked
        pending.extend(_masked_children(node, masked))
    return masks


def _masked_children(node: ast.AST, masked: frozenset[str]) -> list[tuple[ast.AST, frozenset[str]]]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [(child, frozenset()) for child in ast.iter_child_nodes(node)]
    if not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return [(child, masked) for child in ast.iter_child_nodes(node)]
    outer_iter = node.generators[0].iter
    targets = masked.union(*(stored_names(generator.target) for generator in node.generators))
    return [(child, masked if child is outer_iter else targets) for child in _comprehension_children(node)]


def _comprehension_children(node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> list[ast.AST]:
    children: list[ast.AST] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.comprehension):
            children.extend(ast.iter_child_nodes(child))
        else:
            children.append(child)
    return children
