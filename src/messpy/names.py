"""Qualified names for one module.

One resolver answers "what imported thing does this name refer to?" for every
rule. It follows lexical scopes, global and nonlocal declarations, rebinding,
comprehension targets, and relative imports. It does not look in other files.
"""

from __future__ import annotations

import ast
from collections.abc import Set as AbstractSet
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
class _AnnotationScope:
    owner: ast.AST


_Scope = ast.AST | _AnnotationScope


@dataclass(frozen=True)
class _BindingEffects:
    definite: dict[int, frozenset[str]]
    conditional: dict[tuple[int, bool], frozenset[str]]


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
    _annotations: dict[int, _AnnotationScope]
    _effects: _BindingEffects
    _keyword_masks: dict[int, frozenset[str]]

    @classmethod
    def build(cls, tree: ast.Module, *, module: tuple[str, ...] | None, path: Path) -> Names:
        package = _package(module, path)
        parents = _parent_map(tree)
        records = {id(scope): _record(package, scope) for scope in _scopes(tree)}
        annotations = _annotation_scopes(tree)
        records.update({id(scope): _annotation_record(scope) for scope in annotations.values()})
        effects = _expression_bindings(tree)
        masks = _expression_masks(tree, effects)
        keyword_masks = _expression_masks(tree, effects, conditional_paths=True)
        return cls(tree, package, parents, records, masks, annotations, effects, keyword_masks)

    def qualified(self, node: ast.expr, *, scope: ast.AST | None = None) -> str:
        return _qualified(self, node, scope)

    def module_of(self, node: ast.ImportFrom) -> str:
        return _module_of(self._package, node)

    def imported(self, node: ast.expr, *, scope: ast.AST | None = None) -> tuple[str, bool] | None:
        """The root import at ``node``, as ``(canonical, from_import)``, or None."""
        return _imported(self, node, scope)

    def is_local(self, node: ast.expr, *, scope: ast.AST | None = None) -> bool:
        """Whether the reference root resolves to an expression or enclosing scope local."""
        return _is_local(self, node, scope)

    def is_expression_local(self, node: ast.expr, *, scope: ast.AST | None = None) -> bool:
        """Whether an expression or type parameter scope binds the reference root."""
        return _is_expression_local(self, node, scope)

    def is_class_keyword_local(self, node: ast.expr) -> bool:
        """Whether a class keyword reference has an established local binding."""
        return _is_class_keyword_local(self, node)


def _is_class_keyword_local(names: Names, node: ast.expr) -> bool:
    return _in_class_keyword(names, node) and (
        _masked_root(node, names._keyword_masks) or _is_local(names, node, None)
    )


def _is_local(names: Names, node: ast.expr, scope: ast.AST | None) -> bool:
    if _query_root_masked(names, node):
        return True
    root = _root_name(node)
    for enclosing in _local_scopes(names, node, scope):
        record = names._records[id(enclosing)]
        if root in record.global_names:
            return False
        if root in record.nonlocal_names:
            continue
        if isinstance(enclosing, ast.ClassDef):
            resolved = _class_local_resolution(names, root, node, enclosing, record)
        elif root in record.imports:
            resolved = False
        elif root in _lexical_assigned(enclosing, record):
            resolved = True
        else:
            continue
        if resolved is not None:
            return resolved
    return False


def _class_local_resolution(
    names: Names, root: str, node: ast.AST, scope: ast.ClassDef, record: _ScopeRecord
) -> bool | None:
    if _class_local_before(names, root, node, scope):
        return True
    if root in _lexical_assigned(scope, record) or root in record.imports:
        return False
    return None


def _local_scopes(names: Names, node: ast.expr, scope: ast.AST | None) -> list[_Scope]:
    scopes: list[_Scope] = []
    class_seen = False
    for enclosing in _scopes_for(names, node, scope)[:-1]:
        if isinstance(enclosing, ast.ClassDef):
            if class_seen:
                continue
            class_seen = True
        scopes.append(enclosing)
    return scopes


def _lexical_assigned(scope: _Scope, record: _ScopeRecord) -> AbstractSet[str]:
    if isinstance(scope, (*_FUNCTION, ast.ClassDef)):
        return _scope_assigned(scope, include_definition_headers=True)
    return record.bound


def _is_expression_local(names: Names, node: ast.expr, scope: ast.AST | None) -> bool:
    if _query_root_masked(names, node):
        return True
    record, bound = _resolved_record(names, _root_name(node), _scopes_for(names, node, scope))
    return bound and any(record is names._records[id(annotation)] for annotation in names._annotations.values())


def _in_class_keyword(names: Names, node: ast.AST) -> bool:
    current = node
    while id(current) in names._parents:
        parent = names._parents[id(current)]
        if isinstance(current, ast.keyword) and isinstance(parent, ast.ClassDef):
            return True
        current = parent
    return False


def _class_local_before(names: Names, root: str, node: ast.AST, scope: ast.ClassDef) -> bool:
    path: list[tuple[ast.AST, ast.AST]] = []
    current = node
    while current is not scope and id(current) in names._parents:
        parent = names._parents[id(current)]
        path.append((parent, current))
        current = parent
    local = False
    for parent, child in reversed(path):
        for field, siblings in ast.iter_fields(parent):
            if isinstance(siblings, list) and child in siblings:
                local = _active_class_binding(names, root, parent, field, local)
                local = _class_prefix_binding(names, root, siblings, child, local)
    return local


def _class_prefix_binding(names: Names, root: str, siblings: list[ast.AST], child: ast.AST | None, local: bool) -> bool:
    for statement in siblings:
        if statement is child:
            break
        if isinstance(statement, ast.stmt):
            binding = _class_binding_kind(names, root, statement)
            if binding is not None:
                local = binding
        elif isinstance(statement, ast.ExceptHandler):
            local = _handler_prefix_binding(names, root, statement, local)
    return local


def _handler_prefix_binding(names: Names, root: str, handler: ast.ExceptHandler, local: bool) -> bool:
    if handler.type is not None and root in names._effects.definite[id(handler.type)]:
        local = True
    parent = names._parents[id(handler)]
    if isinstance(parent, ast.TryStar) and _class_root_externalized(root, handler):
        return False
    return local


def _active_class_binding(names: Names, root: str, parent: ast.AST, field: str, local: bool) -> bool:
    local = _block_entry_binding(names, root, parent, field, local)
    return local or root in _block_bindings(names, parent, field)


def _block_entry_binding(names: Names, root: str, parent: ast.AST, field: str, local: bool) -> bool:
    if isinstance(parent, (ast.Try, ast.TryStar)):
        if field == "orelse":
            return _class_prefix_binding(names, root, parent.body, None, local)
        if field in ("handlers", "finalbody"):
            return local and not _class_root_externalized(root, parent)
    if isinstance(parent, (ast.For, ast.AsyncFor, ast.While)) and field in ("body", "orelse"):
        return local and not any(_class_root_externalized(root, child) for child in parent.body)
    return local


def _block_bindings(names: Names, parent: ast.AST, field: str) -> AbstractSet[str]:
    if isinstance(parent, ast.Match) and field == "cases":
        return names._effects.definite[id(parent.subject)]
    if isinstance(parent, (ast.If, ast.While)) and field in ("body", "orelse"):
        return names._effects.conditional[(id(parent.test), field == "body")]
    if isinstance(parent, (ast.For, ast.AsyncFor)) and field in ("body", "orelse"):
        return _for_block_bindings(names, parent, field)
    if field != "body":
        return frozenset()
    return _block_body_bindings(names, parent)


def _block_body_bindings(names: Names, parent: ast.AST) -> AbstractSet[str]:
    if isinstance(parent, (ast.With, ast.AsyncWith)):
        return _with_block_bindings(names, parent)
    if isinstance(parent, ast.ExceptHandler):
        return _handler_bindings(names, parent)
    if isinstance(parent, ast.match_case):
        found = _assigned_in(parent.pattern)
        if parent.guard is not None:
            found.update(names._effects.conditional[(id(parent.guard), True)])
        return found
    return frozenset()


def _for_block_bindings(names: Names, parent: ast.For | ast.AsyncFor, field: str) -> AbstractSet[str]:
    found = {
        root for root in names._effects.definite[id(parent.iter)]
        if not any(_class_root_externalized(root, child) for child in parent.body)
    }
    if field == "body":
        found.update(_stored_names(parent.target))
    return found


def _handler_bindings(names: Names, handler: ast.ExceptHandler) -> AbstractSet[str]:
    found = {handler.name} if handler.name is not None else set()
    if handler.type is not None:
        found.update(names._effects.definite[id(handler.type)])
    return found


def _with_block_bindings(names: Names, node: ast.With | ast.AsyncWith) -> AbstractSet[str]:
    targets: set[str] = set()
    for item in node.items:
        if item.optional_vars is not None:
            targets.update(_stored_names(item.optional_vars))
    return targets | names._effects.definite[id(node)]


def _class_binding_kind(names: Names, root: str, statement: ast.stmt) -> bool | None:
    if isinstance(statement, ast.If) and _literal_truth(statement.test) is not None:
        return _known_class_branch(names, root, statement)
    if isinstance(statement, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.TryStar, ast.Match)):
        return False if _class_root_externalized(root, statement) else None
    return _class_direct_binding(names, root, statement)


def _class_direct_binding(names: Names, root: str, statement: ast.stmt) -> bool | None:
    if root in _imports_in(names._package, statement) or _deleted_in(root, statement):
        return False
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and root in names._effects.definite[id(statement)]:
        return True
    if isinstance(statement, ast.AnnAssign) and statement.value is None:
        return None
    if root in _assigned_in(statement, include_lambda_defaults=False):
        return isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign, *_FUNCTION, ast.ClassDef))
    return None


def _known_class_branch(names: Names, root: str, statement: ast.If) -> bool | None:
    branch = statement.body if _literal_truth(statement.test) else statement.orelse
    state: bool | None = None
    for child in branch:
        binding = _class_binding_kind(names, root, child)
        if binding is not None:
            state = binding
    return state


def _class_root_externalized(root: str, node: ast.AST) -> bool:
    if isinstance(node, (ast.ClassDef, *_FUNCTION)):
        return False
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return root in _imports_in(None, node)
    if isinstance(node, ast.Delete):
        return any(root in _stored_names(target) for target in node.targets)
    if isinstance(node, ast.ExceptHandler) and node.name == root:
        return True
    return any(_class_root_externalized(root, child) for child in _active_binding_children(node))


def _active_binding_children(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.If) and _literal_truth(node.test) is not None:
        return node.body if _literal_truth(node.test) else node.orelse
    return list(ast.iter_child_nodes(node))


def _deleted_in(root: str, node: ast.AST) -> bool:
    if isinstance(node, (ast.ClassDef, *_FUNCTION)):
        return False
    if isinstance(node, ast.Delete):
        return any(root in _stored_names(target) for target in node.targets)
    if isinstance(node, ast.ExceptHandler) and node.name == root:
        return True
    return any(_deleted_in(root, child) for child in ast.iter_child_nodes(node))


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
    if _query_root_masked(names, node):
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


def _resolved_record(names: Names, name: str, scopes: list[_Scope]) -> tuple[_ScopeRecord, bool]:
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


def _scopes_for(names: Names, node: ast.AST, scope: ast.AST | None) -> list[_Scope]:
    if scope is not None and id(node) not in names._parents:
        return _chain_from(names, scope)
    return _scopes_for_node(names, node)


def _scopes_for_node(names: Names, node: ast.AST) -> list[_Scope]:
    scopes: list[_Scope] = []
    current = node
    skip_class = False
    while id(current) in names._parents:
        parent = names._parents[id(current)]
        if isinstance(parent, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            skip_class = skip_class or _in_comprehension_body(node, parent, names._parents)
        if not (skip_class and isinstance(parent, ast.ClassDef)):
            scopes = _with_parent_scope(scopes, current, parent, names._parents)
        annotation = names._annotations.get(id(parent))
        if annotation is not None and _annotation_applies(node, current, parent, names._parents):
            scopes.append(annotation)
        current = parent
    scopes.append(names._tree)
    return scopes


def _in_comprehension_body(
    node: ast.AST, scope: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp, parents: dict[int, ast.AST]
) -> bool:
    outer_iter = scope.generators[0].iter
    return node is not outer_iter and not _contains(node, outer_iter, parents)


def _with_parent_scope(
    scopes: list[_Scope], node: ast.AST, parent: ast.AST, parents: dict[int, ast.AST]
) -> list[_Scope]:
    if isinstance(parent, _FUNCTION) and _in_body(node, parent, parents):
        return [*scopes, parent]
    if not isinstance(parent, ast.ClassDef) or not _in_body(node, parent, parents):
        return scopes
    if _function_covers(scopes, parent, parents):
        return scopes
    return [*scopes, parent]


def _chain_from(names: Names, scope: ast.AST) -> list[_Scope]:
    scopes: list[_Scope] = [scope]
    annotation = names._annotations.get(id(scope))
    if annotation is not None:
        scopes.append(annotation)
    current = scope
    while id(current) in names._parents:
        parent = names._parents[id(current)]
        if isinstance(parent, _FUNCTION):
            scopes.append(parent)
        annotation = names._annotations.get(id(parent))
        if annotation is not None and _annotation_applies(scope, current, parent, names._parents):
            scopes.append(annotation)
        current = parent
    if scopes[-1] is not names._tree:
        scopes.append(names._tree)
    return scopes


def _function_covers(scopes: list[_Scope], class_node: ast.ClassDef, parents: dict[int, ast.AST]) -> bool:
    return any(isinstance(scope, _FUNCTION) and _contains(scope, class_node, parents) for scope in scopes)


def _annotation_scopes(tree: ast.Module) -> dict[int, _AnnotationScope]:
    return {id(node): _AnnotationScope(node) for node in _module_nodes(tree) if getattr(node, "type_params", ())}


def _annotation_record(scope: _AnnotationScope) -> _ScopeRecord:
    parameters = getattr(scope.owner, "type_params", ())
    return _ScopeRecord({}, frozenset(parameter.name for parameter in parameters), frozenset(), frozenset())


def _annotation_applies(node: ast.AST, child: ast.AST, owner: ast.AST, parents: dict[int, ast.AST]) -> bool:
    if isinstance(owner, ast.ClassDef):
        return child not in owner.decorator_list
    if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return (
            child in owner.type_params or child is owner.returns or _in_body(node, owner, parents)
            or _in_argument_annotation(node, owner.args, parents)
        )
    return True


def _in_argument_annotation(node: ast.AST, arguments: ast.arguments, parents: dict[int, ast.AST]) -> bool:
    current = node
    while id(current) in parents and current is not arguments:
        parent = parents[id(current)]
        if isinstance(parent, ast.arg) and current is parent.annotation:
            return True
        current = parent
    return False


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
    return _masked_root(node, names._masks)


def _query_root_masked(names: Names, node: ast.expr) -> bool:
    masks = names._keyword_masks if _in_class_keyword(names, node) else names._masks
    return _masked_root(node, masks)


def _masked_root(node: ast.expr, masks: dict[int, frozenset[str]]) -> bool:
    root = _root_node(node)
    return isinstance(root, ast.Name) and root.id in masks.get(id(root), ())


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


def _scope_assigned(scope: ast.AST, *, include_definition_headers: bool = False) -> set[str]:
    names: set[str] = set()
    if isinstance(scope, _FUNCTION):
        names.update(_parameter_names(scope))
    for statement in _statements(scope):
        names.update(_assigned_in(
            statement, include_lambda_defaults=include_definition_headers or not isinstance(scope, ast.ClassDef),
            include_definition_headers=include_definition_headers,
        ))
    return names


def _parameter_names(scope: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> set[str]:
    arguments = scope.args
    names = {argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return names


def _assigned_in(
    node: ast.AST, *, include_lambda_defaults: bool = True, include_definition_headers: bool = False
) -> set[str]:
    if isinstance(node, ast.Lambda):
        return _assigned_lambda_defaults(node) if include_lambda_defaults else set()
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return _assigned_definition(node, include_definition_headers)
    found = _pattern_names(node)
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        found.add(node.id)
    for child in _assigned_children(node):
        found.update(_assigned_in(
            child, include_lambda_defaults=include_lambda_defaults, include_definition_headers=include_definition_headers
        ))
    return found


def _assigned_definition(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, include_header: bool) -> set[str]:
    found = {node.name}
    if include_header:
        for expression in _definition_header(node):
            found.update(_assigned_in(expression, include_definition_headers=True))
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


def _expression_masks(
    tree: ast.Module, bindings: _BindingEffects, *, conditional_paths: bool = False
) -> dict[int, frozenset[str]]:
    masks: dict[int, frozenset[str]] = {}
    pending: list[_MaskedNode] = [(tree, frozenset(), False)]
    while pending:
        node, masked, class_namespace = pending.pop()
        if masked and isinstance(node, (ast.Name, ast.Attribute)):
            masks[id(node)] = masked
        pending.extend(_masked_children(node, masked, class_namespace, bindings, conditional_paths))
    return masks


def _masked_children(
    node: ast.AST, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects, conditional_paths: bool
) -> list[_MaskedNode]:
    masked = _statement_masks(node, masked, class_namespace, conditional_paths)
    if isinstance(node, ast.IfExp) and conditional_paths:
        return _conditional_masked_children(node, masked, class_namespace, bindings)
    if isinstance(node, ast.ClassDef):
        return _class_header_masked_children(node, masked, class_namespace, bindings, conditional_paths)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [
            (child, frozenset(), False) if isinstance(child, ast.stmt) else (child, masked, class_namespace)
            for child in ast.iter_child_nodes(node)
        ]
    if isinstance(node, ast.Lambda):
        return _lambda_masked_children(node, masked, class_namespace, bindings)
    if not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return _ordinary_masked_children(node, masked, class_namespace, bindings)
    return _comprehension_masked_children(node, masked, class_namespace, bindings)


def _statement_masks(node: ast.AST, masked: frozenset[str], class_namespace: bool, conditional_paths: bool) -> frozenset[str]:
    if conditional_paths and class_namespace and isinstance(node, ast.stmt):
        return _retained_class_masks(masked, node)
    return masked


def _comprehension_masked_children(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    masked: frozenset[str],
    class_namespace: bool,
    bindings: _BindingEffects,
) -> list[_MaskedNode]:
    outer_iter = node.generators[0].iter
    captured = frozenset() if class_namespace else masked
    targets = captured.union(*(_stored_names(generator.target) for generator in node.generators))
    children: list[_MaskedNode] = [(outer_iter, masked, class_namespace)]
    current = targets | bindings.definite[id(outer_iter)]
    for index, generator in enumerate(node.generators):
        if index:
            children.append((generator.iter, current, False))
            current = current | bindings.definite[id(generator.iter)]
        children.append((generator.target, current, False))
        for condition in generator.ifs:
            children.append((condition, current, False))
            current = current | bindings.conditional[(id(condition), True)]
    elements = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
    children.extend(_sequence_masked_children(elements, current, False, bindings))
    return children


def _condition_path_bindings(
    node: ast.AST,
    truth: bool,
    bindings: dict[int, frozenset[str]],
    conditions: dict[tuple[int, bool], frozenset[str]],
) -> set[str]:
    if isinstance(node, ast.BoolOp):
        return _boolean_condition_bindings(node, truth, conditions)
    if isinstance(node, ast.IfExp):
        return _conditional_condition_bindings(node, truth, conditions)
    if isinstance(node, ast.Compare) and truth:
        return _comparison_condition_bindings(node, bindings)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return set(conditions[(id(node.operand), not truth)])
    return set()


def _comparison_condition_bindings(node: ast.Compare, bindings: dict[int, frozenset[str]]) -> set[str]:
    found = set(bindings[id(node.left)])
    for comparator in node.comparators:
        found.update(bindings[id(comparator)])
    return found


def _boolean_condition_bindings(
    node: ast.BoolOp,
    truth: bool,
    conditions: dict[tuple[int, bool], frozenset[str]],
) -> set[str]:
    prefix: set[str] = set()
    if isinstance(node.op, ast.And) == truth:
        for value in node.values:
            prefix.update(conditions[(id(value), truth)])
        return prefix
    paths: list[set[str]] = []
    for value in node.values:
        paths.append(prefix | set(conditions[(id(value), truth)]))
        prefix.update(conditions[(id(value), not truth)])
    return set.intersection(*paths)


def _conditional_condition_bindings(
    node: ast.IfExp,
    truth: bool,
    conditions: dict[tuple[int, bool], frozenset[str]],
) -> set[str]:
    test_truth = _literal_truth(node.test)
    if test_truth is not None:
        branch = node.body if test_truth else node.orelse
        return set(conditions[(id(node.test), test_truth)] | conditions[(id(branch), truth)])
    paths = [
        conditions[(id(node.test), True)] | conditions[(id(node.body), truth)],
        conditions[(id(node.test), False)] | conditions[(id(node.orelse), truth)],
    ]
    return set(paths[0] & paths[1])


def _class_header_masked_children(
    node: ast.ClassDef, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects, conditional_paths: bool
) -> list[_MaskedNode]:
    header = [*node.decorator_list, *node.bases, *node.keywords]
    children = _sequence_masked_children(header, masked, class_namespace, bindings)
    body = _sequence_masked_children(node.body, frozenset(), True, bindings)
    if conditional_paths:
        body = _keyword_class_body(node.body, bindings)
    children.extend(body)
    handled_ids = {id(child) for child in [*header, *node.body]}
    children.extend((child, frozenset(), True) for child in ast.iter_child_nodes(node) if id(child) not in handled_ids)
    return children


def _retained_class_masks(masked: frozenset[str], node: ast.AST) -> frozenset[str]:
    return frozenset(root for root in masked if not _class_root_externalized(root, node))


def _keyword_class_body(statements: list[ast.stmt], bindings: _BindingEffects) -> list[_MaskedNode]:
    children: list[_MaskedNode] = []
    masked: frozenset[str] = frozenset()
    for statement in statements:
        children.append((statement, masked, True))
        masked = _retained_class_masks(masked | bindings.definite[id(statement)], statement)
    return children


def _lambda_masked_children(
    node: ast.Lambda, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects
) -> list[_MaskedNode]:
    defaults = [default for default in [*node.args.defaults, *node.args.kw_defaults] if default is not None]
    children = _sequence_masked_children(defaults, masked, class_namespace, bindings)
    # Defaults use the enclosing namespace; lambda bodies cannot capture a class namespace.
    captured = frozenset() if class_namespace else masked | bindings.definite[id(node)]
    bound = captured | frozenset(_scope_assigned(node))
    return [*children, (node.body, bound, False)]


def _ordinary_masked_children(
    node: ast.AST, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects
) -> list[_MaskedNode]:
    if isinstance(node, ast.IfExp):
        branch_mask = masked | bindings.definite[id(node.test)]
        return [(node.test, masked, class_namespace), (node.body, branch_mask, class_namespace), (node.orelse, branch_mask, class_namespace)]
    if isinstance(node, ast.Dict):
        children = [part for pair in zip(node.keys, node.values) for part in pair if part is not None]
        return _sequence_masked_children(children, masked, class_namespace, bindings)
    if isinstance(node, ast.expr):
        return _sequence_masked_children(list(ast.iter_child_nodes(node)), masked, class_namespace, bindings)
    return [(child, masked, class_namespace) for child in ast.iter_child_nodes(node)]


def _conditional_masked_children(
    node: ast.IfExp, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects
) -> list[_MaskedNode]:
    return [
        (node.test, masked, class_namespace),
        (node.body, masked | bindings.conditional[(id(node.test), True)], class_namespace),
        (node.orelse, masked | bindings.conditional[(id(node.test), False)], class_namespace),
    ]


def _sequence_masked_children(
    children: list[ast.AST], masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects
) -> list[_MaskedNode]:
    found: list[_MaskedNode] = []
    for child in children:
        found.append((child, masked, class_namespace))
        masked = masked | bindings.definite[id(child)]
    return found


def _expression_bindings(tree: ast.Module) -> _BindingEffects:
    bindings: dict[int, frozenset[str]] = {}
    conditions: dict[tuple[int, bool], frozenset[str]] = {}
    for node in reversed(_module_nodes(tree)):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            found = _evaluated_definition_bindings(node, bindings)
        elif isinstance(node, ast.stmt):
            found = _evaluated_statement_bindings(node, bindings)
        else:
            found = _evaluated_bindings(node, bindings)
        bindings[id(node)] = frozenset(found)
        for truth in (False, True):
            conditions[(id(node), truth)] = frozenset(found | _condition_path_bindings(node, truth, bindings, conditions))
    return _BindingEffects(bindings, conditions)


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
    for child in _definition_header(node):
        found.update(bindings[id(child)])
    return found


def _definition_header(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)]
    return [
        *node.decorator_list,
        *(default for default in [*node.args.defaults, *node.args.kw_defaults] if default is not None),
        *_function_annotations(node),
    ]


def _function_annotations(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    arguments.extend(argument for argument in (node.args.vararg, node.args.kwarg) if argument is not None)
    annotations = [*(argument.annotation for argument in arguments), node.returns]
    return [annotation for annotation in annotations if annotation is not None]


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


def _stored_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Starred):
        return _stored_names(node.value)
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for element in node.elts for name in _stored_names(element)]
    return []
