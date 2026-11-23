# Issue 304 redo run log — written as phases progress

AFK run for <https://github.com/quality-gates/messpy/issues/304>,
following `/diagnosing-bugs` in order. This log is appended
after each phase, before the next phase and before shipping.
No phase is skipped; if one were, the justification would be
recorded here at that point.

Redo note: the original fix for #304 already merged as
PR #317 (`444d873`). This redo starts from the pre-fix base
`79e6eed` so the loop can go red in order, then re-verifies
that fix. See Phase 5/6 for how it is shipped.

## Environment: locked install

```sh
uv lock
uv venv --python 3.12 --seed --python-preference only-managed .venv
uv sync --frozen --python 3.12 --managed-python
```

Python 3.12.12, `messpy==0.1.24` editable. See
`uv-lock.log`, `uv-venv.log`, `uv-sync-frozen.log`.
Dependencies stay in this workspace; throwaway scripts in
`$TMPDIR`.

## Phase 1: feedback loop — DONE, recorded before Phase 2

Loop command (already run at least once):

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B "$TMPDIR/issue304_redo_loop.py"
```

The loop builds flat classes with M constant-sized methods
each returning `os.sep`, counts class-body entries consumed
while resolving each method reference via `Names.imported`,
and asserts visits <= 4*M (linear) versus M*(M+1)/2
(quadratic).

Output (`loop-before.log`):

```text
M=100 body_visits=5050 quadratic_expected=5050 lookup_s=0.001 RED-quadratic
M=200 body_visits=20100 quadratic_expected=20100 lookup_s=0.004 RED-quadratic
M=400 body_visits=80200 quadratic_expected=80200 lookup_s=0.015 RED-quadratic
LOOP_ASSERT FAIL-RED threshold=1600 got=80200
```

Criteria: red-capable (drives the reported code path and
asserts the reported quadratic symptom), deterministic
(exact counts), fast (<1 s), agent-runnable.
No hypothesis or code theory was formed before this loop
ran.

## Phase 2: reproduce + minimise — DONE, recorded before Phase 3

Re-ran the Phase 1 loop (`loop-before-run2.log`): identical
exact counts, `FAIL-RED`. Symptom matches the issue:
quadratic in method count for a flat class.

Minimise (`minimise.log`): smallest red scenario is one flat
class, M constant-sized methods, one imported attribute
reference per method, no decorators/bases/annotations/
nesting/calls. M=40 gives 820 = 40*41/2; M=5 gives 15;
M=1 gives 1. Removing the class or reducing to one method
removes the quadratic growth, so flat class + M methods +
one reference per method are load-bearing. Every remaining
element is load-bearing.

## Phase 3: hypothesise — DONE, recorded before Phase 4 testing

Ranked, each falsifiable ("If X, then changing Y…"):

1. If per-reference class-body scans in name resolution are
   the cause, then indexing direct body membership will
   make body visits per reference O(1) and the Phase 1
   counter linear.
2. If per-method copies of all class-local names in
   dependency extraction are a cause, then sharing class
   and method name layers will make distinct local-set
   entries linear, even with hypothesis 1 fixed alone.
3. If per-reference copies of the growing dependency set
   are a cause, then linking entries and collecting once
   will make dependency collection linear in references.
4. If scope-list copies per parent step are the main
   cause, then they would be bounded by AST depth, not
   method count, and fixing 1–3 would leave them minor.
5. If one-time name-index construction is the main cause,
   then it would be linear in AST size and paid once per
   module, not per reference.

AFK note: shown above / in transcript before testing; no
block on user re-ranking.

## Phase 4: instrument — DONE, recorded before Phase 5

No `[DEBUG-...]` logs added. Profile M=400
(`profile-before.log`): 670204 calls, 0.070 s;
`_in_body` 800 calls / 0.049 s cumulative, `_contains`
80200 calls — confirms hypothesis 1 dominates.
End-to-end counter (`loop2-before.log`): M=40/80 gives
860/3320 body visits and 1721/6641 distinct local-set
entries — confirms hypothesis 2 (and, by code inspection
after Phase 3, hypothesis 3's growing-set copy). Hypotheses
4–5 are bounded/one-time as predicted.

## Phase 5: fix + regression test — DONE, recorded before Phase 6

Correct seam: `Names.imported`/`qualified` and
`measure_class_dependencies`. Regression tests were applied
first, before the production fix: scaling test FAIL
(`1721 not less than or equal to 160`,
`regression-tests-before-fix.log`), semantics test OK.
Fix applied next (indexed body membership; shared name
layers; linked dependency collection). Both tests OK after
(`regression-tests-after-fix.log`). Phase 1 loop re-run on
original scenario: PASS-GREEN (`loop-after.log`,
`loop2-after.log`); profile 670k/0.070s -> 108k/0.019s
(`profile-after.log`). Hypotheses 1, 2 and 3 were correct.

## Phase 6: cleanup — recorded before shipping

- Original repro no longer reproduces: Phase 1 loop PASS-GREEN above.
- Regression tests pass (above); full suite in shipping verification below.
- No `[DEBUG-...]` instrumentation added (grep checked before shipping).
- Throwaway scripts in `$TMPDIR`, not the repo.
