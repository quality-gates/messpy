# Exploratory testing: production gate, team policy, and onion

**Date:** 2026-10-10
**Build:** `messpy` 0.1.20 at `43f3795be03bbbb44694c56ee41d2f7d4a42e00a`, editable `.venv` from `uv sync --frozen --python 3.12 --python-preference only-managed`, Python 3.12.12, macOS arm64 (Darwin 25.6.0)
**Interface:** the documented `messpy` CLI, plus the documented `analyze` / `select_rules` snippet. Starting checkout was `main` fast-forwarded to `origin/main`. Pre-existing untracked `.claude/`, `.serena/`, and `uv.lock` were left untouched.
**Configuration:** standard shell, umask `022`. No application configuration or instrumentation was changed.
**Evidence:** [fixtures, replay script, and captured stdout/stderr/status](evidence/2026-10-10-gate-policy-onion/README.md).

## Journeys

| # | User goal and expected result | Actions and actual result | Status |
|---|---|---|---|
| J1 | Gate a small billing package before a PR: scan production code, ignore tests, fail CI on findings, and keep a JSON report. | `messpy src text python --ignore-tests` reported the expected mess and a syntax error, exit 1. Tests and `generated/` stayed out. A JSON report replaced the previous file. An unreadable directory aborted the scan. | Explored |
| J2 | Put team thresholds in XML, fail closed on a bad ruleset, then correct it. | The README policy raised `LongVariable.maximum` to 50 and dropped `DevelopmentCodeFragment`. A typo'd ruleset exited 1 with `Unknown ruleset reference 'pyhton'`. `--only` of a rule not in the policy exited 1. The documented package API returned the same two findings. | Explored |
| J3 | Confirm a domain layer has no actions or outer imports. | Configured `onion` reported outer imports, body actions, and an import-time call spread. A calculation file was quiet, exit 0. Missing `domain` exited 1. Removing `import requests` removed that finding. | Explored |

### J1: Production gate

- **Starting conditions:** `j1/src/billing` with a messy invoice module, a class hierarchy, a syntax error, a `generated/` tree, and `j1/tests`.
- **Replay:** From `j1/`, `messpy src text python --ignore-tests`. Exit 1. Findings included `LongVariable`, `UnusedLocalVariable`, `DevelopmentCodeFragment`, `EmptyCatchBlock`, `IfStatementAssignment`, `UnusedPrivateField`, and `UnusedPrivateMethod` on the unrelated stamp. `Receipt` using `SignedDocument._sign` was not flagged. `generated/` was skipped. `legacy.py` was a `ProcessingError`; other files were still reported.
- **Variation:** Scanning `.` without `--ignore-tests` added the test TODO. `--ignore-tests` removed it. `python,opinionated` on `flow.py` flagged the `else` after an always-returning `try`/`finally` and after an always-returning `match`. `--reportfile runs/gate.json` wrote a complete JSON report and left stdout empty. Listing the same clean file twice did not double findings.
- **Lasting effect:** `j1/runs/gate.json` is the report from the failing scan. Exit became 2 after the syntax error was fixed in the scratch session; the committed `legacy.py` is still broken so the committed ordinary capture stays at exit 1.

### J2: Team policy

- **Starting conditions:** `j2/sample.py` and `j2/team-policy.xml`, the README example.
- **Replay:** `messpy sample.py text team-policy.xml` exited 0. The same file under `python` exited 2 with `LongVariable` and `DevelopmentCodeFragment`.
- **Variation:** `broken-policy.xml` (`ref="pyhton"`) exited 1 and printed `Unknown ruleset reference 'pyhton'`. `--only ExitExpression` on the `python` policy exited 1 with `Unknown loaded rule 'ExitExpression'`. `--disable` of an unknown rule did the same. A later case-insensitive `LongVariable` reference overrode `maximum` to 40 and priority to 1. The documented `select_rules(RuleSelection(rulesets=("python",)))` snippet returned the same findings as the CLI.
- **Lasting effect:** Correcting the typo'd reference back to `python` restored the two findings and exit 2.

### J3: Onion gate

- **Starting conditions:** `j3/src/shop` with a domain layer, infra, and web, plus `j3/onion.xml` (`domain="*/shop/domain/*"`).
- **Replay:** `messpy src text onion.xml` exited 2. It reported `requests`, the relative `shop.infra` import, the `TYPE_CHECKING` web import, the in-function `sqlalchemy` import, `print`, the `self.total` write, `repo.add`, and the import-time `publish()` spread in `boot.py`. `pricing.py` was quiet, exit 0. `Order.discounted` reading `self.total` was quiet. Infra `print` was quiet because that file is outside the domain pattern.
- **Variation:** `onion-missing-domain.xml` and a bare `onion` ruleset both exited 1 with `DomainAction property 'domain' must name at least one path pattern`. The same findings appeared when the scan root changed from `j3` to `j3/src`. A suppression on the `print` line hid the direct `DomainAction` and still spread to the caller; `--strict` showed `[suppressed]`. A suppression above the `def` did not cover the body finding. Removing `import requests` removed that `DomainOuterImport` and left the other findings.
- **Lasting effect:** The committed `orders.py` still imports `requests`, matching `j3/runs/onion.stdout.txt`.

## Findings

### Confirmed

1. **An unreadable directory aborts the scan and drops findings from readable files.** [#258](https://github.com/quality-gates/messpy/issues/258)
   - **Impact:** A tree with one unreadable subdirectory produces no findings and no report file. `--ignore-errors-on-exit` then exits 0, so CI can go green without scanning.
   - **Starting conditions:** `j1/mixed/ok/visible.py` and `j1/mixed/secret/hidden.py`, both with a TODO. Both readable.
   - **Replay:** `messpy mixed text python` exits 2 with both findings. `chmod 000 mixed/secret` and the same command exits 1, stdout empty, stderr `Error: [Errno 13] Permission denied`. The `visible.py` finding is absent. `--ignore-errors-on-exit --reportfile` exits 0 and does not create the report file. Passing the readable file and the locked directory together also drops the readable file.
   - **Expected:** An unreadable input becomes an error in the report, and other valid files are still analyzed. Ignore-on-exit changes only the status.
   - **Actual:** Discovery raises `PermissionError` from `Path.iterdir()` before a report is rendered.
   - **Repeat:** Same failure on a second lock/unlock cycle. Contrast: an unreadable file stays in the report as `ProcessingError` and the sibling finding is kept. Captures: `j1/runs/baseline.*`, `locked.*`, `locked-2.*`, `locked-ignore.*`, `two-paths.*`, `file-contrast.*`. Replay script: `replay-unreadable-directory.sh`.

### Rejected

- SARIF artifact URIs percent-encode space, comma, percent, and `&`. GitHub workflow commands percent-encode `,` and `%` in the file property. Spaces stay literal, which matches `docs/reports.md`.
- GitLab `fingerprint` is the lowercase hex of UTF-8 `path:line:1:ruleName:message`, not a digest.
- `try`/`else`, `for`/`else`, and a non-exiting `if`/`else` were not flagged by `ElseExpression`. Always-exiting `try`/`finally` and `match` branches were.
- Private methods used through a subclass, `super()`, an explicit class reference, or multiple inheritance were not flagged. An unused private method was.
- `from __future__ import annotations` kept an `open()` annotation quiet. An `open()` default argument was still an import-time action, which is correct: postponed annotations do not defer defaults.
- A nested directory symlink whose target sat outside the tree was not followed. An explicit directory symlink was scanned.
- `BooleanGetMethodName` flagged boolean methods and left `get_user() -> str` quiet. A module-level `get_ready()` was quiet; the rule is documented for methods.
- `GlobalVariable` flagged a mutated `counter` and left a constant and an `ImportError` import fallback quiet.

### Unresolved

None.

## Usability observations

These are not confirmed bugs.

1. `--exclude billing/` does not exclude a directory named `billing`. The token is matched exactly against path components, so the trailing slash never matches. `--exclude billing` does. This was already noted on 2026-10-03. [#171](https://github.com/quality-gates/messpy/issues/171) is a discovery-design issue, not a filed defect for the trailing slash.
2. A comma in a path argument is a path separator (`<path[,path...]>`), so that path cannot be named on the command line. The error is `Input path does not exist`. A file with a comma in its name is still reported when a parent directory is scanned.
3. `--reportfile` does not create missing parent directories. Exit 1, and the error names the temporary file.
4. A namespace package without `__init__.py` does not resolve `from ..infra.repository import Repo`, so `DomainOuterImport` stays quiet against `shop.infra`. That matches the documented fallback: unresolved relative imports are matched as written.
5. `messpy-disable-next-line` above a `def` does not waive a `DomainAction` anchored on the body line. The directive on the flagged line does, and the action still spreads. [#189](https://github.com/quality-gates/messpy/issues/189) already asks the explicitness docs to say this.
6. `analyze(["does-not-exist"], ...)` raises `OSError: Input path does not exist` instead of returning an error value. The CLI catches that and exits 1.

## Scope limits

This pass used the CLI on isolated trees and one call to the documented package API. It did not install the Homebrew bottle, did not run Atheris, and did not upload SARIF or GitLab reports to a host. `messpy src text python --ignore-tests` on this repository's own `src` was clean, exit 0. Scanning `.` also walked untracked `.claude/` and the fuzz corpus, which is local checkout state, not a product failure.
