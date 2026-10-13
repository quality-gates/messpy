# Explicitness classifier contract

`messpy` is a syntax-only analyzer. It parses Python source and does not import modules, run code, inspect runtime objects, or trust type annotations as proof of behavior.

The `explicitness` ruleset classifies callable bodies into three observable outcomes:

- `ImplicitInput` means the callable reads data that does not arrive through its parameters.
- `ImplicitOutput` means the callable sends data out through ambient I/O, outer storage, or caller-owned reachable storage rather than through `return`.
- `UnknownEffect` means the callable performs an operation whose effects are not established by the analyzer.

A clean report means the callable is a calculation only inside the supported subset below. It does not prove purity for arbitrary runtime values.

## Supported calculation subset

The analyzer treats these operations as established when their bindings are not shadowed:

- Exact built-in scalar arithmetic and comparisons over ordinary built-in values.
- Plain built-in containers created in the callable, including list, dict, set, and tuple literals.
- Modeled pure built-ins such as `len`, `sum`, `min`, `max`, `sorted`, and simple numeric constructors.
- Resolved same-file functions, methods on `self` or `cls`, lambdas, and returned callables when the call target is established by lexical scope resolution.
- Plain empty classes used as local records.
- Fixed captures from an enclosing function when the captured binding is not later mutated. This includes scalar captures and fresh built-in containers whose contents are read later under the documented built-in numeric-value assumptions.

Dynamic user objects that override arithmetic, comparison, iteration, container construction, or descriptor behavior are outside this supported subset unless their effects are resolved as same-file callables. Type annotations alone do not certify runtime values.

## Effect summaries

Each callable has a finite summary of semantic facts:

- Parameter-relative reads and writes.
- Ambient reads and writes.
- Unresolved operations with a stable reason.
- Returned callable aliases, returned storage provenance, and local callable aliases.
- A completeness flag that is false when any unknown effect remains.

Calls are propagated to a fixed point over the finite set of callable identities and effect facts. Recursive cycles terminate because facts are joined monotonically and provenance strings are stable.

When a call is resolved, parameter-relative effects are substituted with the actual argument storage at that call site. Mutating caller-owned argument storage remains an action. Mutating fresh private outer storage can stay local to the caller. Ambient and unknown effects are never erased by private-argument substitution.

## Storage ownership

Storage facts distinguish the outer allocation from reachable contents.

A fresh shallow copy, such as `list(values)`, gives the caller a private outer container. The elements can still be caller-owned. Mutating the copied container itself is local. Mutating an element reached through the copy is an `ImplicitOutput`.

Aliases and rebinding are evaluated at the operation site. Branches and loops join possible origins. If ownership escapes or cannot be established, the analyzer keeps uncertainty rather than certifying a calculation.

## Callback execution

Creating or returning a callback does not execute its body in the factory summary. The callback body is analyzed under its own callable owner.

Invoking an established callback carries its effects to the caller. Invoking an injected callback or other unresolved callable reports `UnknownEffect`. Unknown callback calls do not fabricate `ImplicitInput` or `ImplicitOutput` findings when there is no evidence for those effects.

Generators, async scheduling, lazy iteration, decorators with dynamic behavior, descriptor dispatch, monkey-patching, imports outside the analyzed file, and dynamic attribute lookup are unsupported unless the operation is explicitly modeled. Unsupported behavior remains unknown.
