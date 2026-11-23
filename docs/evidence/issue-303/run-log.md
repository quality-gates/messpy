# Issue 303 run log

Issue: https://github.com/quality-gates/messpy/issues/303. Work began from acb4ac1. Issue initially open, unassigned. Two existing open PRs #318 and #321 were discovered; #318 uses this worktree branch.

## Environment

No project lockfile or virtualenv existed in this checkout. Generated a workspace-local lock with `uv lock`, created a workspace-local seeded managed Python 3.12 venv using `uv venv --python 3.12 --seed --python-preference only-managed .venv`, then used `uv sync --frozen --python 3.12 --managed-python`. Outputs are recorded alongside this log. TMPDIR was supplied by fleet and used for the temporary loop. No other checkout's dependencies were modified.

## Phase 1: feedback loop

` .venv/bin/python "$TMPDIR/issue303_loop.py" 10` (without leading space) drives the real onion acceptance seam on the issue's generated diamond, profiles calls to `_ActionPath.phrase`, asserts the three findings, and bounds calls at 20 per layer. Before fix: `depth=10 status=2 findings=3 phrase_calls=2050 bound=200`, AssertionError `exponential witness traversal`. It runs unattended in under a second; counts are deterministic. The profiling seam is temporary and later verification uses a graph-lookup regression that also works after implementation changes.

## Phase 2: reproduce and minimise

Repeated depths 4, 5, 8, 10 yielded 34, 66, 514, 2050 calls respectively, with 3 findings each. A repeated depth 10 produced 2050 again. Two alternatives per layer, reconvergence, a later action, and a caller of that mixed function exercise the reported failed-path search. The threshold crosses at depth 7; smaller depths retain the pattern but cannot exceed this deliberately linear bound. Removing either branch removes the exponential pattern; removing the later action or caller removes the affected spread search. The loop keeps the issue's workload; no timing threshold is used.

## Phase 3: hypotheses before probes

1. Search enters callees outside the precomputed action-reachable set. Prediction: pruning them eliminates growth on the pure diamond.
2. Cyclic, action-reachable reconverging branches are revisited in the same search. Prediction: per-search visited nodes bound work while preserving first DFS witness.
3. Path-local set copying amplifies the cost. Prediction: removing copies lowers overhead but does not alone eliminate repeated traversals.
4. Each finding starts an independent search. Prediction: graph work can still scale with the number of findings even after individual searches are bounded.

## Phase 4: probe and measurement

The profiler in the feedback loop measures the actual search boundary. The 4/5/8/10-layer counts (34/66/514/2050) follow approximately 2^(D+1), while the generated graph grows linearly. Inspection of the measured path shows the propagation set is only consulted for initial sites, confirming hypothesis 1; each recursive edge copies the active set, supporting hypothesis 3 as an amplifier. Searches are independently started per qualifying site, confirming hypothesis 4 and limiting the general complexity claim. Hypothesis 2 is addressed by a cycle regression; each search must preserve the original depth-first ordering. Bisection is not useful here: the issue identifies the responsible implementation and the work-count probe directly distinguishes the cause; no behavioral regression range is claimed.

## Phase 5: regression first

Reusing the focused tests and fix from existing PR #318 on this branch, replayed on the current default tip rather than reverting intervening changes. The graph-lookup test counts actual `CallGraph.callees` calls at the onion acceptance seam and asserts the output. The cycle test checks first-witness ordering. Red and green results follow.

Before fix: `python -m unittest discover -s tests -p test_onion.py -k reconverging_pure_calls` failed: 2073 lookups > 220. After applying PR #318's change: all 62 onion tests passed, including the cycle and work-count regressions. The original loop returns 3 findings with 2 phrase calls at depths 10 and 18. The new iterative ordered DFS visits each reachable node at most once per search, skips pure branches, avoids recursive stack growth, and retains first DFS witness; independent searches cost O(F × (V + E) + L), assuming constant-time hashing and bounded names. For the issue's fixed number of findings this is O(V + E + L); no linear bound across arbitrary numbers of findings is claimed.

## Phase 6: cleanup and verification

- Original loop and regression: green, as above. No tagged debug instrumentation in source or tests.
- Python 3.12.12: full unittest discovery passed 521 tests, 2 skipped; the onion suite passed 62. `check_accumulator_copies.py`, `generate_rule_docs.py --check`, and installed-command self-analysis passed.
- State-machine parity: doctor produced `0.1.24` and `commit`; baseline 3448957 matched across 551 samples and 19 CLI cases. Negative control detected its injected cursor fault. The changed M31 transition was reviewed; the cycle ordering test covers the relevant boundary.
- Ruleset precedence: no differences from a5b7ca4 in the skill's listed paths. All 15 single and 225 ordered XML policies, CLI and partial overrides passed; CrossHair 0.0.110 confirmed all four contracts. To honor frozen installs, its separate temporary workspace-local project had a generated lock and `uv sync --frozen`, rather than using the skill's unlocked `uv run --with` command.
- Diagnostics: the first wrapper around ruleset verification printed `zsh: read-only variable: status` after the verifier ran, because `status` is reserved by zsh. Output already reported all contracts passed, but the wrapper returned 1; reran with `result` and verified exit 0. An initial `import crosshair` in the project venv reported `ModuleNotFoundError`; the locked separate verifier environment resolved this. These were setup/wrapper failures, not test failures.
- Temporary scripts, the separate verifier environment, generated local lockfile and project venv are run artifacts to be removed after shipping; the fleet-provided TMPDIR holds command output. No source debug probes were added.
