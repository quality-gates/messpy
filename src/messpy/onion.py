from __future__ import annotations

import ast
import fnmatch
import importlib.util
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from .rulesets import LoadedRule, RulesetError

if TYPE_CHECKING:
    from .analyzer import Finding

DOMAIN_ACTION_RULE_NAME = "DomainAction"
DOMAIN_OUTER_IMPORT_RULE_NAME = "DomainOuterImport"


def validate_onion_rules(rules: Sequence[LoadedRule]) -> None:
    for rule in rules:
        if rule.name == DOMAIN_ACTION_RULE_NAME:
            _require_list(rule, "domain", "path pattern")
        elif rule.name == DOMAIN_OUTER_IMPORT_RULE_NAME:
            _require_list(rule, "domain", "path pattern")
            _require_list(rule, "outer-layers", "module")


def onion_findings(path: Path, tree: ast.Module, rules: Sequence[LoadedRule]) -> list[Finding]:
    action_rule = _named_rule(rules, DOMAIN_ACTION_RULE_NAME)
    import_rule = _named_rule(rules, DOMAIN_OUTER_IMPORT_RULE_NAME)
    findings = []
    if action_rule is not None and _in_domain(path, action_rule):
        findings.extend(_domain_action_findings(path, tree, action_rule))
    if import_rule is not None and _in_domain(path, import_rule):
        findings.extend(_outer_import_findings(path, tree, import_rule))
    return findings


def _require_list(rule: LoadedRule, property_name: str, kind: str) -> None:
    if _property_items(rule, property_name):
        return
    raise RulesetError(f"{rule.name} property '{property_name}' must name at least one {kind}.")


def _named_rule(rules: Sequence[LoadedRule], name: str) -> LoadedRule | None:
    return next((rule for rule in rules if rule.name == name), None)


def _property_items(rule: LoadedRule, property_name: str) -> list[str]:
    raw = rule.properties.get(property_name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _in_domain(path: Path, rule: LoadedRule) -> bool:
    posix = path.resolve().as_posix()
    for pattern in _property_items(rule, "domain"):
        if fnmatch.fnmatchcase(posix, pattern):
            return True
    return False


def _domain_action_findings(path: Path, tree: ast.Module, rule: LoadedRule) -> list:
    direct, phrases = _direct_actions(path, tree, rule)
    return [*_import_time_findings(path, tree, rule), *direct, *_spread_findings(path, tree, rule, phrases)]


def _direct_actions(path: Path, tree: ast.Module, rule: LoadedRule) -> tuple[list, dict[int, str]]:
    from .analyzer import (
        _ScopeChain,
        _clean_code_callables,
        _enclosing_scopes,
        _implicit_input_findings,
        _implicit_instance_output_findings,
        _implicit_output_findings,
        _name_scopes,
    )

    parents = _parent_map(tree)
    name_scopes = _name_scopes(tree)
    findings = []
    phrases: dict[int, str] = {}
    for callable_info in _clean_code_callables(tree):
        chain = _ScopeChain(
            (callable_info.node, *_enclosing_scopes(callable_info.node, tree, parents)),
            name_scopes,
        )
        found = [
            *_implicit_input_findings(path, callable_info, rule, chain),
            *_implicit_output_findings(path, callable_info, rule, chain),
            *_implicit_instance_output_findings(path, callable_info, rule, chain),
        ]
        findings.extend(found)
        if found:
            phrases[id(callable_info.node)] = _action_phrase(found[0].message)
    return findings, phrases


def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return parents


def _action_phrase(message: str) -> str:
    sentence, _separator, _rest = message.partition(". ")
    _prefix, separator, phrase = sentence.partition("() ")
    if separator:
        return phrase
    return sentence


def _import_time_findings(path: Path, tree: ast.Module, rule: LoadedRule) -> list:
    from .analyzer import _ScopeChain, _ambient_read, _ambient_write, _name_scopes

    chain = _ScopeChain((tree,), _name_scopes(tree))
    reads: dict[str, ast.AST] = {}
    writes: dict[str, ast.AST] = {}
    for node in _import_time_nodes(tree):
        reads = _with_ambient(node, chain, _ambient_read, reads)
        writes = _with_ambient(node, chain, _ambient_write, writes)
    return [
        *_ambient_findings(path, rule, reads, "reads the implicit input"),
        *_ambient_findings(path, rule, writes, "writes the implicit output"),
    ]


def _with_ambient(node: ast.AST, chain, classify, found: dict[str, ast.AST]) -> dict[str, ast.AST]:
    name = classify(node, chain)
    if not name or name in found:
        return found
    return {**found, name: node}


def _ambient_findings(path: Path, rule: LoadedRule, found: dict[str, ast.AST], action: str) -> list:
    return [
        _finding(
            path,
            node.lineno,
            rule,
            f"The module {action} {name} at import time. Move the action to the interaction layer.",
        )
        for name, node in found.items()
    ]


def _import_time_nodes(tree: ast.Module) -> list[ast.AST]:
    deferred = _annotations_are_deferred(tree)
    nodes: list[ast.AST] = []
    for statement in tree.body:
        nodes.extend(_import_time_node(statement, deferred))
    return nodes


def _annotations_are_deferred(tree: ast.Module) -> bool:
    if _running_python_defers_annotations():
        return True
    return any(
        isinstance(statement, ast.ImportFrom)
        and statement.module == "__future__"
        and any(alias.name == "annotations" for alias in statement.names)
        for statement in tree.body
    )


def _running_python_defers_annotations() -> bool:
    # annotationlib ships with the Python release that defers annotations.
    return importlib.util.find_spec("annotationlib") is not None


def _import_time_node(node: ast.AST, deferred: bool) -> list[ast.AST]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _import_time_signature(node, deferred)
    if isinstance(node, ast.Lambda):
        return _import_time_defaults(node, deferred)
    if isinstance(node, ast.ClassDef):
        return _import_time_class(node, deferred)
    if isinstance(node, ast.AnnAssign):
        return _import_time_annotation(node, deferred)
    if _is_type_alias(node):
        return []
    found = [node]
    for child in ast.iter_child_nodes(node):
        found.extend(_import_time_node(child, deferred))
    return found


def _is_type_alias(node: ast.AST) -> bool:
    type_alias = getattr(ast, "TypeAlias", None)
    return type_alias is not None and isinstance(node, type_alias)


def _import_time_signature(node: ast.FunctionDef | ast.AsyncFunctionDef, deferred: bool) -> list[ast.AST]:
    found = _import_time_present((*node.decorator_list, *node.args.defaults, *node.args.kw_defaults), deferred)
    if deferred:
        return found
    return [*found, *_import_time_present(_signature_annotations(node), deferred)]


def _import_time_defaults(node: ast.Lambda, deferred: bool) -> list[ast.AST]:
    return _import_time_present((*node.args.defaults, *node.args.kw_defaults), deferred)


def _import_time_class(node: ast.ClassDef, deferred: bool) -> list[ast.AST]:
    found = _import_time_present(
        (*node.decorator_list, *node.bases, *(item.value for item in node.keywords)),
        deferred,
    )
    for statement in node.body:
        found.extend(_import_time_node(statement, deferred))
    return found


def _import_time_annotation(node: ast.AnnAssign, deferred: bool) -> list[ast.AST]:
    found = [node, *_import_time_node(node.target, deferred)]
    if node.value is not None:
        found.extend(_import_time_node(node.value, deferred))
    if deferred or node.annotation is None:
        return found
    found.extend(_import_time_node(node.annotation, deferred))
    return found


def _import_time_present(nodes: Sequence[ast.AST | None], deferred: bool) -> list[ast.AST]:
    found: list[ast.AST] = []
    for node in nodes:
        if node is not None:
            found.extend(_import_time_node(node, deferred))
    return found


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


def _spread_findings(path: Path, tree: ast.Module, rule: LoadedRule, phrases: dict[int, str]) -> list:
    index = _index_callables(tree)
    edges = _call_edges(index, _parent_map(tree))
    actions = _action_ids(phrases, edges)
    findings = []
    for caller_id, sites in edges.items():
        for site in sites:
            if site.callee_id not in actions:
                continue
            phrase = _chain_phrase(site.callee_id, phrases, edges, set())
            if not phrase:
                continue
            findings.append(_spread_finding(path, rule, index, caller_id, site, phrase))
    return findings


def _action_ids(phrases: dict[int, str], edges: dict[int, list[_CallSite]]) -> set[int]:
    actions = set(phrases)
    changed = True
    while changed:
        changed = False
        for caller_id, sites in edges.items():
            if caller_id in actions:
                continue
            if any(site.callee_id in actions for site in sites):
                actions.add(caller_id)
                changed = True
    return actions


def _chain_phrase(
    callee_id: int,
    phrases: dict[int, str],
    edges: dict[int, list[_CallSite]],
    seen: set[int],
) -> str:
    direct = phrases.get(callee_id, "")
    if direct:
        return direct
    if callee_id in seen:
        return ""
    followed = {*seen, callee_id}
    for site in edges.get(callee_id, ()):
        phrase = _chain_phrase(site.callee_id, phrases, edges, followed)
        if phrase:
            return f"calls {site.callee_name}(), which {phrase}"
    return ""


def _spread_finding(path, rule, index: _CallableIndex, caller_id: int, site: _CallSite, phrase: str):
    kind, context = _caller_context(index, caller_id)
    message = (
        f"The {kind} {context}() calls {site.callee_name}(), which {phrase}. "
        "Move the action to the interaction layer."
    )
    return _finding(path, site.line, rule, message, context)


def _caller_context(index: _CallableIndex, caller_id: int) -> tuple[str, str]:
    owner = index.owners.get(caller_id, "")
    label = index.labels[caller_id]
    if owner:
        return "method", f"{owner}.{label}"
    return "function", label


@dataclass(frozen=True)
class _CallSite:
    callee_id: int
    callee_name: str
    line: int


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
    owners: dict[int, str]
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


def _call_edges(index: _CallableIndex, parents: dict[int, ast.AST]) -> dict[int, list[_CallSite]]:
    from .analyzer import _evaluated_nodes

    edges: dict[int, list[_CallSite]] = {}
    for caller_id, node in index.nodes.items():
        seen: set[int] = set()
        for child in _evaluated_nodes(node):
            if not isinstance(child, ast.Call):
                continue
            callee_id = _resolved_callee(index, caller_id, child, parents)
            if callee_id is None or callee_id in seen:
                continue
            seen.add(callee_id)
            edges.setdefault(caller_id, []).append(
                _CallSite(callee_id, _called_name(child, index, callee_id), child.lineno)
            )
    return edges


def _called_name(call: ast.Call, index: _CallableIndex, callee_id: int) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return index.labels[callee_id]


def _resolved_callee(
    index: _CallableIndex, caller_id: int, call: ast.Call, parents: dict[int, ast.AST]
) -> int | None:
    func = call.func
    if isinstance(func, ast.Name):
        if func.id in _comprehension_targets(call, parents):
            return None
        return _resolve_bare_name(index, caller_id, func.id)
    if isinstance(func, ast.Attribute):
        return _resolve_receiver_call(index, caller_id, func)
    if isinstance(func, ast.Lambda) and id(func) in index.nodes:
        return id(func)
    return None


def _comprehension_targets(call: ast.Call, parents: dict[int, ast.AST]) -> set[str]:
    targets: set[str] = set()
    current: ast.AST = call
    while id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            break
        if isinstance(current, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            targets.update(_comprehension_target_names(call, current, parents))
    return targets


def _comprehension_target_names(
    call: ast.Call,
    comp: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    parents: dict[int, ast.AST],
) -> set[str]:
    if _in_outer_iterable(call, comp, parents):
        return set()
    names: set[str] = set()
    for generator in comp.generators:
        names.update(_stored_names(generator.target))
    return names


def _in_outer_iterable(
    call: ast.Call,
    comp: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    parents: dict[int, ast.AST],
) -> bool:
    outer_iter = comp.generators[0].iter
    current: ast.AST = call
    while id(current) in parents and current is not comp:
        if current is outer_iter:
            return True
        current = parents[id(current)]
    return False


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
    owners: dict[int, str] = field(default_factory=dict)
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
        owners={**state.owners, id(node): class_node.name},
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


def _outer_import_findings(path: Path, tree: ast.Module, rule: LoadedRule) -> list:
    layers = _property_items(rule, "outer-layers")
    findings = []
    for node in ast.walk(tree):
        for module, layer in _matched_imports(path, node, layers):
            findings.append(_import_finding(path, node, rule, module, layer))
    return findings


def _matched_imports(path: Path, node: ast.AST, layers: Sequence[str]) -> list[tuple[str, str]]:
    if not isinstance(node, (ast.Import, ast.ImportFrom)):
        return []
    if isinstance(node, ast.ImportFrom):
        base = _absolute_module(path, node)
        layer = _matching_layer(base, layers)
        if layer:
            return [(base, layer)]
    matches: list[tuple[str, str]] = []
    seen: set[str] = set()
    for module in _imported_module_names(path, node):
        layer = _matching_layer(module, layers)
        if not layer or module in seen:
            continue
        seen.add(module)
        matches.append((module, layer))
    return matches


def _imported_module_names(path: Path, node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    base = _absolute_module(path, node)
    names = [base] if base else []
    names.extend(
        f"{base}.{alias.name}" if base else alias.name
        for alias in node.names
        if alias.name != "*"
    )
    return names


def _absolute_module(path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = _package_parts(path)
    if package is None:
        return ""
    climb = node.level - 1
    if climb >= len(package):
        return ""
    kept = package[: len(package) - climb]
    if node.module:
        return ".".join((*kept, node.module))
    return ".".join(kept)


def _package_parts(path: Path) -> tuple[str, ...] | None:
    parts: list[str] = []
    directory = path.parent
    while (directory / "__init__.py").is_file():
        parts.append(directory.name)
        parent = directory.parent
        if parent == directory:
            break
        directory = parent
    if not parts:
        return None
    parts.reverse()
    return tuple(parts)


def _matching_layer(module: str, layers: Sequence[str]) -> str:
    for layer in layers:
        module_prefix = layer.removesuffix(".*")
        if module_prefix and (module == module_prefix or module.startswith(f"{module_prefix}.")):
            return layer
    return ""


def _import_finding(path: Path, node: ast.AST, rule: LoadedRule, module: str, layer: str):
    message = (
        f"The module imports {module}, which belongs to the outer layer {layer}. "
        "The domain layer must not know about the interaction layer."
    )
    return _finding(path, node.lineno, rule, message)


def _finding(path: Path, line: int, rule: LoadedRule, message: str, context: str = ""):
    from .analyzer import Finding

    return Finding(path, line, rule.name, rule.priority, message, context=context)
