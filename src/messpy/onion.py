from __future__ import annotations

import ast
import fnmatch
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .rulesets import LoadedRule, RulesetError

DOMAIN_ACTION_RULE_NAME = "DomainAction"
DOMAIN_OUTER_IMPORT_RULE_NAME = "DomainOuterImport"


def validate_onion_rules(rules: Sequence[LoadedRule]) -> None:
    for rule in rules:
        if rule.name == DOMAIN_ACTION_RULE_NAME:
            _require_list(rule, "domain", "path pattern")
        elif rule.name == DOMAIN_OUTER_IMPORT_RULE_NAME:
            _require_list(rule, "domain", "path pattern")
            _require_list(rule, "outer-layers", "module")


def onion_findings(path: Path, tree: ast.Module, rules: Sequence[LoadedRule]) -> list:
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
        _record_ambient(node, chain, _ambient_read, reads)
        _record_ambient(node, chain, _ambient_write, writes)
    return [
        *_ambient_findings(path, rule, reads, "reads the implicit input"),
        *_ambient_findings(path, rule, writes, "writes the implicit output"),
    ]


def _record_ambient(node: ast.AST, chain, classify, found: dict[str, ast.AST]) -> None:
    name = classify(node, chain)
    if name:
        found.setdefault(name, node)


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
    collector = _ImportTimeNodes()
    for statement in tree.body:
        collector.visit(statement)
    return collector.nodes


class _ImportTimeNodes(ast.NodeVisitor):
    def __init__(self) -> None:
        self.nodes: list[ast.AST] = []

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._visit_signature(node)
            return
        if isinstance(node, ast.Lambda):
            self._visit_defaults(node)
            return
        if isinstance(node, ast.ClassDef):
            self._visit_class(node)
            return
        self.nodes.append(node)
        super().generic_visit(node)

    def _visit_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for child in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if child is not None:
                self.visit(child)

    def _visit_defaults(self, node: ast.Lambda) -> None:
        for child in (*node.args.defaults, *node.args.kw_defaults):
            if child is not None:
                self.visit(child)

    def _visit_class(self, node: ast.ClassDef) -> None:
        for child in (*node.decorator_list, *node.bases, *(item.value for item in node.keywords)):
            self.visit(child)
        for statement in node.body:
            self.visit(statement)


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
    names: dict[int, str]
    labels: dict[int, str]
    bindings: dict[int, dict[str, int]]
    shadows: dict[int, set[str]]
    enclosing: dict[int, tuple[int, ...]]
    class_methods: dict[int, dict[str, int]]
    callable_class: dict[int, int]
    receivers: dict[int, str]
    owners: dict[int, str]
    class_ids: frozenset[int]


def _index_callables(tree: ast.Module) -> _CallableIndex:
    binder = _CallableBinder()
    binder.visit(tree)
    return _CallableIndex(
        nodes=binder.nodes,
        names=binder.names,
        labels=binder.labels,
        bindings=binder.bindings,
        shadows=binder.shadows,
        enclosing=binder.enclosing,
        class_methods=binder.class_methods,
        callable_class=binder.callable_class,
        receivers=binder.receivers,
        owners=binder.owners,
        class_ids=frozenset(binder.class_ids),
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
                _CallSite(callee_id, index.names[callee_id], child.lineno)
            )
    return edges


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
    return None


def _comprehension_targets(call: ast.Call, parents: dict[int, ast.AST]) -> set[str]:
    targets: set[str] = set()
    current: ast.AST = call
    while id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef, ast.Module)):
            break
        if isinstance(current, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            _add_comprehension_targets(call, current, parents, targets)
    return targets


def _add_comprehension_targets(
    call: ast.Call,
    comp: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    parents: dict[int, ast.AST],
    targets: set[str],
) -> None:
    if _in_outer_iterable(call, comp, parents):
        return
    for generator in comp.generators:
        targets.update(_stored_names(generator.target))


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
        if name in index.shadows.get(scope_id, ()):
            return None
        callee_id = index.bindings.get(scope_id, {}).get(name)
        if callee_id is not None:
            return callee_id
    return None


def _resolve_receiver_call(index: _CallableIndex, caller_id: int, attribute: ast.Attribute) -> int | None:
    receiver = index.receivers.get(caller_id, "")
    value = attribute.value
    if not receiver or not isinstance(value, ast.Name) or value.id != receiver:
        return None
    class_id = index.callable_class.get(caller_id)
    if class_id is None:
        return None
    return index.class_methods.get(class_id, {}).get(attribute.attr)


class _CallableBinder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.nodes: dict[int, ast.AST] = {}
        self.names: dict[int, str] = {}
        self.labels: dict[int, str] = {}
        self.bindings: dict[int, dict[str, int]] = {}
        self.shadows: dict[int, set[str]] = {}
        self.enclosing: dict[int, tuple[int, ...]] = {}
        self.class_methods: dict[int, dict[str, int]] = {}
        self.callable_class: dict[int, int] = {}
        self.receivers: dict[int, str] = {}
        self.owners: dict[int, str] = {}
        self.class_ids: set[int] = set()
        self._scopes: list[ast.AST] = []
        self._classes: list[ast.ClassDef] = []

    def visit_Module(self, node: ast.Module) -> None:
        self._scopes.append(node)
        for statement in node.body:
            self.visit(statement)
        self._scopes.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._shadow(node.name)
        self.class_ids.add(id(node))
        for child in (*node.decorator_list, *node.bases):
            self.visit(child)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self._classes.append(node)
        self._scopes.append(node)
        for statement in node.body:
            self.visit(statement)
        self._scopes.pop()
        self._classes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._define_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._define_function(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        bound = _lambda_binding(node)
        if bound is not None:
            name, lambda_node = bound
            self._bind_callable(name, lambda_node)
            self._enter_lambda(lambda_node)
            return
        for target in node.targets:
            self._shadow_target(target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and isinstance(node.value, ast.Lambda):
            self._bind_callable(node.target.id, node.value)
            self._enter_lambda(node.value)
            return
        self._shadow_target(node.target)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._shadow(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self._shadow(alias.asname or alias.name)

    def generic_visit(self, node: ast.AST) -> None:
        self._shadow_node(node)
        super().generic_visit(node)

    def _define_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._bind_callable(node.name, node)
        self._record_method(node)
        self.enclosing[id(node)] = tuple(id(scope) for scope in reversed(self._scopes))
        self._scopes.append(node)
        self._shadow_arguments(node)
        for statement in node.body:
            self.visit(statement)
        self._scopes.pop()

    def _enter_lambda(self, node: ast.Lambda) -> None:
        self.enclosing[id(node)] = tuple(id(scope) for scope in reversed(self._scopes))
        self._scopes.append(node)
        self._shadow_arguments(node)
        self.visit(node.body)
        self._scopes.pop()

    def _bind_callable(self, name: str, node: ast.AST) -> None:
        scope = self._scopes[-1]
        self.bindings.setdefault(id(scope), {})[name] = id(node)
        self.shadows.setdefault(id(scope), set()).discard(name)
        self.nodes[id(node)] = node
        self.names[id(node)] = name
        self.labels[id(node)] = "<lambda>" if isinstance(node, ast.Lambda) else node.name

    def _record_method(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if not self._classes or self._scopes[-1] is not self._classes[-1]:
            return
        class_node = self._classes[-1]
        self.class_methods.setdefault(id(class_node), {})[node.name] = id(node)
        self.callable_class[id(node)] = id(class_node)
        self.owners[id(node)] = class_node.name
        receiver = _receiver_name(node)
        if receiver:
            self.receivers[id(node)] = receiver

    def _shadow_arguments(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            self._shadow(argument.arg)
        if node.args.vararg is not None:
            self._shadow(node.args.vararg.arg)
        if node.args.kwarg is not None:
            self._shadow(node.args.kwarg.arg)

    def _shadow(self, name: str) -> None:
        scope = self._scopes[-1]
        self.shadows.setdefault(id(scope), set()).add(name)
        self.bindings.setdefault(id(scope), {}).pop(name, None)

    def _shadow_target(self, node: ast.AST) -> None:
        for name in _stored_names(node):
            self._shadow(name)

    def _shadow_node(self, node: ast.AST) -> None:
        if isinstance(node, (ast.For, ast.AsyncFor, ast.NamedExpr)):
            self._shadow_target(node.target)
            return
        if isinstance(node, (ast.With, ast.AsyncWith)):
            self._shadow_with(node)
            return
        if isinstance(node, ast.ExceptHandler) and node.name is not None:
            self._shadow(node.name)

    def _shadow_with(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._shadow_target(item.optional_vars)


def _lambda_binding(node: ast.Assign) -> tuple[str, ast.Lambda] | None:
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return None
    if not isinstance(node.value, ast.Lambda):
        return None
    return node.targets[0].id, node.value


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
    if not base:
        return []
    return [base]


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
        if module == layer or module.startswith(f"{layer}."):
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
