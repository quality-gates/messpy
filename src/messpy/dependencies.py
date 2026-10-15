"""External type dependency extraction for Python classes.

Computes the set of external class and module dependencies referenced by a class
for the Coupling Between Objects (CBO) metric.
"""

from __future__ import annotations

import ast
import builtins
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from .callgraph import _arguments, _direct_bindings, _dotted_name
from .names import Names

__all__ = ["ClassInfo", "measure_class_dependencies"]


@dataclass(frozen=True)
class ClassInfo:
    """The structure and member definitions of one class."""

    node: ast.ClassDef
    name: str
    fields: tuple[str, ...] = ()
    methods: tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...] = ()
    is_ast_visitor: bool = False
    has_unresolved_base: bool = False


def measure_class_dependencies(
    class_info: ClassInfo,
    names: Names,
    module_names: AbstractSet[str] = frozenset(),
) -> frozenset[str]:
    """Extract the set of external class and module dependencies referenced by a class."""
    local_names = {
        class_info.name,
        *module_names,
        *class_info.fields,
        *(method.name for method in class_info.methods),
    }
    dependencies: set[str] = set()
    header = [
        *class_info.node.bases,
        *(keyword.value for keyword in class_info.node.keywords),
        *class_info.node.decorator_list,
    ]
    for expression in header:
        dependencies = _dependency_state(expression, names, class_info.node, local_names, dependencies)
    for statement in class_info.node.body:
        if not isinstance(statement, ast.ClassDef):
            dependencies = _dependency_state(statement, names, class_info.node, local_names, dependencies)
    if class_info.is_ast_visitor:
        dependencies = {dependency for dependency in dependencies if not dependency.startswith("ast.")}
    return frozenset(dependencies)



def _dependency_state(
    node: ast.AST,
    names: Names,
    scope: ast.AST,
    local_names: set[str],
    dependencies: set[str],
) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _dependency_function(node, names, scope, local_names, dependencies)
    if isinstance(node, ast.ClassDef):
        return dependencies
    if isinstance(node, (ast.AnnAssign, ast.arg)):
        return _dependency_annotation_state(node, names, scope, local_names, dependencies)
    referenced = _dependency_reference(node, names, scope, local_names, dependencies)
    if referenced is not None:
        return referenced
    return _dependency_children(node, names, scope, local_names, dependencies)


def _dependency_annotation_state(
    node: ast.AnnAssign | ast.arg,
    names: Names,
    scope: ast.AST,
    local_names: set[str],
    dependencies: set[str],
) -> set[str]:
    if isinstance(node, ast.arg):
        return _dependency_annotation(node.annotation, names, scope, local_names, dependencies)
    dependencies = _dependency_annotation(node.annotation, names, scope, local_names, dependencies)
    if node.value is None:
        return dependencies
    return _dependency_state(node.value, names, scope, local_names, dependencies)


def _dependency_reference(
    node: ast.AST,
    names: Names,
    scope: ast.AST,
    local_names: set[str],
    dependencies: set[str],
) -> set[str] | None:
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load):
            return _with_dependency(node, names, scope, local_names, dependencies)
        return dependencies
    if isinstance(node, ast.Attribute) and _dotted_name(node):
        return _with_dependency(node, names, scope, local_names, dependencies)
    return None


def _dependency_children(
    node: ast.AST,
    names: Names,
    scope: ast.AST,
    local_names: set[str],
    dependencies: set[str],
) -> set[str]:
    for child in ast.iter_child_nodes(node):
        dependencies = _dependency_state(child, names, scope, local_names, dependencies)
    return dependencies


def _dependency_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    names: Names,
    scope: ast.AST,
    local_names: set[str],
    dependencies: set[str],
) -> set[str]:
    scope_names = {*(argument.arg for argument in _arguments(node.args)), *_direct_bindings(node)}
    scope_names -= _function_import_names(node)
    inner_names = local_names | scope_names
    for decorator in node.decorator_list:
        dependencies = _dependency_state(decorator, names, scope, inner_names, dependencies)
    for argument in _arguments(node.args):
        dependencies = _dependency_state(argument, names, scope, inner_names, dependencies)
    for default in [*node.args.defaults, *node.args.kw_defaults]:
        if default is not None:
            dependencies = _dependency_state(default, names, scope, inner_names, dependencies)
    dependencies = _dependency_annotation(node.returns, names, scope, inner_names, dependencies)
    for statement in node.body:
        dependencies = _dependency_state(statement, names, node, inner_names, dependencies)
    return dependencies


def _function_import_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    found: set[str] = set()
    for statement in node.body:
        found.update(_import_names_under(statement))
    return found


def _import_names_under(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return set()
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {alias.asname or alias.name.split(".", 1)[0] for alias in node.names}
    found: set[str] = set()
    for child in ast.iter_child_nodes(node):
        found.update(_import_names_under(child))
    return found


def _dependency_annotation(
    annotation: ast.expr | None,
    names: Names,
    scope: ast.AST,
    local_names: set[str],
    dependencies: set[str],
) -> set[str]:
    expression = _annotation_expression(annotation)
    if expression is None:
        return dependencies
    return _dependency_state(expression, names, scope, local_names, dependencies)


def _with_dependency(
    node: ast.expr,
    names: Names,
    scope: ast.AST,
    local_names: set[str],
    dependencies: set[str],
) -> set[str]:
    dependency = _dependency_name(node, names, scope, local_names)
    if not dependency or dependency.startswith(("typing.", "collections.abc.", "builtins.")):
        return dependencies
    return {*dependencies, dependency}


def _dependency_name(
    node: ast.expr,
    names: Names,
    scope: ast.AST,
    local_names: set[str],
) -> str:
    dotted = _dotted_name(node)
    if not dotted:
        return ""
    root, *tail = dotted.split(".")
    if root in dir(builtins) or root == "typing":
        return ""
    imported = names.imported(node, scope=scope)
    if imported is not None:
        return _imported_dependency(imported, tail)
    if root in local_names:
        return ""
    return _spelling_dependency(root, tail)


def _imported_dependency(imported: tuple[str, bool], tail: list[str]) -> str:
    canonical, is_symbol = imported
    if is_symbol:
        return canonical
    return ".".join([canonical, *tail[:1]])


def _spelling_dependency(root: str, tail: list[str]) -> str:
    if tail:
        return ".".join([root, *tail[:1]])
    if root[:1].isupper():
        return root
    return ""


def _annotation_expression(annotation: ast.expr | None) -> ast.expr | None:
    if not isinstance(annotation, ast.Constant) or not isinstance(annotation.value, str):
        return annotation
    try:
        return ast.parse(annotation.value, mode="eval").body
    except (SyntaxError, RecursionError):
        # Ignore string annotations that are not valid Python expressions.
        return None
