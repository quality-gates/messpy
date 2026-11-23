# Issue 304 run log — class dependency analysis rescans class body

This log records the AFK run for
<https://github.com/quality-gates/messpy/issues/304>, following
`/diagnosing-bugs` in order. No phase was skipped. The code
fix is the pre-existing open PR #317
(`fleet/worktree-messpy-304`, originally `d3a61e9`); this run
adopted it, rebased it onto the then-current `origin/main`
(`79e6eed`, new head `5c62eab`), re-verified it, and shipped
it. Phase 3's user checkpoint was not blocked on: the run is
AFK, so the ranked hypotheses below were proceeded with as
written.

## Environment: locked install

The worktree had no `uv.lock` and no `.venv`. The project has
no third-party runtime dependencies, and its lockfile is
untracked local state, so the lock was generated inside the
workspace, exactly as in the issue 302 run:

```sh
uv lock                       # Resolved 2 packages
uv venv --python 3.12 --seed --python-preference only-managed .venv
uv sync --frozen --python 3.12 --managed-python
```

The frozen sync installed `messpy==0.1.24` editable into the
seeded Python 3.12.12 venv (pip 26.3 retained for the
distribution tests, per `AGENTS.md`). See `uv-lock.log`,
`uv-venv.log`, and `uv-sync-frozen.log`. Dependencies and
build outputs stayed in this workspace; throwaway scripts
lived in `$TMPDIR`. No symlink into another checkout was
used.

## Phase 1: feedback loop

Two deterministic counters, both agent-runnable in seconds.

Loop 1 (from the issue): build a flat class of M methods
(`def mI(self): return os.sep`), wrap the class body in a
counting list, call `Names.imported` once per method, and
assert body visits <= 4*M. Red-capable: linear predicts
<= 4*M visits; the bug predicts M*(M+1)/2.

Before the fix (`loop-before.log`): M=100/200/400 visits were
5050/20100/80200, exactly M*(M+1)/2, and the loop asserted
`FAIL-RED`. Isolated lookup was 0.001/0.004/0.015 s on this
machine.

Loop 2 (end-to-end, from the PR's scaling test): run
`measure_class_dependencies` on a flat class of M methods
returning distinct `external.ItemI`, counting class-body
visits and distinct local-name-set entries traced in
`_dependency_state`. Before the fix (`loop2-before.log`):
M=40 gave 860 visits and 1721 set entries; M=80 gave 3320
and 6641 — both quadratic, matching the PR description.

## Phase 2: reproduce + minimise

Reproduced on the smallest shape in the issue: one flat
class, constant-sized methods, one imported attribute
reference per method, bounded depth. No decorators, bases,
annotations, nesting, or calls are needed; M methods in one
class and Q=M references are load-bearing. Removing the
method count collapses the counter to the linear case.

## Phase 3: hypotheses (ranked)

1. `Names._in_body` linearly scans the class body for every
   imported reference, calling `_contains` per entry.
   Prediction: counting body entries yields M*(M+1)/2, and
   pre-indexing body membership makes it O(1) per lookup.
2. `_dependency_function` builds `local_names | scope_names`
   per method, where `local_names` holds all M method names.
   Prediction: distinct set entries are Theta(M^2) even if
   hypothesis 1 alone is fixed; sharing class/method layers
   linearises it.
3. `_with_dependency` copies the growing dependency set
   (`{*dependencies, dependency}`) per reference.
   Prediction: with D distinct dependencies the copy cost is
   Theta(D^2) (and Theta(Q) copies even for one repeated
   dependency in the issue's `os.sep` shape); linking entries
   and collecting once linearises it.
4. `_scopes_for_node` copies the scope list per parent step
   (`[*scopes, parent]`) and `_function_covers` walks
   ancestors. Prediction: bounded by AST depth H, not by M,
   so minor for the flat workload and unchanged by the fix.
5. `Names.build` scope/record construction rescans the tree.
   Prediction: linear in AST size, paid once per module.

Hypotheses 1, 2, and 3 were correct and are all fixed by
PR #317. Hypotheses 4 and 5 remain, as expected, at
O(H) per lookup and O(AST) per build.

## Phase 4: instrument

No `[DEBUG-...]` logs were added. `cProfile` on
`measure_class_dependencies` at M=400 (`profile-before.log`):
670204 calls in 0.071 s, with `_in_body` 800 calls,
`_contains` 80200 calls, and `_scopes_for_node` 0.051 s
cumulative — the body scan dominates, confirming
hypothesis 1. After the fix (`profile-after.log`): 108004
calls in 0.020 s, `_in_body` gone, no function above
0.020 s cumulative.

## Phase 5: fix + regression test

The correct seam exists (`Names.qualified`/`imported` and
`measure_class_dependencies`, plus the CLI coupling rule),
and PR #317 adds regressions there:

- `test_dependencies.DependencyScalingTests` counts body
  visits and distinct local-name-set entries for 40 methods
  and asserts both <= 4*40, and asserts the dependency set.
- `test_syntax.SyntaxResolutionTests.
  test_class_body_headers_and_nested_functions_keep_their_scopes`
  guards class-body assignments, decorators, defaults,
  nested functions, and shadowing.

Red/green check in this run: with the new tests in place and
the production files reverted to `origin/main`,
`regression-tests-before-fix.log` shows the scaling test
FAIL (`1721 not less than or equal to 160`) while the
semantics test passes. With the fix restored,
`regression-tests-after-fix.log` shows both OK, and
`loop-after.log` / `loop2-after.log` show 0 body visits for
direct lookup and 40 visits / 81 set entries for M=40 in
`measure_class_dependencies`.

Correctness beyond the new tests: a differential dump over
`src/` (every `Name`/`Attribute` qualified/imported result
and every class's dependency set, excluding the two changed
files themselves) is byte-identical before and after
(SHA-256 `3de6ebc8…15015`, `differential-before.log` /
`differential-after.log`), as is a 12-snippet dump covering
bases, metaclasses, decorators, defaults, annotations,
lambdas, async, nested functions/classes, comprehensions,
and shadowing (`tricky-before.log` / `tricky-after.log`).
Failure diagnostic preserved: the first differential harness
crashed on `Assign.target` and then differed only because
the fix adds the `_Dependency` class to the dump; both were
harness bugs, fixed in the throwaway script, and the
corrected harness is what produced the identical hashes.

Semantics note recorded for the next reader: the fix's
`_body_nodes` set is a global body-membership index, which
is sound because `_with_parent_scope` is only called with
`node` as the direct AST child of `parent` (a node has one
parent in a parsed tree), and the lambda case is included
via `_statements`. The dependency fix replaces the copied
union with shared tuple layers and the copied set with a
linked `_Dependency` chain collected once.

## Phase 6: verification (on the rebased candidate, locked install)

- `uv sync --frozen` install: pass (`uv-sync-final.log`).
- `python -m unittest discover -s tests`: 519 tests, OK
  (2 expected Atheris skips). See `tests.log`.
- `verify_self_analysis.py`: exit 0. See `self-analysis.log`.
- `check_accumulator_copies.py`: exit 0. See `accumulator.log`.
- `generate_rule_docs.py --check`: exit 0. See `docs.log`.
- `verify_state_machine_parity.py`: exit 0, public behavior
  matches the recorded baseline on 548 samples and 19 CLI
  cases. See `state-parity.log`.
- Scaling after: loop 1 visits 0 at M=100/200/400; loop 2
  M=40/80 visits 40/80 with 81/161 set entries; profile
  0.071 s -> 0.020 s at M=400 with 670k -> 108k calls.
- Issue #304 re-read before merging: open, no assignee
  (checked at adoption and again before the merge below).

## Cleanup

- No `[DEBUG-...]` instrumentation was added.
- Throwaway loop/profile/dump scripts lived in `$TMPDIR`,
  not the repo.
- Scratch, `uv.lock`, and `.venv` live in this workspace;
  the worktree is removed after the PR lands.
