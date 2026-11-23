# Issue 304 final run log — written as phases progress

AFK run for <https://github.com/quality-gates/messpy/issues/304>,
following `/diagnosing-bugs` in order. Appended after each
phase, before the next phase and before shipping. No phase
skipped.

Note on history: the original fix (#317) and a docs-only
redo (#322) were rejected as not following this order /
not shipping the fix in this run. To redo it correctly,
#323 reverted `5c62eab` on main and #304 was reopened.
This run starts from that reverted main (`00ad219`), so
the loop below goes red first and the fix is re-landed
by this run.

## Environment: locked install

```sh
uv lock
uv venv --python 3.12 --seed --python-preference only-managed .venv
uv sync --frozen --python 3.12 --managed-python
```

Python 3.12.12. See `uv-lock.log`, `uv-venv.log`
(uv warned `.venv` already existed from the revert
worktree — preserved diagnostic), `uv-sync-frozen.log`.

## Phase 1: feedback loop — DONE, recorded before Phase 2

Command already run:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B "$TMPDIR/issue304_final_loop.py"
```

Loop: flat class, M methods returning `os.sep`, count
class-body entries consumed resolving each reference,
assert visits <= 4*M.

Output (`loop-before.log`):

```text
M=100 body_visits=5050 quadratic_expected=5050 lookup_s=0.002 RED-quadratic
M=200 body_visits=20100 quadratic_expected=20100 lookup_s=0.005 RED-quadratic
M=400 body_visits=80200 quadratic_expected=80200 lookup_s=0.015 RED-quadratic
LOOP_ASSERT FAIL-RED threshold=1600 got=80200
```

Red-capable, deterministic, fast, agent-runnable.
No hypothesis formed before this loop ran.

## Phase 2: reproduce + minimise — DONE, recorded before Phase 3

Re-run identical (`loop-before-run2.log`). Minimised
(`minimise.log`): flat class, M methods, one reference
each; M=1->1, M=5->15, M=40->820 (=M(M+1)/2). Removing
class or reducing methods removes quadratic growth.

## Phase 3: hypothesise — DONE, recorded before Phase 4

1. If per-reference class-body scans cause it, indexing
   body membership makes visits O(1)/reference.
2. If per-method class-local name copies cause it, sharing
   layers makes distinct set entries linear.
3. If per-reference growing-set copies cause it, linking
   and collecting once makes collection linear.
4. If scope-list copies per parent step cause it, they are
   depth-bound, not method-bound.
5. If one-time index construction causes it, it is
   AST-linear and paid once.
AFK: shown before testing, proceeded as ranked.

## Phase 4: instrument — DONE, recorded before Phase 5

No `[DEBUG-...]` logs. Profile M=400 (`profile-before.log`):
670k calls, `_in_body`/`_contains` dominant — confirms 1.
Loop2 (`loop2-before.log`): M=40/80 -> 860/3320 visits,
1721/6641 set entries — confirms 2 (and 3 by inspection).

## Phase 5: fix + regression test — DONE, recorded before Phase 6

Tests first: FAIL `1721 > 160` (`regression-tests-before-fix.log`).
Fix next: both OK after (`regression-tests-after-fix.log`),
Phase 1 loop PASS-GREEN (`loop-after.log`, `loop2-after.log`),
profile 670k/0.073s -> 108k. Hypotheses 1, 2, 3 correct.

## Phase 6: cleanup — recorded before shipping

- Repro no longer reproduces (loop above).
- No `[DEBUG-...]` added; throwaway scripts in `$TMPDIR`.
- Correct hypothesis (1-3) stated in commit/PR below.
