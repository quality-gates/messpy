"""Storage ownership inside one callable.

The analysis follows each local name through the body of one callable. A Storage value gives the outer
storage that the value can be (outer), the outer storage that the value can reach (reachable), the builtin
kinds that the value can have, whether the analysis cannot follow the value (opaque), and whether the value
can reach storage that the analysis cannot follow (deep). A mutation of opaque storage is an unknown effect,
because the storage can be shared.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from .reachability import constant_truth, evaluated_children, live_statements

__all__ = [
    "PURE_CALL_KINDS",
    "Origin",
    "Ownership",
    "Storage",
    "argument_ownership",
    "augmented_mutation",
    "storage_value",
]


@dataclass(frozen=True)
class Origin:
    scope: int
    name: str


@dataclass(frozen=True)
class Storage:
    outer: frozenset[Origin] = frozenset()
    reachable: frozenset[Origin] = frozenset()
    kinds: frozenset[str] = frozenset({"unknown"})
    opaque: bool = False
    deep: bool = False

    @property
    def everything(self) -> frozenset[Origin]:
        return self.outer | self.reachable

    @property
    def reaches_unknown(self) -> bool:
        return self.opaque or self.deep

    def join(self, other: Storage) -> Storage:
        return Storage(
            self.outer | other.outer,
            self.reachable | other.reachable,
            self.kinds | other.kinds,
            self.opaque or other.opaque,
            self.deep or other.deep,
        )


# A call of one of these kinds does not keep a reference to its arguments.
_COPY_KINDS = frozenset({"list", "dict", "set", "tuple", "frozenset"})
PURE_CALL_KINDS = _COPY_KINDS | frozenset({"fresh", "element"})
_ELEMENT_METHODS = MappingProxyType({
    "list": frozenset({"pop", "index", "count"}),
    "dict": frozenset({"get", "pop", "setdefault", "items", "keys", "values", "popitem"}),
    "set": frozenset({"pop"}),
})
_COMPREHENSION_KINDS = MappingProxyType({ast.ListComp: "list", ast.SetComp: "set", ast.DictComp: "dict", ast.GeneratorExp: "generator"})


@dataclass(frozen=True)
class Ownership:
    observations: dict[int, dict[str, Storage]]
    external: dict[str, Storage]
    copies: dict[int, str]
    returned: dict[int, Storage] = field(default_factory=dict)

    def value(self, expression: ast.AST, node: ast.AST) -> Storage:
        return storage_value(expression, self.observations.get(id(node), {}), self.external, self.copies, self.returned)


@dataclass(frozen=True)
class _View:
    bindings: Mapping[str, Storage]
    external: Mapping[str, Storage]
    calls: Mapping[int, str]
    returned: Mapping[int, Storage]

    def name(self, name: str) -> Storage:
        found = self.bindings.get(name)
        if found is None:
            found = self.external.get(name, Storage(opaque=True))
        return found


def storage_value(
    expression: ast.AST,
    bindings: Mapping[str, Storage],
    external: Mapping[str, Storage],
    copies: Mapping[int, str],
    returned: Mapping[int, Storage] | None = None,
) -> Storage:
    """The storage that an expression gives, for the name bindings that hold where Python evaluates it."""
    return _value(expression, _View(bindings, external, copies, returned or {}))


def _value(expression: ast.AST, view: _View) -> Storage:
    handler = _VALUE_HANDLERS.get(type(expression))
    if handler is not None:
        return handler(expression, view)
    if isinstance(expression, tuple(_COMPREHENSION_KINDS)):
        return _comprehension_storage(expression, view)
    return Storage(opaque=True)


def _name_storage(expression: ast.Name, view: _View) -> Storage:
    return view.name(expression.id)


def _constant_storage(expression: ast.Constant, _view: _View) -> Storage:
    return Storage(kinds=frozenset({type(expression.value).__name__}))


def _string_storage(_expression: ast.AST, _view: _View) -> Storage:
    return Storage(kinds=frozenset({"str"}))


def _comparison_storage(_expression: ast.AST, _view: _View) -> Storage:
    return Storage(kinds=frozenset({"bool"}))


def _branch_storage(expression: ast.IfExp, view: _View) -> Storage:
    return _value(expression.body, view).join(_value(expression.orelse, view))


def _either_storage(expression: ast.BoolOp, view: _View) -> Storage:
    return _joined(_value(value, view) for value in expression.values)


def _walrus_storage(expression: ast.NamedExpr, view: _View) -> Storage:
    return _value(expression.value, view)


def _starred_storage(expression: ast.Starred, view: _View) -> Storage:
    # A starred value in a display gives the elements of the value.
    return _elements(_value(expression.value, view))


def _operator_storage(expression: ast.BinOp | ast.UnaryOp, view: _View) -> Storage:
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        return Storage(kinds=frozenset({"bool"}))
    operands = [expression.operand] if isinstance(expression, ast.UnaryOp) else [expression.left, expression.right]
    values = [_value(operand, view) for operand in operands]
    # An operator of a value that the analysis cannot follow can give that value.
    return replace(_fresh_from(values), opaque=any(value.opaque for value in values))


def _lambda_storage(_expression: ast.Lambda, _view: _View) -> Storage:
    return Storage(kinds=frozenset({"function"}))


def _selected_storage(expression: ast.Attribute | ast.Subscript, view: _View) -> Storage:
    base = _value(expression.value, view)
    if isinstance(expression, ast.Subscript) and isinstance(expression.slice, ast.Slice):
        return Storage(reachable=base.everything, kinds=base.kinds, opaque=base.opaque, deep=base.deep)
    return _elements(base)


def _call_storage(expression: ast.Call, view: _View) -> Storage:
    returned = view.returned.get(id(expression))
    if returned is not None:
        return returned
    kind = view.calls.get(id(expression), "")
    if kind:
        return _known_call_storage(expression, kind, view)
    if isinstance(expression.func, ast.Attribute):
        return _method_storage(expression.func, view)
    return Storage(opaque=True)


def _known_call_storage(expression: ast.Call, kind: str, view: _View) -> Storage:
    arguments = [_value(argument, view) for argument in _call_arguments(expression)]
    if kind in _COPY_KINDS:
        source = arguments[0] if expression.args else Storage(kinds=frozenset())
        return Storage(reachable=source.everything, kinds=frozenset({kind}), deep=source.reaches_unknown)
    if kind == "element":
        return _elements(_joined(arguments))
    return _fresh_from(arguments)


def _method_storage(function: ast.Attribute, view: _View) -> Storage:
    receiver = _value(function.value, view)
    if receiver.opaque or len(receiver.kinds) != 1:
        return Storage(opaque=True)
    kind = next(iter(receiver.kinds))
    if function.attr == "copy" and kind in {"list", "dict", "set"}:
        return Storage(reachable=receiver.everything, kinds=receiver.kinds, deep=receiver.deep)
    if function.attr in _ELEMENT_METHODS.get(kind, frozenset()):
        return _elements(receiver)
    return Storage(kinds=frozenset()) if kind == "str" else Storage(opaque=True)


def _container_storage(expression: ast.List | ast.Tuple | ast.Set | ast.Dict, view: _View) -> Storage:
    elements = [_value(child, view) for child in ast.iter_child_nodes(expression) if isinstance(child, ast.expr)]
    container = _fresh_from(elements)
    return replace(container, kinds=frozenset({type(expression).__name__.lower()}))


def _comprehension_storage(expression: ast.expr, view: _View) -> Storage:
    targets = {name.id for generator in expression.generators for name in ast.walk(generator.target) if isinstance(name, ast.Name)}
    sources = [view.bindings.get(name) or view.external.get(name) for name in sorted(_comprehension_reads(expression) - targets)]
    container = _fresh_from(source for source in sources if source is not None)
    return replace(container, kinds=frozenset({_COMPREHENSION_KINDS[type(expression)]}))


def _comprehension_reads(expression: ast.expr) -> set[str]:
    return {node.id for node in ast.walk(expression) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}


_VALUE_HANDLERS = MappingProxyType({
    ast.Name: _name_storage,
    ast.Constant: _constant_storage,
    ast.JoinedStr: _string_storage,
    ast.Compare: _comparison_storage,
    ast.IfExp: _branch_storage,
    ast.BoolOp: _either_storage,
    ast.NamedExpr: _walrus_storage,
    ast.Starred: _starred_storage,
    ast.BinOp: _operator_storage,
    ast.UnaryOp: _operator_storage,
    ast.Lambda: _lambda_storage,
    ast.Attribute: _selected_storage,
    ast.Subscript: _selected_storage,
    ast.Call: _call_storage,
    ast.List: _container_storage,
    ast.Tuple: _container_storage,
    ast.Set: _container_storage,
    ast.Dict: _container_storage,
})


def _elements(storage: Storage) -> Storage:
    return Storage(storage.everything, storage.everything, opaque=storage.reaches_unknown, deep=storage.reaches_unknown)


def _fresh_from(sources) -> Storage:
    sources = list(sources)
    reachable = frozenset(origin for source in sources for origin in source.everything)
    return Storage(reachable=reachable, deep=any(source.reaches_unknown for source in sources))


def _joined(sources) -> Storage:
    joined = Storage(kinds=frozenset())
    for source in sources:
        joined = joined.join(source)
    return joined


def _call_arguments(call: ast.Call) -> list[ast.expr]:
    return [*call.args, *(keyword.value for keyword in call.keywords)]


_IN_PLACE_OPERATORS = (ast.Add, ast.Mult, ast.BitOr, ast.BitAnd, ast.BitXor, ast.Sub)
_IMMUTABLE_KINDS = frozenset({"int", "float", "complex", "bool", "str", "bytes", "NoneType", "tuple"})
_NUMERIC_KINDS = frozenset({"int", "float", "complex", "bool"})
_MUTABLE_KINDS = frozenset({"list", "dict", "set"})


def augmented_mutation(node: ast.AST, ownership: Ownership) -> str:
    """How an augmented assignment changes the storage of a name: "write", "unknown", or ""."""
    if not isinstance(node, ast.AugAssign) or not isinstance(node.target, ast.Name):
        return ""
    if not isinstance(node.op, _IN_PLACE_OPERATORS):
        return ""
    target = ownership.value(ast.Name(node.target.id, ast.Load()), node)
    if not (target.outer or target.opaque) or target.kinds <= _IMMUTABLE_KINDS:
        return ""
    return _in_place_mutation(target, ownership.value(node.value, node))


def _in_place_mutation(target: Storage, value: Storage) -> str:
    if target.kinds & _MUTABLE_KINDS:
        return "write"
    if value.kinds <= _NUMERIC_KINDS:
        return ""
    return "write" if value.kinds & (_MUTABLE_KINDS | {"tuple"}) else "unknown"


@dataclass(frozen=True)
class _Seen:
    node: int
    bindings: Mapping[str, Storage]


@dataclass(frozen=True)
class _Flow:
    """The bindings after a node, and the bindings that Python sees at each node inside it."""

    bindings: dict[str, Storage]
    trace: tuple = ()


@dataclass(frozen=True)
class _Context:
    external: Mapping[str, Storage]
    calls: Mapping[int, str]
    rebound: frozenset[str]

    def value(self, expression: ast.AST, bindings: Mapping[str, Storage]) -> Storage:
        return _value(expression, _View(bindings, self.external, self.calls, {}))


def argument_ownership(
    callable_node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    parameters: set[str],
    external: dict[str, Storage],
    copies: dict[int, str],
    receiver: str | None = None,
) -> Ownership:
    """The storage of each name at each evaluated node of the callable."""
    context = _Context(external, copies, _nested_nonlocal_names(callable_node))
    flow = _visit_body(callable_node, _initial_bindings(callable_node, parameters, receiver, context), context)
    return Ownership(_observations(flow.trace), external, copies)


def _initial_bindings(callable_node, parameters: set[str], receiver: str | None, context: _Context) -> dict[str, Storage]:
    initial = {}
    for name in parameters:
        origin = frozenset({Origin(id(callable_node), name)})
        initial[name] = _rebound(name, Storage(origin, origin), context)
    arguments = getattr(callable_node, "args", ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]))
    for argument, kind in ((arguments.vararg, "tuple"), (arguments.kwarg, "dict")):
        if argument is not None:
            storage = Storage(reachable=frozenset({Origin(id(callable_node), argument.arg)}), kinds=frozenset({kind}))
            initial[argument.arg] = _rebound(argument.arg, storage, context)
    if receiver:
        # The instance rules report a change through the receiver itself. A local alias of it is not followed.
        initial[receiver] = Storage(opaque=True)
    return initial


def _visit_body(callable_node, bindings: dict[str, Storage], context: _Context) -> _Flow:
    if isinstance(callable_node, ast.Lambda):
        return _visit(callable_node.body, bindings, context)
    if isinstance(callable_node, ast.GeneratorExp):
        return _visit_comprehension(callable_node, bindings, context)
    return _block(callable_node.body, bindings, context)


def _nested_nonlocal_names(callable_node: ast.AST) -> frozenset[str]:
    nested = [node for node in ast.walk(callable_node) if node is not callable_node]
    return frozenset(name for node in nested if isinstance(node, ast.Nonlocal) for name in node.names)


def _rebound(name: str, storage: Storage, context: _Context) -> Storage:
    # A nested function can rebind the name at any call, so the analysis cannot follow its value.
    return Storage(opaque=True).join(storage) if name in context.rebound else storage


def _observations(trace) -> dict[int, dict[str, Storage]]:
    observed: dict[int, dict[str, Storage]] = {}
    pending = [trace]
    while pending:
        item = pending.pop()
        if isinstance(item, _Seen):
            observed[item.node] = dict(item.bindings)
        else:
            pending.extend(reversed(item))
    return observed


def _then(*traces) -> tuple:
    return tuple(trace for trace in traces if trace != ())


def _visit(node: ast.AST, bindings: dict[str, Storage], context: _Context) -> _Flow:
    seen = _Seen(id(node), bindings)
    handler = _STATEMENT_HANDLERS.get(type(node), _visit_children)
    flow = handler(node, bindings, context)
    return _Flow(flow.bindings, _then(seen, flow.trace))


def _block(statements: Sequence[ast.AST], bindings: dict[str, Storage], context: _Context) -> _Flow:
    traces = []
    for statement in live_statements(statements):
        flow = _visit(statement, bindings, context)
        bindings = flow.bindings
        traces.append(flow.trace)
    return _Flow(bindings, _then(*traces))


def _sequence(nodes: Sequence[ast.AST | None], bindings: dict[str, Storage], context: _Context) -> _Flow:
    traces = []
    for node in nodes:
        if node is not None:
            flow = _visit(node, bindings, context)
            bindings = flow.bindings
            traces.append(flow.trace)
    return _Flow(bindings, _then(*traces))


def _visit_children(node: ast.AST, bindings: dict[str, Storage], context: _Context) -> _Flow:
    return _sequence(evaluated_children(node), bindings, context)


def _visit_definition(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, bindings, context) -> _Flow:
    # Python evaluates decorators, defaults and bases where it defines the callable. A class body runs there too.
    if isinstance(node, ast.ClassDef):
        flow = _sequence([*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)], bindings, context)
        body = _block(node.body, flow.bindings, context)
        flow = _Flow(flow.bindings, _then(flow.trace, body.trace))
    else:
        flow = _sequence([*node.decorator_list, *node.args.defaults, *node.args.kw_defaults], bindings, context)
    # A decorator can give any value.
    value = Storage(opaque=True) if node.decorator_list else Storage(kinds=frozenset({type(node).__name__}))
    return _Flow(_bound(flow.bindings, node.name, value, context), flow.trace)


def _visit_lambda(node: ast.Lambda, bindings, context) -> _Flow:
    return _sequence([*node.args.defaults, *node.args.kw_defaults], bindings, context)


def _visit_if(node: ast.If | ast.IfExp, bindings, context) -> _Flow:
    test = _visit(node.test, bindings, context)
    truth = constant_truth(node.test)
    body = node.body if isinstance(node.body, list) else [node.body]
    orelse = node.orelse if isinstance(node.orelse, list) else [node.orelse]
    if truth is not None:
        chosen = _block(body if truth else orelse, test.bindings, context)
        return _Flow(chosen.bindings, _then(test.trace, chosen.trace))
    left = _block(body, test.bindings, context)
    right = _block(orelse, test.bindings, context)
    return _Flow(_join_bindings(left.bindings, right.bindings, context), _then(test.trace, left.trace, right.trace))


def _visit_boolean(node: ast.BoolOp, bindings, context) -> _Flow:
    # Each operand after the first runs only on some paths.
    exits = []
    traces = []
    for value in evaluated_children(node):
        flow = _visit(value, bindings, context)
        bindings = flow.bindings
        exits.append(bindings)
        traces.append(flow.trace)
    return _Flow(_join_all(exits, context), _then(*traces))


def _visit_loop(node: ast.For | ast.AsyncFor | ast.While, bindings, context) -> _Flow:
    truth = constant_truth(node.test) if isinstance(node, ast.While) else None
    if truth is False:
        test = _visit(node.test, bindings, context)
        orelse = _block(node.orelse, test.bindings, context)
        return _Flow(orelse.bindings, _then(test.trace, orelse.trace))
    head = _visit(node.iter, bindings, context) if not isinstance(node, ast.While) else _Flow(bindings)
    current = head.bindings
    while True:
        entered = _loop_entry(node, current, context)
        body = _block(node.body, entered.bindings, context)
        updated = _join_bindings(current, body.bindings, context)
        if updated == current:
            break
        current = updated
    if truth:
        # A literal-true while loop leaves only through a jump, so its else clause never runs.
        return _Flow(current, _then(head.trace, entered.trace, body.trace))
    orelse = _block(node.orelse, current, context)
    return _Flow(orelse.bindings, _then(head.trace, entered.trace, body.trace, orelse.trace))


def _loop_entry(node: ast.For | ast.AsyncFor | ast.While, bindings, context) -> _Flow:
    if isinstance(node, ast.While):
        return _visit(node.test, bindings, context)
    element = Storage(opaque=True) if isinstance(node, ast.AsyncFor) else _elements(context.value(node.iter, bindings))
    target = _visit(node.target, bindings, context)
    return _Flow(_bind(node.target, element, target.bindings, context), target.trace)


def _visit_try(node: ast.Try, bindings, context) -> _Flow:
    # A handler can start after any statement of the body, so its entry joins every state in the body.
    states = [bindings]
    traces = []
    for statement in live_statements(node.body):
        flow = _visit(statement, states[-1], context)
        states.append(flow.bindings)
        traces.append(flow.trace)
    raised = _join_all(states, context)
    normal = _block(node.orelse, states[-1], context)
    exits = [normal.bindings, raised]
    traces.append(normal.trace)
    for handler in node.handlers:
        flow = _visit_handler(handler, raised, context)
        exits.append(flow.bindings)
        traces.append(flow.trace)
    final = _block(node.finalbody, _join_all(exits, context), context)
    return _Flow(final.bindings, _then(*traces, final.trace))


def _visit_handler(handler: ast.ExceptHandler, bindings, context) -> _Flow:
    flow = _sequence([handler.type], bindings, context)
    entered = _bound(flow.bindings, handler.name, Storage(opaque=True), context) if handler.name else flow.bindings
    body = _block(handler.body, entered, context)
    return _Flow(body.bindings, _then(flow.trace, body.trace))


def _visit_with(node: ast.With | ast.AsyncWith, bindings, context) -> _Flow:
    # A context manager gives a value that the analysis does not follow.
    traces = []
    for item in node.items:
        flow = _sequence([item.context_expr, item.optional_vars], bindings, context)
        bindings = _bind(item.optional_vars, Storage(opaque=True), flow.bindings, context) if item.optional_vars else flow.bindings
        traces.append(flow.trace)
    body = _block(node.body, bindings, context)
    return _Flow(body.bindings, _then(*traces, body.trace))


def _visit_match(node: ast.Match, bindings, context) -> _Flow:
    subject = _visit(node.subject, bindings, context)
    captured = _elements(context.value(node.subject, bindings))
    exits = [subject.bindings]
    traces = [subject.trace]
    for case in node.cases:
        entered = subject.bindings
        for name in _pattern_names(case.pattern):
            entered = _bound(entered, name, captured, context)
        flow = _sequence([case.guard], entered, context)
        body = _block(case.body, flow.bindings, context)
        exits.append(body.bindings)
        traces.extend([flow.trace, body.trace])
    return _Flow(_join_all(exits, context), _then(*traces))


def _pattern_names(pattern: ast.AST) -> list[str]:
    names = []
    for node in ast.walk(pattern):
        name = getattr(node, "name", None) if isinstance(node, (ast.MatchAs, ast.MatchStar)) else None
        rest = node.rest if isinstance(node, ast.MatchMapping) else None
        names.extend(item for item in (name, rest) if item)
    return names


def _visit_assignment(node: ast.Assign | ast.AnnAssign, bindings, context) -> _Flow:
    value = _sequence([node.value], bindings, context)
    stored = context.value(node.value, value.bindings) if node.value is not None else None
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    bindings = value.bindings
    traces = [value.trace]
    for target in targets:
        flow = _visit(target, value.bindings, context)
        traces.append(flow.trace)
        if stored is not None:
            bindings = _bind(target, stored, bindings, context)
    return _Flow(bindings, _then(*traces))


def _visit_walrus(node: ast.NamedExpr, bindings, context) -> _Flow:
    value = _visit(node.value, bindings, context)
    stored = context.value(node.value, value.bindings)
    return _Flow(_bind(node.target, stored, value.bindings, context), value.trace)


def _visit_augmented(node: ast.AugAssign, bindings, context) -> _Flow:
    flow = _sequence([node.value, node.target], bindings, context)
    added = _fresh_from([context.value(node.value, flow.bindings)])
    if isinstance(node.target, ast.Name):
        current = flow.bindings.get(node.target.id, context.external.get(node.target.id, Storage(opaque=True)))
        return _Flow(_bound(flow.bindings, node.target.id, current.join(added), context), flow.trace)
    return _Flow(_linked(flow.bindings, _root(node.target), added), flow.trace)


def _visit_delete(node: ast.Delete, bindings, context) -> _Flow:
    flow = _sequence(node.targets, bindings, context)
    removed = {target.id for target in node.targets if isinstance(target, ast.Name)}
    return _Flow({name: value for name, value in flow.bindings.items() if name not in removed}, flow.trace)


def _visit_import(node: ast.Import | ast.ImportFrom, bindings, context) -> _Flow:
    for alias in node.names:
        bindings = _bound(bindings, (alias.asname or alias.name).split(".")[0], Storage(opaque=True), context)
    return _Flow(bindings)


def _visit_call(node: ast.Call, bindings, context) -> _Flow:
    flow = _visit_children(node, bindings, context)
    if context.calls.get(id(node), "") in PURE_CALL_KINDS:
        return flow
    # A call can store each argument in each other argument, and in the receiver of a method call.
    parts = [*([node.func.value] if isinstance(node.func, ast.Attribute) else []), *_call_arguments(node)]
    parts = [part.value if isinstance(part, ast.Starred) else part for part in parts]
    bindings = flow.bindings
    for index, part in enumerate(parts):
        others = [context.value(other, flow.bindings) for position, other in enumerate(parts) if position != index]
        bindings = _linked(bindings, _root(part), _fresh_from(others))
    return _Flow(bindings, flow.trace)


def _visit_comprehension(node: ast.expr, bindings, context) -> _Flow:
    # The targets of a comprehension belong to its own scope. A walrus target belongs to the enclosing callable.
    inner = bindings
    traces = []
    for generator in node.generators:
        iterated = _visit(generator.iter, inner, context)
        element = Storage(opaque=True) if generator.is_async else _elements(context.value(generator.iter, iterated.bindings))
        target = _visit(generator.target, iterated.bindings, context)
        inner = _bind(generator.target, element, target.bindings, context)
        tests = _sequence(generator.ifs, inner, context)
        inner = tests.bindings
        traces.extend([_Seen(id(generator), iterated.bindings), iterated.trace, target.trace, tests.trace])
        if any(constant_truth(test) is False for test in generator.ifs):
            break
    else:
        results = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        traces.append(_sequence(results, inner, context).trace)
    walrus = {target.target.id for target in ast.walk(node) if isinstance(target, ast.NamedExpr)}
    for name in walrus:
        bindings = _bound(bindings, name, Storage(opaque=True), context)
    return _Flow(bindings, _then(*traces))


_STATEMENT_HANDLERS = MappingProxyType({
    ast.FunctionDef: _visit_definition,
    ast.AsyncFunctionDef: _visit_definition,
    ast.ClassDef: _visit_definition,
    ast.Lambda: _visit_lambda,
    ast.If: _visit_if,
    ast.IfExp: _visit_if,
    ast.BoolOp: _visit_boolean,
    ast.For: _visit_loop,
    ast.AsyncFor: _visit_loop,
    ast.While: _visit_loop,
    ast.Try: _visit_try,
    ast.TryStar: _visit_try,
    ast.With: _visit_with,
    ast.AsyncWith: _visit_with,
    ast.Match: _visit_match,
    ast.Assign: _visit_assignment,
    ast.AnnAssign: _visit_assignment,
    ast.NamedExpr: _visit_walrus,
    ast.AugAssign: _visit_augmented,
    ast.Delete: _visit_delete,
    ast.Import: _visit_import,
    ast.ImportFrom: _visit_import,
    ast.Call: _visit_call,
    ast.ListComp: _visit_comprehension,
    ast.SetComp: _visit_comprehension,
    ast.DictComp: _visit_comprehension,
    ast.GeneratorExp: _visit_comprehension,
})


def _bind(target: ast.AST, value: Storage, bindings: dict[str, Storage], context: _Context) -> dict[str, Storage]:
    if isinstance(target, ast.Name):
        return _bound(bindings, target.id, value, context)
    if isinstance(target, ast.Starred):
        rest = Storage(reachable=value.everything, kinds=frozenset({"list"}), deep=value.reaches_unknown)
        return _bind(target.value, rest, bindings, context)
    if isinstance(target, (ast.Tuple, ast.List)):
        for child in target.elts:
            bindings = _bind(child, value if isinstance(child, ast.Starred) else _elements(value), bindings, context)
        return bindings
    # A store into an element or an attribute makes the value reachable from the root of the target.
    return _linked(bindings, _root(target), _fresh_from([value]))


def _bound(bindings: dict[str, Storage], name: str, value: Storage, context: _Context) -> dict[str, Storage]:
    return {**bindings, name: _rebound(name, value, context)}


def _linked(bindings: dict[str, Storage], root: str, added: Storage) -> dict[str, Storage]:
    current = bindings.get(root)
    if current is None or not (added.everything or added.reaches_unknown):
        return bindings
    linked = replace(current, reachable=current.reachable | added.everything, deep=current.deep or added.reaches_unknown)
    return {**bindings, root: linked}


def _root(expression: ast.AST) -> str:
    while isinstance(expression, (ast.Attribute, ast.Subscript, ast.Starred)):
        expression = expression.value
    return expression.id if isinstance(expression, ast.Name) else ""


def _join_all(states: Sequence[dict[str, Storage]], context: _Context) -> dict[str, Storage]:
    joined = states[0]
    for state in states[1:]:
        joined = _join_bindings(joined, state, context)
    return joined


def _join_bindings(left: dict[str, Storage], right: dict[str, Storage], context: _Context) -> dict[str, Storage]:
    # A name that one path does not bind keeps the value from the other path, or its outer value.
    joined = {}
    for name in left.keys() | right.keys():
        missing = context.external.get(name)
        values = [value for value in (left.get(name, missing), right.get(name, missing)) if value is not None]
        joined[name] = _joined(values)
    return joined
