from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from .reachability import constant_truth, evaluated_children, live_statements

__all__ = [
    "PURE_CALL_KINDS",
    "CallableBody",
    "Origin",
    "Ownership",
    "OwnershipProgram",
    "Storage",
    "argument_ownership",
    "augmented_mutation",
    "project_storage",
    "storage_value",
]


@dataclass(frozen=True)
class Origin:
    scope: int
    name: str
    path: tuple[tuple[str, str | int], ...] = ()

    def selected(self, key: tuple[str, str | int]) -> Origin:
        if any(part[0] == "uncertain" for part in self.path):
            return self
        path = self.path
        path = (*path, key) if len(path) < 8 else (*path[:7], ("uncertain", "*"))
        return Origin(self.scope, self.name, path)


def _origin_paths(origins: frozenset[Origin]) -> frozenset[Origin]:
    groups: dict[tuple[int, str], list[Origin]] = {}
    for origin in origins:
        groups.setdefault((origin.scope, origin.name), []).append(origin)
    return frozenset(origin for group in groups.values() for origin in _bounded_paths(group))


def _bounded_paths(origins: Sequence[Origin]) -> Sequence[Origin]:
    roots = [origin for origin in origins if not origin.path]
    members = _distinct_paths(origins)
    if len(members) <= _MAX_TRACKED_PATHS:
        return [*roots, *members]
    prefix = _common_path([origin.path for origin in members])
    root = origins[0]
    return [*roots, Origin(root.scope, root.name, (*prefix, ("uncertain", "*")))]


def _distinct_paths(origins: Sequence[Origin]) -> Sequence[Origin]:
    members = [origin for origin in origins if origin.path]
    uncertain = [origin for origin in members if origin.path[-1][0] == "uncertain"]
    known = [origin for origin in members if not any(_covers(path, origin) for path in uncertain)]
    return [*known, *uncertain]


def _covers(uncertain: Origin, origin: Origin) -> bool:
    prefix = uncertain.path[:-1]
    return len(origin.path) >= len(uncertain.path) and origin.path[:len(prefix)] == prefix


def _common_path(paths: Sequence[tuple[tuple[str, str | int], ...]]) -> tuple[tuple[str, str | int], ...]:
    prefix = []
    for position in range(min(len(path) for path in paths)):
        parts = {path[position] for path in paths}
        if len(parts) != 1:
            break
        prefix.append(paths[0][position])
    return tuple(prefix)


@dataclass(frozen=True)
class _Cell:
    activation: tuple[int, ...]
    name: str


@dataclass(frozen=True)
class _Closure:
    node: ast.AST
    bindings: tuple[tuple[str, _Cell], ...]


@dataclass(frozen=True)
class Storage:
    outer: frozenset[Origin] = frozenset()
    reachable: frozenset[Origin] = frozenset()
    kinds: frozenset[str] = frozenset({"unknown"})
    opaque: bool = False
    deep: bool = False
    slots: tuple[tuple[tuple[str, str | int], Storage], ...] = ()
    indexed: bool = False
    references: frozenset[tuple[int, ...]] = frozenset()
    functions: frozenset[_Closure] = frozenset()

    def __post_init__(self) -> None:
        outer = _origin_paths(self.outer)
        reachable = _origin_paths(self.reachable)
        object.__setattr__(self, "opaque", self.opaque or outer != self.outer)
        object.__setattr__(self, "deep", self.deep or reachable != self.reachable)
        object.__setattr__(self, "outer", outer)
        object.__setattr__(self, "reachable", reachable)

    @property
    def everything(self) -> frozenset[Origin]:
        return self.outer | self.reachable

    @property
    def reaches_unknown(self) -> bool:
        return self.opaque or self.deep

    def join(self, other: Storage) -> Storage:
        if self == other:
            return self
        right = dict(other.slots)
        indexed = self.indexed and other.indexed
        return Storage(
            self.outer | other.outer,
            self.reachable | other.reachable,
            self.kinds | other.kinds,
            self.opaque or other.opaque,
            self.deep or other.deep,
            tuple((key, value.join(right[key])) for key, value in self.slots if key in right) if indexed else (),
            indexed,
            self.references | other.references,
            self.functions | other.functions,
        )


@dataclass(frozen=True)
class _State(Mapping[str, Storage]):
    names: Mapping[str, _Cell] = field(default_factory=dict)
    cells: Mapping[_Cell, Storage] = field(default_factory=dict)
    heap: Mapping[tuple[int, ...], Storage] = field(default_factory=dict)
    evaluated: Mapping[int, Storage] = field(default_factory=dict)
    result: Storage = field(default_factory=lambda: Storage(kinds=frozenset()))
    calls: Mapping[tuple, tuple[Storage, Mapping, Mapping]] = field(default_factory=dict, compare=False)

    def __getitem__(self, name: str) -> Storage:
        return self.cells[self.names[name]]

    def __iter__(self) -> Iterator[str]:
        return iter(self.names)

    def __len__(self) -> int:
        return len(self.names)


@dataclass(frozen=True)
class CallableBody:
    node: ast.AST
    local: frozenset[str]
    external: Mapping[str, Storage]
    calls: Mapping[int, str]
    receiver: str | None = None
    cold: bool = False
    transformed: bool = False


@dataclass(frozen=True)
class OwnershipProgram:
    bodies: Mapping[int, CallableBody] = field(default_factory=dict)
    targets: Mapping[int, ast.AST] = field(default_factory=dict)


_COPY_KINDS = frozenset({"list", "dict", "set", "tuple", "frozenset"})
PURE_CALL_KINDS = _COPY_KINDS | frozenset({"fresh", "element", "record"})
_ELEMENT_METHODS = MappingProxyType({
    "list": frozenset({"pop", "index", "count"}),
    "dict": frozenset({"get", "pop", "setdefault", "items", "keys", "values", "popitem"}),
    "set": frozenset({"pop"}),
})
_COMPREHENSION_KINDS = MappingProxyType({ast.ListComp: "list", ast.SetComp: "set", ast.DictComp: "dict", ast.GeneratorExp: "generator"})
_MAX_TRACKED_SLOTS = 16
_MAX_TRACKED_PATHS = 16
_MAX_CALL_DEPTH = 4


@dataclass(frozen=True)
class Ownership:
    observations: dict[int, _State]
    external: dict[str, Storage]
    copies: dict[int, str]

    def value(self, expression: ast.AST, node: ast.AST) -> Storage:
        return storage_value(expression, self.observations.get(id(node), _State()), self.external, self.copies)


@dataclass(frozen=True)
class _View:
    bindings: _State
    external: Mapping[str, Storage]
    calls: Mapping[int, str]

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
) -> Storage:
    """The storage that an expression gives, for the name bindings that hold where Python evaluates it."""
    state = bindings if isinstance(bindings, _State) else _state_from_names(bindings)
    return _value(expression, _View(state, external, copies))


def _state_from_names(bindings: Mapping[str, Storage]) -> _State:
    names = {name: _Cell((), name) for name in bindings}
    return _State(names, {names[name]: value for name, value in bindings.items()})


def _value(expression: ast.AST, view: _View) -> Storage:
    cached = view.bindings.evaluated.get(id(expression))
    if cached is not None:
        return _resolved(cached, view.bindings.heap)
    handler = _VALUE_HANDLERS.get(type(expression))
    if handler is not None:
        return _resolved(handler(expression, view), view.bindings.heap)
    if isinstance(expression, tuple(_COMPREHENSION_KINDS)):
        return _comprehension_storage(expression, view)
    return Storage(opaque=True)


def _resolved(storage: Storage, heap: Mapping[tuple[int, ...], Storage], seen: frozenset[tuple[int, ...]] = frozenset()) -> Storage:
    references = storage.references - seen
    if references:
        values = [heap.get(reference, Storage(opaque=True)) for reference in references]
        storage = replace(_joined(values), references=storage.references)
        seen |= references
    children = tuple((key, _resolved(value, heap, seen)) for key, value in storage.slots)
    if not children:
        return storage
    reachable = frozenset(origin for _, child in children for origin in child.everything)
    deep = any(child.reaches_unknown for _, child in children)
    return replace(storage, slots=children, reachable=storage.reachable | reachable, deep=storage.deep or deep)


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
    return _elements(_value(expression.value, view))


def _operator_storage(expression: ast.BinOp | ast.UnaryOp, view: _View) -> Storage:
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        return Storage(kinds=frozenset({"bool"}))
    operands = [expression.operand] if isinstance(expression, ast.UnaryOp) else [expression.left, expression.right]
    values = [_value(operand, view) for operand in operands]
    return replace(_fresh_from(values), opaque=any(value.opaque for value in values))


def _lambda_storage(_expression: ast.Lambda, _view: _View) -> Storage:
    closure = _Closure(_expression, tuple(_view.bindings.names.items()))
    return Storage(kinds=frozenset({"function"}), functions=frozenset({closure}))


def _selected_storage(expression: ast.Attribute | ast.Subscript, view: _View) -> Storage:
    base = _value(expression.value, view)
    if isinstance(expression, ast.Subscript) and isinstance(expression.slice, ast.Slice):
        return Storage(reachable=base.everything, kinds=base.kinds, opaque=base.opaque, deep=base.deep)
    key = _slot_key(expression)
    return project_storage(base, (key or ("element", "*"),))


def project_storage(storage: Storage, path: tuple[tuple[str, str | int], ...]) -> Storage:
    for key in path:
        storage = _project_member(storage, key)
    return storage


def _project_member(storage: Storage, key: tuple[str, str | int]) -> Storage:
    if key[0] == "uncertain":
        return Storage(opaque=True)
    selected = dict(storage.slots).get(key)
    if selected is not None:
        return selected
    if key[0] == "element" and storage.indexed:
        return _joined(child for _, child in storage.slots)
    if storage.indexed or storage.opaque:
        return Storage(opaque=True)
    origins = frozenset(origin.selected(key) for origin in storage.everything)
    return Storage(origins, origins, opaque=storage.reaches_unknown, deep=storage.reaches_unknown)


def _slot_key(expression: ast.Attribute | ast.Subscript) -> tuple[str, str | int] | None:
    if isinstance(expression, ast.Attribute):
        return ("attribute", expression.attr)
    if isinstance(expression.slice, ast.Constant) and type(expression.slice.value) in {str, int}:
        return ("item", expression.slice.value)
    return None


def _call_storage(expression: ast.Call, view: _View) -> Storage:
    kind = view.calls.get(id(expression), "")
    if kind:
        return _known_call_storage(expression, kind, view)
    if isinstance(expression.func, ast.Attribute):
        return _method_storage(expression, view)
    return Storage(opaque=True)


def _known_call_storage(expression: ast.Call, kind: str, view: _View) -> Storage:
    arguments = [_value(argument, view) for argument in _call_arguments(expression)]
    if kind in _COPY_KINDS:
        source = arguments[0] if expression.args else Storage(kinds=frozenset())
        return _copied(source, kind)
    if kind == "element":
        return _elements(_joined(arguments))
    if kind == "record":
        return replace(_fresh_from(arguments), kinds=frozenset({"record"}), indexed=not arguments)
    return _fresh_from(arguments)


def _copied(source: Storage, kind: str) -> Storage:
    indexed = source.indexed and kind in {"list", "tuple", "dict"}
    return Storage(
        reachable=frozenset() if indexed else source.everything,
        kinds=frozenset({kind}), deep=source.reaches_unknown,
        slots=source.slots if indexed else (), indexed=indexed,
    )


def _method_storage(call: ast.Call, view: _View) -> Storage:
    function = call.func
    receiver = _value(function.value, view)
    if receiver.opaque or len(receiver.kinds) != 1:
        return Storage(opaque=True)
    kind = next(iter(receiver.kinds))
    return _established_method_value(call, receiver, kind, view)


def _established_method_value(call: ast.Call, receiver: Storage, kind: str, view: _View) -> Storage:
    function = call.func
    if function.attr == "copy" and kind in {"list", "dict", "set"}:
        return _copied(receiver, kind)
    if kind == "dict" and function.attr in {"get", "pop", "setdefault"}:
        return _dictionary_value(call, receiver, view)
    if function.attr in _ELEMENT_METHODS.get(kind, frozenset()):
        return _elements(receiver)
    return Storage(kinds=frozenset()) if kind == "str" else Storage(opaque=True)


def _dictionary_value(call: ast.Call, receiver: Storage, view: _View) -> Storage:
    key = call.args[0] if call.args else None
    if not isinstance(key, ast.Constant) or type(key.value) not in {str, int}:
        return _elements(receiver)
    selected = dict(receiver.slots).get(("item", key.value))
    if selected is not None:
        return selected
    if receiver.indexed and call.func.attr in {"get", "setdefault"}:
        return _value(call.args[1], view) if len(call.args) > 1 else Storage(kinds=frozenset({"NoneType"}))
    return project_storage(receiver, (("item", key.value),))


def _container_storage(expression: ast.List | ast.Tuple | ast.Set | ast.Dict, view: _View) -> Storage:
    elements = [_value(child, view) for child in ast.iter_child_nodes(expression) if isinstance(child, ast.expr)]
    container = _fresh_from(elements)
    kind = frozenset({type(expression).__name__.lower()})
    slots = _literal_slots(expression, view)
    if slots is None:
        return replace(container, kinds=kind)
    if len(slots) > _MAX_TRACKED_SLOTS:
        return Storage(kinds=kind, opaque=True)
    return replace(container, kinds=kind, slots=slots, indexed=True)


def _literal_slots(expression: ast.List | ast.Tuple | ast.Set | ast.Dict, view: _View):
    if isinstance(expression, (ast.List, ast.Tuple)):
        return tuple((("item", index), _value(value, view)) for index, value in enumerate(expression.elts))
    if isinstance(expression, ast.Dict) and all(isinstance(key, ast.Constant) and type(key.value) in {str, int} for key in expression.keys):
        return tuple((("item", key.value), _value(value, view)) for key, value in zip(expression.keys, expression.values))
    return None


def _comprehension_storage(expression: ast.expr, view: _View) -> Storage:
    targets = {name.id for generator in expression.generators for name in ast.walk(generator.target) if isinstance(name, ast.Name)}
    sources = [_resolved(view.name(name), view.bindings.heap) for name in sorted(_comprehension_reads(expression) - targets)]
    container = _fresh_from(sources)
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
    return project_storage(storage, (("element", "*"),))


def _fresh_from(sources) -> Storage:
    sources = list(sources)
    reachable = frozenset(origin for source in sources for origin in source.everything)
    return Storage(reachable=reachable, deep=any(source.reaches_unknown for source in sources))


def _joined(sources) -> Storage:
    iterator = iter(sources)
    joined = next(iterator, Storage(kinds=frozenset()))
    for source in iterator:
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
    bindings: _State


@dataclass(frozen=True)
class _Flow:

    bindings: _State
    trace: tuple = ()


@dataclass(frozen=True)
class _Context:
    body: CallableBody
    program: OwnershipProgram
    activation: tuple[int, ...]
    active: frozenset[int]

    @property
    def external(self) -> Mapping[str, Storage]:
        return self.body.external

    @property
    def calls(self) -> Mapping[int, str]:
        return self.body.calls

    @property
    def receiver(self) -> str | None:
        return self.body.receiver

    @property
    def receiver_origin(self) -> Origin | None:
        return Origin(id(self.body.node), self.receiver) if self.receiver else None

    def value(self, expression: ast.AST, bindings: _State) -> Storage:
        return _value(expression, _View(bindings, self.external, self.calls))


def argument_ownership(
    callable_node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    parameters: set[str],
    external: dict[str, Storage],
    copies: dict[int, str],
    receiver: str | None = None,
    program: OwnershipProgram | None = None,
) -> Ownership:
    program = program or OwnershipProgram()
    body = program.bodies.get(id(callable_node), CallableBody(callable_node, frozenset(parameters), external, copies, receiver))
    context = _Context(body, program, (id(callable_node),), frozenset({id(callable_node)}))
    flow = _visit_body(callable_node, _initial_bindings(callable_node, parameters, receiver, context), context)
    return Ownership(_observations(flow.trace), external, copies)


def _initial_bindings(callable_node, parameters: set[str], receiver: str | None, context: _Context) -> _State:
    initial = _frame_state(_State(), (), context)
    arguments = getattr(callable_node, "args", ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]))
    for argument in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]:
        if argument.arg in parameters:
            origin = frozenset({Origin(id(callable_node), argument.arg)})
            initial = _allocated(argument, Storage(origin, origin), initial, context)
            initial = _bound(initial, argument.arg, initial.evaluated[id(argument)], context)
    for argument, kind in ((arguments.vararg, "tuple"), (arguments.kwarg, "dict")):
        if argument is not None:
            storage = Storage(reachable=frozenset({Origin(id(callable_node), argument.arg)}), kinds=frozenset({kind}))
            initial = _bound(initial, argument.arg, storage, context)
    if receiver:
        initial = _bound(initial, receiver, Storage(opaque=True), context)
    return initial


def _frame_state(state: _State, captures: tuple[tuple[str, _Cell], ...], context: _Context) -> _State:
    names = dict(captures)
    cells = dict(state.cells)
    for name, storage in context.external.items():
        origin = next(iter(storage.outer), Origin(id(context.body.node), name))
        cell = names.setdefault(name, _Cell((origin.scope,), name))
        cells.setdefault(cell, storage)
    for name in context.body.local:
        cell = _Cell(context.activation, name)
        names[name] = cell
        cells[cell] = Storage(opaque=True)
    return replace(state, names=names, cells=cells, evaluated={}, result=Storage(kinds=frozenset()))


def _visit_body(callable_node, bindings: _State, context: _Context) -> _Flow:
    if isinstance(callable_node, ast.Lambda):
        flow = _visit(callable_node.body, bindings, context)
        return _Flow(replace(flow.bindings, result=context.value(callable_node.body, flow.bindings)), flow.trace)
    if isinstance(callable_node, ast.GeneratorExp):
        return _visit_comprehension(callable_node, bindings, context)
    return _block(callable_node.body, bindings, context)


def _observations(trace) -> dict[int, _State]:
    observed: dict[int, _State] = {}
    pending = [trace]
    while pending:
        item = pending.pop()
        if isinstance(item, _Seen):
            observed[item.node] = item.bindings
        else:
            pending.extend(reversed(item))
    return observed


def _then(*traces) -> tuple:
    return tuple(trace for trace in traces if trace != ())


def _visit(node: ast.AST, bindings: _State, context: _Context) -> _Flow:
    if id(node) in bindings.evaluated:
        bindings = replace(bindings, evaluated={key: value for key, value in bindings.evaluated.items() if key != id(node)})
    seen = _Seen(id(node), bindings)
    handler = _STATEMENT_HANDLERS.get(type(node), _visit_children)
    flow = handler(node, bindings, context)
    return _Flow(flow.bindings, _then(seen, flow.trace))


def _block(statements: Sequence[ast.AST], bindings: _State, context: _Context) -> _Flow:
    traces = []
    for statement in live_statements(statements):
        flow = _visit(statement, bindings, context)
        bindings = flow.bindings
        traces.append(flow.trace)
    return _Flow(bindings, _then(*traces))


def _sequence(nodes: Sequence[ast.AST | None], bindings: _State, context: _Context) -> _Flow:
    traces = []
    for node in nodes:
        if node is not None:
            flow = _visit(node, bindings, context)
            bindings = flow.bindings
            traces.append(flow.trace)
    return _Flow(bindings, _then(*traces))


def _visit_children(node: ast.AST, bindings: _State, context: _Context) -> _Flow:
    return _sequence(evaluated_children(node), bindings, context)


def _visit_definition(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, bindings, context) -> _Flow:
    # Python evaluates decorators, defaults and bases where it defines the callable. A class body runs there too.
    if isinstance(node, ast.ClassDef):
        flow = _sequence([*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)], bindings, context)
        body = _block(node.body, flow.bindings, context)
        flow = _Flow(flow.bindings, _then(flow.trace, body.trace))
    else:
        flow = _sequence([*node.decorator_list, *node.args.defaults, *node.args.kw_defaults], bindings, context)
    closure = _Closure(node, tuple(flow.bindings.names.items()))
    value = Storage(kinds=frozenset({type(node).__name__}), functions=frozenset({closure}))
    if node.decorator_list or isinstance(node, ast.ClassDef):
        value = Storage(opaque=bool(node.decorator_list), kinds=frozenset({type(node).__name__}))
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
    stored = _assigned_value(node.value, value.bindings, context) if node.value is not None else None
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
    stored = _assigned_value(node.value, value.bindings, context)
    return _Flow(_bind(node.target, stored, value.bindings, context), value.trace)


def _assigned_value(expression: ast.expr, bindings: _State, context: _Context) -> Storage:
    if isinstance(expression, ast.Name) and expression.id == context.receiver and len(context.activation) == 1:
        origin = frozenset({Origin(id(context.body.node), expression.id)})
        return Storage(origin, origin)
    return context.value(expression, bindings)


def _visit_augmented(node: ast.AugAssign, bindings, context) -> _Flow:
    flow = _sequence([node.value, node.target], bindings, context)
    added = _fresh_from([context.value(node.value, flow.bindings)])
    if isinstance(node.target, ast.Name):
        current = context.value(node.target, flow.bindings)
        updated = current.join(added)
        return _Flow(_update_aliases(flow.bindings, current, updated), flow.trace)
    return _Flow(_linked(flow.bindings, _root(node.target), added), flow.trace)


def _visit_delete(node: ast.Delete, bindings, context) -> _Flow:
    flow = _sequence(node.targets, bindings, context)
    removed = {target.id for target in node.targets if isinstance(target, ast.Name)}
    names = {name: cell for name, cell in flow.bindings.names.items() if name not in removed}
    return _Flow(replace(flow.bindings, names=names), flow.trace)


def _visit_return(node: ast.Return, bindings, context) -> _Flow:
    flow = _sequence([node.value], bindings, context)
    value = context.value(node.value or ast.Constant(None), flow.bindings)
    result = _joined((flow.bindings.result, value)) if flow.bindings.result.kinds else value
    return _Flow(replace(flow.bindings, result=result), flow.trace)


def _visit_allocation(node: ast.AST, bindings, context) -> _Flow:
    flow = _visit_children(node, bindings, context)
    return _Flow(_allocated(node, context.value(node, flow.bindings), flow.bindings, context), flow.trace)


def _allocated(node: ast.AST, value: Storage, state: _State, context: _Context) -> _State:
    reference = (*context.activation, id(node))
    stored = replace(value, references=frozenset(), slots=tuple((key, _stored(child)) for key, child in value.slots))
    if stored.indexed:
        stored = replace(stored, reachable=frozenset(), deep=False)
    heap = {**state.heap, reference: stored}
    selected = Storage(kinds=frozenset(), references=frozenset({reference}))
    return replace(state, heap=heap, evaluated={**state.evaluated, id(node): selected})


def _visit_import(node: ast.Import | ast.ImportFrom, bindings, context) -> _Flow:
    for alias in node.names:
        bindings = _bound(bindings, (alias.asname or alias.name).split(".")[0], Storage(opaque=True), context)
    return _Flow(bindings)


def _visit_call(node: ast.Call, bindings, context) -> _Flow:
    flow = _visit_children(node, bindings, context)
    flow = _Flow(flow.bindings, _then(flow.trace, _Seen(id(node), flow.bindings)))
    if context.calls.get(id(node), "") in PURE_CALL_KINDS:
        state = _allocated(node, context.value(node, flow.bindings), flow.bindings, context)
        return _Flow(state, flow.trace)
    closures = _call_closures(node, flow.bindings, context)
    if closures:
        states = [_execute(closure, node, flow.bindings, context) for closure in closures]
        state = _join_all(states, context)
        return _Flow(state, flow.trace)
    appended = _append_slot(node, flow.bindings, context)
    if appended is not None:
        return _Flow(appended, flow.trace)
    invalidated = _invalidated_slots(node, flow.bindings, context)
    if invalidated is not None:
        return _Flow(invalidated, flow.trace)
    linked = _linked_call_arguments(node, flow.bindings, context)
    state = _invalidate_passed_slots(node, linked, context)
    return _Flow(state, flow.trace)


def _call_closures(node: ast.Call, state: _State, context: _Context) -> frozenset[_Closure]:
    value = context.value(node.func, state)
    if value.functions:
        return value.functions
    target = context.program.targets.get(id(node))
    if target is None:
        return frozenset()
    body = context.program.bodies[id(target)]
    captures = tuple(
        (name, cell) for name, cell in state.names.items()
        if any(origin.scope == cell.activation[-1] for origin in body.external.get(name, Storage()).outer)
    )
    return frozenset({_Closure(target, captures)})


def _execute(closure: _Closure, call: ast.Call, state: _State, context: _Context) -> _State:
    body = context.program.bodies.get(id(closure.node))
    if body is None or body.cold or body.transformed:
        return _cached(call, Storage(opaque=True), state)
    if id(body.node) in context.active or len(context.active) >= _MAX_CALL_DEPTH:
        return _uncertain_execution(closure, call, state, context)
    values = _bound_values(body, call, state, context)
    if values is None:
        return _cached(call, Storage(opaque=True), _invalidate_passed_slots(call, state, context))
    return _memo_execution(body, closure, call, values, state, context)


def _memo_execution(body: CallableBody, closure: _Closure, call: ast.Call, values: Mapping[str, Storage], state: _State, context: _Context) -> _State:
    if closure.bindings:
        return _execute_body(body, closure, call, values, state, context)
    key = (id(body.node), tuple(sorted(values.items())), context.active)
    cached = state.calls.get(key)
    if cached is not None:
        cached_result, cell_delta, heap_delta = cached
        return _cached(call, cached_result, replace(state, cells={**state.cells, **cell_delta}, heap={**state.heap, **heap_delta}))
    result = _execute_body(body, closure, call, values, state, context)
    cell_delta = {k: v for k, v in result.cells.items() if state.cells.get(k) is not v}
    heap_delta = {k: v for k, v in result.heap.items() if state.heap.get(k) is not v}
    return replace(result, calls={**result.calls, key: (result.evaluated[id(call)], cell_delta, heap_delta)})


def _escaping_cells(storage: Storage) -> set[_Cell]:
    cells = {cell for func in storage.functions for _, cell in func.bindings}
    for _, child in storage.slots:
        cells.update(_escaping_cells(child))
    return cells


def _execute_body(body: CallableBody, closure: _Closure, call: ast.Call, values: Mapping[str, Storage], state: _State, context: _Context) -> _State:
    activation = (*context.activation, id(call), id(body.node))
    entered = _Context(body, context.program, activation, context.active | {id(body.node)})
    frame = _frame_state(state, closure.bindings, entered)
    for name, value in values.items():
        frame = _bound(frame, name, value, entered)
    output = _visit_body(body.node, frame, entered).bindings
    escaping = _escaping_cells(output.result)
    retained_cells = {
        cell: val for cell, val in output.cells.items()
        if cell in escaping or cell.activation[:len(activation)] != activation
    }
    restored = replace(output, names=state.names, cells=retained_cells, evaluated=state.evaluated, result=state.result, calls=output.calls)
    return _cached(call, output.result if output.result.kinds else Storage(kinds=frozenset({"NoneType"})), restored)


def _uncertain_execution(closure: _Closure, call: ast.Call, state: _State, context: _Context) -> _State:
    arguments = _call_arguments(call)
    if isinstance(call.func, ast.Attribute):
        arguments = [call.func.value, *arguments]
    values = [context.value(argument, state) for argument in arguments]
    captures = {cell: state.cells[cell] for _, cell in closure.bindings if cell in state.cells}
    values.extend(_resolved(value, state.heap) for value in captures.values())
    for value in values:
        state = _uncertain_storage(value, state, frozenset())
    cells = {**state.cells, **{cell: value.join(Storage(opaque=True)) for cell, value in captures.items()}}
    return _cached(call, Storage(opaque=True), replace(state, cells=cells))


def _uncertain_storage(value: Storage, state: _State, seen: frozenset[tuple[int, ...]]) -> _State:
    references = value.references - seen
    if value.references and not references:
        return state
    for _, child in value.slots:
        state = _uncertain_storage(child, state, seen | references)
    uncertain = replace(value, opaque=True, deep=True, slots=(), indexed=False)
    return _update_aliases(state, value, uncertain)


def _cached(node: ast.AST, value: Storage, state: _State) -> _State:
    return replace(state, evaluated={**state.evaluated, id(node): value})


def _bound_values(body: CallableBody, call: ast.Call, state: _State, context: _Context) -> dict[str, Storage] | None:
    if _spread_arguments(call):
        return None
    arguments = body.node.args
    positional = [*arguments.posonlyargs, *arguments.args]
    values = [context.value(value, state) for value in call.args]
    if body.receiver and isinstance(call.func, ast.Attribute):
        values.insert(0, context.value(call.func.value, state))
    bound = {argument.arg: value for argument, value in zip(positional, values)}
    bound.update((keyword.arg, context.value(keyword.value, state)) for keyword in call.keywords)
    bound = _with_defaults(arguments, positional, bound, state, context)
    return _packed_values(arguments, positional, values, bound)


def _spread_arguments(call: ast.Call) -> bool:
    return any(isinstance(value, ast.Starred) for value in call.args) or any(keyword.arg is None for keyword in call.keywords)


def _with_defaults(arguments: ast.arguments, positional, bound, state: _State, context: _Context):
    bound = dict(bound)
    for argument, value in zip(positional[-len(arguments.defaults):], arguments.defaults):
        bound.setdefault(argument.arg, _default_value(value, state, context))
    for argument, value in zip(arguments.kwonlyargs, arguments.kw_defaults):
        if value is not None:
            bound.setdefault(argument.arg, _default_value(value, state, context))
    return bound


def _default_value(node: ast.expr, state: _State, context: _Context) -> Storage:
    return context.value(node, state) if isinstance(node, ast.Constant) or id(node) in state.evaluated else Storage(opaque=True)


def _packed_values(arguments: ast.arguments, positional, values, bound) -> dict[str, Storage] | None:
    if not _complete_arguments(arguments, positional, values, bound):
        return None
    bound = dict(bound)
    if arguments.vararg is not None:
        slots = tuple((("item", index), value) for index, value in enumerate(values[len(positional):]))
        bound[arguments.vararg.arg] = Storage(kinds=frozenset({"tuple"}), slots=slots, indexed=True)
    known = {argument.arg for argument in [*positional, *arguments.kwonlyargs]}
    if arguments.kwarg is not None:
        slots = tuple((("item", name), value) for name, value in bound.items() if name not in known)
        bound[arguments.kwarg.arg] = Storage(kinds=frozenset({"dict"}), slots=slots, indexed=True)
    return bound


def _complete_arguments(arguments: ast.arguments, positional, values, bound) -> bool:
    known = {argument.arg for argument in [*positional, *arguments.kwonlyargs]}
    if not known <= bound.keys():
        return False
    if arguments.vararg is None and len(values) > len(positional):
        return False
    return arguments.kwarg is not None or bound.keys() <= known


def _linked_call_arguments(node: ast.Call, bindings: _State, context: _Context) -> _State:
    parts = [*([node.func.value] if isinstance(node.func, ast.Attribute) else []), *_call_arguments(node)]
    parts = [part.value if isinstance(part, ast.Starred) else part for part in parts]
    starting = bindings
    for index, part in enumerate(parts):
        others = [context.value(other, starting) for position, other in enumerate(parts) if position != index]
        bindings = _linked(bindings, _root(part), _fresh_from(others))
    return bindings


def _invalidate_passed_slots(node: ast.Call, bindings: _State, context: _Context) -> _State:
    if not isinstance(node.func, ast.Name):
        return bindings
    for argument in _call_arguments(node):
        if not isinstance(argument, ast.Name):
            continue
        current = context.value(argument, bindings)
        if current is not None and current.indexed:
            updated = Storage(current.outer, current.reachable, current.kinds, opaque=True, deep=current.deep)
            bindings = _update_aliases(bindings, current, updated)
    return bindings


def _append_slot(node: ast.Call, bindings: _State, context: _Context) -> _State | None:
    receiver = _append_receiver(node)
    if receiver is None:
        return None
    current = context.value(receiver, bindings)
    if current is None or not current.indexed or current.kinds != frozenset({"list"}):
        return None
    if len(current.slots) >= _MAX_TRACKED_SLOTS:
        return _update_aliases(bindings, current, Storage(kinds=current.kinds, opaque=True))
    key = ("item", len(current.slots))
    value = context.value(node.args[0], bindings)
    return _update_aliases(bindings, current, _with_slots(current, (*current.slots, (key, value))))


def _append_receiver(node: ast.Call) -> ast.expr | None:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "append":
        return None
    if len(node.args) != 1 or node.keywords:
        return None
    return node.func.value


_REORDERING_METHODS = MappingProxyType({
    "list": frozenset({"clear", "extend", "insert", "pop", "remove", "reverse", "sort"}),
    "dict": frozenset({"clear", "pop", "popitem", "setdefault", "update"}),
})


def _invalidated_slots(node: ast.Call, bindings: _State, context: _Context) -> _State | None:
    if not isinstance(node.func, ast.Attribute):
        return None
    current = context.value(node.func.value, bindings)
    if current is None or not current.indexed or len(current.kinds) != 1:
        return None
    kind = next(iter(current.kinds))
    if node.func.attr not in _REORDERING_METHODS.get(kind, frozenset()):
        return None
    return _update_aliases(bindings, current, Storage(current.outer, current.reachable, current.kinds, opaque=True))


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
    ast.Return: _visit_return,
    ast.List: _visit_allocation,
    ast.Tuple: _visit_allocation,
    ast.Set: _visit_allocation,
    ast.Dict: _visit_allocation,
    ast.ListComp: _visit_comprehension,
    ast.SetComp: _visit_comprehension,
    ast.DictComp: _visit_comprehension,
    ast.GeneratorExp: _visit_comprehension,
})


def _bind(target: ast.AST, value: Storage, bindings: _State, context: _Context) -> _State:
    if isinstance(target, ast.Name):
        return _bound(bindings, target.id, value, context)
    if isinstance(target, ast.Starred):
        rest = Storage(reachable=value.everything, kinds=frozenset({"list"}), deep=value.reaches_unknown)
        return _bind(target.value, rest, bindings, context)
    if isinstance(target, (ast.Tuple, ast.List)):
        for child in target.elts:
            bindings = _bind(child, value if isinstance(child, ast.Starred) else _elements(value), bindings, context)
        return bindings
    if isinstance(target, (ast.Attribute, ast.Subscript)):
        current = context.value(target.value, bindings)
        key = _slot_key(target)
        if key is not None:
            slots = {**dict(current.slots), key: value}
            return _update_aliases(bindings, current, _with_slots(current, tuple(slots.items())))
        updated = Storage(current.outer, current.reachable | value.everything, current.kinds, opaque=True, deep=True)
        return _update_aliases(bindings, current, updated)
    return _linked(bindings, _root(target), _fresh_from([value]))


def _with_slots(current: Storage, slots: tuple[tuple[tuple[str, str | int], Storage], ...]) -> Storage:
    return replace(
        current,
        reachable=frozenset() if current.indexed else current.reachable,
        deep=False if current.indexed else current.deep,
        slots=slots,
    )


def _update_aliases(bindings: _State, current: Storage, updated: Storage) -> _State:
    heap = dict(bindings.heap)
    stored = replace(updated, references=frozenset(), slots=tuple((key, _stored(child)) for key, child in updated.slots))
    for reference in current.references:
        previous = heap.get(reference, Storage(opaque=True))
        heap[reference] = stored if len(current.references) == 1 else previous.join(stored)
    cells = {cell: updated if value is current else value for cell, value in bindings.cells.items()}
    return replace(bindings, cells=cells, heap=heap)


def _bound(bindings: _State, name: str, value: Storage, context: _Context) -> _State:
    cell = bindings.names.get(name, _Cell(context.activation, name))
    return replace(bindings, names={**bindings.names, name: cell}, cells={**bindings.cells, cell: _stored(value)})


def _stored(value: Storage) -> Storage:
    if value.references:
        return Storage(kinds=frozenset(), references=value.references)
    if value.slots:
        return replace(value, slots=tuple((key, _stored(child)) for key, child in value.slots))
    return value


def _linked(bindings: _State, root: str, added: Storage) -> _State:
    current = bindings.get(root)
    if current is None or not (added.everything or added.reaches_unknown):
        return bindings
    current = _resolved(current, bindings.heap)
    linked = replace(current, reachable=current.reachable | added.everything, deep=current.deep or added.reaches_unknown)
    return _update_aliases(bindings, current, linked)


def _root(expression: ast.AST) -> str:
    while isinstance(expression, (ast.Attribute, ast.Subscript, ast.Starred)):
        expression = expression.value
    return expression.id if isinstance(expression, ast.Name) else ""


def _join_all(states: Sequence[_State], context: _Context) -> _State:
    joined = states[0]
    for state in states[1:]:
        joined = _join_bindings(joined, state, context)
    return joined


def _join_bindings(left: _State, right: _State, _context: _Context) -> _State:
    return _State(
        {**left.names, **right.names},
        _joined_entries(left.cells, right.cells),
        _joined_entries(left.heap, right.heap),
        _joined_entries(left.evaluated, right.evaluated),
        _joined((left.result, right.result)),
        {**left.calls, **right.calls},
    )


def _joined_entries(left: Mapping, right: Mapping) -> dict:
    if left is right:
        return dict(left)
    result = dict(left)
    for key, right_value in right.items():
        left_value = result.get(key)
        if left_value is None:
            result[key] = right_value
        elif left_value is not right_value:
            result[key] = left_value.join(right_value)
    return result

