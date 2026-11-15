# Candidate A. Local state owners

## Caller usage

The public CLI and analysis APIs remain unchanged. Runtime loops name the state they advance. Each owner controls its own invariants. No generic event dispatcher or universal state-machine base class is introduced.

```python
cursor = _ArgumentCursor(tuple(arguments))
while cursor.has_next:
    cursor = cursor.consume()
return cursor.finish()

suppression = _SuppressionState(directives, source_lines, comment_rules, header_lines)
for finding in sorted(findings, key=lambda item: item.line):
    suppression = suppression.before(finding.line)
    output.append(replace(finding, suppressed=suppression.applies(finding)))

iteration = _EffectIteration.initial(owners)
while not iteration.converged:
    iteration = iteration.advance(owners, graph)
return iteration.summaries
```

These are sketches, not proposals to force every machine into those three interfaces. Existing `_BindState`, `_NamingState`, `_State`, and `Storage` already carry real state and have named authoritative transition functions. Keep them when their invariant is already encoded. Improve specific ambiguous regions inside them.

## Grounding

Current main is `3448957`. The original inventory was made against `fbb539f`. Current main extracted cohesion to `cohesion.py`, evaluated and lexical regions to `regions.py`, shared syntax to `syntax.py`, and argument binding to `parameters.py`. Names and call graph now share comprehension masks through `syntax.py`. Ownership added persistent `_LayeredMap` storage and memoized call results with cell and heap deltas. Ruleset configuration now retains field-level explicitness markers in `_ConfiguredRule` to preserve partial overrides.

The runtime goes from `cli.run` through selection and `analyzer.analyze`, file discovery and decoding, `analyze_source`, and rule dispatch. Names, callables, syntax regions, and call graphs are shared views of the same unchanged AST. Effect analysis collects direct facts, interprets ownership, records deferred forcing, then solves an interprocedural summary fixed point. Rules query these results to emit findings. Suppression is applied afterward. CLI rendering and report publication finish the run.

The primary risk is a structural rewrite accidentally changing traversal order, proof conservatism, or identity. AST identity connects all analysis tables. A copy of an AST that looks equivalent is not interchangeable.

## Module and type sketch

Keep owners private in the module that already owns the decisions. Public model names remain unchanged. Transition functions can remain free functions when they clearly take and return the owner state. Methods are appropriate when they hide a multi-field invariant.

```python
@dataclass(frozen=True)
class _ArgumentCursor:
    arguments: tuple[str, ...]
    index: int = 0
    parsed: _ArgumentParseState = field(default_factory=_ArgumentParseState)
    def consume(self) -> _ArgumentCursor: raise NotImplementedError
    def finish(self) -> ParsedArguments: raise NotImplementedError

@dataclass(frozen=True)
class _RulesetContext:
    directory: Path
    ancestry: tuple[Path, ...] = ()
    def enter(self, path: Path) -> _RulesetContext: raise NotImplementedError

@dataclass(frozen=True)
class _RuleConfiguration:
    rules: Mapping[str, _ConfiguredRule]
    def merge(self, incoming: Iterable[_ConfiguredRule]) -> _RuleConfiguration: raise NotImplementedError
    def exclude(self, name: str) -> _RuleConfiguration: raise NotImplementedError

@dataclass(frozen=True)
class _CallableVisit:
    node: ast.AST
    nearest_scope: ast.AST | None
    enclosing_callables: tuple[ast.AST, ...]
    def children(self) -> tuple[_CallableVisit, ...]: raise NotImplementedError

@dataclass(frozen=True)
class _ComprehensionUse:
    name: str
    used: bool = False
    shadowed: bool = False
    def following_clause(self, clause: ast.comprehension) -> _ComprehensionUse: raise NotImplementedError

@dataclass(frozen=True)
class _KnownDeferred:
    bodies: tuple[tuple[ast.AST, ast.Call], ...]
class _OrdinaryValue: pass
class _UnknownDeferred: pass
DeferredValue = _OrdinaryValue | _KnownDeferred | _UnknownDeferred

@dataclass(frozen=True)
class _DeferredBindings:
    writes: Counter[str]
    values: Mapping[str, DeferredValue]
    def assign(self, name: str, expression: ast.expr, resolve) -> _DeferredBindings: raise NotImplementedError

@dataclass(frozen=True)
class _LoopIteration:
    bindings: _State
    entered: _Flow | None = None
    body: _Flow | None = None
    converged: bool = False
    def advance(self, node, context) -> _LoopIteration: raise NotImplementedError
```

The loop sketch's optional traces must not escape the iteration owner. An alternative result pair with distinct `PendingLoop` and `StableLoop` variants avoids optional fields if the implementation starts relying on them outside `advance`. Do not introduce status enums that merely mirror existing `None` checks without controlling state.

Report publication is an I/O lifecycle, so a private resource owner is appropriate. Its methods create and write the temporary file, close it, set permissions, publish with replace, and discard on failure. The owner must control the temporary path. A stage field is useful only if its operations reject invalid sequencing or derive allowed operations from the represented resource. A field updated after operations while old code still writes the path is cosmetic.

The umask lifecycle can become a dedicated context manager that acquires the original mask and restores it in `finally`. Its caller computes the creation mode from the yielded original value. Existing permission behavior remains unchanged.

## Full inventory correspondence

| ID | Current owner | Proposed action and invariant |
|---|---|---|
| M01 | `cli._ArgumentParseState`, `_consume_argument` | Add a cursor owner for tokens plus parse state, or retain named reducer and add explicit cursor record. Consumed flags alone determine error policy. First suffix option replaces defaults. |
| M02 | `rulesets._load_reference` | Add immutable `_RulesetContext.enter`. Cycle detection uses active ancestry, not global visited paths. Repeated references in separate branches remain legal. |
| M03 | `rulesets._ConfiguredRule`, `_merge`, `_exclude` | Keep field markers and authoritative `_merge`; encapsulate loaded map in `_RuleConfiguration` only if it removes competing writers. Field omission differs from an explicit catalog-default value. |
| M04 | `cli._write_report` | Add publication resource owner. Distinguish temporary ownership from published destination. Preserve atomic replace and permission order. |
| M05 | `cli._destination_file_mode` | Add dedicated umask context owner. Always restore even when computing mode fails. |
| M06 | `analyzer._source_files`, `_analyze_files` | `_Discovery` owns path set, error order, and error deduplication. A read outcome type makes decoded-source versus processing-error states explicit before `analyze_source`. Existing `AnalysisResult` remains terminal outcome. |
| M07 | `callables.module_callables` | Replace anonymous pending tuples with `_CallableVisit` and a named advance/children transition. Preserve pre-order and nearest-scope ownership through class-body control flow. |
| M08 | `callgraph._BindState` | Already adequate state and transitions. `_bind_name`, `_shadow`, `_push_scope`, `_pop_scope` jointly update the authoritative state. Verify no competing mutation path. Retain rather than wrap. |
| M09 | `names._resolved_record`, `_scopes_for_node`; analyzer `_ScopeChain`; callgraph resolvers | Name lookup cursor and resolution outcomes where tuples and walking locals obscure the state. Do not merge consumers whose policies differ. Global jumps to module; nonlocal skips; class scopes differ across function boundaries. |
| M10 | `syntax.comprehension_masks`, `_masked_children` | Use named masked-node work items. Keep the shared implementation. Outer iterable inherits incoming masks; targets apply through lambdas but definitions reset them. |
| M11 | `analyzer._later_comprehension_uses` | `_ComprehensionUse` combines use evidence and terminal shadowing. A later iterable sees the old name before its target shadows it. |
| M12 | `constants.scope_constants` | `_ConstantKinds` owns known/import/write information and assignment transition. Preserve one forward pass. Do not retry unresolved earlier assignments. |
| M13 | `analyzer._NamingState` | Already adequate state with definition/binding transitions. Optional local enter/leave methods may consolidate context/depth/receiver invariants. Avoid a parallel context object while old writers survive. |
| M14 | `analyzer._function_scopes`, `_comprehension_scopes` | `_SymbolTableMatches` owns candidate queues and consume operation. No table can be reused. Preserve same-line matching and fallback order. |
| M15 | `ownership._State`, `_bound`, `_allocated`, `_visit_*` | Existing state adequate. Name and centralize any residual direct update that bypasses cell/heap invariants. Keep persistent map optimization. |
| M16 | `ownership._Flow`, `_join_bindings`, `_visit_if`, `_visit_try` | Existing abstract state and named join adequate. A branch-exit accumulator can replace repeated states/traces pairing. Preserve conservative exception entry states. |
| M17 | `ownership._visit_loop` | `_LoopIteration.advance` owns equality comparison and last entered/body traces. Keep equality semantics, including last-iteration trace selection. No new arbitrary iteration cap. |
| M18 | `ownership._Context`, `_frame_state`, `_execute_body` | Existing activation and frame state adequate. Add a call-frame return owner if it reduces restoration duplication. Restore caller names/evaluated/result; preserve escaping captured cells and heap changes. |
| M19 | `Storage`, `_resolved`, `_uncertain_storage`, `_update_aliases` | Existing precision lattice and transition helpers mostly adequate. Name traversal guard state if needed. Strong update only for one location; multiple-location updates join. Preserve widening limits. |
| M20 | `ownership._visit_comprehension` | Named comprehension frame captures outer bindings and evolving inner flow. Return outer bindings plus opaque walrus writes, not inner target scope. |
| M21 | `execution._deferred_bindings` | Replace `()`/tuple/`None` union with named ordinary/known/unknown values and authoritative assignment and force decisions. Force records do not consume provenance. |
| M22 | `effects._callable_aliases` | `_CallableAliases` owns current targets and pre-transition observations. Unstable and shared names remain excluded. Bind known callable, clear unknown assignment. |
| M23 | `effects._fixed_point` | `_EffectIteration` owns summary map and equality transition. Recompute a synchronous round from the prior complete map. Do not accidentally turn this into an in-place asynchronous solver. |
| M24 | `reachability.live_statements`, `_short_circuit`, `_until_false` | A small domain-specific scan owner or explicit live/stopped result makes termination state visible. Preserve inclusion of the terminal item and existing comprehension result-before-generators traversal order. |
| M25 | `analyzer._apply_suppressions` | `_SuppressionState` owns directive cursor and per-rule depth, with `before(line)` and `applies`. Enable clamps at zero. Same-line directives do not yet apply. |
| M26 | `analyzer._next_line_suppression` | Same suppression owner owns scheduled lines separately from regional depths. Preserve comment-finding filtering and wrapped signature expansion. |
| M27 | `analyzer._global_candidates` | `_GlobalBindings` owns first targets, annotation status, and initialization identities. Mutation queries use that owner. A later same-name target is not initial merely because its name matches. |
| M28 | `analyzer._exported_names`, `_dynamic_attribute_accesses` | `_NameEvidence` owns known names and an irreversible unknown latch, with named observe/obscure transitions. Static later observations must not clear uncertainty. |
| M29 | `analyzer._all_paths_return_boolean` | `_BooleanReturnProof` owns suffix verdict and backward statement transition. Unsupported return-containing constructs invalidate, even when some branches look boolean. |
| M30 | `analyzer._inherited_ast_visitor_class_ids` | `_VisitorInheritance` owns known set and advancing round. Preserve in-round promotion semantics and qualification rules. |
| M31 | `onion._action_ids`, `_chain_phrase` | `_ActionPropagation` owns accepted IDs and pending callers. A separate immutable chain path owns explanation recursion guard. Distinguish classification membership from active path. |
| M32 | `captures._scope_nodes`, `_helper_parameter` | `_CaptureSearch` names queried name, chain, pending nodes. Helper-entry transition rejects active callee before extending scopes. Definition-time expressions still traverse when nested body rebinding prunes. |
| M33 | `CallGraph.reachable_from`, analyzer `_linked_classes`, `protocols._ancestors`, ownership heap traversals | Local named frontier/ancestry records or existing immutable guards. Do not use one visited semantics everywhere. Reachability intentionally includes the root only if a cycle reaches it; ancestry tracks strings; heap tracking uses allocation identities. |
| M34 | `cohesion._relationship_component_count` | `_MethodComponents` owns parent links, find/compress and union. Count derives from roots. Preserve current no-active-method result of one. |
| M35 | `analyzer._duplicated_array_key_findings` | `_DictionaryKeys.observe` returns first witness without replacing it. Preserve Python key equality, including bool/int equivalence, and skip unknown keys. |
| M36 | `analyzer._scope_usage` | `_ScopeUsageCache` owns memo and recursive propagation. `ScopeUsage` already names output. Child free names captured locally become uses; uncaptured free names propagate. |
| M37 | `ownership._observations` | `_ObservationHistory` owns pending trace items and latest mapping. Flatten left-to-right and replace by AST identity. Do not join observations. |
| M38 | various first-witness and dedup maps | Use concrete evidence owners, e.g. `_FirstInputs`, `_ReportedEffects`, rather than a generic registry. Existing `setdefault`, membership gates, and set reductions are adequate only when their invariant is clear and local. Preserve first versus last choice per consumer. |
| M39 | `lru_cache`, `cache`, ownership evaluated and calls maps | Decorated memoization is already explicit and bounded. Keep it. Make ownership evaluation invalidation and memo-result delta replay named transitions. Existing `_cached`, `_visit`, `_memo_execution` expose most of this; include call memoization in correspondence because current main added it. |

## Verification

Use the existing full acceptance suite and clean self-analysis as required gates. Compare baseline and candidate public `analyze_source` findings, errors, suppression flags, ordering, CLI text/JSON outputs, and exit statuses over a deterministic corpus. The corpus must include nested definitions, shadowed imports, comprehensions, closures, branch/loop joins, repeated generator forcing, recursion limits, same-line lambdas, wrapped suppression signatures, partial ruleset overrides, dictionary key equality, and private-member uncertainty.

Use focused behavior tests for new state boundaries. Good tests assert that a repeated enable cannot drive suppression negative, a later unknown export cannot become precise again, a later comprehension iterable reads the previous binding, an aliased heap update is visible through its other name, and source errors do not stop later files. Prefer these over assertions that an enum changed from one name to another.

Run the existing `verify-ruleset-precedence` skill and maintain its correspondence. It checks `_merge` directly with CrossHair; changing that function's signature or introducing a wrapper around it requires moving the symbolic contracts to the new authoritative boundary. The loader behavior checks must remain. Keep its bounded claim separate from the full public differential checks.

Mutation-check several decisive properties. At minimum reverse equality termination or update timing in one fixed-point unit, clear an uncertainty latch, remove directive cursor advancement, replace first witness with last, or change closure return retention. A mutation that fails to cause a test failure is a coverage gap, not proof.

## Alternatives rejected

A universal enum/event framework makes arbitrary algorithms look alike and adds indirection without owning their invariants. Reject it. It also encourages decorative phase flags while old mutable collections remain authoritative.

Adding one new dataclass for every inventory row is excessive. Several rows are orthogonal parts of existing typed state and several are explicitly declared Python cache policies. Retain adequate owners, document exact transition symbols, and verify consumers.

Moving all state into a new `state_machines.py` separates domain knowledge from its callers. Reject it. Domain owners stay in the existing modules unless extraction materially shortens the reader's path.

The broad scope still requires implementation changes for the anonymous tuple, sentinel, latch, and cursor machines. A document alone cannot complete those entries.
