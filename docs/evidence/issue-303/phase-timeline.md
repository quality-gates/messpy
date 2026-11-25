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
