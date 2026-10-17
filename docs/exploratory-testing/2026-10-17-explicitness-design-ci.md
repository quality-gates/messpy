# Exploratory testing: explicitness, design review, and CI reports

**Date:** 2026-10-17
**Build:** `messpy` 0.1.21 at `d3736652324a658f2e1f9db7843fa3d64e6ba069`, editable `.venv` from `uv sync --frozen --python 3.12 --python-preference only-managed`, Python 3.12.12, macOS arm64 (Darwin 26.6.2)
**Interface:** the documented `messpy` CLI, plus the documented `analyze` / `select_rules` snippet. Starting checkout was `main` fast-forwarded to `origin/main`. Pre-existing untracked `.claude/`, `.serena/`, and `uv.lock` were left untouched.
**Configuration:** standard shell, umask `022`. No application configuration or instrumentation was changed. `uv sync --frozen` removed the seeded `pip` package from `.venv`; that is environment setup, not product behavior.
**Evidence:** [fixtures, replay scripts, and captured stdout/status](evidence/2026-10-17-explicitness-design-ci/README.md).

## Journeys

| # | User goal and expected result | Actions and actual result | Status |
|---|---|---|---|
| J1 | Gate a pricing module with `explicitness`: calculations stay quiet, ambient reads and caller-owned writes are reported, then a correction and a suppression stick. | The documented calculation subset matched. A passed-in cache was still an output when mutated. A next-line suppression hid `print`; `--strict` showed it. The documented package API returned the same two findings as the CLI. | Explored |
| J2 | Review class design before a PR: dead `else`, coupling, and cohesion, then correct a threshold. | Always-exiting `try`/`except`/`else`, `try`/`finally`, and `match` were flagged. An imported `metaclass` and a keyword-only type counted. A split class was flagged; a cohesive class was quiet. A live loop `else` was also flagged. | Explored |
| J3 | Publish a CI report a consumer can parse, then correct a bad format and a locked directory. | Exit codes, atomic `--reportfile` replacement, and format field rules matched `docs/reports.md` for text, JSON, XML, HTML, GitHub, GitLab, and SARIF. Checkstyle interleaved a processing error. GitLab fingerprints for that error changed between checkouts. | Explored |

### J1: Explicitness gate

- **Starting conditions:** `j1/src/billing` with calculations, a mutable cache, argument mutation, copies, captures, async reads, and an injected callback.
- **Replay:** From `j1/`, `messpy src text explicitness --ignore-tests`. Exit 2. `net`, `taxed`, `read_immutable`, `copy_and_stamp`, `scale`, and frozen `Money` addition were quiet. `CACHE`, `UPPER`, `MUTABLE_TUPLE`, `os.environ`, and `open` were inputs. Argument `append` and nested-element mutation were outputs. `announce` printed twice and produced one finding. `schedule_only()` did not inherit the un-awaited coroutine. `load_note()` did, at the `await` line.
- **Variation:** Same-file helpers transferred reads and prints to the caller. `while False` rebinding was pruned; `while not True` was retained. A fresh `push([])` stayed quiet; `push(items)` was an output, but the message still said `target`. Passing `cache` in removed the input finding and left the write. `messpy-disable-next-line ImplicitOutput` hid `announce`; `--strict` marked it `[suppressed]`. `onion.xml` reported `requests`, the `print`, and `publish()` calls `save_report()`, which writes the implicit output print. `pricing.py` outside the domain pattern stayed quiet. Missing `domain` exited 1.
- **Lasting effect:** `j1/runs/ordinary.stdout` is the first scan. `j1/runs/corrected-strict.stdout` still shows the suppressed print. The committed `orders.py` still imports `requests`.

### J2: Design review

- **Starting conditions:** `j2/src/review` with dead-else shapes, an imported metaclass, and a class split across two fields.
- **Replay:** `messpy src/review/flow.py text opinionated` exited 2. It flagged the dead `else` after an always-returning `try`/`except`/`else`, after `try`/`finally`, and after an always-returning `match`. A falling `except` did not flag the outer `else`. A `for`/`else` that can still run after a conditional `break` stayed quiet.
- **Variation:** `coupling-max-1.xml` flagged `Service(metaclass=CustomMeta)` and `Movie(total=Marker)` and left `Quiet` alone. `LackOfCohesionOfMethods` flagged `Split` at LCOM4 2 and left `Together` quiet. Trivial accessors did not inflate the score. `get_ready() -> bool` was flagged; `get_user() -> str` was not. Short indexes and exception names stayed quiet.
- **Lasting effect:** The committed `live_else.py` still raises on an empty list. The scan says to delete that `else`.

### J3: CI report

- **Starting conditions:** `j3/src/app` with a long name, a `TODO`, a syntax error, and a clean module. Later, a locked subdirectory.
- **Replay:** `messpy src text python --ignore-tests` exited 1. Findings came first; the syntax error followed. `--ignore-errors-on-exit` exited 2. `--ignore-violations-on-exit` exited 1. Both flags exited 0. The report rows stayed. A typo'd format exited 1 with `Unknown format: txt`. Correcting it produced the report.
- **Variation:** `--reportfile` left stdout empty and replaced an existing JSON file. A bad ruleset did not clobber a sentinel file. A missing parent exited 1 and named both the requested path and a temporary file. GitHub percent-encoded `%`, `,`, `:`, CR, and LF in the file property and left spaces literal. SARIF percent-encoded space, `&`, and newlines in `uri`. HTML and XML escaped `&` and quotes. An unreadable directory stayed a `ProcessingError`; the sibling finding remained, including under `--ignore-errors-on-exit --reportfile`.
- **Lasting effect:** `j3/runs/gate.json` was replaced by a later clean scan during the pass. The committed `replays/` captures are the checkstyle order and the two GitLab fingerprints.

## Findings

### Confirmed

1. **ElseExpression flags a live loop else when the body returns or raises.** [#276](https://github.com/quality-gates/messpy/issues/276)
   - **Impact:** A reviewer is told to delete an `else` that still runs when the loop is not entered. Deleting it changes the result.
   - **Starting conditions:** `j2/src/review/live_else.py`. `first([])` raises `LookupError`. `pop_or_empty([])` returns `"empty"`.
   - **Replay:** `messpy live_else.py text opinionated --only ElseExpression`. Exit 2. Both `else` clauses are flagged as dead and removable. The same finding appears on `async for`.
   - **Expected:** An `else` that runs when the body is not entered is not dead. The rule should not say to remove it.
   - **Actual:** A `return` or `raise` in the body is treated as if the body always runs.
   - **Repeat:** Same two findings on a second scan. Captures: `j2/runs/live-else-1.stdout`, `live-else-2.stdout`. Replay: `replay-live-loop-else.sh`.

2. **checkstyle places a processing error among later findings.** [#277](https://github.com/quality-gates/messpy/issues/277)
   - **Impact:** A consumer that reads findings until the first `ProcessingError` drops findings in files that sort later.
   - **Starting conditions:** `src/a_ok.py`, `src/m_broken.py`, and `src/z_ok.py`.
   - **Replay:** `messpy src checkstyle python`. File order is `a_ok.py`, then `m_broken.py` as `ProcessingError`, then `z_ok.py`.
   - **Expected:** `docs/reports.md` says single-stream formats, including checkstyle, emit the findings group first, then processing errors.
   - **Actual:** Checkstyle sorts the mixed groups by path. `text`, `github`, and `gitlab` keep findings first.
   - **Repeat:** Same order on a second render. Capture: `replays/checkstyle-order.xml`. Replay: `replay-checkstyle-order.sh`.

3. **ProcessingError messages embed an absolute path, so GitLab fingerprints change between checkouts.** [#278](https://github.com/quality-gates/messpy/issues/278)
   - **Impact:** The same syntax error is a new GitLab Code Quality issue when the workspace path changes.
   - **Starting conditions:** Two directories, each with `pkg/broken.py` containing `def broken(`.
   - **Replay:** `messpy pkg gitlab python` in each directory. The `path` field is `pkg/broken.py` in both. The descriptions differ by absolute path. The fingerprints differ.
   - **Expected:** The fingerprint formula in `docs/reports.md` should identify the same relative source error across machines. The relative `path` field already locates the file.
   - **Actual:** The message is `Could not parse` plus the absolute path. The fingerprint includes that message.
   - **Repeat:** A second pair of directories, `left` and `right`, disagreed again. A `TODO` finding in the same scan kept one fingerprint. Captures: `replays/gitlab-left.json`, `replays/gitlab-right.json`. Replay: `replay-gitlab-fingerprint.sh`.

### Rejected

- Calculations, immutable tuples, `Final` scalars, `ImportError` fallbacks, and frozen dataclass field reads were quiet under `explicitness`. Mutable `UPPER` and `Final` lists were inputs.
- Shallow-copy mutation was quiet. Mutating an element reached through the copy was an output. Branch joins, aliases, and loop rebinding followed the contract. `while False` was pruned; `while not True` was not.
- Calling an async function or generator did not transfer body effects. `await`, `asyncio.run`, `yield from`, and `list()` on a generator expression did.
- `sorted` and `list.sort` executed their `key` callback. An injected callback was `UnknownEffect`. Recursion terminated and flagged the parameter write.
- An imported metaclass and a keyword-only class reference counted toward `CouplingBetweenObjects`. A local class used only as a metaclass did not, which matches the external-dependency rule.
- Exit 1 beat findings. Ignore-on-exit flags changed only the status. `--reportfile` replaced atomically and did not clobber a file when the ruleset was unknown.
- An unreadable directory was a `ProcessingError`. The sibling finding remained. This is the #258 fix, still holding.
- SARIF artifact URIs and GitHub workflow-command properties percent-encoded the characters `docs/reports.md` names. GitLab fingerprints for ordinary findings were the documented hex of `path:line:1:ruleName:message`.
- Repeated inputs did not double findings. An explicit directory symlink was scanned. A nested directory symlink was not followed.
- `messpy src text python --ignore-tests` on this repository's `src` was clean, exit 0.

### Unresolved

None.

## Usability observations

These are not confirmed bugs.

1. `ElseExpression` calls a module-level function a method: `The method always_exiting_try uses an else`.
2. A transferred `ImplicitOutput` keeps the callee's parameter name. `via_helper()` writes `target` at `push(items)`, and `via_helper` has no name `target`.
3. `say = print; say(total)` is `UnknownEffect` from `say`, not `ImplicitOutput` from `print`. The call is not missed, but the advice is less specific.
4. `open()` is an input or output, and `handle.read()` / `handle.write()` is also `UnknownEffect`. `sys.stdout.write` is both an input and an output of `sys.stdout`.
5. `@dataclass(frozen=True)` is a module-level `UnknownEffect` even when later field reads of that frozen class are quiet.
6. Following "Pass it as an argument instead" on `CACHE` removes the input and leaves an output if the function still assigns into that argument.
7. `--minimumpriority 2` drops priority 1 and keeps 2 and 3. The help text matches that numeric bound. "Start enforcement at priority 1–2, then widen" is `--maximumpriority`, not `--minimumpriority`.
8. `--reportfile` does not create missing parents. The error names the requested path and a temporary file. A comma in a path argument is still a path separator. `analyze(["does-not-exist"])` still raises `OSError` instead of returning an error value. All three were already noted on 2026-10-10.

## Scope limits

This pass used the CLI on isolated trees and the documented package API. It did not install the Homebrew bottle, did not build the Docker image, and did not upload SARIF or GitLab reports to a host. No Docker container, image, or volume was created. Scanning `.` of this checkout also walks untracked `.claude/` and the fuzz corpus; that is local checkout state, not a product failure.
