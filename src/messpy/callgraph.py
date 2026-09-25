"""Intra-module call graph.

One place answers "what does this ``ast.Call`` call?" for every rule. It follows
lexical scopes, global and nonlocal declarations, shadowing bindings,
comprehension targets, receiver method calls on ``self`` or ``cls``, and import
aliases. Analysis stays within one module.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

__all__ = ["CallGraph", "CallSite", "build_call_graph"]


@dataclass(frozen=True)
class CallSite:
    """The first call from a caller to one callable it resolves to."""

    caller: ast.AST
    callee: ast.AST
    name: str
    line: int


@dataclass(frozen=True)
class CallGraph:
    """The callables of one module and the resolved calls between them."""

    callables: tuple[ast.AST, ...]
    _links: _CallLinks

    def callees(self, caller: ast.AST) -> tuple[CallSite, ...]:
        return self._links.callees.get(id(caller), ())

    def callers(self, callee: ast.AST) -> tuple[CallSite, ...]:
        return self._links.callers.get(id(callee), ())

    def reachable_from(self, caller: ast.AST) -> set[ast.AST]:
        """Every callable the caller reaches through one or more calls."""
        reached: set[ast.AST] = set()
        pending = [caller]
        while pending:
            for site in self.callees(pending.pop()):
                if site.callee not in reached:
                    reached.add(site.callee)
                    pending.append(site.callee)
        return reached

    def resolve_target(self, call: ast.Call) -> ast.AST | None:
        """The callable in this module that the call calls, if any."""
        return self._links.targets.get(id(call))

    def qualified_name(self, call: ast.Call) -> str:
        """The dotted name the call calls after import aliases; empty when a local binding hides it."""
        names = self._links.qualified_names
        if not names:
            names.update(_resolved_call_names(self._links.tree, self._links.masks))
        return names.get(id(call), "")

    def method_class(self, callable_node: ast.AST) -> ast.ClassDef | None:
        return self._links.classes.get(id(callable_node))


@dataclass(frozen=True)
class _CallLinks:
    tree: ast.Module
    callees: dict[int, tuple[CallSite, ...]]
    callers: dict[int, tuple[CallSite, ...]]
    targets: dict[int, ast.AST]
    masks: dict[int, frozenset[str]]
    qualified_names: dict[int, str]
    classes: dict[int, ast.ClassDef]


def build_call_graph(tree: ast.Module) -> CallGraph:
    index = _index_callables(tree)
    masks = _comprehension_masks(tree)
    resolved = _resolved_calls(tree, index, masks)
    callees = _call_edges(index, resolved)
    return CallGraph(
        callables=tuple(index.nodes.values()),
        _links=_CallLinks(
            tree=tree,
            callees=callees,
            callers=_reverse_edges(callees),
            targets={id(call): index.nodes[callee_id] for _caller_id, call, callee_id in resolved},
            masks=masks,
            qualified_names={},
            classes=index.owners,
        ),
    )


def _resolved_calls(
    tree: ast.Module, index: _CallableIndex, masks: dict[int, frozenset[str]]
) -> list[tuple[int, ast.Call, int]]:
    resolved: list[tuple[int, ast.Call, int]] = []
    for caller_id, node in ((index.module_id, tree), *index.nodes.items()):
        for child in _evaluated_nodes(node):
            if not isinstance(child, ast.Call):
                continue
            callee_id = _resolved_callee(index, caller_id, child, masks)
            if callee_id is not None:
                resolved.append((caller_id, child, callee_id))
    return resolved


def _call_edges(
    index: _CallableIndex, resolved: Sequence[tuple[int, ast.Call, int]]
) -> dict[int, tuple[CallSite, ...]]:
    edges: dict[int, list[CallSite]] = {}
    linked: set[tuple[int, int]] = set()
    for caller_id, call, callee_id in resolved:
        if caller_id not in index.nodes or (caller_id, callee_id) in linked:
            continue
        linked.add((caller_id, callee_id))
        edges.setdefault(caller_id, []).append(
            CallSite(
                index.nodes[caller_id],
                index.nodes[callee_id],
                _called_name(call, index, callee_id),
                call.lineno,
            )
        )
    return {caller_id: tuple(sites) for caller_id, sites in edges.items()}


def _reverse_edges(edges: dict[int, tuple[CallSite, ...]]) -> dict[int, tuple[CallSite, ...]]:
    reverse: dict[int, list[CallSite]] = {}
    for sites in edges.values():
        for site in sites:
            reverse.setdefault(id(site.callee), []).append(site)
    return {callee_id: tuple(sites) for callee_id, sites in reverse.items()}


def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return parents


@dataclass(frozen=True)
class _CallableIndex:
    nodes: dict[int, ast.AST]
    labels: dict[int, str]
    bindings: dict[int, dict[str, int]]
    shadows: dict[int, set[str]]
    enclosing: dict[int, tuple[int, ...]]
    class_methods: dict[int, dict[str, int]]
    callable_class: dict[int, int]
    receivers: dict[int, str]
    owners: dict[int, ast.ClassDef]
    class_ids: frozenset[int]
    module_id: int
    declared_global: dict[int, set[str]]
    declared_nonlocal: dict[int, set[str]]


def _index_callables(tree: ast.Module) -> _CallableIndex:
    state = _visit_module(_BindState(), tree)
    return _CallableIndex(
        nodes=state.nodes,
        labels=state.labels,
        bindings=state.bindings,
        shadows=state.shadows,
        enclosing=state.enclosing,
        class_methods=state.class_methods,
        callable_class=state.callable_class,
        receivers=state.receivers,
        owners=state.owners,
        class_ids=state.class_ids,
        module_id=state.module_id,
        declared_global=state.declared_global,
        declared_nonlocal=state.declared_nonlocal,
    )


def _called_name(call: ast.Call, index: _CallableIndex, callee_id: int) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return index.labels[callee_id]


def _resolved_callee(
    index: _CallableIndex, caller_id: int, call: ast.Call, masks: dict[int, frozenset[str]]
) -> int | None:
    func = call.func
    if isinstance(func, ast.Name):
        if func.id in masks.get(id(call), ()):
            return None
        return _resolve_bare_name(index, caller_id, func.id)
    if isinstance(func, ast.Attribute):
        return _resolve_receiver_call(index, caller_id, func)
    if isinstance(func, ast.Lambda) and id(func) in index.nodes:
        return id(func)
    return None


def _comprehension_masks(tree: ast.Module) -> dict[int, frozenset[str]]:
    """Map each call to the comprehension targets that hide names at that call.

    Targets apply through lambdas but not definitions, and never to the
    outermost iterable, which is evaluated in the enclosing scope.
    """
    masks: dict[int, frozenset[str]] = {}
    pending: list[tuple[ast.AST, frozenset[str]]] = [(tree, frozenset())]
    while pending:
        node, masked = pending.pop()
        if isinstance(node, ast.Call) and masked:
            masks[id(node)] = masked
        pending.extend(_masked_children(node, masked))
    return masks


def _masked_children(node: ast.AST, masked: frozenset[str]) -> list[tuple[ast.AST, frozenset[str]]]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [(child, frozenset()) for child in ast.iter_child_nodes(node)]
    if not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return [(child, masked) for child in ast.iter_child_nodes(node)]
    outer_iter = node.generators[0].iter
    targets = masked.union(*(_stored_names(generator.target) for generator in node.generators))
    return [
        (child, masked if child is outer_iter else targets)
        for child in _comprehension_children(node)
    ]


def _comprehension_children(node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> list[ast.AST]:
    children: list[ast.AST] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.comprehension):
            children.extend(ast.iter_child_nodes(child))
        else:
            children.append(child)
    return children


def _resolve_bare_name(index: _CallableIndex, caller_id: int, name: str) -> int | None:
    scopes = (caller_id, *index.enclosing.get(caller_id, ()))
    for scope_id in scopes:
        if scope_id in index.class_ids:
            continue
        if name in index.declared_global.get(scope_id, ()):
            return _bound_callable(index, index.module_id, name)
        if name in index.declared_nonlocal.get(scope_id, ()):
            continue
        resolved, callee_id = _lookup_scope(index, scope_id, name)
        if resolved:
            return callee_id
    return None


def _lookup_scope(index: _CallableIndex, scope_id: int, name: str) -> tuple[bool, int | None]:
    if name in index.shadows.get(scope_id, ()):
        return True, None
    callee_id = index.bindings.get(scope_id, {}).get(name)
    if callee_id is not None:
        return True, callee_id
    return False, None


def _bound_callable(index: _CallableIndex, scope_id: int, name: str) -> int | None:
    resolved, callee_id = _lookup_scope(index, scope_id, name)
    if resolved:
        return callee_id
    return None


def _resolve_receiver_call(index: _CallableIndex, caller_id: int, attribute: ast.Attribute) -> int | None:
    value = attribute.value
    if not isinstance(value, ast.Name):
        return None
    class_id = _class_for_receiver(index, caller_id, value.id)
    if class_id is None:
        return None
    return index.class_methods.get(class_id, {}).get(attribute.attr)


def _class_for_receiver(index: _CallableIndex, caller_id: int, receiver_name: str) -> int | None:
    scopes = (caller_id, *index.enclosing.get(caller_id, ()))
    for scope_id in scopes:
        if index.receivers.get(scope_id) == receiver_name:
            return index.callable_class.get(scope_id)
        if scope_id in index.class_ids:
            continue
        resolved, _callee_id = _lookup_scope(index, scope_id, receiver_name)
        if resolved:
            return None
    return None


@dataclass(frozen=True)
class _BindState:
    nodes: dict[int, ast.AST] = field(default_factory=dict)
    labels: dict[int, str] = field(default_factory=dict)
    bindings: dict[int, dict[str, int]] = field(default_factory=dict)
    shadows: dict[int, set[str]] = field(default_factory=dict)
    enclosing: dict[int, tuple[int, ...]] = field(default_factory=dict)
    class_methods: dict[int, dict[str, int]] = field(default_factory=dict)
    callable_class: dict[int, int] = field(default_factory=dict)
    receivers: dict[int, str] = field(default_factory=dict)
    owners: dict[int, ast.ClassDef] = field(default_factory=dict)
    class_ids: frozenset[int] = frozenset()
    module_id: int = 0
    declared_global: dict[int, set[str]] = field(default_factory=dict)
    declared_nonlocal: dict[int, set[str]] = field(default_factory=dict)
    scopes: tuple[ast.AST, ...] = ()
    classes: tuple[ast.ClassDef, ...] = ()


def _visit_module(state: _BindState, node: ast.Module) -> _BindState:
    state = replace(state, module_id=id(node))
    state = _push_scope(state, node)
    for statement in node.body:
        state = _visit_binding(state, statement)
    return _pop_scope(state)


def _visit_binding(state: _BindState, node: ast.AST) -> _BindState:
    defined = _visit_definition(state, node)
    if defined is not None:
        return defined
    return _visit_binding_statement(state, node)


def _visit_definition(state: _BindState, node: ast.AST) -> _BindState | None:
    if isinstance(node, ast.ClassDef):
        return _visit_class(state, node)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _define_function(state, node)
    return None


def _visit_binding_statement(state: _BindState, node: ast.AST) -> _BindState:
    if isinstance(node, ast.Assign):
        return _visit_assign(state, node)
    if isinstance(node, ast.AnnAssign):
        return _visit_annotated_assignment(state, node)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return _visit_import(state, node)
    if isinstance(node, (ast.Lambda, ast.Global, ast.Nonlocal, ast.Match)):
        return _visit_runtime_binding(state, node)
    return _visit_binding_children(_shadow_statement(state, node), node)


def _visit_class(state: _BindState, node: ast.ClassDef) -> _BindState:
    state = _shadow(state, node.name)
    state = replace(state, class_ids=frozenset({*state.class_ids, id(node)}))
    for child in (*node.decorator_list, *node.bases):
        state = _visit_binding(state, child)
    for keyword in node.keywords:
        state = _visit_binding(state, keyword.value)
    state = replace(state, classes=(*state.classes, node))
    state = _push_scope(state, node)
    for statement in node.body:
        state = _visit_binding(state, statement)
    state = _pop_scope(state)
    return replace(state, classes=state.classes[:-1])


def _define_function(state: _BindState, node: ast.FunctionDef | ast.AsyncFunctionDef) -> _BindState:
    state = _bind_callable(state, node.name, node)
    state = _record_method(state, node)
    state = replace(
        state,
        enclosing={**state.enclosing, id(node): tuple(id(scope) for scope in reversed(state.scopes))},
    )
    state = _visit_enclosing_expressions(state, node.decorator_list, node.args)
    state = _push_scope(state, node)
    state = _shadow_arguments(state, node)
    for statement in node.body:
        state = _visit_binding(state, statement)
    return _pop_scope(state)


def _visit_assign(state: _BindState, node: ast.Assign) -> _BindState:
    bound = _bind_lambda_assignment(state, node)
    if bound is not None:
        return bound
    for target in node.targets:
        state = _shadow_target(state, target)
    return _visit_binding_children(state, node)


def _visit_annotated_assignment(state: _BindState, node: ast.AnnAssign) -> _BindState:
    if isinstance(node.target, ast.Name) and isinstance(node.value, ast.Lambda):
        return _bind_lambda(state, node.target.id, node.value)
    state = _shadow_target(state, node.target)
    return _visit_binding_children(state, node)


def _visit_import(state: _BindState, node: ast.Import | ast.ImportFrom) -> _BindState:
    for alias in node.names:
        bound_name = alias.asname or (alias.name.split(".", 1)[0] if isinstance(node, ast.Import) else alias.name)
        state = _shadow(state, bound_name)
    return state


def _visit_runtime_binding(state: _BindState, node: ast.AST) -> _BindState:
    state = _record_runtime_binding(state, node)
    if isinstance(node, ast.Match):
        return _visit_binding_children(state, node)
    return state


def _visit_binding_children(state: _BindState, node: ast.AST) -> _BindState:
    for child in ast.iter_child_nodes(node):
        state = _visit_binding(state, child)
    return state


def _bind_callable(state: _BindState, name: str, node: ast.AST) -> _BindState:
    return _bind_name(_register_callable(state, node), name, node)


def _register_callable(state: _BindState, node: ast.AST) -> _BindState:
    label = "<lambda>" if isinstance(node, ast.Lambda) else node.name
    return replace(state, nodes={**state.nodes, id(node): node}, labels={**state.labels, id(node): label})


def _bind_name(state: _BindState, name: str, node: ast.AST) -> _BindState:
    scope_id = id(state.scopes[-1])
    scope_bindings = dict(state.bindings.get(scope_id, {}))
    scope_bindings[name] = id(node)
    scope_shadows = set(state.shadows.get(scope_id, ()))
    scope_shadows.discard(name)
    return replace(
        state,
        bindings={**state.bindings, scope_id: scope_bindings},
        shadows={**state.shadows, scope_id: scope_shadows},
    )


def _record_method(state: _BindState, node: ast.FunctionDef | ast.AsyncFunctionDef) -> _BindState:
    if not state.classes or state.scopes[-1] is not state.classes[-1]:
        return state
    class_node = state.classes[-1]
    methods = dict(state.class_methods.get(id(class_node), {}))
    methods[node.name] = id(node)
    receiver = _receiver_name(node)
    receivers = {**state.receivers, id(node): receiver} if receiver else state.receivers
    return replace(
        state,
        class_methods={**state.class_methods, id(class_node): methods},
        callable_class={**state.callable_class, id(node): id(class_node)},
        owners={**state.owners, id(node): class_node},
        receivers=receivers,
    )


def _enter_lambda(state: _BindState, node: ast.Lambda) -> _BindState:
    state = replace(
        state,
        enclosing={**state.enclosing, id(node): tuple(id(scope) for scope in reversed(state.scopes))},
    )
    state = _visit_enclosing_expressions(state, (), node.args)
    state = _push_scope(state, node)
    state = _shadow_arguments(state, node)
    state = _visit_binding(state, node.body)
    return _pop_scope(state)


def _shadow_arguments(
    state: _BindState, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
) -> _BindState:
    for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
        state = _shadow(state, argument.arg)
    if node.args.vararg is not None:
        state = _shadow(state, node.args.vararg.arg)
    if node.args.kwarg is not None:
        state = _shadow(state, node.args.kwarg.arg)
    return state


def _shadow(state: _BindState, name: str) -> _BindState:
    scope_id = id(state.scopes[-1])
    scope_shadows = set(state.shadows.get(scope_id, ()))
    scope_shadows.add(name)
    scope_bindings = dict(state.bindings.get(scope_id, {}))
    scope_bindings.pop(name, None)
    return replace(
        state,
        shadows={**state.shadows, scope_id: scope_shadows},
        bindings={**state.bindings, scope_id: scope_bindings},
    )


def _shadow_target(state: _BindState, node: ast.AST) -> _BindState:
    for name in _stored_names(node):
        state = _shadow(state, name)
    return state


def _push_scope(state: _BindState, node: ast.AST) -> _BindState:
    return replace(state, scopes=(*state.scopes, node))


def _pop_scope(state: _BindState) -> _BindState:
    return replace(state, scopes=state.scopes[:-1])


def _bind_lambda_assignment(state: _BindState, node: ast.Assign) -> _BindState | None:
    names = _lambda_target_names(node)
    if not names or not isinstance(node.value, ast.Lambda):
        return None
    state = _register_callable(state, node.value)
    for name in names:
        state = _bind_name(state, name, node.value)
    return _enter_lambda(state, node.value)


def _bind_lambda(state: _BindState, name: str, node: ast.Lambda) -> _BindState:
    state = _register_callable(state, node)
    state = _bind_name(state, name, node)
    return _enter_lambda(state, node)


def _record_runtime_binding(state: _BindState, node: ast.AST) -> _BindState:
    if isinstance(node, ast.Lambda):
        return _enter_lambda(_register_callable(state, node), node)
    if isinstance(node, ast.Global):
        return _declare_names(state, "declared_global", node.names)
    if isinstance(node, ast.Nonlocal):
        return _declare_names(state, "declared_nonlocal", node.names)
    if isinstance(node, ast.Match):
        for case in node.cases:
            for name in _pattern_bindings(case.pattern):
                state = _shadow(state, name)
    return state


def _declare_names(state: _BindState, field_name: str, names: list[str]) -> _BindState:
    scope_id = id(state.scopes[-1])
    declared = dict(getattr(state, field_name))
    declared[scope_id] = set(declared.get(scope_id, ())) | set(names)
    return replace(state, **{field_name: declared})


def _visit_enclosing_expressions(
    state: _BindState,
    decorators: Sequence[ast.expr],
    arguments: ast.arguments,
) -> _BindState:
    for decorator in decorators:
        state = _visit_binding(state, decorator)
    for child in (*arguments.defaults, *arguments.kw_defaults):
        if child is not None:
            state = _visit_binding(state, child)
    return state


def _shadow_statement(state: _BindState, node: ast.AST) -> _BindState:
    if isinstance(node, (ast.For, ast.AsyncFor, ast.NamedExpr)):
        return _shadow_target(state, node.target)
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return _shadow_context_targets(state, node)
    if isinstance(node, ast.ExceptHandler) and node.name is not None:
        return _shadow(state, node.name)
    return state


def _shadow_context_targets(state: _BindState, node: ast.With | ast.AsyncWith) -> _BindState:
    for item in node.items:
        if item.optional_vars is not None:
            state = _shadow_target(state, item.optional_vars)
    return state


def _lambda_target_names(node: ast.Assign) -> list[str] | None:
    if not isinstance(node.value, ast.Lambda):
        return None
    names: list[str] = []
    for target in node.targets:
        if not isinstance(target, ast.Name):
            return None
        names.append(target.id)
    return names


def _pattern_bindings(pattern: ast.pattern) -> list[str]:
    names: list[str] = []
    for node in ast.walk(pattern):
        if isinstance(node, ast.MatchAs) and node.name:
            names.append(node.name)
        elif isinstance(node, ast.MatchStar) and node.name:
            names.append(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.append(node.rest)
    return names


def _receiver_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    if _is_staticmethod(node):
        return ""
    positional = [*node.args.posonlyargs, *node.args.args]
    if not positional:
        return ""
    return positional[0].arg


def _is_staticmethod(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "staticmethod":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "staticmethod":
            return True
    return False


def _stored_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Starred):
        return _stored_names(node.value)
    if isinstance(node, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in node.elts:
            names.extend(_stored_names(element))
        return names
    return []


_BindingScope = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef


@dataclass(frozen=True)
class _ScopeCallImports:
    """The call-relevant imports and the other name bindings of one scope."""

    call_modules: dict[str, str]
    rebound: set[str]


def _resolved_call_names(tree: ast.Module, masks: dict[int, frozenset[str]]) -> dict[int, str]:
    aliases = _imported_call_aliases(tree)
    bindings = _scope_bindings(tree)
    resolved_calls: dict[int, str] = {}
    active_names, changes = _call_scope_entered({}, [], tree, aliases, bindings)
    pending: list[tuple[ast.AST, bool]] = [(tree, False)]
    while pending:
        node, leaving_scope = pending.pop()
        if leaving_scope:
            active_names, changes = _call_scope_left(active_names, changes)
            continue
        if isinstance(node, ast.Call):
            resolved_calls[id(node)] = _qualified_call_name(node, active_names, masks)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            active_names, changes = _call_scope_entered(active_names, changes, node, aliases, bindings)
            pending.append((node, True))
        children = list(ast.iter_child_nodes(node))
        pending.extend((child, False) for child in reversed(children))
    return resolved_calls


def _call_scope_entered(
    active_names: dict[str, str],
    changes: list[list[tuple[str, str | None]]],
    scope: _BindingScope,
    aliases: dict[int, _ScopeCallImports],
    bindings: dict[int, set[str]],
) -> tuple[dict[str, str], list[list[tuple[str, str | None]]]]:
    imports = aliases[id(scope)]
    scope_bindings = bindings[id(scope)]
    recorded: list[tuple[str, str | None]] = []
    updated = dict(active_names)
    for name in imports.rebound | set(imports.call_modules) | scope_bindings:
        recorded.append((name, active_names.get(name)))
        if name in imports.rebound or name not in imports.call_modules:
            updated[name] = ""
        else:
            updated[name] = imports.call_modules[name]
    return updated, [*changes, recorded]


def _call_scope_left(
    active_names: dict[str, str],
    changes: list[list[tuple[str, str | None]]],
) -> tuple[dict[str, str], list[list[tuple[str, str | None]]]]:
    updated = dict(active_names)
    for name, previous in reversed(changes[-1]):
        if previous is None:
            updated.pop(name, None)
        else:
            updated[name] = previous
    return updated, changes[:-1]


def _qualified_call_name(call: ast.Call, active_names: dict[str, str], masks: dict[int, frozenset[str]]) -> str:
    original_name = _dotted_name(call.func)
    if original_name.split(".", 1)[0] in masks.get(id(call), ()):
        return ""
    return _resolve_call_name(original_name, active_names)


def _resolve_call_name(
    original_name: str,
    active_names: dict[str, str],
) -> str:
    root_name = original_name.split(".", 1)[0]
    attributes = original_name[len(root_name):]
    resolved_name = active_names.get(root_name)
    if resolved_name is None:
        return original_name
    if not resolved_name:
        return ""
    return f"{resolved_name}{attributes}"


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else ""
    return ""


def _imported_call_aliases(tree: ast.Module) -> dict[int, _ScopeCallImports]:
    return {id(scope): _scope_call_imports(scope) for scope in _binding_scopes(tree)}


def _scope_call_imports(scope: _BindingScope) -> _ScopeCallImports:
    call_modules: dict[str, str] = {}
    rebound: set[str] = set()
    for statement in _scope_statements(scope):
        call_modules.update(_call_import_map(statement))
        rebound.update(_rebound_names(statement))
    return _ScopeCallImports(call_modules=call_modules, rebound=rebound)


def _call_import_map(node: ast.AST) -> dict[str, str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return {}
    if isinstance(node, ast.Import):
        return _call_import_aliases(node)
    if isinstance(node, ast.ImportFrom) and node.module in {"sys", "os", "builtins", "pdb"}:
        return _call_import_from_aliases(node)
    if isinstance(node, (ast.ImportFrom,)):
        return {}
    found: dict[str, str] = {}
    for child in ast.iter_child_nodes(node):
        found.update(_call_import_map(child))
    return found


def _rebound_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.Lambda)):
        return set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    found = _pattern_binding_names(node)
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        found.add(node.id)
    for child in ast.iter_child_nodes(node):
        found.update(_rebound_names(child))
    return found


def _call_import_aliases(statement: ast.Import) -> dict[str, str]:
    return {
        imported.asname or imported.name: imported.name
        for imported in statement.names
        if imported.name in {"sys", "os", "builtins", "pdb"}
    }


def _call_import_from_aliases(statement: ast.ImportFrom) -> dict[str, str]:
    return {
        imported.asname or imported.name: f"{statement.module}.{imported.name}"
        for imported in statement.names
    }


def _binding_scopes(tree: ast.Module) -> list[_BindingScope]:
    scopes: list[_BindingScope] = [tree]
    scopes.extend(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef))
    )
    return scopes


def _scope_statements(scope: _BindingScope) -> list[ast.AST]:
    return [scope.body] if isinstance(scope, ast.Lambda) else list(scope.body)


def _scope_bindings(tree: ast.Module) -> dict[int, set[str]]:
    return {id(scope): _direct_bindings(scope) for scope in _binding_scopes(tree)}


def _direct_bindings(scope: _BindingScope) -> set[str]:
    names: set[str] = set()
    if not isinstance(scope, (ast.Module, ast.ClassDef)):
        names.update(argument.arg for argument in _arguments(scope.args))
    for statement in _scope_statements(scope):
        names.update(_scope_binding_names(statement))
    return names


def _scope_binding_names(node: ast.AST) -> set[str]:

    found = _recorded_binding_names(node)
    if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return found
    for child in ast.iter_child_nodes(node):
        found.update(_scope_binding_names(child))
    return found


def _recorded_binding_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id} if isinstance(node.ctx, ast.Store) else set()
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return set(_import_binding_names(node))
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    return _pattern_binding_names(node)


def _import_binding_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    return [imported.asname or imported.name.split(".", 1)[0] for imported in node.names]


def _pattern_binding_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.MatchAs, ast.MatchStar, ast.ExceptHandler)) and node.name is not None:
        return {node.name}
    if isinstance(node, ast.MatchMapping) and node.rest is not None:
        return {node.rest}
    return set()


def _evaluated_nodes(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> list[ast.AST]:
    roots = [node.body] if isinstance(node, ast.Lambda) else node.body
    found: list[ast.AST] = []
    for root in roots:
        found.extend(_evaluated_node_list(root))
    return found


def _evaluated_node_list(node: ast.AST) -> list[ast.AST]:
    # Python evaluates decorators, defaults, class bases, and nested class bodies here.
    # It does not evaluate a local annotation or a nested function body.
    if isinstance(node, ast.AnnAssign):
        return [node, *_evaluated_present([node.target, node.value])]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _evaluated_present([*node.decorator_list, *node.args.defaults, *node.args.kw_defaults])
    if isinstance(node, ast.Lambda):
        return _evaluated_present([*node.args.defaults, *node.args.kw_defaults])
    if isinstance(node, ast.ClassDef):
        return _evaluated_present([*node.decorator_list, *node.bases, *node.keywords, *node.body])
    found = [node]
    for child in ast.iter_child_nodes(node):
        found.extend(_evaluated_node_list(child))
    return found


def _evaluated_present(nodes: Sequence[ast.AST | None]) -> list[ast.AST]:
    found: list[ast.AST] = []
    for node in nodes:
        if node is not None:
            found.extend(_evaluated_node_list(node))
    return found


def _arguments(arguments: ast.arguments) -> list[ast.arg]:
    values = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        values.append(arguments.vararg)
    if arguments.kwarg is not None:
        values.append(arguments.kwarg)
    return values
