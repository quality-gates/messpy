from __future__ import annotations

import ast
import fnmatch
import importlib.util
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .callables import module_callables
from .callgraph import CallGraph, CallSite, _module_nodes
from .names import Names
from .rulesets import LoadedRule

if TYPE_CHECKING:
    from .analyzer import Finding, SourceFile

DOMAIN_ACTION_RULE_NAME = "DomainAction"
DOMAIN_OUTER_IMPORT_RULE_NAME = "DomainOuterImport"


def onion_findings(
    identity: SourceFile,
    tree: ast.Module,
    rules: Sequence[LoadedRule],
    call_graph: Callable[[], CallGraph],
    names: Names | None = None,
) -> list[Finding]:
    resolved_names = names if names is not None else Names.build(tree, module=identity.module, path=identity.path)
    action_rule = _named_rule(rules, DOMAIN_ACTION_RULE_NAME)
    import_rule = _named_rule(rules, DOMAIN_OUTER_IMPORT_RULE_NAME)
    findings = []
    if action_rule is not None and _in_domain(identity.path, action_rule):
        findings.extend(_domain_action_findings(identity.path, tree, action_rule, call_graph(), resolved_names))
    if import_rule is not None and _in_domain(identity.path, import_rule):
        findings.extend(_outer_import_findings(identity, tree, import_rule, resolved_names))
    return findings


def _named_rule(rules: Sequence[LoadedRule], name: str) -> LoadedRule | None:
    return next((rule for rule in rules if rule.name == name), None)


def _in_domain(path: Path, rule: LoadedRule) -> bool:
    posix = path.as_posix()
    for pattern in rule.items("domain"):
        if fnmatch.fnmatchcase(posix, pattern):
            return True
    return False


def _domain_action_findings(
    path: Path, tree: ast.Module, rule: LoadedRule, graph: CallGraph, names: Names
) -> list:
    direct, phrases = _direct_actions(path, tree, rule, names)
    return [
        *_import_time_findings(path, tree, rule, names),
        *direct,
        *_spread_findings(path, tree, graph, rule, phrases),
    ]


def _direct_actions(path: Path, tree: ast.Module, rule: LoadedRule, names: Names) -> tuple[list, dict[int, str]]:
    from .analyzer import (
        _ScopeChain,
        _implicit_input_findings,
        _implicit_instance_output_findings,
        _implicit_output_findings,
        _name_scopes,
    )

    parents = {id(child): parent for parent in _module_nodes(tree) for child in ast.iter_child_nodes(parent)}
    name_scopes = _name_scopes(tree)
    findings = []
    phrases: dict[int, str] = {}
    for callable_info in module_callables(tree):
        chain = _ScopeChain(
            (callable_info.node, *callable_info.enclosing),
            name_scopes,
            parents=parents,
            enclosing=callable_info.enclosing,
            names=names,
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


def _action_phrase(message: str) -> str:
    sentence, _separator, _rest = message.partition(". ")
    _prefix, separator, phrase = sentence.partition("() ")
    if separator:
        return phrase
    return sentence


def _import_time_findings(path: Path, tree: ast.Module, rule: LoadedRule, names: Names) -> list:
    from .analyzer import _ScopeChain, _ambient_read, _ambient_write, _name_scopes

    chain = _ScopeChain((tree,), _name_scopes(tree), names=names)
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


def _spread_findings(
    path: Path, tree: ast.Module, graph: CallGraph, rule: LoadedRule, phrases: dict[int, str]
) -> list:
    actions = _action_ids(graph, phrases)
    sites = [site for caller in graph.callables for site in graph.callees(caller)]
    sites.extend(_module_call_sites(tree, graph))

    findings = []
    for site in sites:
        if id(site.callee) not in actions:
            continue
        phrase = _chain_phrase(site.callee, phrases, graph, set())
        if not phrase:
            continue
        findings.append(_spread_finding(path, rule, graph, site, phrase))
    return findings


def _module_call_sites(tree: ast.Module, graph: CallGraph) -> list[CallSite]:
    sites = []
    seen: set[int] = set()
    for node in _import_time_nodes(tree):
        if not isinstance(node, ast.Call):
            continue
        site = graph.call_site(tree, node)
        if site is None or id(site.callee) in seen:
            continue
        seen.add(id(site.callee))
        sites.append(site)
    return sites


def _action_ids(graph: CallGraph, phrases: dict[int, str]) -> set[int]:
    actions = set(phrases)
    pending = [node for node in graph.callables if id(node) in phrases]
    while pending:
        for site in graph.callers(pending.pop()):
            if id(site.caller) not in actions:
                actions.add(id(site.caller))
                pending.append(site.caller)
    return actions


def _chain_phrase(callee: ast.AST, phrases: dict[int, str], graph: CallGraph, seen: set[int]) -> str:
    direct = phrases.get(id(callee), "")
    if direct:
        return direct
    if id(callee) in seen:
        return ""
    followed = {*seen, id(callee)}
    for site in graph.callees(callee):
        phrase = _chain_phrase(site.callee, phrases, graph, followed)
        if phrase:
            return f"calls {site.name}(), which {phrase}"
    return ""


def _spread_finding(path, rule, graph: CallGraph, site: CallSite, phrase: str):
    if isinstance(site.caller, ast.Module):
        message = (
            f"The module calls {site.name}(), which {phrase}, at import time. "
            "Move the action to the interaction layer."
        )
        return _finding(path, site.line, rule, message)

    kind, context = _caller_context(graph, site.caller)
    message = (
        f"The {kind} {context}() calls {site.name}(), which {phrase}. "
        "Move the action to the interaction layer."
    )
    return _finding(path, site.line, rule, message, context)


def _caller_context(graph: CallGraph, caller: ast.AST) -> tuple[str, str]:
    owner = graph.method_class(caller)
    label = "<lambda>" if isinstance(caller, ast.Lambda) else caller.name
    if owner is not None:
        return "method", f"{owner.name}.{label}"
    return "function", label


def _outer_import_findings(identity: SourceFile, tree: ast.Module, rule: LoadedRule, names: Names) -> list:
    layers = rule.items("outer-layers")
    findings = []
    for node in ast.walk(tree):
        for module, layer in _matched_imports(names, node, layers):
            findings.append(_import_finding(identity.path, node, rule, module, layer))
    return findings


def _matched_imports(names: Names, node: ast.AST, layers: Sequence[str]) -> list[tuple[str, str]]:
    if not isinstance(node, (ast.Import, ast.ImportFrom)):
        return []
    if isinstance(node, ast.Import):
        imported = [alias.name for alias in node.names]
    else:
        base = names.module_of(node)
        layer = _matching_layer(base, layers)
        if layer:
            return [(base, layer)]
        imported = _imported_module_names(base, node)
    matches: list[tuple[str, str]] = []
    seen: set[str] = set()
    for module in imported:
        layer = _matching_layer(module, layers)
        if not layer or module in seen:
            continue
        seen.add(module)
        matches.append((module, layer))
    return matches


def _imported_module_names(base: str, node: ast.ImportFrom) -> list[str]:
    names = [base] if base else []
    names.extend(
        f"{base}.{alias.name}" if base else alias.name
        for alias in node.names
        if alias.name != "*"
    )
    return names


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
