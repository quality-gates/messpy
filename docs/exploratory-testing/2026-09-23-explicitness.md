# Exploratory testing: explicitness rulesets

**Date:** 2026-09-23

## Scope and setup

- Diff under test: `ca4d6bb` (Add explicitness and strictexplicitness rulesets) on `feature/explicitness-ruleset`, compared with `origin/main` `24d16af`.
- Build: editable `.venv/bin/messpy` 0.1.14, Python 3.12, macOS.
- Interface: the `messpy` CLI, which is the product.
- Scratch state: `/tmp/messpy-explore-2026-09-23` (journeys `j1/`–`j3/`, reproducers, replays) and `/tmp/messpy-lim` (limitation replays), removed after the pass. Replay steps are self-contained below and in the filed issues; the confirmed bugs are pinned by tests in `tests/test_explicitness.py`.
- Fix commits made during the pass: `d0ecff6`, `77e443c`, `6a5de14`.

## Journeys

| # | Goal | Ordinary path | Variation | Lasting effects | Result |
|---|---|---|---|---|---|
| J1 | Find implicit inputs and outputs in a realistic module (`j1/app/inventory.py`) | `explicitness`, text: 11 findings, all correct | Fixed `cached_lookup` (its 3 findings went away). Added a suppression directive above the `def` (no effect), then above the body line (works; `--strict` shows `suppressed: True`) | `--reportfile` JSON written and parsed | Explored |
| J2 | Enforce stricter class-state rules (`j2/shapes.py`) | `strictexplicitness`, text | `--disable`, `--only` (an unloaded rule gives exit 1 with "Unknown loaded rule"), case-insensitive names, custom XML with exclude and priority override, `--verbose`, formats sarif/github/checkstyle/gitlab/html/xml | Report files are valid | Explored. Found C1 |
| J3 | Survive unusual syntax without crashing or noise (`j3/edge.py`, stdlib) | Comprehensions, `del`, star-assign, nested global, for/with targets, conditional global, async | Whole 3.12 stdlib: 12.5 s under `strictexplicitness`, 26.5 s under `python`. stderr empty | n/a | Explored. Found C2 and C3 |

## Confirmed bugs (all fixed on the branch)

### C1: `__new__` changing class state is not an ImplicitInstanceOutput
- **Impact:** in `strictexplicitness`, a change to shared class state made in `__new__` goes unreported. The spec says "changing the class's data is classed as an implicit output".
- **Replay:** `messpy j3/c1.py text strictexplicitness`, where `c1.py` has `class Tracked: count = 0` and `def __new__(cls): cls.count += 1; return super().__new__(cls)`.
- **Expected:** both ImplicitInstanceInput and ImplicitInstanceOutput for `cls.count`. **Actual:** input only. Identical on 2 runs, and on the minimal `c1a.py` (`cls.count = 1`).
- **Root cause:** `__new__` was in `CONSTRUCTOR_METHOD_NAMES`, which makes `_implicit_instance_output_findings` return early. A `[DEBUG-c1]` probe confirmed the early return. Fixed in `d0ecff6`; the rule doc was regenerated.

### C2: data read by nested definitions at definition time was invisible
- **Impact:** false negatives. Python evaluates lambda and def defaults, def decorators, and class decorators, bases and keywords when the enclosing function runs, but ImplicitInput missed them.
- **Replay:** `messpy j3/c2.py text explicitness`, or single-construct files `c2a.py`…`c2e.py` (the control is `c2ctl.py`).
- **Expected:** ImplicitInput for `counter`/`registry` in each enclosing function. **Actual:** 0 findings, exit 0. Identical on 3 runs.
- **Root cause:** the shared `_ExecutableNodeCollector` returns early on every nested FunctionDef, AsyncFunctionDef, Lambda and ClassDef. A `[DEBUG-c23]` probe showed that `counter`/`registry` never reached any callable's node list.
- **Fix:** `6a5de14`. The explicitness rules now use `_EvaluatedNodeCollector`; the shared collector is unchanged.
- **Stdlib check:** 15 new findings, all genuine (`self.x` bound as a nested default), and 4 findings anchored to an earlier line. No new noise.

### C3: local variable annotations reported as implicit inputs
- **Impact:** false positives on ordinary typed code. `result: Vector = []` reported `Vector`, although Python does not evaluate local annotations. This was checked at runtime.
- **Replay:** `messpy j3/c3.py text explicitness`. The minimal case is `c3a.py` (`pending: settings`).
- **Expected:** no findings. **Actual:** ImplicitInput for `Vector` (line 6) and `settings` (line 7). Identical on 2 runs.
- **Root cause:** the collector descended into `AnnAssign.annotation`. The `[DEBUG-c23]` probe showed `settings` returning a finding. Fixed in `77e443c`; the target and value are still read.

## Rejected candidates

- **A suppression directive above `def summarise` did not waive the `print` finding.** Rejected: `docs/usage.md` states that a def-level directive covers the signature only. This is a usability note; see below.
- **j1 dropped from 11 findings to 7 at the final replay.** Rejected: J1's variation had edited the file (`cached_lookup` fixed, `print` suppressed).
- **j3 stderr showed 15 lines at the final replay.** Rejected as a driver artefact: zsh MULTIOS tees `2>&1 >/dev/null`. Redirecting to separate files shows stderr at 0 bytes.
- **`--minimumpriority 1` returned every finding.** Rejected: this is existing behaviour and not part of the diff.

## Known limitations (filed)

Each was replayed twice at `c3ca49a`.

- [#184](https://github.com/quality-gates/messpy/issues/184): **nested class bodies** (`class Local: value = counter` inside a function) are not analysed. The class body is a separate scope; `_ScopeChain` would need class scopes. A naive fix reports each class attribute as an ImplicitOutput.
- [#185](https://github.com/quality-gates/messpy/issues/185): **nested def argument and return annotations are not treated as reads.** They are evaluated at definition time on Python 3.12 and 3.13, but not on 3.14 (PEP 649) or with `from __future__ import annotations`.
- [#186](https://github.com/quality-gates/messpy/issues/186): **decorators that mutate** (`@registry.append`) are reported as an input only, not an output.
- [#187](https://github.com/quality-gates/messpy/issues/187): **`setattr(sys, name, value)`** is not detected as an output, while `sys.flag = value` is.

## Usability observations

- [#189](https://github.com/quality-gates/messpy/issues/189) **Observation:** findings name the function but are anchored to the body line. A user who puts a suppression above the `def` sees no effect. **Suggestion:** mention in the rule notes that suppressions go on the flagged line.
- [#188](https://github.com/quality-gates/messpy/issues/188) **Observation:** the advice "Pass it as an argument instead" and "Return it instead" reads oddly for `open`, `print` and `logging` calls. **Suggestion:** wording such as "Move this I/O to the caller" for ambient calls.

## Branch state

- `origin/main` `e25ddf9` moved the analysis engine from `src/messpy/cli.py` into `src/messpy/analyzer.py`, so the branch conflicted. The merge `c3ca49a` ported the explicitness code into `analyzer.py` and restored `_enclosing_scopes`, which main's #176 had deleted.
- Main's scope-resolution performance fixes (#175, #176) were rechecked after the port: 3000 call sites take 0.29 s under `explicitness` (0.88 s under `python`), and 150 nested lambdas take 0.04 s. No errors.
- The public `analyze()` facade reports both C1 findings.

## Verification at HEAD `c3ca49a`

- `tests.test_explicitness`: 13 tests OK.
- Full suite: 204 OK, 1 skipped (Atheris).
- Self-analysis gate OK. `generate_rule_docs.py --check` OK.
- All reproducers replayed.

## Filed issues

C1–C3 are not filed: they existed only on this unmerged branch and are fixed there. Limitations and usability observations: #184, #185, #186, #187 (bugs), #188 (enhancement), #189 (documentation).
