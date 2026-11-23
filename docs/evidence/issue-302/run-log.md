# Issue 302 run log — call-graph indexing copies growing scope maps

This log records the AFK run for
<https://github.com/quality-gates/messpy/issues/302>, following
`/diagnosing-bugs` in order. The code fix shipped as PR #316
(merge commit `bb8db6b` on `origin/main`); this evidence ships
afterwards because the first run's log capture failed (below).

## Environment: locked install

The worktree had no `uv.lock` and no `.venv`. The project has no
third-party runtime dependencies, and its lockfile is untracked
local state, so the lock was generated inside the workspace:

```sh
uv lock                       # Resolved 2 packages; byte-identical to the host copy
uv venv --python 3.12 --seed --python-preference only-managed .venv
uv sync --frozen --python 3.12 --managed-python
```

The frozen sync installed `messpy==0.1.24` editable into the
seeded Python 3.12.12 venv (pip 26.3 retained for the
distribution tests, per `AGENTS.md`). See `uv-sync-frozen.log`.

Failure diagnostics preserved:

- An earlier run in this session used
  `uv pip install --python .venv/bin/python -e .` with no frozen
  or locked flag. That did **not** satisfy the locked-install
  policy and was redone as above.
- `uv sync --seed` is not a valid flag
  (`error: unexpected argument '--seed'`; see
  `uv-sync-seed-failure.log`). Seeding is done by the separate
  `uv venv --seed` step, exactly as `AGENTS.md` prescribes.
- An earlier evidence capture failed with
  `tee: docs/evidence/issue-302/adopted-tests.log: No such file
  or directory` because the evidence directory did not exist yet.
  This run creates it before teeing.

## Phase 1: feedback loop

Loop: build flat modules of F no-call functions
(`def fN(): return N`), assert `len(graph.callables) == F`, and
time `build_call_graph` (best of 3). Red-capable: linear scaling
predicts ~8× time for 8× input; the bug predicts ~64×.

Before the fix (from the first run of this session): index-only
800=17.6ms, 1600=44.6ms, 3200=130.2ms, 6400=428.0ms — 24.3× time
for 8× input. Full build at 3200 was ~675ms.

## Phase 2: reproduce + minimise

Reproduced on the smallest shape in the issue: flat, no-call,
no-nesting modules. No calls, classes, or nesting are needed;
F top-level defs in one module are load-bearing.

## Phase 3: hypotheses (ranked)

1. `{**state.nodes, ...}` / `{**state.labels, ...}` per function
   copy O(F) entries each. Prediction: removing them linearises
   index time.
2. `dict(state.bindings.get(scope_id))` per bind copies the whole
   module scope. Prediction: same, for the inner scope map.
3. Outer-map copies per transition are O(#scopes/#classes).
   Prediction: minor for flat input, quadratic for many scopes.
4. `_rebound_globals` walks each scope once. Prediction: linear.
5. `annotations_are_deferred(module)` rescans `tree.body` per
   callable on Python 3.12. Prediction: full-build timing stays
   superlinear until this is hoisted/cached too.

Hypotheses 1, 2 and 5 were correct.

## Phase 4: instrument

`cProfile` on F=3200: `_index_callables` 131ms vs 17ms at F=800
(7.8× for 4×); `Names.build` scaled linearly. No debug logs were
added.

## Phase 5: fix + regression tests

An open PR #316 already implemented hypotheses 1–3 and 5
(shared per-build maps; one future-annotation scan per graph)
with deterministic scaling regressions, rebinding/shadowing
semantics tests, and accumulator-copy policy rules. This run
adopted it instead of shipping a duplicate: the branch was
rebased onto the then-current `origin/main`, re-verified, and
merged. A separate cons-chain implementation prepared in this
session was discarded in favour of the existing green PR.

## Phase 6: verification (on merged `origin/main`, locked install)

- `uv sync --frozen` install: pass (above).
- `python -m unittest discover -s tests`: 517 tests, OK
  (2 expected Atheris skips). See `tests.log`.
- `verify_self_analysis.py`: exit 0. See `self-analysis.log`.
- `check_accumulator_copies.py`: exit 0. See `accumulator.log`.
- `generate_rule_docs.py --check`: exit 0. See `docs.log`.
- Scaling after (`scaling-after.log`): 400=7.0ms, 800=14.3ms,
  1600=28.6ms, 3200=57.7ms — 8.2× time for 8× input.
- Old-vs-new call-graph dumps over `src/messpy` were
  byte-identical in the first run (SHA-256 recorded there).
- Issue #302 re-read before merging: open, no assignee.
  PR #316 CI green on the rebased head; merged as `bb8db6b`;
  issue closed by the PR's `Closes #302`.

## Cleanup

- No `[DEBUG-...]` instrumentation was added.
- Throwaway scale/dump scripts lived in `$TMPDIR`, not the repo.
- Scratch and venv live in this workspace's `.venv`; the
  worktree is removed after this evidence PR lands.
