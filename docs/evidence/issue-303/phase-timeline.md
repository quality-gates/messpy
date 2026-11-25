# Issue 303 phase timeline (as-you-go provenance)

Post-merge appendix to `run-log.md`. The original `run-log.md`
was batched at bc6b9b8 (2026-11-25 04:29:52) before merge
fac9826. This appendix was built **incrementally in this
follow-up run**, one commit per diagnosing-bugs phase, in
phase order. Each phase section below was written immediately
after that phase's evidence command and before the next phase
started. Original evidence commands and outputs are quoted
from the already-committed artifacts, not re-asserted.

## Phase 1: feedback loop (logged first)

Evidence (`loop-before.log`, `loop-after.log` at fac9826):

```text
depth=10 status=2 findings=3 callees_calls=2073 bound=220 verdict=FAIL-RED
AssertionError: exponential witness traversal exceeds linear bound
depth=10 status=2 findings=3 callees_calls=26 bound=220 verdict=PASS
depth=12 status=2 findings=3 callees_calls=30 bound=260 verdict=PASS
depth=18 status=2 findings=3 callees_calls=42 bound=380 verdict=PASS
OK: linear witness search
```

Loop (`issue303_loop.py`) counted `CallGraph.callees` calls on
the issue's layered diamond via the real CLI seam, asserted
3 findings and `callees <= 20*(D+1)`. Red at 2073, green at
26–42. Deterministic, ~0.27 s. This is the tight red-capable
signal every later phase depends on.

## Phase 2: reproduce + minimise (logged second)

Evidence (`loop-minimise.log`, `loop-before-repeat.log`):

```text
depth=6 callees_calls=145 bound=140 FAIL-RED
depth=7 callees_calls=275 bound=160 FAIL-RED
depth=10 callees_calls=2073 bound=220 FAIL-RED
depth=12 callees_calls=8221 bound=260 FAIL-RED
depth=18 callees_calls=524329 bound=380 FAIL-RED
```

Repeat depth-10 reproduced 2073 identically. Two branches
per layer, reconvergence, later action, and a caller of the
mixed function are each load-bearing. Logged here before any
Phase 3 hypothesis was tested.

## Phase 3: hypotheses (logged third, before probes)

Ranked hypotheses (falsifiable predictions):

1. Search enters callees outside `actions` → pruning them
   removes pure-diamond visits.
2. Action-reachable reconvergence revisited per search →
   per-search visited set bounds at O(V+E) preserving first DFS.
3. Copying `active | {…}` amplifies → removing copies alone
   does not fix exponential.
4. Independent search per site → total remains O(F·(V+E)+L).

Skipped sub-step justification: bisection (no behavioural
range; Phase 4 baseline replaces it) and AFK checkpoint.
Logged before any Phase 4 probe.

## Phase 4: instrument (logged fourth)

Evidence (`profile-before.log`/`profile-after.log`):
pre-fix 8194 `phrase` calls / 8221 `callees` calls at depth
12 (~2^(D+1)); post-fix `phrase` no longer dominates,
loop counts 26/30/42. No `[DEBUG-...]` logs (perf counts
replace logs). Inspection confirmed hypotheses 1+3
(`actions` unused for DFS expansion, `active | {…}` copy),
and 4 (independent searches). Logged before any fix claim.

## Phase 5: fix + regression test (logged fifth)

Evidence (`regression-red.log`/`regression-after.log`):
production reverted to origin/main → FAIL `2073 not <= 220`;
fix restored → 2 tests OK (work-count + cycle-order).
Fix: iterative ordered DFS, skip non-`actions`, visit once,
first-DFS witness, O(F·(V+E)+L). Only `mock.patch` seam kept;
#321 policy/docs adopted. Logged with the red proof, before
Phase 6 verification.
