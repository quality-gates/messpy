from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .callables import CallableNode, module_callables
from .callgraph import CallGraph, _arguments, _dotted_name, _evaluated_nodes, _module_nodes, build_call_graph
from .names import Names
from .ownership import Origin, Ownership
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


_PURE_CALLS = frozenset({
    "builtins.abs", "builtins.all", "builtins.any", "builtins.bin", "builtins.bool", "builtins.chr",
    "builtins.dict", "builtins.divmod", "builtins.enumerate", "builtins.float", "builtins.format",
    "builtins.frozenset", "builtins.hex", "builtins.int", "builtins.isinstance", "builtins.issubclass",
    "builtins.len", "builtins.list", "builtins.max", "builtins.min", "builtins.oct", "builtins.ord",
    "builtins.pow", "builtins.range", "builtins.reversed", "builtins.round", "builtins.set",
    "builtins.sorted", "builtins.str", "builtins.sum", "builtins.tuple", "builtins.zip",
    "math.ceil", "math.floor", "math.sqrt", "math.fabs", "math.isfinite", "math.isnan", "math.isinf",
})
_MUTATORS = {
    "list": frozenset({"append", "clear", "extend", "insert", "pop", "remove", "reverse", "sort"}),
    "dict": frozenset({"clear", "pop", "popitem", "setdefault", "update"}),
    "set": frozenset({"add", "clear", "discard", "pop", "remove", "update"}),
}
_PURE_METHODS = {
    "list": frozenset({"copy", "count", "index"}),
    "dict": frozenset({"copy", "get", "items", "keys", "values"}),
    "set": frozenset({"copy", "difference", "intersection", "union", "issubset", "issuperset"}),
    "str": frozenset({"capitalize", "casefold", "endswith", "find", "join", "lower", "replace", "split", "startswith", "strip", "upper"}),
}


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
    from .analyzer import _ScopeChain, _argument_ownership, _caller_owned_parameters, _name_scopes

    parents = {id(child): parent for parent in _module_nodes(tree) for child in ast.iter_child_nodes(parent)}
    scopes = _name_scopes(tree)
    owners = []
    for callable_info in module_callables(tree):
        chain = _ScopeChain((callable_info.node, *callable_info.enclosing), scopes, parents=parents, names=names)
        nodes = _evaluated_nodes(callable_info.node)
        ownership = _argument_ownership(callable_info, nodes, chain, _caller_owned_parameters(callable_info), graph)
        callable_aliases = _callable_aliases(callable_info, nodes, graph)
        direct = _direct_effects(callable_info, chain, ownership)
        calls = tuple(node for node in nodes if isinstance(node, ast.Call))
        direct.update(_unknown_calls(calls, callable_info, chain, ownership, graph, callable_aliases))
        owners.append(CallableEffects(callable_info, direct, ownership, calls, callable_aliases))
    return tuple(owners)


def _unknown_calls(calls, callable_info, chain, ownership, graph, callable_aliases) -> dict[Effect, ast.AST]:
    return {
        Effect(
            "UnknownEffect",
            _dotted_name(call.func) or "<dynamic call>",
            callback=_callback_origin(call, callable_info, chain),
            reason="unresolved call",
        ): call
        for call in calls
        if _resolved_call_target(call, None, graph, callable_aliases) is None
        and not _established_call(call, callable_info, chain, ownership)
    }


def _callable_aliases(callable_info: CallableNode, nodes: Sequence[ast.AST], graph: CallGraph) -> dict[int, dict[str, ast.AST]]:
    aliases: dict[str, ast.AST] = {}
    observations: dict[int, dict[str, ast.AST]] = {}
    for node in nodes:
        observations[id(node)] = dict(aliases)
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            aliases = _updated_callable_aliases(aliases, node.targets[0], node.value, callable_info, graph)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            aliases = _updated_callable_aliases(aliases, node.target, node.value, callable_info, graph)
    return observations


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
    if not isinstance(call.func, ast.Name):
        return None
    parameters = {argument.arg for argument in _arguments(callable_info.node.args)}
    if call.func.id in parameters and chain.binding(call.func.id)[1] is callable_info.node:
        return Origin(id(callable_info.node), call.func.id)
    return None


def _direct_effects(callable_info: CallableNode, chain: _ScopeChain, ownership: Ownership) -> dict[Effect, ast.AST]:
    from .analyzer import (
        _input_nodes, _method_receiver, _read_nodes,
    )

    direct = {}
    for name, node in _input_nodes(callable_info, chain).items():
        origin = Origin(id(chain.binding(name)[1]), name) if isinstance(node, ast.Name) else None
        direct[Effect("ImplicitInput", name, origin)] = node
    receiver = _method_receiver(callable_info)
    read_nodes = _read_nodes(callable_info.node)
    called = {id(node.func) for node in read_nodes if isinstance(node, ast.Call)}
    for node in read_nodes:
        for effect in _write_effects(node, chain.for_node(node), ownership):
            direct.setdefault(effect, node)
        for effect in _instance_effects(node, callable_info, chain, receiver, called):
            direct.setdefault(effect, node)
    return direct


def _write_effects(node: ast.AST, chain: _ScopeChain, ownership: Ownership) -> tuple[Effect, ...]:
    from .analyzer import _ambient_write, _changed_object, _storage_write

    name = _storage_write(node, chain, ownership) or _ambient_write(node, chain)
    if not name:
        return ()
    changed = _changed_object(node, chain)
    origins = ownership.value(changed, node).outer if changed is not None else frozenset()
    if not origins and isinstance(node, ast.Name):
        origins = frozenset({Origin(id(chain.binding(node.id)[1]), node.id)})
    return tuple(Effect("ImplicitOutput", name, origin) for origin in origins or {None})


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
    if qualified in IMPLICIT_INPUT_NAMES | IMPLICIT_OUTPUT_NAMES | OPEN_CALL_NAMES:
        return True
    if _changed_object(call, chain) is not None:
        return True
    receiver = _method_receiver(callable_info)
    if receiver is not None and _receiver_call(call, receiver):
        return True
    if _type_alias_call(call, chain):
        return True
    if qualified in _PURE_CALLS:
        return not any(keyword.arg == "key" for keyword in call.keywords)
    base, _, method = qualified.rpartition(".")
    if base.removeprefix("builtins.") in _MUTATORS and base.startswith("builtins."):
        return method in _MUTATORS[base.removeprefix("builtins.")]
    if isinstance(call.func, ast.Attribute):
        receiver = ownership.value(call.func.value, call)
        if len(receiver.kinds) == 1:
            kind = next(iter(receiver.kinds))
            methods = _MUTATORS.get(kind, frozenset()) | _PURE_METHODS.get(kind, frozenset())
            return call.func.attr in methods and not any(keyword.arg == "key" for keyword in call.keywords)
    return _empty_constructor(call, chain)


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
            return _plain_class(node)
    return False


def _plain_class(node: ast.ClassDef) -> bool:
    return not node.bases and not node.keywords and not node.decorator_list and all(
        isinstance(statement, ast.Pass) or isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
        for statement in node.body
    )


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
        target = _resolved_call_target(call, owner, graph, owner.callable_aliases)
        if target is None:
            continue
        for fact in summaries[id(target)].facts:
            for effect in _call_effects(fact, target, call, owner, graph, summaries):
                located.setdefault(effect, call)
    return located


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
    if callback is None or callback.scope != id(target):
        return _substitute(effect, target, call, owner)
    value = _bound_argument(target, call, callback.name)
    if value is None:
        return (Effect("UnknownEffect", "<callback binding>", reason="missing callback binding"),)
    site = graph.call_site(owner.callable.node, ast.copy_location(ast.Call(func=value, args=[], keywords=[]), call))
    if site is not None:
        return _callback_effects(site.callee, call, owner, summaries)
    if isinstance(value, ast.Name) and value.id in {argument.arg for argument in _arguments(owner.callable.node.args)}:
        return (Effect("UnknownEffect", value.id, callback=Origin(id(owner.callable.node), value.id), reason="injected callback"),)
    return (Effect("UnknownEffect", effect.name, reason="unresolved callback"),)


def _callback_effects(target: ast.AST, call: ast.Call, owner: CallableEffects, summaries) -> tuple[Effect, ...]:
    mapped = []
    for fact in summaries[id(target)].facts:
        if fact.origin is not None and fact.origin.scope == id(target):
            mapped.append(Effect("UnknownEffect", "<callback arguments>", reason="callback argument provenance"))
        else:
            mapped.extend(_substitute(fact, target, call, owner))
    return tuple(mapped)


def _substitute(effect: Effect, target: ast.AST, call: ast.Call, owner: CallableEffects) -> tuple[Effect, ...]:
    origin = effect.origin
    if origin is None:
        return (effect,)
    if origin.scope == id(owner.callable.node):
        if effect.rule == "ImplicitInput":
            return ()
        storage = owner.ownership.value(ast.Name(origin.name, ast.Load()), call)
        return tuple(Effect(effect.rule, effect.name, source) for source in storage.outer)
    if origin.scope != id(target):
        return (effect,)
    value = _bound_argument(target, call, origin.name)
    if value is None or isinstance(value, ast.Starred):
        return (Effect("UnknownEffect", "<argument binding>", reason="missing argument binding"),)
    storage = owner.ownership.value(value, call)
    return tuple(Effect(effect.rule, effect.name, source) for source in storage.outer)


def _bound_argument(target: ast.AST, call: ast.Call, name: str) -> ast.expr | None:
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
        phrase = f"reads the implicit input {effect.name}. Pass it as an argument instead."
    else:
        phrase = f"writes the implicit output {effect.name}. Return it instead."
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
