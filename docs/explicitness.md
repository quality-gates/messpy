# Explicitness classifier contract

`messpy` parses Python source without importing modules, running code, inspecting runtime objects, or treating annotations as proof of behavior.

The `explicitness` ruleset reports three kinds of findings:

- `ImplicitInput`: data read from ambient state, mutable module storage, or mutable captured storage.
- `ImplicitOutput`: data sent through ambient I/O or writes to outer or caller-owned reachable storage.
- `UnknownEffect`: an operation whose behavior the analyzer cannot establish.

Reading a parameter, including its reachable contents, is explicit input. Writing through a parameter is an output. A calculation has no findings inside the supported subset below. A clean report does not prove purity for arbitrary runtime objects.

## Supported calculations

When bindings are established and not shadowed, the analyzer supports:

- Scalar arithmetic and comparisons under ordinary built-in numeric and scalar value assumptions.
- Plain built-in containers created locally, including list, dict, set, tuple, and comprehension results.
- Modeled built-ins such as `len`, `sum`, `min`, `max`, `sorted`, and scalar constructors.
- Resolved same-file functions, methods on `self` or `cls`, lambdas, and returned callable aliases.
- Plain empty record classes and simple frozen dataclasses with literal field declarations, no inheritance, and no custom initialization hooks.
- Fixed scalar captures and proven private container captures whose binding and contents cannot change between reads.

Immutable constants require a fixed binding and established immutable contents. Uppercase spelling or a `Final` annotation does not make a mutable container immutable. Tuple, frozenset, and read-only mapping contents are checked recursively.

Captured parameters used as scalars can be calculations under the built-in value assumption. Reading a captured shared container, including through a resolved helper, is implicit input. A private container capture remains a calculation only when its uses establish that no other operation can mutate or escape it.

## Ownership and calls

Storage facts distinguish the outer allocation from reachable contents. A shallow copy such as `list(values)` has a private outer container but can still contain caller-owned elements. Mutating the copy itself is local; mutating an element reached through it is an `ImplicitOutput`.

Aliases and rebinding are evaluated at the operation site. Branches join possible origins, and loops compute a fixed point. Escaping or opaque storage retains uncertainty.

Lexical bindings refer to cells, and containers and plain records refer to allocations with independent member slots. Replacing one established slot removes its old alias; sibling slots keep their own origins. Invoked same-file helpers and established closures update that same allocation state. Creating an uncalled closure leaves the creator's bindings unchanged.

Ownership execution tracks at most four active callable bodies, sixteen literal slots, sixteen relative paths per origin, and eight selectors per path. Recursive or deeper ownership execution makes passed and captured storage uncertain. Excess relative paths collapse to a shared prefix with an uncertainty selector. These bounds preserve uncertainty instead of proving unchecked storage private; effect summaries still transfer established ambient and parameter-relative effects through recursive call graphs.

Each callable has a finite effect summary. Resolved calls substitute parameter-relative effects with actual argument storage. A helper that mutates a parameter remains an action; calling it with fresh private storage can be a calculation. Ambient and unknown effects survive substitution. Recursive call cycles join facts to a fixed point.

Creating or returning a function or lambda does not execute its body. Its findings belong to that callable. Invoking an established callback transfers its effects. Injected or unresolved callbacks report `UnknownEffect` without inventing input or output evidence. `sorted`, `min`, `max`, and established list `sort` calls execute their `key` callback.

## Deferred execution

Python coroutine and generator bodies are cold. Calling a known async function or generator function creates a deferred value; it does not transfer body effects to the creating caller. The body still has its own findings.

`await`, supported asyncio schedulers, iteration, `yield from`, and modeled consuming built-ins transfer established deferred effects to the forcing operation. Named generator bodies keep their function owner. Generator expressions use `<genexpr>`; constructing one evaluates its outermost iterable in the factory and leaves its body deferred. A resolved factory returning a generator expression can preserve that deferred body through consumption.

Deferred tracking supports direct creation and fixed local aliases. An unresolved awaitable reports `UnknownEffect`. Forcing a possibly deferred local binding after uncertain rebinding also reports `UnknownEffect`, unless operation-site storage establishes an ordinary built-in value. Arbitrary iterator pipelines, external scheduler behavior, and dynamic deferred-value factories are outside the precise lifecycle model.

## Module initialization and pruning

Load-time statements, function defaults, decorators, class bases, and class body expressions belong to `<module>` or their enclosing executing callable. Nested function bodies remain separate. Known decorator effects execute at definition time; invoking a callable transformed by an unestablished decorator remains unknown.

Only literal branch conditions are pruned. For example, `if False` is dead, while `if not True` is retained. The same rule applies when checking capture stability and storage mutation.

## Protocols and limits

Declared same-file descriptors, operator protocols, iteration protocols, and virtual overrides provide evidence of dynamic dispatch. Operations on opaque receivers then report `UnknownEffect`; established ordinary built-in storage stays precise. Custom context managers also retain uncertainty.

Imports outside the analyzed file, arbitrary runtime monkey-patching, dynamic attributes, unmodeled decorators, and user-defined protocols without local evidence are outside the supported calculation assumptions. A method name or type annotation alone never establishes a pure call. Receiver state remains subject to the selected policy: `strictexplicitness` includes instance inputs and outputs; excluded receiver effects can remain unknown in `explicitness`.

Findings identify the owning callable and the operation line. Transferred findings use the call or forcing line. The report deduplicates repeated semantic effects per owner; it is an effect summary, rather than an execution count.

A user pass of this contract is recorded in [the 2026-10-17 exploratory report](exploratory-testing/2026-10-17-explicitness-design-ci.md).
