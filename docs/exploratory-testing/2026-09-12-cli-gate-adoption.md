# Exploratory testing: adopting messpy as a quality gate

**Date:** 2026-09-12
**Build:** messpy 0.1.12 at `c236953`, editable install in `.venv` (Python 3.12.12), macOS 25.6.0 (arm64), umask 022
**Interface driven:** the `messpy` CLI (`.venv/bin/messpy`), as documented in `README.md`, `docs/usage.md`, `docs/reports.md`, `docs/rules.md`
**Baseline:** `.venv/bin/python -m unittest discover -s tests` — 156 tests, OK (1 expected Atheris skip)
**Scratch projects:** `/tmp/messpy-et/proj` (exploration), `/tmp/messpy-repro/proj` (clean replays) — both removed after the pass

## Journeys exercised

### 1. Adopt the gate on a new project

Scanned a small hand-written package with `messpy src text python --ignore-tests`. Eight findings across five rules, exit 2. Variations attempted: adding a `messpy-disable-next-line` waiver and re-running (finding disappears, exit stays 2 on the rest), `--strict` (waiver reappears marked `[suppressed]`), `--minimumpriority` / `--maximumpriority`, `--only`, `--disable`, `--exclude`, `--suffixes`, `--ignore-tests`, duplicate and overlapping input paths, `--ignore-errors-on-exit`, `--ignore-violations-on-exit`.

Path dedup, default skip directories (`generated` skipped without being named), and exit-code precedence (errors over findings) all behaved as documented. A deliberately malformed file became a `ProcessingError` while the other files still reported.

**Found:** [#137](https://github.com/quality-gates/messpy/issues/137) — a waiver placed above a decorator is silently ineffective.

### 2. Wire a machine report into CI

Generated all eight formats to `--reportfile` and parsed each. JSON, XML, Checkstyle, SARIF, and GitLab all parse and match `docs/reports.md`, including the GitLab `fingerprint` formula (hex of `path:line:1:ruleName:message` — note it uses `message`, not the context-suffixed `description`), the priority→severity mappings, and the separate findings/errors collections.

Report-write failure modes are all graceful with a clear message and exit 1: missing parent directory, destination is a directory, unwritable directory. No temporary files were left behind.

**Found:** [#139](https://github.com/quality-gates/messpy/issues/139) — report files are written `0600` and replacing an existing file discards its permissions.

### 3. Put team thresholds in a custom XML ruleset

Wrote a `<ruleset>` excluding a rule from `python` and overriding `LongVariable`'s priority and `maximum`. Both took effect and `--verbose` listed the loaded set correctly. Malformed ruleset handling is otherwise strict and well-messaged: mismatched tag, reference cycle, unknown `ref`, unknown `<exclude>`, out-of-range `<priority>`, non-integer property value, missing `ref`, wrong root element, `<property>` missing `name`/`value`.

**Found:** [#136](https://github.com/quality-gates/messpy/issues/136) — a misspelled property *name* is the one mistake that passes silently.

### 4. Robustness sweep (outside the three journeys, cheap to run)

- **Encodings:** latin-1 coding cookie, UTF-8 BOM, CRLF — all analysed. Null bytes and binary content become `ProcessingError` and the run continues.
- **Large corpora:** the CPython 3.12 standard library (28.9 s, 16 318 findings, 0 processing errors, nothing on stderr) and `site-packages` (8.4 s) both completed without a crash.
- **Framework shapes:** `@abstractmethod` bodies, `Protocol` methods, `*args`/`**kwargs`, `_`-prefixed unused parameters, walrus, `match`, `nonlocal`, comprehensions, star-unpacking, `with ... as`, `except ... as`, dataclasses, and name-mangled `__`-private members all behaved sensibly.

**Found:** [#138](https://github.com/quality-gates/messpy/issues/138) — `UnusedPrivateMethod` fires on protected overrides of an imported base class.

## Confirmed bugs filed

| Issue | Summary | Journey |
|---|---|---|
| [#136](https://github.com/quality-gates/messpy/issues/136) | Unknown ruleset property names are silently ignored | 3 |
| [#137](https://github.com/quality-gates/messpy/issues/137) | `messpy-disable-next-line` above a decorator does not suppress | 1 |
| [#138](https://github.com/quality-gates/messpy/issues/138) | `UnusedPrivateMethod` flags protected overrides of an imported base | 4 |
| [#139](https://github.com/quality-gates/messpy/issues/139) | `--reportfile` writes mode 0600 and discards existing permissions | 2 |

Each was reduced to a minimal file set and replayed at least twice from a clean directory; replay steps and observed output are in the issue bodies.

A fifth crash — `RecursionError` on a long left-nested `+` chain, aborting the whole scan — was already open as [#132](https://github.com/quality-gates/messpy/issues/132). Added a [corroborating comment](https://github.com/quality-gates/messpy/issues/132#issuecomment-5642110806) with a more ordinary-looking reproducer (a 400-term string-concatenation constant) and a narrower threshold for the `python` ruleset.

## Candidates examined and rejected

- **`UnusedLocalVariable` on `x = f(); del x`.** Flagged. `del` removes a binding rather than reading it, so "no proven use" holds and the store really is dead. Consistent with the documented wording.
- **`UnusedFormalParameter` on `**kwargs` and on overrides.** Flagged, but the rule lives in `opinionated`, which `docs/rules.md` presents as the deliberately stricter set, and only underscore-named parameters are promised quiet. Distinct from #138, which is in the default `python` set.
- **`EmptyCatchBlock` on a handler containing a comment then `pass`.** Flagged. The handler is still empty at runtime.
- **`IfStatementAssignment` on `if (n := len(v)) > 2:`.** Exactly what `docs/rules.md` says the rule does.
- **Bare `# messpy-disable` with no rule names.** Ignored. `docs/usage.md` says malformed directives are ignored, and the documented form always names rules.
- **GitLab `fingerprint` apparently not matching the docs.** Observation error on my side — the formula uses `message`, not `description`. It matches.
- **`CamelCasePropertyName` on messpy's own `visit_AsyncFunctionDef = visit_FunctionDef` alias.** Real finding from a `controversial` rule outside the self-analysis gate's `codesize,design,unusedcode` scope. Not a defect.

## Unresolved

None. Every candidate raised during the pass is classified above.

## Usability observations

These are observations from the attempted journeys, not filed defects.

- **`--minimumpriority` reads backwards from PMD.** `--minimumpriority 2` *excludes* priority 1, the most severe. `docs/usage.md` is explicit ("Inclusive priority filters"), and "start at priority 1–2, then widen" points at `--maximumpriority`, but anyone arriving from PMD will reach for the wrong flag and quietly drop their blockers. A one-line note in the options table naming the inversion would cost nothing.
- **`Error: Input path does not exist` does not name the path.** With several comma-separated inputs there is nothing to act on. It also hides a real consequence of comma-separated paths: a directory whose name contains a comma (`odd, dir`) cannot be scanned at all, and the error gives no hint why.
- **`ProcessingError` messages carry an absolute, symlink-resolved path that contradicts the relative path in the same line.** `src/shop/broken.py:1: ProcessingError Could not parse /private/tmp/.../src/shop/broken.py: invalid syntax`. Harmless, but the duplication is noisy in CI logs.
- **A suppression directive that matches nothing is silent.** This is what makes #137 land as a surprise rather than a typo. `--verbose` would be a natural place to report unmatched directives.
- **`UnusedPrivateMethod`'s message calls a class-level alias assignment a "property".** Accurate to the rule's name, confusing at the call site.

## Limitations of this pass

- Single platform (macOS arm64) and single interpreter (3.12.12). Behaviour on 3.11 was not exercised; `CLAUDE.md` records a known `UnusedLocalVariable` difference there.
- The Homebrew standalone executable was not tested; only the editable Python install.
- Fuzzing (`docs/fuzzing.md`) was not run — it needs Python 3.11 plus Atheris in a separate environment.
- Rule-by-rule correctness was sampled, not swept. The stdlib scan gives breadth (no crashes, no processing errors across 16 318 findings) but findings were spot-checked, concentrating on the unused-code rules as the highest false-positive risk for a gate.
- No instrumentation or configuration changes were made to the product during the pass; every observation above is from the ordinary documented CLI.
