from __future__ import annotations

import ast
import fnmatch
import importlib.util
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .callgraph import CallGraph, CallSite, _parent_map
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


def onion_findings(
    path: Path, tree: ast.Module, rules: Sequence[LoadedRule], call_graph: Callable[[], CallGraph]
) -> list[Finding]:
    action_rule = _named_rule(rules, DOMAIN_ACTION_RULE_NAME)
    import_rule = _named_rule(rules, DOMAIN_OUTER_IMPORT_RULE_NAME)
    findings = []
    if action_rule is not None and _in_domain(path, action_rule):
        findings.extend(_domain_action_findings(path, tree, action_rule, call_graph()))
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


def _domain_action_findings(path: Path, tree: ast.Module, rule: LoadedRule, graph: CallGraph) -> list:
    direct, phrases = _direct_actions(path, tree, rule)
    return [*_import_time_findings(path, tree, rule), *direct, *_spread_findings(path, graph, rule, phrases)]


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


def _spread_findings(path: Path, graph: CallGraph, rule: LoadedRule, phrases: dict[int, str]) -> list:
    actions = _action_ids(graph, phrases)
    findings = []
    for caller in graph.callables:
        for site in graph.callees(caller):
            if id(site.callee) not in actions:
                continue
            phrase = _chain_phrase(site.callee, phrases, graph, set())
            if not phrase:
                continue
            findings.append(_spread_finding(path, rule, graph, site, phrase))
    return findings


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
