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
class _ClassMaskFlow:
    """Masks for each statement exit; None means that no path has that exit."""

    normal: frozenset[str] | None
    breaks: frozenset[str] | None = None
    continues: frozenset[str] | None = None
    raises: frozenset[str] | None = None


@dataclass(frozen=True)
class _MaskProjection:
    masks: dict[int, frozenset[str]]
    frames: dict[int, frozenset[str]]


@dataclass(frozen=True)
class _ClassBinding:
    local: bool
    imported: _ImportBinding | None = None


@dataclass(frozen=True)
class KeywordBinding:
    """Possible imports and local bindings at an eager class keyword read."""

    local: bool
    imports: frozenset[tuple[str, bool]]
    unresolved: bool


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
        # Limit renewal to roots covered by the existing mask rules.
        ordinary_roots = _mask_projection(tree, effects).frames
        masks = _expression_masks(tree, effects, ordinary_roots=ordinary_roots)
        effects = _expression_bindings(tree, reachable=True)
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

    def is_class_keyword_target(self, node: ast.expr) -> bool:
        """Whether a keyword reads the name assigned by its class statement."""
        return _is_class_keyword_target(self, node)

    def keyword_binding(self, node: ast.expr) -> KeywordBinding | None:
        """Resolve an eager keyword read without changing deferred name queries."""
        return _keyword_binding(self, node)


def _keyword_binding(names: Names, node: ast.expr) -> KeywordBinding | None:
    if not _eager_class_keyword(names, node):
        return None
    if not _keyword_prefix_supported(names, _root_name(node), node):
        return None
    if _query_root_masked(names, node):
        return KeywordBinding(True, frozenset(), False)
    bindings = _keyword_bindings(names, _root_name(node), node, [*_local_scopes(names, node, None), names._tree])
    return _keyword_result(bindings) if bindings is not None else None


def _keyword_result(bindings: frozenset[_ClassBinding | None]) -> KeywordBinding:
    imports = frozenset((binding.imported.canonical, binding.imported.symbol) for binding in bindings if binding is not None and binding.imported is not None)
    local = all(binding is not None and binding.local for binding in bindings)
    unresolved = any(binding is None or (not binding.local and binding.imported is None) for binding in bindings)
    return KeywordBinding(local, imports, unresolved)


def _keyword_prefix_supported(names: Names, root: str, node: ast.AST) -> bool:
    for scope in _local_scopes(names, node, None):
        record = names._records[id(scope)]
        if root in record.global_names or root in record.nonlocal_names:
            return False
    for parent, _, siblings, child in _binding_statement_path(names, node, names._tree):
        if isinstance(parent, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.TryStar, ast.Match)):
            return False
        if not _keyword_statements_supported(root, siblings, child):
            return False
    return True


def _keyword_statements_supported(root: str, siblings: list[ast.AST], child: ast.AST) -> bool:
    for statement in siblings:
        if statement is child:
            break
        if _keyword_unknown_block(root, statement):
            return False
    return True


def _keyword_unknown_block(root: str, node: ast.AST) -> bool:
    if isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.TryStar, ast.Match)):
        return root in _assigned_in(node) or _class_root_externalized(root, node)
    if isinstance(node, (ast.ClassDef, *_FUNCTION)):
        return False
    return any(_keyword_unknown_block(root, child) for child in ast.iter_child_nodes(node))


def _eager_class_keyword(names: Names, node: ast.AST) -> bool:
    owner = _class_keyword_owner(names, node)
    if owner is None:
        return False
    current = node
    while current is not owner:
        parent = names._parents[id(current)]
        if isinstance(parent, ast.Lambda) and _in_body(node, parent, names._parents):
            return False
        if isinstance(parent, ast.GeneratorExp) and _in_comprehension_body(node, parent, names._parents):
            return False
        current = parent
    return True


def _keyword_bindings(names: Names, root: str, node: ast.AST, scopes: list[_Scope]) -> frozenset[_ClassBinding | None] | None:
    scope, *outer = scopes
    record = names._records[id(scope)]
    if isinstance(scope, _AnnotationScope):
        return frozenset({_ClassBinding(True)}) if root in record.bound else _keyword_bindings(names, root, node, outer)
    bindings = _keyword_bindings_before(names, root, node, scope)
    if bindings is None:
        return None
    if isinstance(scope, ast.ClassDef):
        if root in _lexical_assigned(scope, record) or root in record.imports:
            outer = [names._tree]
        return _keyword_class_fallback(names, root, node, outer, bindings)
    return _keyword_outer_bindings(names, root, node, scopes, bindings)


def _keyword_outer_bindings(names: Names, root: str, node: ast.AST, scopes: list[_Scope], bindings: frozenset[_ClassBinding | None]) -> frozenset[_ClassBinding | None] | None:
    scope, *outer = scopes
    record = names._records[id(scope)]
    if None not in bindings:
        return bindings
    if isinstance(scope, _FUNCTION) and root in _lexical_assigned(scope, record):
        return (bindings - {None}) | {_ClassBinding(True)}
    fallback = _keyword_bindings(names, root, node, outer) if outer else frozenset({None})
    return (bindings - {None}) | fallback if fallback is not None else None


def _keyword_class_fallback(names: Names, root: str, node: ast.AST, outer: list[_Scope], bindings: frozenset[_ClassBinding | None]) -> frozenset[_ClassBinding | None] | None:
    retained = bindings - {None}
    if None not in bindings:
        return retained
    fallback = _keyword_bindings(names, root, node, outer)
    return retained | fallback if fallback is not None else None


def _keyword_bindings_before(names: Names, root: str, node: ast.AST, scope: ast.AST) -> frozenset[_ClassBinding | None] | None:
    initial = _ClassBinding(True) if isinstance(scope, _FUNCTION) and root in _parameter_names(scope) else None
    bindings = frozenset({initial})
    for parent, field, siblings, child in _binding_statement_path(names, node, scope):
        if field == "body" and parent is not scope:
            if isinstance(parent, _FUNCTION):
                return None
            if isinstance(parent, ast.ClassDef):
                return bindings
        bindings = frozenset(_active_class_binding(names, root, parent, field, binding) for binding in bindings)
        bindings = _keyword_prefix_bindings(names, root, siblings, child, bindings)
    return bindings


def _keyword_prefix_bindings(names: Names, root: str, siblings: list[ast.AST], child: ast.AST | None, bindings: frozenset[_ClassBinding | None]) -> frozenset[_ClassBinding | None]:
    for statement in siblings:
        if statement is child:
            break
        if isinstance(statement, ast.stmt):
            bindings = frozenset(result for binding in bindings for result in _keyword_statement_bindings(names, root, statement, binding))
        elif isinstance(statement, ast.ExceptHandler):
            bindings = frozenset(_handler_prefix_binding(names, root, statement, binding) for binding in bindings)
    return bindings


def _keyword_statement_bindings(names: Names, root: str, statement: ast.stmt, before: _ClassBinding | None) -> frozenset[_ClassBinding | None]:
    if isinstance(statement, (ast.Return, ast.Raise)):
        return frozenset()
    if isinstance(statement, ast.Delete) and _deleted_in(root, statement):
        return frozenset({None})
    if isinstance(statement, ast.If):
        return _keyword_if_bindings(names, root, statement, before)
    assigned = _keyword_direct_binding(names, root, statement, before)
    return frozenset({before if assigned is None else assigned})


def _keyword_if_bindings(names: Names, root: str, statement: ast.If, before: _ClassBinding | None) -> frozenset[_ClassBinding | None]:
    truth = _literal_truth(statement.test)
    fields = ("body", "orelse") if truth is None else ("body" if truth else "orelse",)
    found: set[_ClassBinding | None] = set()
    for field in fields:
        entry = _active_class_binding(names, root, statement, field, before)
        found.update(_keyword_prefix_bindings(names, root, getattr(statement, field), None, frozenset({entry})))
    return frozenset(found)


def _keyword_direct_binding(names: Names, root: str, statement: ast.stmt, before: _ClassBinding | None) -> _ClassBinding | None:
    if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return _ClassBinding(True) if _keyword_evaluated_local(names, root, statement) else None
    return _statement_binding(names, root, statement, before)


def _keyword_evaluated_local(names: Names, root: str, statement: ast.Assign | ast.AnnAssign | ast.AugAssign) -> bool:
    if root in names._effects.definite[id(statement)]:
        return True
    if isinstance(statement, ast.Assign):
        return any(root in _stored_names(target) for target in statement.targets)
    return statement.value is not None and root in _stored_names(statement.target)


def _is_class_keyword_local(names: Names, node: ast.expr) -> bool:
    binding = _class_keyword_binding(names, node)
    if binding is not None:
        return binding.local
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
    return _class_keyword_owner(names, node) is not None


def _class_keyword_owner(names: Names, node: ast.AST) -> ast.ClassDef | None:
    current = node
    while id(current) in names._parents:
        parent = names._parents[id(current)]
        if isinstance(current, ast.keyword) and isinstance(parent, ast.ClassDef):
            return parent
        current = parent
    return None


def _is_class_keyword_target(names: Names, node: ast.expr) -> bool:
    owner = _class_keyword_owner(names, node)
    return owner is not None and owner.name == _root_name(node)


def _class_keyword_binding(names: Names, node: ast.expr) -> _ClassBinding | None:
    if not _is_class_keyword_target(names, node):
        return None
    if _query_root_masked(names, node):
        return _ClassBinding(True)
    root = _root_name(node)
    for scope in [*_local_scopes(names, node, None), names._tree]:
        record = names._records[id(scope)]
        if root in record.global_names:
            return None
        if root in record.nonlocal_names:
            continue
        binding = _keyword_scope_binding(names, root, node, scope, record)
        if binding is not None:
            return binding
    return None


def _keyword_scope_binding(names: Names, root: str, node: ast.AST, scope: _Scope, record: _ScopeRecord) -> _ClassBinding | None:
    if isinstance(scope, _AnnotationScope):
        return _ClassBinding(True) if root in record.bound else None
    binding = _class_binding_before(names, root, node, scope)
    if binding is not None:
        return binding
    if isinstance(scope, ast.ClassDef) and root in record.bound:
        return _ClassBinding(False, names._records[id(names._tree)].imports.get(root))
    if root in record.imports:
        return _ClassBinding(False, record.imports[root])
    if root in _lexical_assigned(scope, record):
        return _ClassBinding(True)
    return None


def _class_local_before(names: Names, root: str, node: ast.AST, scope: ast.ClassDef) -> bool:
    binding = _class_binding_before(names, root, node, scope)
    return binding is not None and binding.local


def _class_binding_before(names: Names, root: str, node: ast.AST, scope: ast.AST) -> _ClassBinding | None:
    binding = _ClassBinding(True) if isinstance(scope, _FUNCTION) and root in _parameter_names(scope) else None
    for parent, field, siblings, child in _binding_statement_path(names, node, scope):
        if field == "body" and parent is not scope:
            if isinstance(parent, _FUNCTION):
                return None
            if isinstance(parent, ast.ClassDef):
                return binding
        binding = _active_class_binding(names, root, parent, field, binding)
        binding = _class_prefix_binding(names, root, siblings, child, binding)
    return binding


def _binding_statement_path(names: Names, node: ast.AST, scope: ast.AST) -> list[tuple[ast.AST, str, list[ast.AST], ast.AST]]:
    path: list[tuple[ast.AST, ast.AST]] = []
    current = node
    while current is not scope and id(current) in names._parents:
        parent = names._parents[id(current)]
        path.append((parent, current))
        current = parent
    statements: list[tuple[ast.AST, str, list[ast.AST], ast.AST]] = []
    for parent, child in reversed(path):
        for field, siblings in ast.iter_fields(parent):
            if isinstance(siblings, list) and child in siblings:
                statements.append((parent, field, siblings, child))
    return statements


def _class_prefix_binding(names: Names, root: str, siblings: list[ast.AST], child: ast.AST | None, binding: _ClassBinding | None) -> _ClassBinding | None:
    for statement in siblings:
        if statement is child:
            break
        if isinstance(statement, ast.stmt):
            assigned = _statement_binding(names, root, statement, binding)
            if assigned is not None:
                binding = assigned
        elif isinstance(statement, ast.ExceptHandler):
            binding = _handler_prefix_binding(names, root, statement, binding)
    return binding


def _handler_prefix_binding(names: Names, root: str, handler: ast.ExceptHandler, binding: _ClassBinding | None) -> _ClassBinding | None:
    if handler.type is not None and root in names._effects.definite[id(handler.type)]:
        binding = _ClassBinding(True)
    parent = names._parents[id(handler)]
    if isinstance(parent, ast.TryStar) and _class_root_externalized(root, handler):
        return _ClassBinding(False)
    return binding


def _active_class_binding(names: Names, root: str, parent: ast.AST, field: str, binding: _ClassBinding | None) -> _ClassBinding | None:
    binding = _block_entry_binding(names, root, parent, field, binding)
    return _ClassBinding(True) if root in _block_bindings(names, parent, field) else binding


def _block_entry_binding(names: Names, root: str, parent: ast.AST, field: str, binding: _ClassBinding | None) -> _ClassBinding | None:
    if isinstance(parent, (ast.Try, ast.TryStar)):
        if field == "orelse":
            return _class_prefix_binding(names, root, parent.body, None, binding)
        if field in ("handlers", "finalbody") and _class_root_externalized(root, parent):
            return _ClassBinding(False)
    if isinstance(parent, (ast.For, ast.AsyncFor, ast.While)) and field in ("body", "orelse"):
        if any(_class_root_externalized(root, child) for child in parent.body):
            return _ClassBinding(False)
    return binding


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
    if isinstance(statement, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.TryStar, ast.Match)):
        return False if _class_root_externalized(root, statement) else None
    return _class_direct_binding(names, root, statement)


def _statement_binding(names: Names, root: str, statement: ast.stmt, before: _ClassBinding | None) -> _ClassBinding | None:
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        imported = _imports_in(names._package, statement).get(root)
        return _ClassBinding(False, imported) if imported is not None else None
    if isinstance(statement, ast.If):
        binding = _conditional_class_binding(names, root, statement, before)
        if binding is not None:
            return binding
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return _completed_with_binding(root, statement)
    local = _class_binding_kind(names, root, statement)
    return _ClassBinding(local) if local is not None else None


def _completed_with_binding(root: str, statement: ast.With | ast.AsyncWith) -> _ClassBinding | None:
    if _class_root_externalized(root, statement):
        return _ClassBinding(False)
    target = statement.items[0].optional_vars
    if isinstance(target, ast.Name) and target.id == root:
        return _ClassBinding(True)
    return None


def _class_direct_binding(names: Names, root: str, statement: ast.stmt) -> bool | None:
    if root in _imports_in(names._package, statement) or _deleted_in(root, statement):
        return False
    if isinstance(statement, ast.AnnAssign) and statement.value is None:
        return None
    return True if _class_evaluated_local(names, root, statement) else None


def _class_evaluated_local(names: Names, root: str, statement: ast.stmt) -> bool:
    if isinstance(statement, (ast.Expr, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and root in names._effects.definite[id(statement)]:
        return True
    return isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign, *_FUNCTION, ast.ClassDef)) and root in _assigned_in(statement, include_lambda_defaults=False)


def _conditional_class_binding(names: Names, root: str, statement: ast.If, before: _ClassBinding | None) -> _ClassBinding | None:
    truth = _literal_truth(statement.test)
    if truth is not None:
        return _class_branch_binding(names, root, statement, "body" if truth else "orelse", before)
    bindings = [_class_branch_binding(names, root, statement, field, before) for field in ("body", "orelse")]
    return _ClassBinding(True) if all(binding is not None and binding.local for binding in bindings) else None


def _class_branch_binding(names: Names, root: str, statement: ast.If, field: str, before: _ClassBinding | None) -> _ClassBinding | None:
    entry = _active_class_binding(names, root, statement, field, before)
    return _class_prefix_binding(names, root, getattr(statement, field), None, entry)


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
    keyword = _class_keyword_binding(names, node)
    if keyword is not None and keyword.imported is not None:
        return keyword.imported.canonical, keyword.imported.symbol
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
    tree: ast.Module, bindings: _BindingEffects, *, conditional_paths: bool = False,
    ordinary_roots: dict[int, frozenset[str]] | None = None
) -> dict[int, frozenset[str]]:
    return _mask_projection(tree, bindings, conditional_paths=conditional_paths, ordinary_roots=ordinary_roots).masks


def _mask_projection(
    tree: ast.Module, bindings: _BindingEffects, *, conditional_paths: bool = False,
    ordinary_roots: dict[int, frozenset[str]] | None = None
) -> _MaskProjection:
    masks: dict[int, frozenset[str]] = {}
    frames: dict[int, frozenset[str]] = {}
    pending: list[_MaskedNode] = [(tree, frozenset(), False)]
    while pending:
        node, masked, class_namespace = pending.pop()
        frames[id(node)] = masked
        if masked and isinstance(node, (ast.Name, ast.Attribute)):
            masks[id(node)] = masked
        pending.extend(_masked_children(node, masked, class_namespace, bindings, conditional_paths, ordinary_roots))
    return _MaskProjection(masks, frames)


def _masked_children(
    node: ast.AST, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects, conditional_paths: bool,
    ordinary_roots: dict[int, frozenset[str]] | None = None
) -> list[_MaskedNode]:
    masked = _statement_masks(node, masked, class_namespace, conditional_paths)
    if conditional_paths and isinstance(node, (ast.IfExp, ast.BoolOp)):
        return _truth_masked_children(node, masked, class_namespace, bindings)
    if isinstance(node, ast.ClassDef):
        return _class_header_masked_children(node, masked, class_namespace, bindings, conditional_paths, ordinary_roots)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [
            (child, frozenset(), False) if isinstance(child, ast.stmt) else (child, masked, class_namespace)
            for child in ast.iter_child_nodes(node)
        ]
    if isinstance(node, ast.Lambda):
        return _lambda_masked_children(node, masked, class_namespace, bindings)
    if not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return _ordinary_masked_children(node, masked, class_namespace, bindings, ordinary_roots)
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
    *, reachable: bool = False,
) -> set[str]:
    if isinstance(node, ast.BoolOp):
        return _boolean_condition_bindings(node, truth, conditions, reachable=reachable)
    if isinstance(node, ast.IfExp):
        return _conditional_condition_bindings(node, truth, conditions, reachable=reachable)
    if isinstance(node, ast.Compare) and truth:
        return _comparison_condition_bindings(node, bindings)
    if isinstance(node, (ast.NamedExpr, ast.UnaryOp)):
        return _wrapped_condition_bindings(node, truth, conditions, reachable)
    return set()


def _wrapped_condition_bindings(
    node: ast.NamedExpr | ast.UnaryOp,
    truth: bool,
    conditions: dict[tuple[int, bool], frozenset[str]],
    reachable: bool,
) -> set[str]:
    if isinstance(node, ast.NamedExpr):
        return set(conditions[(id(node.value), truth)]) if reachable else set()
    if isinstance(node.op, ast.Not):
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
    *, reachable: bool = False,
) -> set[str]:
    prefix: set[str] = set()
    if isinstance(node.op, ast.And) == truth:
        for value in node.values:
            prefix.update(conditions[(id(value), truth)])
        return prefix
    paths: list[set[str]] = []
    for value in node.values:
        if not reachable or _truth_possible(value, truth):
            paths.append(prefix | set(conditions[(id(value), truth)]))
        if reachable and not _truth_possible(value, not truth):
            break
        prefix.update(conditions[(id(value), not truth)])
    return set.intersection(*paths) if paths else set()


def _conditional_condition_bindings(
    node: ast.IfExp,
    truth: bool,
    conditions: dict[tuple[int, bool], frozenset[str]],
    *, reachable: bool = False,
) -> set[str]:
    test_truth = _literal_truth(node.test)
    if test_truth is not None:
        branch = node.body if test_truth else node.orelse
        return set(conditions[(id(node.test), test_truth)] | conditions[(id(branch), truth)])
    paths = [
        set(conditions[(id(node.test), branch_truth)] | conditions[(id(branch), truth)])
        for branch_truth, branch in [(True, node.body), (False, node.orelse)]
        if not reachable or (_truth_possible(node.test, branch_truth) and _truth_possible(branch, truth))
    ]
    return set.intersection(*paths) if paths else set()


def _truth_possible(node: ast.AST, truth: bool) -> bool:
    literal = _literal_truth(node)
    if literal is not None:
        return literal == truth
    if isinstance(node, ast.NamedExpr):
        return _truth_possible(node.value, truth)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _truth_possible(node.operand, not truth)
    if isinstance(node, ast.BoolOp):
        return _boolean_truth_possible(node, truth)
    if isinstance(node, ast.IfExp):
        return _conditional_truth_possible(node, truth)
    return True


def _boolean_truth_possible(node: ast.BoolOp, truth: bool) -> bool:
    possibilities = [_truth_possible(value, truth) for value in node.values]
    return all(possibilities) if isinstance(node.op, ast.And) == truth else any(possibilities)


def _conditional_truth_possible(node: ast.IfExp, truth: bool) -> bool:
    return any(
        _truth_possible(node.test, branch_truth) and _truth_possible(branch, truth)
        for branch_truth, branch in [(True, node.body), (False, node.orelse)]
    )


def _class_header_masked_children(
    node: ast.ClassDef, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects, conditional_paths: bool,
    ordinary_roots: dict[int, frozenset[str]] | None = None
) -> list[_MaskedNode]:
    header = [*node.decorator_list, *node.bases, *node.keywords]
    children = _sequence_masked_children(header, masked, class_namespace, bindings)
    body = _ordinary_class_body(node.body, frozenset(), bindings, roots=ordinary_roots) if ordinary_roots is not None else _sequence_masked_children(node.body, frozenset(), True, bindings)
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
        effects = bindings.definite[id(statement)]
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            effects = bindings.definite[id(statement.items[0].context_expr)]
        masked = _retained_class_masks(masked | effects, statement)
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
    node: ast.AST, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects,
    ordinary_roots: dict[int, frozenset[str]] | None
) -> list[_MaskedNode]:
    if class_namespace and ordinary_roots is not None and isinstance(node, (ast.Tuple, ast.List)) and isinstance(node.ctx, ast.Store):
        return _ordinary_target_sequence(node.elts, masked, bindings, ordinary_roots.get(id(node), frozenset()))
    if isinstance(node, ast.expr):
        return _ordinary_expression_children(node, masked, class_namespace, bindings)
    if class_namespace and ordinary_roots is not None:
        return _class_statement_children(node, masked, bindings, ordinary_roots.get(id(node), frozenset()))
    return [(child, masked, class_namespace) for child in ast.iter_child_nodes(node)]


def _ordinary_expression_children(
    node: ast.expr, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects
) -> list[_MaskedNode]:
    if isinstance(node, ast.IfExp):
        branch_mask = masked | bindings.definite[id(node.test)]
        return [(node.test, masked, class_namespace), (node.body, branch_mask, class_namespace), (node.orelse, branch_mask, class_namespace)]
    if isinstance(node, ast.Dict):
        children = [part for pair in zip(node.keys, node.values) for part in pair if part is not None]
        return _sequence_masked_children(children, masked, class_namespace, bindings)
    return _sequence_masked_children(list(ast.iter_child_nodes(node)), masked, class_namespace, bindings)


def _class_statement_children(node: ast.AST, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> list[_MaskedNode]:
    found: list[_MaskedNode] = []
    for field, value in ast.iter_fields(node):
        if isinstance(value, list):
            children = [child for child in value if isinstance(child, ast.AST)]
            found.extend(_ordinary_class_field(node, field, children, masked, bindings, retain))
        elif isinstance(value, ast.AST):
            entry = _ordinary_target_masks(node, field, masked, bindings, retain)
            found.append((value, entry, True))
    return found


def _ordinary_target_masks(node: ast.AST, field: str, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> frozenset[str]:
    if isinstance(node, (ast.For, ast.AsyncFor, ast.While)) and field in ("target", "test"):
        return _ordinary_loop_read_masks(node, masked, bindings, retain)
    preceding = _ordinary_target_input(node, field)
    return masked | (retain & bindings.definite[id(preceding)]) if preceding is not None else masked


def _ordinary_target_input(node: ast.AST, field: str) -> ast.AST | None:
    if isinstance(node, ast.withitem) and field == "optional_vars":
        return node.context_expr
    if isinstance(node, (ast.Assign, ast.AnnAssign)) and field in ("target", "targets"):
        return node.value
    if isinstance(node, ast.AugAssign) and field == "value":
        return node.target
    return None


def _ordinary_target_sequence(children: list[ast.AST], masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> list[_MaskedNode]:
    found: list[_MaskedNode] = []
    for child in children:
        found.append((child, masked, True))
        masked = masked | (retain & (bindings.definite[id(child)] | frozenset(_stored_names(child))))
    return found


def _ordinary_class_field(
    node: ast.AST, field: str, children: list[ast.AST], masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]
) -> list[_MaskedNode]:
    if field == "targets" and isinstance(node, ast.Assign):
        entry = _ordinary_target_masks(node, field, masked, bindings, retain)
        return _ordinary_target_sequence(children, entry, bindings, retain)
    if field == "items" and isinstance(node, (ast.With, ast.AsyncWith)):
        return _ordinary_with_items(node, masked, bindings, retain)
    if field in ("body", "orelse", "finalbody"):
        entry = _ordinary_clause_masks(node, field, masked, bindings, retain)
        return _ordinary_class_body(children, entry, bindings, retain=retain)
    if field == "handlers" and isinstance(node, (ast.Try, ast.TryStar)):
        return _ordinary_handler_children(node, masked, bindings, retain)
    return [(child, masked, True) for child in children]


def _ordinary_class_body(
    children: list[ast.AST], masked: frozenset[str], bindings: _BindingEffects, *, retain: frozenset[str] | None = None,
    roots: dict[int, frozenset[str]] | None = None
) -> list[_MaskedNode]:
    """Carry existing local proofs through a class statement prefix."""
    found: list[_MaskedNode] = []
    for child in children:
        found.append((child, masked, True))
        allowed = masked | bindings.definite[id(child)] if retain is None else retain
        if roots is not None:
            allowed = allowed | roots.get(id(child), frozenset())
        masked = _ordinary_exit_masks(child, masked, bindings, allowed)
    return found


def _ordinary_clause_masks(node: ast.AST, field: str, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> frozenset[str]:
    if isinstance(node, (ast.Try, ast.TryStar)):
        flow = _ordinary_body_flow(node.body, masked, bindings, retain)
        if field == "finalbody":
            return _ordinary_all_masks(_ordinary_try_paths(node, masked, bindings, retain), masked)
        return flow.normal if field == "orelse" and flow.normal is not None else masked
    if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
        return _ordinary_loop_clause_masks(node, field, masked, bindings, retain)
    if isinstance(node, ast.If):
        return masked | (retain & bindings.conditional[(id(node.test), field == "body")])
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return _ordinary_with_body_masks(node, masked, bindings, retain)
    return masked


def _ordinary_with_item_masks(item: ast.withitem, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> frozenset[str]:
    targets = bindings.definite[id(item.optional_vars)] | frozenset(_stored_names(item.optional_vars)) if item.optional_vars is not None else frozenset()
    return masked | (retain & (bindings.definite[id(item.context_expr)] | targets))


def _ordinary_with_items(node: ast.With | ast.AsyncWith, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> list[_MaskedNode]:
    children: list[_MaskedNode] = []
    for item in node.items:
        children.append((item, masked, True))
        masked = _ordinary_with_item_masks(item, masked, bindings, retain)
    return children


def _ordinary_with_body_masks(node: ast.With | ast.AsyncWith, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> frozenset[str]:
    for item in node.items:
        masked = _ordinary_with_item_masks(item, masked, bindings, retain)
    return masked


def _ordinary_loop_clause_masks(node: ast.For | ast.AsyncFor | ast.While, field: str, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> frozenset[str]:
    entry, body = _ordinary_loop_body(node, masked, bindings, retain)
    if field == "body":
        return entry
    if field == "orelse":
        header = _ordinary_loop_header(node, masked, bindings, retain)
        if _empty_class_loop(node):
            return header
        return _ordinary_loop_exhaustion(node, header, body, bindings, retain) or frozenset()
    return masked


def _ordinary_handler_children(node: ast.Try | ast.TryStar, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> list[_MaskedNode]:
    found: list[_MaskedNode] = []
    flow = _ordinary_body_flow(node.body, masked, bindings, retain)
    entry = flow.raises if flow.raises is not None else _ordinary_all_masks(flow, masked)
    for handler in node.handlers:
        if handler.type is not None:
            found.append((handler.type, entry, True))
            entry = entry | (retain & bindings.definite[id(handler.type)])
        alias = retain & {handler.name} if handler.name is not None else frozenset()
        found.extend(_ordinary_class_body(handler.body, entry | alias, bindings, retain=retain))
        if isinstance(node, ast.TryStar):
            entry = _ordinary_all_masks(_ordinary_handler_flow(handler, entry, bindings, retain), entry)
    return found


def _ordinary_mask_meet(*states: frozenset[str] | None) -> frozenset[str] | None:
    paths = [state for state in states if state is not None]
    return frozenset.intersection(*paths) if paths else None


def _ordinary_flow_join(*flows: _ClassMaskFlow) -> _ClassMaskFlow:
    return _ClassMaskFlow(
        _ordinary_mask_meet(*(flow.normal for flow in flows)),
        _ordinary_mask_meet(*(flow.breaks for flow in flows)),
        _ordinary_mask_meet(*(flow.continues for flow in flows)),
        _ordinary_mask_meet(*(flow.raises for flow in flows)),
    )


def _ordinary_all_masks(flow: _ClassMaskFlow, fallback: frozenset[str]) -> frozenset[str]:
    result = _ordinary_mask_meet(flow.normal, flow.breaks, flow.continues, flow.raises)
    return result if result is not None else fallback


def _ordinary_body_flow(statements: list[ast.stmt], masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> _ClassMaskFlow:
    flow = _ClassMaskFlow(masked)
    for statement in statements:
        if flow.normal is None:
            break
        after = _ordinary_statement_flow(statement, flow.normal, bindings, retain)
        flow = _ordinary_flow_join(_ClassMaskFlow(None, flow.breaks, flow.continues, flow.raises), after)
    return flow


def _ordinary_exit_masks(node: ast.AST, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> frozenset[str]:
    flow = _ordinary_statement_flow(node, masked, bindings, retain)
    return flow.normal if flow.normal is not None else _ordinary_all_masks(flow, masked)


def _ordinary_statement_flow(node: ast.AST, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> _ClassMaskFlow:
    if isinstance(node, ast.If):
        return _ordinary_if_flow(node, masked, bindings, retain)
    if isinstance(node, (ast.Try, ast.TryStar)):
        flow = _ordinary_try_paths(node, masked, bindings, retain)
        return _ordinary_finally_flow(flow, node.finalbody, bindings, retain)
    if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
        return _ordinary_loop_flow(node, masked, bindings, retain)
    return _ordinary_simple_flow(node, masked, bindings, retain)


def _ordinary_simple_flow(node: ast.AST, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> _ClassMaskFlow:
    effects = bindings.definite[id(node)] | _ordinary_completed_targets(node)
    after = _retained_ordinary_class_masks(masked, node) | (retain & effects)
    if isinstance(node, ast.Break):
        return _ClassMaskFlow(None, breaks=after)
    if isinstance(node, ast.Continue):
        return _ClassMaskFlow(None, continues=after)
    if isinstance(node, ast.Raise):
        return _ClassMaskFlow(None, raises=after)
    if isinstance(node, ast.Assert) and _literal_truth(node.test) is False:
        return _ordinary_assert_flow(node, after, bindings, retain)
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return _ordinary_with_flow(node, masked, bindings, retain)
    return _ClassMaskFlow(after)


def _ordinary_completed_targets(node: ast.AST) -> frozenset[str]:
    if isinstance(node, ast.Assign):
        return frozenset(name for target in node.targets for name in _stored_names(target))
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
        return frozenset(_stored_names(node.target))
    return frozenset()


def _ordinary_assert_flow(node: ast.Assert, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> _ClassMaskFlow:
    if node.msg is not None:
        masked = masked | (retain & bindings.definite[id(node.msg)])
    return _ClassMaskFlow(None, raises=masked)


def _ordinary_with_flow(node: ast.With | ast.AsyncWith, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> _ClassMaskFlow:
    entry = _ordinary_with_body_masks(node, masked, bindings, retain)
    flow = _ordinary_body_flow(node.body, entry, bindings, retain)
    # A context manager can suppress a raised exception.
    normal = _ordinary_mask_meet(flow.normal, flow.raises)
    first = node.items[0]
    if len(node.items) > 1 or (first.optional_vars is not None and not isinstance(first.optional_vars, ast.Name)):
        # Earlier managers can suppress later entry or target-unpacking failures.
        skipped = masked | (retain & bindings.definite[id(first.context_expr)])
        if isinstance(first.optional_vars, ast.Name):
            skipped = skipped | (retain & {first.optional_vars.id})
        normal = _ordinary_mask_meet(normal, skipped)
    return _ClassMaskFlow(normal, flow.breaks, flow.continues, flow.raises)


def _ordinary_if_flow(node: ast.If, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> _ClassMaskFlow:
    truth = _literal_truth(node.test)
    if truth is not None:
        entry = masked | (retain & bindings.conditional[(id(node.test), truth)])
        return _ordinary_body_flow(node.body if truth else node.orelse, entry, bindings, retain)
    positive = masked | (retain & bindings.conditional[(id(node.test), True)])
    negative = masked | (retain & bindings.conditional[(id(node.test), False)])
    return _ordinary_flow_join(_ordinary_body_flow(node.body, positive, bindings, retain), _ordinary_body_flow(node.orelse, negative, bindings, retain))


def _ordinary_try_paths(node: ast.Try | ast.TryStar, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> _ClassMaskFlow:
    body = _ordinary_body_flow(node.body, masked, bindings, retain)
    normal = _ordinary_body_flow(node.orelse, body.normal, bindings, retain) if body.normal is not None else _ClassMaskFlow(None)
    paths = [normal, _ClassMaskFlow(None, body.breaks, body.continues)]
    entry = body.raises if body.raises is not None else _ordinary_all_masks(body, masked)
    for handler in node.handlers:
        if handler.type is not None:
            entry = entry | (retain & bindings.definite[id(handler.type)])
        after = _ordinary_handler_flow(handler, entry, bindings, retain)
        paths.append(after)
        if isinstance(node, ast.TryStar):
            entry = _ordinary_all_masks(after, entry)
    if body.raises is not None:
        paths.append(_ClassMaskFlow(None, raises=entry))
    return _ordinary_flow_join(*paths)


def _ordinary_handler_flow(node: ast.ExceptHandler, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> _ClassMaskFlow:
    effects = bindings.definite[id(node.type)] if node.type is not None else frozenset()
    alias = retain & {node.name} if node.name is not None else frozenset()
    flow = _ordinary_body_flow(node.body, masked | alias | (effects & retain), bindings, retain)
    return _ClassMaskFlow(*(state - alias if state is not None else None for state in (flow.normal, flow.breaks, flow.continues, flow.raises)))


def _ordinary_finally_flow(flow: _ClassMaskFlow, statements: list[ast.stmt], bindings: _BindingEffects, retain: frozenset[str]) -> _ClassMaskFlow:
    paths: list[_ClassMaskFlow] = []
    for index, state in enumerate((flow.normal, flow.breaks, flow.continues, flow.raises)):
        if state is None:
            continue
        final = _ordinary_body_flow(statements, state, bindings, retain)
        prior: list[frozenset[str] | None] = [None, None, None, None]
        prior[index] = final.normal
        paths.append(_ordinary_flow_join(_ClassMaskFlow(*prior), _ClassMaskFlow(None, final.breaks, final.continues, final.raises)))
    return _ordinary_flow_join(*paths)


def _ordinary_loop_header(node: ast.For | ast.AsyncFor | ast.While, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> frozenset[str]:
    header = node.test if isinstance(node, ast.While) else node.iter
    return masked | (retain & bindings.definite[id(header)])


def _ordinary_loop_body(node: ast.For | ast.AsyncFor | ast.While, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> tuple[frozenset[str], _ClassMaskFlow]:
    entry = _ordinary_loop_header(node, masked, bindings, retain)
    targets = bindings.definite[id(node.target)] | frozenset(_stored_names(node.target)) if isinstance(node, (ast.For, ast.AsyncFor)) else frozenset()
    renewal = bindings.conditional[(id(node.test), True)] if isinstance(node, ast.While) else targets
    entry = entry | (retain & renewal)
    body = _ordinary_body_flow(node.body, entry, bindings, retain)
    repeat = _ordinary_mask_meet(body.normal, body.continues)
    if repeat is None or _single_class_iteration(node):
        return entry, body
    repeated = (entry & repeat) | (retain & renewal)
    if repeated == entry:
        return entry, body
    return repeated, _ordinary_body_flow(node.body, repeated, bindings, retain)


def _ordinary_loop_read_masks(node: ast.For | ast.AsyncFor | ast.While, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> frozenset[str]:
    header = masked if isinstance(node, ast.While) else _ordinary_loop_header(node, masked, bindings, retain)
    if _single_class_iteration(node):
        return header
    _, body = _ordinary_loop_body(node, masked, bindings, retain)
    repeat = _ordinary_mask_meet(body.normal, body.continues)
    return header if repeat is None else header & repeat


def _ordinary_loop_exhaustion(node: ast.For | ast.AsyncFor | ast.While, masked: frozenset[str], body: _ClassMaskFlow, bindings: _BindingEffects, retain: frozenset[str]) -> frozenset[str] | None:
    ended = _ordinary_mask_meet(body.normal, body.continues)
    if isinstance(node, ast.While):
        if _literal_truth(node.test) is True:
            return None
        masked = masked | (retain & bindings.conditional[(id(node.test), False)])
        if ended is not None:
            ended = ended | (retain & bindings.conditional[(id(node.test), False)])
    if _nonempty_class_loop(node):
        return ended
    return _ordinary_mask_meet(masked, ended)


def _ordinary_loop_flow(node: ast.For | ast.AsyncFor | ast.While, masked: frozenset[str], bindings: _BindingEffects, retain: frozenset[str]) -> _ClassMaskFlow:
    header = _ordinary_loop_header(node, masked, bindings, retain)
    if _empty_class_loop(node):
        return _ordinary_body_flow(node.orelse, header, bindings, retain)
    _, body = _ordinary_loop_body(node, masked, bindings, retain)
    ended = _ordinary_loop_exhaustion(node, header, body, bindings, retain)
    normal = _ordinary_body_flow(node.orelse, ended, bindings, retain) if ended is not None else _ClassMaskFlow(None)
    return _ordinary_flow_join(normal, _ClassMaskFlow(body.breaks, raises=body.raises))


def _nonempty_class_loop(node: ast.AST) -> bool:
    return isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)) and any(not isinstance(item, ast.Starred) for item in node.iter.elts)


def _empty_class_loop(node: ast.AST) -> bool:
    if isinstance(node, ast.While):
        return not _truth_possible(node.test, True)
    return isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.iter, (ast.Tuple, ast.List)) and not node.iter.elts


def _single_class_iteration(node: ast.AST) -> bool:
    return _empty_class_loop(node) or (
        isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List))
        and len(node.iter.elts) == 1 and not isinstance(node.iter.elts[0], ast.Starred)
    )


def _retained_ordinary_class_masks(masked: frozenset[str], node: ast.AST) -> frozenset[str]:
    return frozenset(root for root in masked if not _ordinary_class_externalized(root, node))


def _ordinary_class_externalized(root: str, node: ast.AST) -> bool:
    if isinstance(node, (ast.ClassDef, *_FUNCTION)):
        return False
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.Delete)):
        return _class_root_externalized(root, node)
    if isinstance(node, ast.ExceptHandler) and node.name == root:
        return True
    children = node.orelse if _empty_class_loop(node) else _active_binding_children(node)
    return any(_ordinary_class_externalized(root, child) for child in children)


def _conditional_masked_children(
    node: ast.IfExp, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects
) -> list[_MaskedNode]:
    return [
        (node.test, masked, class_namespace),
        (node.body, masked | bindings.conditional[(id(node.test), True)], class_namespace),
        (node.orelse, masked | bindings.conditional[(id(node.test), False)], class_namespace),
    ]


def _truth_masked_children(
    node: ast.IfExp | ast.BoolOp, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects
) -> list[_MaskedNode]:
    if isinstance(node, ast.BoolOp):
        return _boolean_masked_children(node, masked, class_namespace, bindings)
    return _conditional_masked_children(node, masked, class_namespace, bindings)


def _boolean_masked_children(
    node: ast.BoolOp, masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects
) -> list[_MaskedNode]:
    children: list[_MaskedNode] = []
    truth = isinstance(node.op, ast.And)
    for value in node.values:
        children.append((value, masked, class_namespace))
        masked = masked | bindings.conditional[(id(value), truth)]
    return children


def _sequence_masked_children(
    children: list[ast.AST], masked: frozenset[str], class_namespace: bool, bindings: _BindingEffects
) -> list[_MaskedNode]:
    found: list[_MaskedNode] = []
    for child in children:
        found.append((child, masked, class_namespace))
        masked = masked | bindings.definite[id(child)]
    return found


def _expression_bindings(tree: ast.Module, *, reachable: bool = False) -> _BindingEffects:
    bindings: dict[int, frozenset[str]] = {}
    conditions: dict[tuple[int, bool], frozenset[str]] = {}
    for node in reversed(_module_nodes(tree)):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            found = _evaluated_definition_bindings(node, bindings)
        elif isinstance(node, ast.stmt):
            found = _evaluated_statement_bindings(node, bindings)
        else:
            found = _evaluated_bindings(node, bindings)
        if reachable and isinstance(node, (ast.BoolOp, ast.IfExp)):
            found.update(_completed_expression_bindings(node, bindings, conditions))
        bindings[id(node)] = frozenset(found)
        for truth in (False, True):
            conditions[(id(node), truth)] = frozenset(found | _condition_path_bindings(node, truth, bindings, conditions, reachable=reachable))
    return _BindingEffects(bindings, conditions)


def _completed_expression_bindings(
    node: ast.BoolOp | ast.IfExp,
    bindings: dict[int, frozenset[str]],
    conditions: dict[tuple[int, bool], frozenset[str]],
) -> set[str]:
    paths = [
        _condition_path_bindings(node, truth, bindings, conditions, reachable=True)
        for truth in (False, True) if _truth_possible(node, truth)
    ]
    return set.intersection(*paths) if paths else set()


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
