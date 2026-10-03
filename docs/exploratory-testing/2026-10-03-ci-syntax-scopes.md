# Exploratory testing: CI machine-readable pipelines, modern Python 3.12 syntax, and lexical scope isolation

**Date:** 2026-10-03
**Build:** `messpy` 0.1.17 at `04f5e56290b1219973e6f274305b6226281be587`, editable `.venv` install, Python 3.12.12, macOS arm64 (Darwin 25.6.0)
**Interface:** the documented `messpy` CLI. Starting checkout was `main` at `origin/main`; it had pre-existing untracked `.claude/`, `.serena/`, and `uv.lock`. The exploration used isolated evidence under `docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes`.
**Configuration:** standard shell environment (umask `022`). No application configuration or instrumentation was changed.
**Evidence:** [fixtures, replay commands, captured stdout/stderr/status, and reports](evidence/2026-10-03-ci-syntax-scopes/README.md).

## Journeys

| # | User goal and expected result | Actions and actual result | Status |
|---|---|---|---|
| J1 | Validate machine-readable CI outputs (`sarif`, `json`, `xml`, `github`, `gitlab`, `checkstyle`) and strict exit code precedence (`0` clean, `1` errors, `2` violations) under varying ignore flags and atomic `--reportfile` writes. | Executed `messpy` across all output formats on a mixed target containing active findings, suppressed findings, and syntax errors. Verified exit code 1 precedence when errors exist, exit code 2 when errors are ignored via `--ignore-errors-on-exit`, and exit code 0 when both errors and violations are ignored. Validated SARIF 2.1.0, JSON, XML schemas, and GitHub/GitLab/Checkstyle stdout annotations. | Explored |
| J2 | Exercise modern Python 3.12 syntax (PEP 695 type aliases, generic functions, pattern matching with guards and rest bindings) against Clean Code and Python rulesets without parser crashes or false positives. | Tested generic function definitions (`def get_first[T]`), type statement aliases (`type Container[T]`), pattern matching destructuring (`case [x, *rest] if ...`), walrus assignments in conditionals, duplicate dictionary keys, and dead `else` clauses. All 3.12 syntax constructs parsed cleanly; `UnusedLocalVariable`, `IfStatementAssignment`, `DuplicatedArrayKey`, and `ElseExpression` triggered as expected. Exit 2. | Explored |
| J3 | Verify lexical scope isolation and member visibility across nested functions, comprehensions, leaked walrus expressions, abstract/protocol stubs, and local inheritance hierarchies. | Scanned shadowed closures, multi-level list comprehensions, leaked walrus variables, protocol/abstract stubs (`...`, `pass`), and derived classes with unused private fields and methods under `unusedcode`. Closures correctly isolated parameters, unused inner comprehension variables flagged without affecting outer variables, leaked walrus was tracked in enclosing scope, and unused private members were flagged. Exit 2. | Explored |

### J1: CI machine-readable pipelines and exit gate precedence

- **Starting conditions:** A test suite under `j1/` with clean code (`service.py`), code containing active and suppressed findings (`handlers.py`), and a file with a deliberate syntax error (`broken.py`).
- **Replay:** From the evidence directory, run `messpy j1 text python,opinionated`. Output reported 1 syntax error in `broken.py` alongside 7 findings in `handlers.py`, exiting with code 1.
- **Variation 1 (ignore flags):**
  - Running with `--ignore-errors-on-exit` suppressed the error exit code, returning exit code 2 (unignored findings remaining).
  - Running with both `--ignore-errors-on-exit` and `--ignore-violations-on-exit` returned exit code 0, while still emitting all diagnostic records to the report.
- **Variation 2 (atomic report files and schemas):**
  - `--strict --reportfile results.sarif` generated a valid SARIF 2.1.0 document with driver rules, results, suppression rationale, and `toolExecutionNotifications` for errors.
  - `--strict --reportfile results.json` generated valid JSON with distinct `findings` and `errors` collections.
  - `--strict --reportfile results.xml` generated attribute-oriented XML matching `MesspyViolationReport`.
  - Formats `github`, `gitlab`, and `checkstyle` produced valid workflow annotations, codequality JSON entries with MD5/SHA fingerprints, and Checkstyle XML elements.
- **Lasting effect:** Verified that atomic file generation leaves clean files in place on exit 1, and verified all report artifacts in `j1/`.

### J2: Modern Python 3.12 syntax and Clean Code rules

- **Starting conditions:** `j2/modern_syntax.py` containing PEP 695 generic functions, PEP 695 type aliases, pattern matching with guards and rest bindings, duplicate dictionary keys (including numeric and boolean equivalence), and walrus expressions in `if` conditions; `j2/clean_flow.py` containing nested `if` statements with returning branches followed by dead `else` blocks.
- **Replay:** Run `messpy j2/modern_syntax.py text python,cleancode`.
  - Generic parameters `[T]` and `type NumberOrText` parsed without AST parse failures or spurious rule violations.
  - Unused `*rest` in `case [x, *rest] if x > 0:` was correctly detected as `UnusedLocalVariable`.
  - Walrus expression `(status := compute()) == 200` was flagged as `IfStatementAssignment` at line 24, column 8.
  - Duplicate dictionary keys `1: "int"` vs `1.0: "float"` and duplicate boolean tuples were flagged as `DuplicatedArrayKey`.
- **Variation:** Run `messpy j2/clean_flow.py text cleancode`.
  - Dead `else` blocks after terminating `if` clauses were flagged as `ElseExpression` at lines 6 and 8.
  - Non-terminating `if` branches correctly left subsequent `else` blocks unflagged.
- **Lasting effect:** Confirms robust AST handling for modern Python 3.12 grammar additions.

### J3: Lexical scope isolation and member visibility

- **Starting conditions:** `j3/scope_isolation.py` with closures shadowing outer parameters, nested comprehensions, leaked walrus variables, and protocol stubs; `j3/member_visibility.py` with base and derived classes containing unreferenced private attributes and methods.
- **Replay:** Run `messpy j3/scope_isolation.py text unusedcode`.
  - Inner closure parameter `items` shadowing outer parameter `items` did not cause false positive `UnusedFormalParameter` on the outer function.
  - Comprehension target `col` in `[1 for row in matrix for col in row]` was flagged as `UnusedLocalVariable` because it was not referenced in the expression, while `row` was recognized as used.
  - Leaked walrus variable in `(val := x * 2)` was correctly tracked as used in the enclosing function scope.
  - Abstract and protocol methods with stubs (`pass` or `...`) correctly exempted parameters from `UnusedFormalParameter`.
- **Variation:** Run `messpy j3/member_visibility.py text unusedcode`.
  - Local class inheritance correctly resolved `_dead_field` as `UnusedPrivateField` and `_unused_private` as `UnusedPrivateMethod`.
- **Lasting effect:** Verified lexical scope boundary isolation and member reference resolution.

## Findings

**Confirmed bugs:** None. All evaluated candidates adhered to the documented architecture and specifications.

**Usability observations:**
1. *Path exclusion token matching:* Passing `--exclude dir/` with a trailing slash fails to exclude `dir` because `_is_excluded` matches exact token membership against relative path components. This limitation is already captured and tracked under open issue [#171](https://github.com/quality-gates/messpy/issues/171) ("Deepen: source discovery and path exclusion into a dedicated module returning resolved paths").
2. *GitLab Code Quality error formatting:* The GitLab formatter unconditionally appends `(context: {record['context']})` to descriptions. For processing errors where `context` is empty, this renders a trailing `(context: )` in the output JSON.

## Scope limits

This exploration focused on CI output serialization, exit gate precedence, Python 3.12 modern AST constructs (PEP 695, pattern matching, walrus expressions), and lexical scope tracking for unused code rules. It did not evaluate Python runtimes prior to 3.12, standalone Homebrew packaging, or fuzzing targets under Atheris (which require a separate Python 3.11 environment).
