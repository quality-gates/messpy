# Issue 303 run log — DomainAction expands exponentially many call paths

This log records the AFK run for
<https://github.com/quality-gates/messpy/issues/303>, following
`/diagnosing-bugs` in order. No phase was skipped; skipped
*sub-steps* carry an explicit justification below. The code fix
is PR #318 (`fleet/worktree-messpy-303`, head `b9c8a3a` plus the
commits on top of it in this run); duplicate PR #321 was not
adopted — see Phase 5 for what was taken from it and why. The
Phase 3 user checkpoint was not blocked on: the run is AFK, so
the ranked hypotheses below were proceeded with as written.

## Environment: locked install

The worktree had no `uv.lock` and no `.venv`. The project has
no third-party runtime dependencies; the lockfile is untracked
local state (`uv.lock` is not committed). The lock was
generated inside the workspace:

```sh
uv lock
uv venv --python 3.12 --seed --python-preference only-managed .venv
uv sync --frozen --python 3.12 --managed-python
```

The frozen sync installed `messpy==0.1.24` into the seeded
Python 3.12.12 venv (pip 26.3 retained for the distribution
tests, per `AGENTS.md`). See `uv-lock.log`, `uv-venv.log`,
`uv-sync.log`. Dependencies and build outputs stayed in this
workspace; throwaway scripts lived in `$TMPDIR`. No symlink
into another checkout was used.

## Phase 1: feedback loop

One deterministic counter, agent-runnable in seconds.

Loop (`$TMPDIR/issue303_loop.py`, copied output in
`loop-before.log`, `loop-after.log`): build the issue's
layered diamond — D layers of two pure functions each selecting
between the two functions at the preceding layer, a later
`action()` that prints, `top()` that first calls the pure
diamond then the action, and `start()` that calls `top()` —
run the real CLI seam via `_analyze_source` (same helper the
onion acceptance tests use), count `CallGraph.callees` calls
with a `mock.patch.object` wrapper, assert the three findings
(status 2, no errors, last line
`calls top(), which calls action(), which writes the implicit
output print`), and assert `callees_calls <= 20 * (D + 1)`.

Red-capable: linear predicts <= 20*(D+1) lookups; the bug
predicts Theta(2^D). Deterministic: same verdict on repeated
runs (`loop-before-repeat.log` repeats depth 10 at 2073
lookups). Fast: ~0.27 s at depth 10. Before the fix:
`depth=10 status=2 findings=3 callees_calls=2073 bound=220
verdict=FAIL-RED` (exit 1). After the fix: depth 10/12/18 give
26/30/42 lookups, all `PASS` (exit 0).

## Phase 2: reproduce + minimise

`loop-minimise.log` (pre-fix): depths 6/7/10/12/18 give
145/275/2073/8221/524329 lookups — each layer roughly doubles,
while the graph grows linearly. Depths 4/5 (45/79 lookups)
still show the pattern but sit below the deliberate 20-per-layer
bound; the bound crosses at depth 6. Removing either branch
per layer removes reconvergence and the exponential pattern;
removing the later action or the `top()` caller removes the
affected spread search. Every remaining element — two branches
per layer, reconverging previous-layer calls, a later action
after the pure branches, and a caller of the mixed function —
is load-bearing. No timing threshold is used; the counter is
the signal.

## Phase 3: hypotheses (ranked, before probes)

1. Search enters callees outside the precomputed
   action-reachable set. Prediction: pruning callees not in
   `actions` eliminates the pure-diamond visits.
2. Action-reachable reconverging branches are revisited in the
   same search (only a path-local `active` set, no per-search
   visited set). Prediction: a per-search visited set bounds
   work at O(V + E) while preserving the first DFS witness.
3. Path-local set copying (`self.active | {id(callee)}`)
   amplifies the cost. Prediction: removing copies lowers the
   per-node overhead but does not alone eliminate repeated
   traversals.
4. Each qualifying call site starts an independent search.
   Prediction: total graph work can still scale with the
   number of findings F even after individual searches are
   bounded, i.e. O(F * (V + E) + L).

Hypotheses 1–3 are fixed by the candidate; hypothesis 4 is
retained as the documented broader limit (constant F for the
specified workload). Bisection was skipped with justification:
there is no behavioural regression range here — the issue
pinpoints the responsible implementation at a known commit and
the work-count probe directly distinguishes the cause, so a
bisection harness would measure nothing extra. The baseline
measurement in Phase 4 replaces it.

## Phase 4: instrument

No `[DEBUG-...]` logs were added; profiling counts replace
logs for this perf bug. `cProfile` at depth 12 before the fix
(`profile-before.log`): 8194 calls to `_ActionPath.phrase` and
8221 `callees` calls, following ~2^(D+1). Code inspection
matches: `_spread_findings` computes `actions` but uses it
only to filter initial sites, then `_ActionPath.phrase`
recursive-DFSes *all* outgoing edges, copying the path-local
`active` set per edge and memoising no failed node — confirming
hypotheses 1 and 3. Each `phrase` call is independent per
qualifying site — confirming hypothesis 4. After the fix
(`profile-after.log`), `phrase` no longer dominates; the
loop's counts are 26/30/42 at depths 10/12/18.

## Phase 5: fix + regression test

The correct seam exists (the onion CLI acceptance seam, which
drives `onion_findings` through the real `cli.run`), and the
candidate adds two regressions there:

- `test_reconverging_pure_calls_do_not_expand_witness_search`
  counts `CallGraph.callees` calls on the depth-10 diamond and
  asserts <= 20*(depth+1), plus the three findings and the
  expected witness. Red/green in this run:
  `regression-red.log` (production reverted to `origin/main`)
  shows `2073 not less than or equal to 220` FAIL; with the
  fix restored, `regression-after.log` shows both new tests OK.
- `test_cycle_prefers_first_reachable_action_in_call_order`
  checks a cyclic graph (`left`/`right` calling each other and
  the actions `first`/`second`) prefers the first action in
  call order:
  `calls left(), which calls right(), which calls second()…`.

The fix replaces the recursive, copying DFS with an iterative
ordered DFS that (a) skips callees not in the precomputed
`actions` set, (b) visits each callable at most once per
search, and (c) renders the first witness in call-site order.
It removes the `@dataclass(frozen=True) active` accumulator;
per `AGENTS.md`, changing an owner requires reviewing its
collection costs — the new `seen`/`stack`/`names` collections
are updated in place, and `scripts/check_accumulator_copies.py`
now forbids copying them (`seen | {…}`, `stack + […]`,
`[*names, …]` in `_ActionPath.phrase`, with a failing example
in `tests/test_accumulator_copies.py`, as in duplicate PR
#321). `docs/state-machines.md` M31 now describes visiting
each callable at most once per explanation and states the
bound: each search is O(V + E + L) for callable vertices V,
call edges E, and rendered witness length L; searches run
separately for F qualifying call sites, so the overall bound
is O(F * (V + E) + L_total), assuming constant-time hashing.
The layered pure-branch case has a constant number of
qualifying sites, hence O(V + E + L); no linear bound across
arbitrary numbers of findings is claimed. Duplicate PR #321
carried the same production change with a different test seam
(`sys.getprofile` counting) and a failing macOS check; only
its accumulator-policy and M31 documentation changes were
adopted here, keeping #318's `mock.patch.object` test seam,
which passes on all CI platforms.

Correctness beyond the new tests: the full onion suite (62
tests) passes, including the pre-existing cyclic cases
(`test_recursion_terminates_without_duplicate_findings`,
which exercises self-recursion and a two-function cycle), and
the parity differential below matches the baseline. A node
that is action-reachable always has a continuation to an
action, so visiting it once suffices; the rendered witness is
the first DFS encounter in call-site order, satisfying the
issue's "preserve or deliberately specify ordering" — the
ordering is specified here as first-DFS-in-call-site-order.

## Phase 6: cleanup and verification

- Original loop and regressions: green, as above
  (`loop-after.log`, `loop-after-10.log`,
  `regression-after.log`).
- No `[DEBUG-...]` instrumentation: `grep -r "DEBUG-" src/
  tests/ scripts/` is empty. Throwaway loop/profile scripts
  live in `$TMPDIR`, not the repo. The production change
  removes the `@dataclass(frozen=True)` import use in
  `onion.py` (`dataclass` is still used by `_ActionPropagation`
  and `_finding` helpers — no unused import introduced; self-
  analysis confirms).
- Python 3.12.12, locked install: `tests.log` shows
  `python -m unittest discover -s tests`: 521 tests, OK
  (2 expected Atheris skips). Onion suite: 62 tests OK.
- `check_accumulator_copies.py`: exit 0 (`accumulator.log`).
- `generate_rule_docs.py --check`: exit 0 (`docs.log`).
- `verify_self_analysis.py .venv/bin/messpy`: exit 0
  (`self-analysis.log` — empty output means clean).
- State-machine parity (M31 changed):
  `PYTHONPATH=src … --version` prints `0.1.24`, exit 0;
  `git cat-file -t 3448957` prints `commit`.
  `verify_state_machine_parity.py`: `state-parity.log` —
  "Public behavior matches 3448957 on 552 source samples and
  19 CLI cases", exit 0. `--negative-control` detects its
  injected cursor fault (`state-parity-negative.log`), exit 0.
- Ruleset precedence: `git diff a5b7ca4 -- src/messpy/
  rulesets.py src/messpy/cli.py src/messpy/analyzer.py docs/
  usage.md tests/test_cli.py tests/test_rulesets.py` produces
  zero lines — no listed path changed, so the recorded sync
  commit still describes the code and the crosshair/XML
  verifier was not re-run; this is the justified skip. The
  command and its empty output were re-checked in this run.
- Issue #303 re-read before merging: open, no assignee
  (checked at adoption and again before the merge below).
- `uv.lock` and `.venv` remain untracked workspace-local
  artifacts; they are not committed. The worktree is removed
  after the PR lands.
