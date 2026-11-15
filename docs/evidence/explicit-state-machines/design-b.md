# Candidate B. Immutable domain reducers and typed continuations

## Caller usage

The public CLI and analysis APIs stay unchanged. Internally, each loop consumes a named state and an event or continuation. The state, rather than scattered locals, contains everything needed for its next step.

```python
parse = ArgumentCursor.start(arguments)
while not parse.finished:
    parse = parse.consume()
return parse.finish()

proof = BooleanSuffix(fallthrough=False)
for statement in reversed(statements):
    proof = proof.prepend(statement)
return proof.proven

summaries = EffectIteration.seed(owners)
while not summaries.converged:
    summaries = summaries.advance(owners, graph)
return summaries.current
```

Domain transitions remain in their owning modules. There is no shared machine engine, global event bus, or synchronization layer.

## Grounding

The CLI parses into `_ArgumentParseState`, resolves rules, analyzes files, renders, and publishes a report. Most rule analysis lives in analyzer.py. Current main has moved evaluated and lexical traversal to regions.py, shared masks and node caches to syntax.py, parameter binding to parameters.py, and cohesion to cohesion.py. Names and callgraph share comprehension masks, but lexical imports and callable target lookup have distinct semantics. Ownership interprets abstract storage using `_State`, `_Flow`, and `_Context`. Effects collects direct witnesses then repeatedly transfers summaries through the call graph. Captures independently proves the safety of closure reads, recursively inspecting helper parameters. None of these should become a centralized statechart.

The current main ruleset loader has `_ConfiguredRule` with `explicit_priority` and `explicit_properties`. Those facts must survive nested merges. Replacing them with a last-write-wins loaded-rule map would restore issue 311. Current ownership also memoizes capture-free calls, preserving cell and heap deltas. It skips memoization when a closure captures cells. The original inventory predates these owners and memoization details.

## Type sketch

These are signature sketches, not production implementations.

```python
@dataclass(frozen=True)
class ArgumentCursor:
    arguments: tuple[str, ...]
    offset: int
    parsed: _ArgumentParseState
    def consume(self) -> ArgumentCursor: raise NotImplementedError
    def finish(self) -> ParsedArguments: raise NotImplementedError

@dataclass(frozen=True)
class RulesetContext:
    directory: Path
    ancestry: tuple[Path, ...]
    def descend(self, reference: str) -> RulesetContext: raise NotImplementedError

@dataclass(frozen=True)
class RuleConfiguration:
    rules: Mapping[str, _ConfiguredRule]
    def include(self, configured: Iterable[_ConfiguredRule]) -> RuleConfiguration: raise NotImplementedError
    def exclude(self, name: str) -> RuleConfiguration: raise NotImplementedError

@dataclass(frozen=True)
class SuppressionState:
    directive_offset: int
    region_depth: Mapping[str, int]
    scheduled: Mapping[int, frozenset[str]]
    def before(self, finding_line: int, context: SuppressionContext) -> SuppressionState: raise NotImplementedError
    def suppresses(self, line: int, rule: str) -> bool: raise NotImplementedError

@dataclass(frozen=True)
class DeferredValue:
    certainty: DeferredCertainty  # ABSENT, KNOWN, AMBIGUOUS
    executions: tuple[DeferredCreation, ...] = ()
    def assigned(self, incoming: DeferredValue, writes: int) -> DeferredValue: raise NotImplementedError

@dataclass(frozen=True)
class ComprehensionUse:
    target: str
    used: bool
    binding: BindingVisibility  # VISIBLE, SHADOWED
    def clause(self, generator: ast.comprehension) -> ComprehensionUse: raise NotImplementedError

@dataclass(frozen=True)
class BooleanSuffix:
    proven: bool
    def prepend(self, statement: ast.stmt) -> BooleanSuffix: raise NotImplementedError
```

For traversal, replace unlabelled tuples with immutable continuations that derive child contexts. A callable continuation contains `(node, lexical_scope, enclosing_callables)`. A masking continuation contains `(node, hidden_names)`. A capture continuation contains `(queried_name, node, helper_chain)` and explicitly decides whether to schedule body children or definition-time expressions. Existing ordering is part of the contract.

Publication is the exception to pure value transitions. Resource ownership should use context managers or typestate objects, so actual cleanup follows state ownership. `PendingReport` owns a temporary path; `publish` replaces it and transfers ownership. A temporary-umask context owns the saved mask and restores it on every exit. Avoid an enum updated alongside the same old scattered operations.

## Complete inventory mapping

| ID | Current owner/state | Candidate transition owner and action |
|---|---|---|
| M01 | cli._ArgumentParseState plus local index | ArgumentCursor owns offset and consumes an argument into the existing parsed value. Existing option reducers remain. |
| M02 | rulesets directory/ancestry parameters | RulesetContext.descend checks active-chain cycles and supplies the child directory. Child contexts are values, so return implicitly restores the parent. |
| M03 | rulesets configured-rule dictionaries and `_merge` | RuleConfiguration.include/exclude own precedence and removal. `_ConfiguredRule` remains authoritative for explicit field provenance. |
| M04 | cli temporary path local and exception branch | PendingReport owns temporary path until atomic replacement succeeds. Its context guarantees cleanup on failure, including permission failure. |
| M05 | cli saved umask local with finally | TemporaryUmask context owns restoration. Preserve that umask is queried only when destination stat fails. |
| M06 | analyzer discovered paths, seen errors, per-file try | DiscoveryState.merge owns deduplication. FileAnalysisResult is a success/error sum type returned by a per-file operation; no synthetic phase field required. |
| M07 | callables pending triples | CallableVisit continuation derives child scope/enclosing values. A traversal object owns pending work and discovered callables. |
| M08 | callgraph._BindState and transition helpers | Existing state/reducer design is adequate. Make bind/shadow/push/pop authority clear and retain those named transitions. No additional lifecycle enum. |
| M09 | Names lookup loop, analyzer ScopeChain, callgraph lookup | Per-resolver immutable lookup cursor with `advance` decisions of FOUND, NEXT, MODULE, or STOP. Do not merge different resolver policies. |
| M10 | syntax.comprehension_masks pending pairs | MaskedVisit.child_visits derives reset/outer-iter/inner masks. Both name and call resolution continue to consume the one shared result. |
| M11 | analyzer used/shadowed tuple | ComprehensionUse.clause owns use-before-shadow ordering and prevents post-shadow evidence entering the old binding. |
| M12 | constants known map | ConstantEnvironment.assign records a classifiable stable assignment. Explicitly preserve a single forward pass. |
| M13 | analyzer._NamingState plus helper transitions | Existing representation is adequate. Named enter/leave/record transitions keep context and receiver restoration authoritative. |
| M14 | analyzer candidate lists keyed by name/line | SymbolTablePool.take_function/take_comprehension consumes exactly one selected candidate. Preserve fallback to first candidate. |
| M15 | ownership._State plus bound/allocated/linked helpers | Existing state is authoritative. Rename opaque `_State` to OwnershipState only if it improves ownership visibility; retain structural sharing. Consolidate writes behind existing named reducers. |
| M16 | ownership._Flow and _join_bindings | Existing fork/join algebra is explicit enough. Name branch operations in _Flow if this reduces repeated binding/trace assembly. Do not add completion outcomes absent in baseline. |
| M17 | ownership local current/updated fixed-point loop | LoopIteration retains current head, entry/body flows, and convergence verdict. `advance` computes one actual interpreter round. |
| M18 | ownership._Context/_Cell/_Closure and _execute_body | Existing activation representation is adequate. Named enter_call/restore_caller operations own restoration and escaping-cell retention. |
| M19 | ownership.Storage plus widening/invalidation helpers | Existing domain representation is explicit. Name precision loss at the single existing operations. Keep bounded path, slots, references, strong/weak update rules. |
| M20 | ownership comprehension outer/inner binding maps | ComprehensionFrame.enter/restore isolates target bindings and returns opaque walrus writes to outer state. |
| M21 | execution tuple/None/empty provenance conventions | DeferredValue sum type plus DeferredBindings.assign/force. Preserve repeated-write ambiguity and non-consuming forcing. |
| M22 | effects aliases map and observation snapshots | CallableAliasState.observe/assign owns snapshot-before-assignment ordering, instability filtering, bind and kill. |
| M23 | effects current/updated summary maps | EffectIteration.advance computes one synchronous round, with fixed-point equality as termination. Do not switch to asynchronous worklist without proving equivalence. |
| M24 | reachability list accumulation and breaks | EvaluationPrefix state consumes statements/operands/filters and records OPEN or STOPPED. Keep trigger-specific stop rules as domain operations. |
| M25 | analyzer suppression rule counters | SuppressionState.apply_region increments/decrements with floor zero. Consume directives strictly before finding line. |
| M26 | analyzer next_line_rules | SuppressionState.schedule selects the first eligible following line and expands wrapped definition signatures. Keep independent scheduled and region state. |
| M27 | analyzer candidate/immutable/initial-target triple | GlobalBindings.initialise preserves the first target identity. `mutation_at` excludes only that target and applies current shadowing policy. |
| M28 | analyzer PrivateMemberUsage and dynamic/export accumulators | UsageEvidence unions known names and joins monotone uncertainty. Final PrivateMemberUsage remains an output snapshot. |
| M29 | analyzer backward boolean accumulator | BooleanSuffix.prepend owns suffix proof. Branches recurse with the incoming suffix, unsupported return-containing syntax clears proof. |
| M30 | analyzer visitor set and changed flag | VisitorClosure.expand returns new known set and equality verdict; IDs are only added. |
| M31 | onion action_ids set and pending list | ActionClosure marks newly discovered callers once. Keep explanation search as a separate ProofPath with active-chain guard. |
| M32 | captures pending list and ScopeChain recursion checks | CaptureQuery continuation derives nested traversal and helper queries. Its child query refuses already-active helper scopes. |
| M33 | callgraph reachable, analyzer linked classes, protocols ancestry, ownership heap walks | Each owner uses a named traversal state with explicit seed, discover, and guard policy. Avoid one universal seed rule because root inclusion and active-chain semantics differ. |
| M34 | cohesion connected map and union helpers | Components.find/union/count owns forest invariant and compression. Existing pure helper behavior can be moved directly into the immutable type. |
| M35 | analyzer seen dictionary keys | KeyHistory.observe returns the prior witness plus updated history. Preserve first witness and Python equality semantics. |
| M36 | analyzer ScopeUsage recursion and cache | ScopeUsage already names output. UsageResolution.resolve_child computes captured/local/outward joins and owns completed cache insertion. |
| M37 | ownership nested trace pending stack and observed map | ObservationReplay.step owns traversal ordering and last-write-by-node behavior. Keep final observation replacement, not join. |
| M38 | per-rule witness maps and dedup sets | Witnesses.record_first and ReportedEffects.claim own first-witness/emission semantics. Apply locally rather than one engine that obscures effect identity. |
| M39 | lru_cache wrappers, analyzer graph lazy value, ownership evaluated/call caches | Existing lru_cache wrappers are already explicit bounded cache machines. Name deferred graph lookup and OwnershipCache invalidate/evaluate/memo transitions; preserve capture-free-only call memoization and delta replay. |

## Boundaries and invariants

The state representation must actually own transitions. A `State(value)` object passed into unchanged loops is insufficient. Each changed field must have one writer or one named reducer. Avoid exposing mutable dictionaries under a frozen dataclass when callers can bypass transitions; use private dictionaries within a mutable owner or immutable mappings within a value type.

Continuations must preserve traversal order, not merely visited membership. `module_callables` is pre-order with reversed child scheduling. `_observations` reverses nested trace children so later logical observations overwrite earlier ones. Capture traversal uses a different stack order. Comprehension evaluated_children currently returns result syntax before generators in some cases. Changing that incidental analysis order can alter alias snapshots and first witnesses, even if runtime evaluation would differ.

No generic finite-state framework is warranted. Most state spaces contain unbounded mappings, counters, stacks, or storage lattices. An enum is useful for genuinely distinct modes such as deferred certainty or prefix stoppedness. It should not duplicate state already derivable from authoritative data.

## Verification contract

Use the existing suite and self-analysis as mandatory gates, then add behavior-focused checks at transitions whose state is currently encoded only by locals or sentinels.

1. CLI parse order, repeated suffix options, missing values, and error-policy flags before versus after failure.
2. Ruleset reference diamond versus active cycle, nested partial overrides, exclusions followed by reintroduction. Run and correspondingly maintain the existing ruleset-precedence verifier.
3. Publication failure at write, chmod, and replace. Existing destination remains intact, temporary resource cleanup is attempted, saved umask is restored.
4. Two same-line callables/comprehensions consume distinct symbol tables. Nested function/class defaults and annotations keep current scope semantics.
5. Ownership alias mutation, caller restoration, escaping closures, capture-free memo hit delta replay, recursion fallback, loop fixed points, walrus leakage, strong/weak heap updates.
6. Deferred ABSENT versus AMBIGUOUS versus KNOWN, repeated forcing, repeated writes, ordinary iterable fallback, scheduler execution.
7. Nested disables with unmatched enables, same-line directives, wrapped signature suppression, and comment-only finding eligibility.
8. First versus last observation/witness semantics. The tests must demonstrate observable findings, rather than only assert that a new enum exists.
9. Differential public observations over fixtures and generated small programs on baseline and candidate. Normalize absolute paths and include status, stdout, stderr, and report-file bytes.
10. Mutation-check representative invariants by breaking transition behavior in a disposable copy. A machine inventory checker proves mapping completeness only; it does not prove behavior or runtime integration.

## Rationale and tradeoffs

Candidate B makes advancement a returned value. This is easiest to reason about in the existing immutable ownership and binding interpreters, and it exposes temporal dependencies in comprehension proofs and symbol-table consumption. Distinct `DeferredValue` variants eliminate the particularly risky tuple/None/empty convention.

Its cost is allocation and more explicit call sites for small scans. Do not convert every list append to an immutable tuple append. Large traversal queues should remain privately mutable inside one traversal owner while continuations stay immutable. A single boolean suffix proof may also be clearer as a named reducer over a boolean than a class; the requirement is authoritative named state and transitions, not a class per inventory row.

I reject a global StateMachine class, central transition registry, log-only state descriptions, duplicated phase flags, or conversion of all bounded library caches to custom caches. They either leave policy scattered or add code without strengthening ownership.

## Source read

Inspected current main ownership.py, effects.py, execution.py, captures.py, reachability.py, callables.py, regions.py, syntax.py, names.py, callgraph.py, constants.py, cohesion.py, rulesets.py, cli.py, and relevant analyzer.py sections. Current main's decisive changes from the inventory are extracted region/syntax/cohesion/parameter ownership, explicit ruleset property provenance, and closure-free call memoization.
