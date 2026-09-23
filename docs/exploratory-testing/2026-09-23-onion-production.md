# Exploratory testing: onion and explicitness as a user

**Date:** 2026-09-23

## Scope and setup

- Build: messpy 0.1.14, Python 3.12.14, git `db147bb` on `main`.
- Interface: the `messpy` command, plus one call to the public `analyze` function.
- Sample: a small `shop` package with a calculation module, a domain module that prints and imports a database package, and a command-line module. The sample was removed after the pass. The checks below can be replayed from those descriptions.

## Journeys

| # | Goal | Ordinary path | Variation | Lasting effect | Result |
|---|---|---|---|---|---|
| J1 | Keep calculations free of I/O and infrastructure imports | `messpy shop text onion.xml` on a domain that prints, opens a file, and imports `shop.infra` | Empty `domain` (exit 1), then the same tree scanned as `.`. Fixed `orders.py` and rescanned. Nested `shop/domain/pricing/tax.py` and `shop/domain/__init__.py` | JSON report file has the same 9 findings as the text report | Explored |
| J2 | See which data enters or leaves a function without being an argument or a return value | `explicitness` and `strictexplicitness` on `cli.py` and `Cart` | Suppressed the `print` line, then `--strict`. `--ignore-violations-on-exit`. Unreadable file beside valid files. Passed the same file twice. Injected `stdout` and rescanned | Report rows stay when the exit code is forced to 0. `analyze()` returns the same 3 cart findings as the CLI | Explored |
| J3 | Use the production gate the way CI does | `messpy src/messpy text rulesets/messpy-onion.xml,explicitness,codesize,design,unusedcode --ignore-tests --strict --color never` and `scripts/verify_self_analysis.py` | Scan `.` from the repository root. Run that command from a directory that does not contain the repository | Both gate commands exit 0 with empty output. `.venv` is not scanned | Explored |

## What matched the documented behavior

- Domain actions and outer imports are reported only for files under the `domain` pattern. `shop/cli.py` imports `sys` and writes `sys.stdout` and is quiet under `onion`. `shop/domain/checkout.py` is quiet under `onion` and `explicitness`.
- Scanning `shop` and scanning `.` produce the same onion findings. `*` matches nested files (`shop/domain/pricing/tax.py`) and `shop/domain/__init__.py`.
- A relative import `from ..infra.db import save_order` is reported as `shop.infra.db`. An import under `if TYPE_CHECKING:` is reported. A default `open(...)` and `os.environ[...]` are import-time `DomainAction` findings. A call to `write_log` in the same file is a spread finding. A suppression on the `print` line hides that finding and leaves the spread.
- `explicitness` does not report `self` reads or writes. `strictexplicitness` does. `onion` reports the `self.items.append` write and not the read. `__init__` is quiet.
- Empty `domain`, and the built-in name `onion` with no XML, exit 1: `DomainAction property 'domain' must name at least one path pattern.`
- A syntax error is a `ProcessingError`, the exit code is 1, and a neighboring file still reports `UnusedLocalVariable`.
- Passing the same path twice does not double the cart findings.
- `--ignore-violations-on-exit` exits 0 and still prints the findings.
- `--reportfile` writes JSON whose `ruleName` values and count match the text report. A missing directory exits 1 and does not leave the temp file behind.
- `naming`, `unusedcode`, and `controversial` still flag `BadMethod`, `localValue`, and an unused parameter.
- `src/messpy` is clean for the production gate. `scripts/verify_self_analysis.py` exits 0.
- `.venv` does not appear in a repository-wide scan. That scan exits 1 because `fuzz/corpus/source-analysis/malformed.py` and `non_utf8.py` are processing errors, and the other findings are still listed.

## Confirmed bugs

None. Every candidate below was replayed from a fresh file or was explained by the documented rules.

## Rejected candidates

- **JSON findings have no rule name.** Rejected. The field is `ruleName`, as in `docs/reports.md`. Nine JSON findings match nine text lines.
- **`messpy .` exits 1 even though `src/messpy` is clean.** Rejected. The report ends with two `ProcessingError` lines for the fuzz corpus. Exit 1 is the documented precedence of errors over findings.
- **`stdout.write` on an injected parameter is quiet, while `sys.stdout.write` is not.** Rejected. `sys.stdout` is an ambient output name. `write` is not in the mutator list. Replayed twice: `sys.stdout.write` and `print` inside a function are both reported, and a module-level `sys.stdout.write` is quiet for `explicitness` and reported as import-time `DomainAction` when the file is in the domain.
- **A `domain` pattern that matches nothing exits 0.** Rejected as a defect. The property is not empty, so it is not the exit-1 case. Replayed twice with `*/no/such/domain/*` on the shop tree: no stdout, exit 0. This is a footgun, recorded under usability.
- **Advice "Return it instead" on `print`, `open`, and `sys.stdout`.** Already filed: https://github.com/quality-gates/messpy/issues/188 (open). Not filed again.

## Usability observations

- **A typo in `domain` looks like a clean domain.** `messpy shop text onion-typo.xml` exits 0 when the pattern matches no file. Suggestion: when the scanned paths include Python files and none match `domain`, say so on stderr. This is an observation, not a filed bug.
- **`onion` plus `explicitness` prints two rows for one write.** `remember()` is both `DomainAction` (priority 2) and `ImplicitOutput` (priority 3). The docs say `onion` reuses those checks so they do not have to be loaded. Loading both is what the production gate does, and it is noisy on code that is not yet clean.
- **A failed `--reportfile` names the temp file.** The error names the requested report path and also an internal temporary name ending in `.<random>`. The requested path is present. The temp path is not a file the user created.

## Blocked or unexplored

- Not run: HTML in a browser, GitHub Actions annotation rendering, SARIF upload, and a scan on Python 3.11. The 3.11 suite was already green in CI on this commit; this pass used Python 3.12.
- `shop/infra` was not placed in the domain, so database calls were only checked as outer imports.
