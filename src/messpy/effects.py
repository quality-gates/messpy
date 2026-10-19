from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from .callables import CallableNode, module_callables
from .callgraph import (
    CallGraph,
    _annotations_are_deferred,
    _arguments,
    _dotted_name,
    _evaluated_nodes,
    _module_nodes,
    build_call_graph,
)
from .names import Names
from .execution import Execution, cold_body, decorator_calls, executions, key_calls, transformed_callable
from .ownership import Origin, Ownership, Storage, augmented_mutation, project_storage
from .protocols import Protocols, uncertainties
from .rulesets import LoadedRule

if TYPE_CHECKING:
    from .analyzer import Finding, _ScopeChain


@dataclass(frozen=True)
class Effect:
    rule: str
    name: str
    origin: Origin | None = None
    callback: Origin | None = None
    reason: str = ""
    arguments: tuple[Storage, ...] | None = None
    keywords: tuple[tuple[str, Storage], ...] = ()
    ambient: bool = False


@dataclass(frozen=True)
class EffectSummary:
    reads: frozenset[Effect] = frozenset()
    writes: frozenset[Effect] = frozenset()
    unknown: frozenset[Effect] = frozenset()
    complete: bool = True

    @property
    def facts(self) -> frozenset[Effect]:
        return self.reads | self.writes | self.unknown

    @classmethod
    def collect(cls, facts: Sequence[Effect]) -> EffectSummary:
        return cls(
            frozenset(fact for fact in facts if fact.rule in {"ImplicitInput", "ImplicitInstanceInput"}),
            frozenset(fact for fact in facts if fact.rule in {"ImplicitOutput", "ImplicitInstanceOutput"}),
            frozenset(fact for fact in facts if fact.rule == "UnknownEffect"),
            not any(fact.rule == "UnknownEffect" for fact in facts),
        )


@dataclass(frozen=True)
class CallableEffects:
    callable: CallableNode
    direct: dict[Effect, ast.AST]
    ownership: Ownership
    calls: tuple[ast.Call, ...]
    callable_aliases: dict[int, dict[str, ast.AST]]
    executions: tuple[Execution, ...] = ()


_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_PURE_CALLS = frozenset({
    "builtins.abs", "builtins.all", "builtins.any", "builtins.bin", "builtins.bool", "builtins.chr",
    "builtins.dict", "builtins.divmod", "builtins.enumerate", "builtins.float", "builtins.format",
    "builtins.frozenset", "builtins.hex", "builtins.int", "builtins.isinstance", "builtins.issubclass",
    "builtins.len", "builtins.list", "builtins.max", "builtins.min", "builtins.oct", "builtins.ord",
    "builtins.pow", "builtins.range", "builtins.reversed", "builtins.round", "builtins.set",
    "builtins.sorted", "builtins.str", "builtins.sum", "builtins.tuple", "builtins.zip",
    "builtins.ValueError", "builtins.TypeError", "builtins.RuntimeError", "builtins.KeyError", "builtins.IndexError",
    "builtins.Exception", "builtins.AssertionError", "builtins.StopIteration", "builtins.OSError",
    "math.ceil", "math.floor", "math.sqrt", "math.fabs", "math.isfinite", "math.isnan", "math.isinf",
})
_MUTATORS = MappingProxyType({
    "list": frozenset({"append", "clear", "extend", "insert", "pop", "remove", "reverse", "sort"}),
    "dict": frozenset({"clear", "pop", "popitem", "setdefault", "update"}),
    "set": frozenset({"add", "clear", "discard", "pop", "remove", "update"}),
})
_PURE_METHODS = MappingProxyType({
    "list": frozenset({"copy", "count", "index"}),
    "dict": frozenset({"copy", "get", "items", "keys", "values"}),
    "set": frozenset({"copy", "difference", "intersection", "union", "issubset", "issuperset"}),
    "str": frozenset({"capitalize", "casefold", "endswith", "find", "join", "lower", "replace", "split", "startswith", "strip", "upper"}),
    "frozenset": frozenset({"copy", "difference", "intersection", "isdisjoint", "issubset", "issuperset", "union"}),
    "tuple": frozenset({"count", "index"}),
    "mapping": frozenset({"get", "items", "keys", "values"}),
    # A substitution can call a replacement function, so only these pattern methods are pure.
    "pattern": frozenset({"findall", "finditer", "fullmatch", "match", "search", "split"}),
})


def explicitness_findings(path: Path, tree: ast.Module, rules: Sequence[LoadedRule], names: Names) -> list[Finding]:
    graph = build_call_graph(tree, names)
    owners = _callable_effects(tree, names, graph)
    summaries = _fixed_point(owners, graph)
    selected = {rule.name: rule for rule in rules}
    findings = []
    for owner in owners:
        located = _located_effects(owner, summaries, graph)
        reported = set()
        for effect, node in located.items():
            rule = selected.get(effect.rule)
            identity = (effect.rule, effect.name)
            if rule is not None and identity not in reported:
                findings.append(_finding(path, owner.callable, rule, effect, node))
                reported.add(identity)
        if "ImplicitInstanceOutput" not in selected or "ImplicitInstanceInput" not in selected:
            findings.extend(_receiver_uncertainty(path, owner, located, selected))
    return findings


def _callable_effects(tree: ast.Module, names: Names, graph: CallGraph) -> tuple[CallableEffects, ...]:
    from .analyzer import _name_scopes, _ownership_program

    parents = {id(child): parent for parent in _module_nodes(tree) for child in ast.iter_child_nodes(parent)}
    scopes = _name_scopes(tree)
    protocols = Protocols.collect(tree)
    owners = _execution_owners(tree, parents)
    for owner in owners:
        scopes = _generator_scope(owner.node, scopes)
    program = _ownership_program(owners, names, graph, parents, scopes)
    return tuple(_owner_effects(info, names, graph, parents, scopes, protocols, program) for info in owners)


def _owner_effects(callable_info, names, graph, parents, scopes, protocols, program) -> CallableEffects:
    from .analyzer import _ScopeChain, _argument_ownership, _caller_owned_parameters

    chain = _ScopeChain((callable_info.node, *callable_info.enclosing), scopes, parents=parents, names=names, graph=graph)
    nodes = _evaluated_nodes(callable_info.node, _annotations_are_deferred(chain.scopes[-1]))
    ownership = _argument_ownership(callable_info, nodes, chain, _caller_owned_parameters(callable_info), program)
    aliases = _callable_aliases(callable_info, nodes, graph)
    keys = key_calls(nodes, chain.qualified_name)
    observations = {id(call): ownership.observations.get(id(source), {}) for source, call in keys}
    ownership = replace(ownership, observations={**ownership.observations, **observations})
    calls = tuple(node for node in nodes if isinstance(node, ast.Call)) + decorator_calls(nodes, chain.qualified_name) + tuple(call for _, call in keys)
    direct = _direct_effects(callable_info, chain, ownership)
    direct.update((Effect("UnknownEffect", name, reason="unresolved protocol dispatch"), node) for name, node in uncertainties(nodes, ownership, chain.qualified_name, graph, protocols))
    direct.update(_unknown_calls(calls, callable_info, chain, ownership, graph, aliases))
    forced, opaque = executions(
        nodes, lambda call: _target_in_scope(call, callable_info, graph, aliases), chain.qualified_name,
        ownership,
    )
    direct.update((Effect("UnknownEffect", "deferred execution", reason="unresolved deferred execution"), node) for node in opaque)
    return CallableEffects(callable_info, direct, ownership, calls, aliases, forced)


def _generator_scope(node: ast.AST, scopes):
    from .analyzer import _scope_name_record

    if isinstance(node, ast.GeneratorExp):
        targets = {name.id for generator in node.generators for name in ast.walk(generator.target) if isinstance(name, ast.Name)}
        return {**scopes, id(node): _scope_name_record((), targets)}
    return scopes


def _execution_owners(tree: ast.Module, parents) -> tuple[CallableNode, ...]:
    owners = [CallableNode(tree, "<module>", "module", None, ())]
    owners.extend(module_callables(tree))
    for node in ast.walk(tree):
        if isinstance(node, ast.GeneratorExp):
            scopes = []
            parent = parents.get(id(node))
            while parent is not None:
                if isinstance(parent, (*_FUNCTIONS, ast.GeneratorExp, ast.Module)):
                    scopes.append(parent)
                parent = parents.get(id(parent))
            owners.append(CallableNode(node, "<genexpr>", "generator", None, tuple(scopes)))
    return tuple(owners)


def _unknown_calls(calls, callable_info, chain, ownership, graph, callable_aliases) -> dict[Effect, ast.AST]:
    unknown = {}
    for call in calls:
        target = _target_in_scope(call, callable_info, graph, callable_aliases)
        if target is not None and not transformed_callable(target, chain.qualified_name):
            continue
        if _established_call(call, callable_info, chain, ownership):
            continue
        callback = _callback_origin(call, callable_info, chain)
        arguments, keywords = _call_arguments(call, ownership) if callback is not None else (None, ())
        name = _dotted_name(call.func) or "<dynamic call>"
        unknown[Effect("UnknownEffect", name, callback=callback, reason="unresolved call", arguments=arguments, keywords=keywords)] = call
    return unknown


def _call_arguments(call: ast.Call, ownership: Ownership) -> tuple[tuple[Storage, ...] | None, tuple[tuple[str, Storage], ...]]:
    if any(isinstance(argument, ast.Starred) for argument in call.args) or any(keyword.arg is None for keyword in call.keywords):
        return None, ()
    arguments = tuple(ownership.value(argument, call) for argument in call.args)
    return arguments, tuple((keyword.arg, ownership.value(keyword.value, call)) for keyword in call.keywords if keyword.arg)


def _callable_aliases(callable_info: CallableNode, nodes: Sequence[ast.AST], graph: CallGraph) -> dict[int, dict[str, ast.AST]]:
    aliases: dict[str, ast.AST] = {}
    observations: dict[int, dict[str, ast.AST]] = {}
    unstable = _rebound_names(callable_info.node, nodes)
    for node in nodes:
        observations[id(node)] = {name: value for name, value in aliases.items() if name not in unstable}
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            aliases = _updated_callable_aliases(aliases, node.targets[0], node.value, callable_info, graph)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            aliases = _updated_callable_aliases(aliases, node.target, node.value, callable_info, graph)
    return observations


def _rebound_names(callable_node: ast.AST, nodes: Sequence[ast.AST]) -> frozenset[str]:
    stores = Counter(node.id for node in nodes if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)))
    shared = {
        name for node in ast.walk(callable_node)
        if isinstance(node, (ast.Global, ast.Nonlocal)) for name in node.names
    }
    return frozenset(name for name, count in stores.items() if count > 1) | frozenset(shared)


def _updated_callable_aliases(
    aliases: dict[str, ast.AST], target: ast.AST, value: ast.AST, callable_info: CallableNode, graph: CallGraph
) -> dict[str, ast.AST]:
    if not isinstance(target, ast.Name):
        return aliases
    updated = dict(aliases)
    resolved = _callable_value(value, callable_info, graph)
    if resolved is None:
        updated.pop(target.id, None)
    else:
        updated[target.id] = resolved
    return updated


def _callable_value(value: ast.AST, callable_info: CallableNode, graph: CallGraph) -> ast.AST | None:
    if isinstance(value, ast.Lambda):
        return value
    if isinstance(value, ast.Name):
        site = graph.call_site(callable_info.node, ast.copy_location(ast.Call(func=value, args=[], keywords=[]), value))
        return site.callee if site is not None else None
    if isinstance(value, ast.Call):
        site = graph.call_site(callable_info.node, ast.copy_location(ast.Call(func=value, args=[], keywords=[]), value))
        return site.callee if site is not None else None
    return None


def _callback_origin(call: ast.Call, callable_info: CallableNode, chain: _ScopeChain) -> Origin | None:
    if not isinstance(call.func, ast.Name) or not isinstance(callable_info.node, _FUNCTIONS):
        return None
    parameters = {argument.arg for argument in _arguments(callable_info.node.args)}
    if call.func.id in parameters and chain.binding(call.func.id)[1] is callable_info.node:
        return Origin(id(callable_info.node), call.func.id)
    return None


def _direct_effects(callable_info: CallableNode, chain: _ScopeChain, ownership: Ownership) -> dict[Effect, ast.AST]:
    from .analyzer import (
        _free_variable_read, _input_nodes, _method_receiver, _read_nodes,
    )

    direct = {}
    for name, node in _input_nodes(callable_info, chain).items():
        is_free = isinstance(node, ast.Name) and bool(_free_variable_read(node, chain))
        origin = Origin(id(chain.binding(name)[1]), name) if is_free else None
        direct[Effect("ImplicitInput", name, origin, ambient=not is_free)] = node
    receiver = _method_receiver(callable_info)
    read_nodes = _read_nodes(callable_info.node, _annotations_are_deferred(chain.scopes[-1]))
    called = {id(node.func) for node in read_nodes if isinstance(node, ast.Call)}
    for node in read_nodes:
        for effect in _write_effects(node, chain.for_node(node), ownership, receiver):
            direct.setdefault(effect, node)
        for effect in _instance_effects(node, callable_info, chain, receiver, called):
            direct.setdefault(effect, node)
    return direct


def _write_effects(node: ast.AST, chain: _ScopeChain, ownership: Ownership, receiver: str | None) -> tuple[Effect, ...]:
    from .analyzer import _ambient_write, _changed_object, _storage_write

    if isinstance(node, ast.AugAssign):
        return _augmented_effects(node, ownership)
    storage_name = _storage_write(node, chain, ownership)
    ambient_name = _ambient_write(node, chain) if not storage_name else ""
    name = storage_name or ambient_name
    changed = _changed_object(node, chain)
    if not name:
        return _unknown_mutation(changed, node, ownership, receiver)
    origins = _output_origins(changed, node, chain, ownership)
    return tuple(Effect("ImplicitOutput", name, origin, ambient=bool(ambient_name)) for origin in origins or {None})


def _output_origins(changed: ast.expr | None, node: ast.AST, chain: _ScopeChain, ownership: Ownership) -> frozenset[Origin]:
    from .analyzer import changed_storage

    if changed is not None:
        origins = changed_storage(changed, node, ownership).outer
        if origins:
            return origins
    return _binding_write_origin(node, chain)


def _binding_write_origin(node: ast.AST, chain: _ScopeChain) -> frozenset[Origin]:
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return frozenset({Origin(id(chain.binding(node.id)[1]), node.id)})
    return frozenset()


def _unknown_mutation(changed: ast.expr | None, node: ast.AST, ownership: Ownership, receiver: str | None) -> tuple[Effect, ...]:
    from .analyzer import _root_name, changed_storage

    if changed is None or not changed_storage(changed, node, ownership).opaque:
        return ()
    root = _root_name(changed)
    if root and root == receiver:
        return ()
    return (Effect("UnknownEffect", f"mutation of {root or '<expression>'}", reason="unknown storage"),)


def _augmented_effects(node: ast.AugAssign, ownership: Ownership) -> tuple[Effect, ...]:
    if not isinstance(node.target, ast.Name):
        return ()
    change = augmented_mutation(node, ownership)
    if not change:
        return ()
    name = node.target.id
    target = ownership.value(ast.Name(name, ast.Load()), node)
    if change == "unknown" or target.opaque:
        return (Effect("UnknownEffect", f"{name} augmented assignment", reason="unknown operand kind"),)
    return tuple(Effect("ImplicitOutput", name, origin) for origin in target.outer)


def _instance_effects(node, callable_info, chain, receiver, called) -> tuple[Effect, ...]:
    from .analyzer import _mutated_expression, _receiver_attribute, CONSTRUCTOR_METHOD_NAMES

    if receiver is None:
        return ()
    effects = []
    name = _instance_read(node, receiver, called)
    if name:
        effects.append(Effect("ImplicitInstanceInput", name))
    expression = _mutated_expression(node, chain.parents, chain.for_node(node))
    name = _receiver_attribute(expression, receiver) if expression is not None else ""
    if name and callable_info.name not in CONSTRUCTOR_METHOD_NAMES:
        effects.append(Effect("ImplicitInstanceOutput", name))
    return tuple(effects)


def _instance_read(node: ast.AST, receiver: str, called: set[int]) -> str:
    from .analyzer import _receiver_attribute

    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and id(node) not in called:
        return _receiver_attribute(node, receiver)
    return ""


def _established_call(call: ast.Call, callable_info: CallableNode, chain: _ScopeChain, ownership: Ownership) -> bool:
    from .analyzer import IMPLICIT_INPUT_NAMES, IMPLICIT_OUTPUT_NAMES, OPEN_CALL_NAMES, _changed_object, _method_receiver

    qualified = chain.qualified_name(call.func)
    known = IMPLICIT_INPUT_NAMES | IMPLICIT_OUTPUT_NAMES | OPEN_CALL_NAMES | {
        "functools.cache", "functools.lru_cache", "builtins.classmethod", "builtins.staticmethod", "builtins.property",
    }
    if qualified in known or _changed_object(call, chain) is not None:
        return True
    receiver = _method_receiver(callable_info)
    if receiver is not None and _receiver_call(call, receiver):
        return True
    if _type_alias_call(call, chain):
        return True
    return _standard_call(call, qualified, ownership) or _empty_constructor(call, chain)


def _standard_call(call: ast.Call, qualified: str, ownership: Ownership) -> bool:
    if qualified in _PURE_CALLS:
        return not any(keyword.arg is None for keyword in call.keywords)
    base, _, method = qualified.rpartition(".")
    if base.startswith("builtins.") and base.removeprefix("builtins.") in _MUTATORS:
        return method in _MUTATORS[base.removeprefix("builtins.")]
    if not isinstance(call.func, ast.Attribute):
        return False
    kinds = ownership.value(call.func.value, call).kinds
    if len(kinds) != 1:
        return False
    kind = next(iter(kinds))
    methods = _MUTATORS.get(kind, frozenset()) | _PURE_METHODS.get(kind, frozenset())
    return call.func.attr in methods and not any(keyword.arg is None for keyword in call.keywords)


def _receiver_call(call: ast.Call, receiver: str) -> bool:
    if isinstance(call.func, ast.Name) and call.func.id == receiver:
        return True
    value = call.func.value if isinstance(call.func, ast.Attribute) else None
    while isinstance(value, (ast.Attribute, ast.Subscript)):
        value = value.value
    return isinstance(value, ast.Name) and value.id == receiver


def _type_alias_call(call: ast.Call, chain: _ScopeChain) -> bool:
    type_alias = getattr(ast, "TypeAlias", None)
    if type_alias is None or not isinstance(call.func, ast.Name):
        return False
    name = call.func.id
    for scope in (chain.callable_node, *chain.enclosing):
        body = getattr(scope, "body", ())
        if isinstance(body, ast.AST):
            body = (body,)
        if any(isinstance(statement, type_alias) and statement.name.id == name for statement in body):
            return True
    return False


def _empty_constructor(call: ast.Call, chain: _ScopeChain) -> bool:
    if not isinstance(call.func, ast.Name):
        return False
    kind, scope = chain.binding(call.func.id)
    if kind != "definition":
        return False
    for node in ast.iter_child_nodes(scope):
        if isinstance(node, ast.ClassDef) and node.name == call.func.id:
            return _plain_class(node) or _frozen_record(node, chain)
    return False


def _plain_class(node: ast.ClassDef) -> bool:
    return not node.bases and not node.keywords and not node.decorator_list and all(
        isinstance(statement, ast.Pass) or isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
        for statement in node.body
    )


def _frozen_record(node: ast.ClassDef, chain: _ScopeChain) -> bool:
    if node.bases or node.keywords or len(node.decorator_list) != 1:
        return False
    decorator = node.decorator_list[0]
    if not isinstance(decorator, ast.Call) or chain.qualified_name(decorator.func) != "dataclasses.dataclass":
        return False
    return any(_true_keyword(keyword, "frozen") for keyword in decorator.keywords) and all(_record_field(statement) for statement in node.body)


def _true_keyword(keyword: ast.keyword, name: str) -> bool:
    return keyword.arg == name and isinstance(keyword.value, ast.Constant) and keyword.value.value is True


def _record_field(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return statement.value is None or isinstance(statement.value, ast.Constant)
    return isinstance(statement, ast.Pass) or isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)


def _fixed_point(owners: Sequence[CallableEffects], graph: CallGraph) -> dict[int, EffectSummary]:
    summaries = {id(owner.callable.node): EffectSummary.collect(tuple(owner.direct)) for owner in owners}
    while True:
        updated = {
            id(owner.callable.node): EffectSummary.collect(tuple(_located_effects(owner, summaries, graph)))
            for owner in owners
        }
        if updated == summaries:
            return updated
        summaries = updated


def _located_effects(owner: CallableEffects, summaries: dict[int, EffectSummary], graph: CallGraph) -> dict[Effect, ast.AST]:
    located = dict(owner.direct)
    for call in owner.calls:
        target = _target_in_scope(call, owner.callable, graph, owner.callable_aliases)
        if target is None or cold_body(target) or transformed_callable(target, graph.qualified_value):
            continue
        for effect in _transferred_effects(target, call, owner, graph, summaries):
            located.setdefault(effect, call)
    for execution in owner.executions:
        for effect in _transferred_effects(execution.target, execution.creation, owner, graph, summaries):
            located.setdefault(effect, execution.site)
    return located


def _transferred_effects(target, call, owner, graph, summaries) -> tuple[Effect, ...]:
    return tuple(effect for fact in summaries[id(target)].facts for effect in _call_effects(fact, target, call, owner, graph, summaries))


def _target_in_scope(call: ast.Call, info: CallableNode, graph: CallGraph, aliases) -> ast.AST | None:
    target = _resolved_call_target(call, None, graph, aliases)
    if target is not None:
        return target
    scope = info.node
    if isinstance(scope, ast.GeneratorExp):
        scope = next((node for node in info.enclosing if not isinstance(node, ast.GeneratorExp)), scope)
    site = graph.call_site(scope, call)
    return site.callee if site is not None else None


def _resolved_call_target(
    call: ast.Call, owner: CallableEffects | None, graph: CallGraph, aliases: dict[int, dict[str, ast.AST]]
) -> ast.AST | None:
    target = graph.resolve_target(call)
    if target is not None:
        return target
    if isinstance(call.func, ast.Name):
        return aliases.get(id(call), {}).get(call.func.id)
    if owner is not None:
        site = graph.call_site(owner.callable.node, call)
        return site.callee if site is not None else None
    return None


def _call_effects(
    effect: Effect, target: ast.AST, call: ast.Call, owner: CallableEffects,
    graph: CallGraph, summaries: dict[int, EffectSummary],
) -> tuple[Effect, ...]:
    callback = effect.callback
    if callback is not None and callback.scope == id(target):
        return _callback_binding_effects(effect, target, call, owner, graph, summaries)
    factory_call = _factory_creation(target, call)
    if factory_call is not None and effect.origin is not None:
        factory = _target_in_scope(factory_call, owner.callable, graph, owner.callable_aliases)
        if factory is not None and effect.origin.scope == id(factory):
            return _substitute(effect, factory, factory_call, owner)
    return _substitute(effect, target, call, owner)


def _factory_creation(target: ast.AST, call: ast.Call) -> ast.Call | None:
    if isinstance(call.func, ast.Call):
        return call.func
    return call if isinstance(target, ast.GeneratorExp) else None


def _callback_binding_effects(effect, target, call, owner, graph, summaries) -> tuple[Effect, ...]:
    from .analyzer import IMPLICIT_INPUT_NAMES, IMPLICIT_OUTPUT_NAMES

    value = _bound_argument(target, call, effect.callback.name)
    if value is None:
        return (Effect("UnknownEffect", "<callback binding>", reason="missing callback binding"),)
    qualified = graph.qualified_value(value)
    if qualified in IMPLICIT_OUTPUT_NAMES:
        return (Effect("ImplicitOutput", qualified.removeprefix("builtins."), ambient=True),)
    if qualified in IMPLICIT_INPUT_NAMES:
        return (Effect("ImplicitInput", qualified.removeprefix("builtins."), ambient=True),)
    effect = _instantiated_arguments(effect, target, call, owner)
    site = graph.call_site(owner.callable.node, ast.copy_location(ast.Call(func=value, args=[], keywords=[]), call))
    if site is not None and not graph.masked_name(call, value):
        return _callback_effects(site.callee, value, effect, call, owner, summaries)
    return _unresolved_callback(value, effect, owner)


def _unresolved_callback(value: ast.expr, effect: Effect, owner: CallableEffects) -> tuple[Effect, ...]:
    if isinstance(value, ast.Name) and isinstance(owner.callable.node, _FUNCTIONS):
        if value.id in {argument.arg for argument in _arguments(owner.callable.node.args)}:
            injected = Origin(id(owner.callable.node), value.id)
            return (Effect("UnknownEffect", value.id, callback=injected, reason="injected callback",
                           arguments=effect.arguments, keywords=effect.keywords),)
    return (Effect("UnknownEffect", effect.name, reason="unresolved callback"),)


def _instantiated_arguments(effect: Effect, target: ast.AST, call: ast.Call, owner: CallableEffects) -> Effect:
    from .analyzer import _instantiate_storage

    if effect.arguments is None:
        return effect
    arguments = tuple(_instantiate_storage(storage, target, call, owner.ownership) for storage in effect.arguments)
    keywords = tuple((name, _instantiate_storage(storage, target, call, owner.ownership)) for name, storage in effect.keywords)
    return replace(effect, arguments=arguments, keywords=keywords)


def _callback_effects(
    target: ast.AST, value: ast.expr, effect: Effect, call: ast.Call, owner: CallableEffects, summaries
) -> tuple[Effect, ...]:
    if cold_body(target):
        return ()
    mapped = []
    for fact in summaries[id(target)].facts:
        origin = fact.origin
        if origin is None or origin.scope != id(target):
            mapped.extend(_substitute(fact, target, call, owner))
            continue
        storage = _callback_parameter(target, value, effect, origin.name)
        if storage is None:
            mapped.append(Effect("UnknownEffect", "<callback arguments>", reason="callback argument provenance"))
        elif fact.rule == "ImplicitOutput":
            mapped.extend(_mapped_through(fact, storage, "<callback argument>"))
    return tuple(mapped)


def _callback_parameter(target: ast.AST, value: ast.expr, effect: Effect, name: str) -> Storage | None:
    if effect.arguments is None or isinstance(value, ast.Attribute) or not isinstance(target, _FUNCTIONS):
        return None
    for keyword, storage in effect.keywords:
        if keyword == name:
            return storage
    positional = [argument.arg for argument in (*target.args.posonlyargs, *target.args.args)]
    if name in positional and positional.index(name) < len(effect.arguments):
        return effect.arguments[positional.index(name)]
    return None


def _substitute(effect: Effect, target: ast.AST, call: ast.Call, owner: CallableEffects) -> tuple[Effect, ...]:
    origin = effect.origin
    if origin is None:
        return (effect,)
    if origin.scope == id(owner.callable.node):
        if effect.rule == "ImplicitInput":
            return ()
        storage = project_storage(owner.ownership.value(ast.Name(origin.name, ast.Load()), call), origin.path)
        return tuple(Effect(effect.rule, effect.name, source, ambient=effect.ambient) for source in storage.outer)
    if origin.scope != id(target):
        return (effect,)
    value = _bound_argument(target, call, origin.name)
    if value is None or isinstance(value, ast.Starred):
        return (Effect("UnknownEffect", "<argument binding>", reason="missing argument binding"),)
    return _mapped_through(effect, owner.ownership.value(value, call), _dotted_name(value) or "<argument>")


def _mapped_through(effect: Effect, storage: Storage, label: str) -> tuple[Effect, ...]:
    if effect.origin is not None:
        storage = project_storage(storage, effect.origin.path)
    mapped = tuple(Effect(effect.rule, effect.name, source, ambient=effect.ambient) for source in storage.outer)
    if storage.opaque and effect.rule == "ImplicitOutput":
        mapped += (Effect("UnknownEffect", f"mutation of {label}", reason="unknown storage"),)
    return mapped


def _bound_argument(target: ast.AST, call: ast.Call, name: str) -> ast.expr | None:
    if not isinstance(target, _FUNCTIONS):
        return None
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    arguments = [*target.args.posonlyargs, *target.args.args]
    if isinstance(call.func, ast.Attribute) and arguments and arguments[0].arg in {"self", "cls"}:
        arguments = arguments[1:]
    for argument, value in zip(arguments, call.args):
        if argument.arg == name:
            return value
    return None


def _finding(path: Path, callable_info: CallableNode, rule: LoadedRule, effect: Effect, node: ast.AST) -> Finding:
    from .analyzer import Finding

    kind = "function" if callable_info.owner is None else "method"
    if effect.rule == "UnknownEffect":
        phrase = f"has an unknown effect from {effect.name}. Establish the callable's effects before treating it as a calculation."
    elif effect.rule in {"ImplicitInput", "ImplicitInstanceInput"}:
        advice = "Move this effect to the caller." if effect.ambient else "Pass it as an argument instead."
        phrase = f"reads the implicit input {effect.name}. {advice}"
    else:
        advice = "Move this effect to the caller." if effect.ambient else "Return it instead."
        phrase = f"writes the implicit output {effect.name}. {advice}"
    return Finding(path, node.lineno, rule.name, rule.priority, f"The {kind} {callable_info.context}() {phrase}", context=callable_info.context)


def _receiver_uncertainty(
    path: Path, owner: CallableEffects, located: dict[Effect, ast.AST], selected: dict[str, LoadedRule]
) -> list[Finding]:
    rule = selected.get("UnknownEffect")
    if rule is None:
        return []
    hidden = {effect.name: node for effect, node in located.items()
              if effect.rule.startswith("ImplicitInstance") and effect.rule not in selected}
    return [_finding(path, owner.callable, rule, Effect("UnknownEffect", name), node) for name, node in hidden.items()]
