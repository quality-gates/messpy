"""Qualified names for one module.

One resolver answers "what imported thing does this name refer to?" for every
rule. It follows lexical scopes, global and nonlocal declarations, rebinding,
comprehension targets, and relative imports. It does not look in other files.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Names"]

_FUNCTION = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_MaskedNode = tuple[ast.AST, frozenset[str], bool]


@dataclass(frozen=True)
class _ImportBinding:
    canonical: str
    symbol: bool


@dataclass(frozen=True)
class _ScopeRecord:
    imports: dict[str, _ImportBinding]
    bound: frozenset[str]
    global_names: frozenset[str]
    nonlocal_names: frozenset[str]


@dataclass(frozen=True)
class Names:
    """The imported names of one module.

    ``qualified`` returns the canonical name, or ``""`` when the name is local,
    rebound, or hidden. An unbound name is ``builtins.<name>``. ``module_of``
    returns the absolute module of an ``import from``, or ``""`` when the
    package cannot be determined.
    """

    _tree: ast.Module
    _package: tuple[str, ...] | None
    _parents: dict[int, ast.AST]
    _records: dict[int, _ScopeRecord]
    _masks: dict[int, frozenset[str]]

    @classmethod
    def build(cls, tree: ast.Module, *, module: tuple[str, ...] | None, path: Path) -> Names:
        package = _package(module, path)
        parents = _parent_map(tree)
        records = {id(scope): _record(package, scope) for scope in _scopes(tree)}
        return cls(tree, package, parents, records, _expression_masks(tree))

    def qualified(self, node: ast.expr, *, scope: ast.AST | None = None) -> str:
        return _qualified(self, node, scope)

    def module_of(self, node: ast.ImportFrom) -> str:
        return _module_of(self._package, node)

    def imported(self, node: ast.expr, *, scope: ast.AST | None = None) -> tuple[str, bool] | None:
        """The root import at ``node``, as ``(canonical, from_import)``, or None."""
        return _imported(self, node, scope)

    def is_expression_local(self, node: ast.expr) -> bool:
        """Whether an enclosing expression scope binds the reference root."""
        return _root_masked(self, node)


def _package(module: tuple[str, ...] | None, path: Path) -> tuple[str, ...] | None:
    if not module:
        return None
    if path.stem == "__init__":
        return module
    return module[:-1]


def _qualified(names: Names, node: ast.expr, scope: ast.AST | None) -> str:
    if _root_masked(names, node):
        return ""
    dotted = _dotted_name(node)
    if not dotted:
        return ""
    root, separator, member = dotted.partition(".")
    record, bound = _resolved_record(names, root, _scopes_for(names, node, scope))
    binding = record.imports.get(root) if bound else None
    if binding is not None:
        return f"{binding.canonical}{separator}{member}"
    if bound:
        return ""
    return f"builtins.{root}{separator}{member}"


def _imported(names: Names, node: ast.expr, scope: ast.AST | None) -> tuple[str, bool] | None:
    if _root_masked(names, node):
        return None
    root = _root_name(node)
    if not root:
        return None
    record, bound = _resolved_record(names, root, _scopes_for(names, node, scope))
    binding = record.imports.get(root) if bound else None
    if binding is None:
        return None
    return binding.canonical, binding.symbol


def _module_of(package: tuple[str, ...] | None, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    if not package:
        return ""
    climb = node.level - 1
    if climb >= len(package):
        return ""
    kept = package[: len(package) - climb]
    if node.module:
        return ".".join((*kept, node.module))
    return ".".join(kept)


def _resolved_record(names: Names, name: str, scopes: list[ast.AST]) -> tuple[_ScopeRecord, bool]:
    for scope in scopes[:-1]:
        record = names._records[id(scope)]
        if name in record.global_names:
            break
        if name in record.nonlocal_names:
            continue
        if name in record.bound:
            return record, True
    module = names._records[id(scopes[-1])]
    return module, name in module.bound


def _scopes_for(names: Names, node: ast.AST, scope: ast.AST | None) -> list[ast.AST]:
    if scope is not None and id(node) not in names._parents:
        return _chain_from(names, scope)
    return _scopes_for_node(names, node)


def _scopes_for_node(names: Names, node: ast.AST) -> list[ast.AST]:
    scopes: list[ast.AST] = []
    current = node
    skip_class = False
    while id(current) in names._parents:
        parent = names._parents[id(current)]
        if isinstance(parent, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            skip_class = skip_class or _in_comprehension_body(node, parent, names._parents)
        if not (skip_class and isinstance(parent, ast.ClassDef)):
            scopes = _with_parent_scope(scopes, current, parent, names._parents)
        current = parent
    scopes.append(names._tree)
    return scopes


def _in_comprehension_body(
    node: ast.AST, scope: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp, parents: dict[int, ast.AST]
) -> bool:
    outer_iter = scope.generators[0].iter
    return node is not outer_iter and not _contains(node, outer_iter, parents)


def _with_parent_scope(
    scopes: list[ast.AST], node: ast.AST, parent: ast.AST, parents: dict[int, ast.AST]
) -> list[ast.AST]:
    if isinstance(parent, _FUNCTION) and _in_body(node, parent, parents):
        return [*scopes, parent]
    if not isinstance(parent, ast.ClassDef) or not _in_body(node, parent, parents):
        return scopes
    if _function_covers(scopes, parent, parents):
        return scopes
    return [*scopes, parent]


def _chain_from(names: Names, scope: ast.AST) -> list[ast.AST]:
    scopes = [scope]
    current = scope
    while id(current) in names._parents:
        parent = names._parents[id(current)]
        if isinstance(parent, _FUNCTION):
            scopes.append(parent)
        current = parent
    if scopes[-1] is not names._tree:
        scopes.append(names._tree)
    return scopes


def _function_covers(scopes: list[ast.AST], class_node: ast.ClassDef, parents: dict[int, ast.AST]) -> bool:
    return any(isinstance(scope, _FUNCTION) and _contains(scope, class_node, parents) for scope in scopes)


def _in_body(node: ast.AST, scope: ast.AST, parents: dict[int, ast.AST]) -> bool:
    body = scope.body
    if isinstance(scope, ast.Lambda):
        return node is body or _contains(node, body, parents)
    return any(node is statement or _contains(node, statement, parents) for statement in body)


def _contains(node: ast.AST, root: ast.AST, parents: dict[int, ast.AST]) -> bool:
    current = node
    while id(current) in parents:
        current = parents[id(current)]
        if current is root:
            return True
    return False


def _root_masked(names: Names, node: ast.expr) -> bool:
    root = _root_node(node)
    return isinstance(root, ast.Name) and root.id in names._masks.get(id(root), ())


def _root_node(node: ast.expr) -> ast.expr:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current


def _root_name(node: ast.expr) -> str:
    root = _root_node(node)
    return root.id if isinstance(root, ast.Name) else ""


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else ""
    return ""


def _record(package: tuple[str, ...] | None, scope: ast.AST) -> _ScopeRecord:
    global_names = _declared(scope, ast.Global)
    nonlocal_names = _declared(scope, ast.Nonlocal)
    assigned = _scope_assigned(scope) - global_names
    imports = _scope_imports(package, scope)
    visible = {
        name: binding
        for name, binding in imports.items()
        if name not in assigned and name not in global_names
    }
    bound = frozenset((assigned | set(imports)) - global_names)
    return _ScopeRecord(visible, bound, global_names, nonlocal_names)


def _scopes(tree: ast.Module) -> list[ast.AST]:
    scopes: list[ast.AST] = [tree]
    scopes.extend(
        node
        for node in _module_nodes(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef))
    )
    return scopes


def _parent_map(tree: ast.Module) -> dict[int, ast.AST]:
    return {id(child): parent for parent in _module_nodes(tree) for child in ast.iter_child_nodes(parent)}


def _module_nodes(tree: ast.Module) -> tuple[ast.AST, ...]:
    from .callgraph import _module_nodes as nodes

    return nodes(tree)


def _statements(scope: ast.AST) -> list[ast.AST]:
    if isinstance(scope, ast.Lambda):
        return [scope.body]
    return list(scope.body)


def _scope_imports(package: tuple[str, ...] | None, scope: ast.AST) -> dict[str, _ImportBinding]:
    found: dict[str, _ImportBinding] = {}
    for statement in _statements(scope):
        found.update(_imports_in(package, statement))
    return found


def _imports_in(package: tuple[str, ...] | None, node: ast.AST) -> dict[str, _ImportBinding]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return {}
    if isinstance(node, ast.Import):
        return _import_aliases(node)
    if isinstance(node, ast.ImportFrom):
        return _from_import(package, node)
    found: dict[str, _ImportBinding] = {}
    for child in ast.iter_child_nodes(node):
        found.update(_imports_in(package, child))
    return found


def _import_aliases(node: ast.Import) -> dict[str, _ImportBinding]:
    found: dict[str, _ImportBinding] = {}
    for alias in node.names:
        binding = alias.asname or alias.name.split(".", 1)[0]
        canonical = alias.name if alias.asname else binding
        found[binding] = _ImportBinding(canonical, False)
    return found


def _from_import(package: tuple[str, ...] | None, node: ast.ImportFrom) -> dict[str, _ImportBinding]:
    module = _module_of(package, node)
    if not module and node.level:
        module = f"{'.' * node.level}{node.module or ''}"
    found: dict[str, _ImportBinding] = {}
    for alias in node.names:
        if alias.name == "*":
            continue
        found[alias.asname or alias.name] = _ImportBinding(_join_name(module, alias.name), True)
    return found


def _join_name(module: str, name: str) -> str:
    if not module or module.endswith("."):
        return f"{module}{name}"
    return f"{module}.{name}"


def _declared(scope: ast.AST, kind: type[ast.Global] | type[ast.Nonlocal]) -> frozenset[str]:
    found: set[str] = set()
    for statement in _statements(scope):
        found.update(_declared_in(statement, kind))
    return frozenset(found)


def _declared_in(node: ast.AST, kind: type[ast.Global] | type[ast.Nonlocal]) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return set()
    if isinstance(node, kind):
        return set(node.names)
    found: set[str] = set()
    for child in ast.iter_child_nodes(node):
        found.update(_declared_in(child, kind))
    return found


def _scope_assigned(scope: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(scope, _FUNCTION):
        names.update(_parameter_names(scope))
    for statement in _statements(scope):
        names.update(_assigned_in(statement, include_lambda_defaults=not isinstance(scope, ast.ClassDef)))
    return names


def _parameter_names(scope: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> set[str]:
    arguments = scope.args
    names = {argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return names


def _assigned_in(node: ast.AST, *, include_lambda_defaults: bool = True) -> set[str]:
    if isinstance(node, ast.Lambda):
        return _assigned_lambda_defaults(node) if include_lambda_defaults else set()
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    found = _pattern_names(node)
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        found.add(node.id)
    for child in _assigned_children(node):
        found.update(_assigned_in(child, include_lambda_defaults=include_lambda_defaults))
    return found


def _assigned_lambda_defaults(node: ast.Lambda) -> set[str]:
    found: set[str] = set()
    for default in [*node.args.defaults, *node.args.kw_defaults]:
        if default is not None:
            found.update(_assigned_in(default))
    return found


def _assigned_children(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.comprehension):
        return [node.iter, *node.ifs]
    return list(ast.iter_child_nodes(node))


def _pattern_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.MatchAs, ast.MatchStar, ast.ExceptHandler)) and node.name is not None:
        return {node.name}
    if isinstance(node, ast.MatchMapping) and node.rest is not None:
        return {node.rest}
    return set()


def _expression_masks(tree: ast.Module) -> dict[int, frozenset[str]]:
    masks: dict[int, frozenset[str]] = {}
    bindings = _expression_bindings(tree)
    pending: list[_MaskedNode] = [(tree, frozenset(), False)]
    while pending:
        node, masked, class_namespace = pending.pop()
        if masked and isinstance(node, (ast.Name, ast.Attribute)):
            masks[id(node)] = masked
        pending.extend(_masked_children(node, masked, class_namespace, bindings))
    return masks


def _masked_children(
    node: ast.AST, masked: frozenset[str], class_namespace: bool, bindings: dict[int, frozenset[str]]
) -> list[_MaskedNode]:
    if isinstance(node, ast.ClassDef):
        return _class_header_masked_children(node, masked, class_namespace, bindings)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [
            (child, frozenset(), False) if isinstance(child, ast.stmt) else (child, masked, class_namespace)
            for child in ast.iter_child_nodes(node)
        ]
    if isinstance(node, ast.Lambda):
        return _lambda_masked_children(node, masked, class_namespace, bindings)
    if not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return _ordinary_masked_children(node, masked, class_namespace, bindings)
    return _comprehension_masked_children(node, masked, class_namespace)


def _comprehension_masked_children(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    masked: frozenset[str],
    class_namespace: bool,
) -> list[_MaskedNode]:
    outer_iter = node.generators[0].iter
    captured = frozenset() if class_namespace else masked
    targets = captured.union(*(_stored_names(generator.target) for generator in node.generators))
    return [
        (child, masked, class_namespace) if child is outer_iter else (child, targets, False)
        for child in _comprehension_children(node)
    ]


def _class_header_masked_children(
    node: ast.ClassDef, masked: frozenset[str], class_namespace: bool, bindings: dict[int, frozenset[str]]
) -> list[_MaskedNode]:
    header = [*node.decorator_list, *node.bases, *node.keywords]
    children = _sequence_masked_children(header, masked, class_namespace, bindings)
    children.extend(_sequence_masked_children(node.body, frozenset(), True, bindings))
    handled_ids = {id(child) for child in [*header, *node.body]}
    children.extend((child, frozenset(), True) for child in ast.iter_child_nodes(node) if id(child) not in handled_ids)
    return children


def _lambda_masked_children(
    node: ast.Lambda, masked: frozenset[str], class_namespace: bool, bindings: dict[int, frozenset[str]]
) -> list[_MaskedNode]:
    defaults = [default for default in [*node.args.defaults, *node.args.kw_defaults] if default is not None]
    children = _sequence_masked_children(defaults, masked, class_namespace, bindings)
    # Defaults use the enclosing namespace; lambda bodies cannot capture a class namespace.
    captured = frozenset() if class_namespace else masked | bindings[id(node)]
    bound = captured | frozenset(_scope_assigned(node))
    return [*children, (node.body, bound, False)]


def _ordinary_masked_children(
    node: ast.AST, masked: frozenset[str], class_namespace: bool, bindings: dict[int, frozenset[str]]
) -> list[_MaskedNode]:
    if isinstance(node, ast.IfExp):
        branch_mask = masked | bindings[id(node.test)]
        return [(node.test, masked, class_namespace), (node.body, branch_mask, class_namespace), (node.orelse, branch_mask, class_namespace)]
    if isinstance(node, ast.Dict):
        children = [part for pair in zip(node.keys, node.values) for part in pair if part is not None]
        return _sequence_masked_children(children, masked, class_namespace, bindings)
    if isinstance(node, ast.expr):
        return _sequence_masked_children(list(ast.iter_child_nodes(node)), masked, class_namespace, bindings)
    return [(child, masked, class_namespace) for child in ast.iter_child_nodes(node)]


def _sequence_masked_children(
    children: list[ast.AST], masked: frozenset[str], class_namespace: bool, bindings: dict[int, frozenset[str]]
) -> list[_MaskedNode]:
    found: list[_MaskedNode] = []
    for child in children:
        found.append((child, masked, class_namespace))
        masked = masked | bindings[id(child)]
    return found


def _expression_bindings(tree: ast.Module) -> dict[int, frozenset[str]]:
    bindings: dict[int, frozenset[str]] = {}
    for node in reversed(_module_nodes(tree)):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            found = _evaluated_definition_bindings(node, bindings)
        elif isinstance(node, ast.stmt):
            found = _evaluated_statement_bindings(node, bindings)
        else:
            found = _evaluated_bindings(node, bindings)
        bindings[id(node)] = frozenset(found)
    return bindings


def _evaluated_statement_bindings(node: ast.stmt, bindings: dict[int, frozenset[str]]) -> set[str]:
    if isinstance(node, ast.If):
        return _evaluated_if_statement_bindings(node, bindings)
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return set(bindings[id(node.iter)])
    if isinstance(node, ast.While):
        return set(bindings[id(node.test)])
    if isinstance(node, (ast.Try, ast.TryStar)):
        return _sequence_bindings(node.finalbody, bindings)
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return _evaluated_context_bindings(node, bindings)
    if isinstance(node, ast.Match):
        return set(bindings[id(node.subject)])
    if isinstance(node, ast.Assert):
        return set(bindings[id(node.test)])
    return _evaluated_bindings(node, bindings)


def _evaluated_if_statement_bindings(node: ast.If, bindings: dict[int, frozenset[str]]) -> set[str]:
    found = set(bindings[id(node.test)])
    truth = _literal_truth(node.test)
    if truth is not None:
        return found | _sequence_bindings(node.body if truth else node.orelse, bindings)
    return found | (_sequence_bindings(node.body, bindings) & _sequence_bindings(node.orelse, bindings))


def _evaluated_context_bindings(node: ast.With | ast.AsyncWith, bindings: dict[int, frozenset[str]]) -> set[str]:
    found: set[str] = set()
    for item in node.items:
        found.update(bindings[id(item.context_expr)])
    return found


def _sequence_bindings(statements: list[ast.stmt], bindings: dict[int, frozenset[str]]) -> set[str]:
    found: set[str] = set()
    for statement in statements:
        found.update(bindings[id(statement)])
    return found


def _evaluated_bindings(node: ast.AST, bindings: dict[int, frozenset[str]]) -> set[str]:
    if isinstance(node, ast.NamedExpr):
        return set(bindings[id(node.value)]) | set(_stored_names(node.target))
    if isinstance(node, ast.Lambda):
        return _evaluated_lambda_defaults(node, bindings)
    if isinstance(node, ast.BoolOp):
        return _evaluated_boolean_bindings(node, bindings)
    if isinstance(node, ast.IfExp):
        return _evaluated_conditional_bindings(node, bindings)
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return set(bindings[id(node.generators[0].iter)])
    if isinstance(node, ast.Compare):
        return set(bindings[id(node.left)] | bindings[id(node.comparators[0])])
    found: set[str] = set()
    for child in ast.iter_child_nodes(node):
        found.update(bindings[id(child)])
    return found


def _evaluated_definition_bindings(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, bindings: dict[int, frozenset[str]]
) -> set[str]:
    found: set[str] = set()
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, ast.stmt):
            found.update(bindings[id(child)])
    return found


def _evaluated_lambda_defaults(node: ast.Lambda, bindings: dict[int, frozenset[str]]) -> set[str]:
    found: set[str] = set()
    for default in [*node.args.defaults, *node.args.kw_defaults]:
        if default is not None:
            found.update(bindings[id(default)])
    return found


def _evaluated_boolean_bindings(node: ast.BoolOp, bindings: dict[int, frozenset[str]]) -> set[str]:
    found: set[str] = set()
    for value in node.values:
        found.update(bindings[id(value)])
        truth = _literal_truth(value)
        if truth is None or (isinstance(node.op, ast.And) and not truth) or (isinstance(node.op, ast.Or) and truth):
            break
    return found


def _evaluated_conditional_bindings(node: ast.IfExp, bindings: dict[int, frozenset[str]]) -> set[str]:
    found = set(bindings[id(node.test)])
    truth = _literal_truth(node.test)
    if truth is not None:
        return found | set(bindings[id(node.body if truth else node.orelse)])
    return found | set(bindings[id(node.body)] & bindings[id(node.orelse)])


def _literal_truth(node: ast.AST) -> bool | None:
    return bool(node.value) if isinstance(node, ast.Constant) else None


def _comprehension_children(node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> list[ast.AST]:
    children: list[ast.AST] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.comprehension):
            children.extend(ast.iter_child_nodes(child))
        else:
            children.append(child)
    return children


def _stored_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Starred):
        return _stored_names(node.value)
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for element in node.elts for name in _stored_names(element)]
    return []
