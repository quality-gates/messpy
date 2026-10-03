# Captured evidence: CI machine-readable pipelines, modern Python 3.12 syntax, and lexical scope isolation

Build under exploration: `messpy` 0.1.17 at `04f5e56`, installed editable in the project `.venv` (Python 3.12.12), on macOS arm64 (Darwin 25.6.0). All runs drove the public `messpy` CLI.

To replay from the repository root with `messpy` on `PATH`:

```console
messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1 text python,opinionated
messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1 text python,opinionated --ignore-errors-on-exit
messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1 text python,opinionated --ignore-errors-on-exit --ignore-violations-on-exit
messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1 sarif python,opinionated --strict --reportfile docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1/results.sarif
messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1 json python,opinionated --strict --reportfile docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1/results.json
messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1 xml python,opinionated --strict --reportfile docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1/results.xml
messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1 github python,opinionated --strict
messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1 gitlab python,opinionated --strict
messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j1 checkstyle python,opinionated --strict

messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j2/modern_syntax.py text python,cleancode
messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j2/clean_flow.py text cleancode

messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j3/scope_isolation.py text unusedcode
messpy docs/exploratory-testing/evidence/2026-10-03-ci-syntax-scopes/j3/member_visibility.py text unusedcode
```

Raw captured outputs (`*.stdout.txt`, `*.stderr.txt`, `*.status.txt`) are preserved under `runs/`.

## J1: CI machine-readable pipelines and exit gate precedence

| Command | Exit | Captured result |
|---|---:|---|
| `messpy j1 text python,opinionated` | 1 | Precedence held: `broken.py` processing error takes precedence over 7 findings in `handlers.py`. |
| `messpy j1 text python,opinionated --ignore-errors-on-exit` | 2 | Errors ignored on exit; exit status 2 reflects remaining unignored findings. |
| `messpy j1 text python,opinionated --ignore-errors-on-exit --ignore-violations-on-exit` | 0 | Both ignored; returns 0 while report stream still outputs all findings and errors. |
| `messpy j1 sarif python,opinionated --strict --reportfile j1/results.sarif` | 1 | Atomic write succeeded; SARIF 2.1.0 output contains driver rules, results, suppressions, and `toolExecutionNotifications`. |
| `messpy j1 json python,opinionated --strict --reportfile j1/results.json` | 1 | Atomic JSON report written with distinct `findings` and `errors` collections. |
| `messpy j1 xml python,opinionated --strict --reportfile j1/results.xml` | 1 | Attribute-oriented XML report generated matching the canonical schema. |
| `messpy j1 github python,opinionated --strict` | 1 | Emitted `::warning` for findings with `[suppressed]` tag and `::error` for `ProcessingError`. |
| `messpy j1 gitlab python,opinionated --strict` | 1 | GitLab Code Quality JSON entries with SHA/fingerprints and severity mappings. |
| `messpy j1 checkstyle python,opinionated --strict` | 1 | Checkstyle XML grouping by file with error tags and suppression attributes. |

## J2: Modern Python 3.12 syntax and Clean Code rules

| Command | Exit | Captured result |
|---|---:|---|
| `messpy j2/modern_syntax.py text python,cleancode` | 2 | PEP 695 generic functions and type aliases parsed cleanly. Unused `**rest` binding in match pattern flagged as `UnusedLocalVariable`. Walrus in `if` condition flagged as `IfStatementAssignment` with exact line and column (line 24, col 8). Static duplicate array keys flagged across types (`1` vs `1.0`, `(True, False)` duplicate). |
| `messpy j2/clean_flow.py text cleancode` | 2 | Dead `else` clauses flagged after terminating nested `if` blocks (lines 6 and 8). Non-terminating `if` branches correctly leave `else` unflagged. |

## J3: Lexical scope isolation and member visibility

| Command | Exit | Captured result |
|---|---:|---|
| `messpy j3/scope_isolation.py text unusedcode` | 2 | Inner function shadowing outer `items` parameter does not corrupt outer usage count. Unused comprehension target `col` in `[1 for row in matrix for col in row]` flagged. Walrus expression leaking into enclosing function scope detected as used. |
| `messpy j3/member_visibility.py text unusedcode` | 2 | Subclass inheriting from locally resolved base class flags `_dead_field` as `UnusedPrivateField` and `_unused_private` as `UnusedPrivateMethod`. Abstract and protocol method stubs (`...`, `pass`) exempt parameters from `UnusedFormalParameter`. |
