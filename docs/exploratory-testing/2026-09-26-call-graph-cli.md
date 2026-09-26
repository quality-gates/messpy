# Exploratory testing: class cohesion, domain imports, and source execution

**Date:** 2026-09-26
**Build:** `messpy` 0.1.15 at `3323e964f38568483b356ff9ecdf83a693c1a750`, editable `.venv` install, Python 3.12.12, macOS arm64 (Darwin 25.6.0)
**Interface:** the documented `messpy` CLI. Starting checkout was `main` at `origin/main`; it had pre-existing untracked `.claude/`, `.serena/`, `fuzz/perffuzz/`, and `uv.lock`. The exploration used isolated data under `/tmp/messpy-afk-2026-09-26`.
**Configuration:** standard shell environment (umask `022`); the XML policies used are included with the evidence. No application configuration or instrumentation was changed.
**Evidence:** [fixtures, replay commands, captured stdout/stderr/status, and JSON reports](evidence/2026-09-26-call-graph-cli/README.md).

## Journeys

| # | User goal and expected result | Actions and actual result | Status |
|---|---|---|---|
| J1 | Find classes with disconnected responsibilities; receiver calls should connect methods, and properties, static/class methods, and abstract stubs should not inflate the score. | `messpy j1/disconnected.py text j1/cohesion.xml` reported LCOM4=2 and exited 2. Adding receiver calls between the groups made `connected.py` exit 0. A class containing properties, static/class methods, and an abstract method also exited 0. The JSON report for the disconnected case contained one finding and no errors. | Explored |
| J2 | Keep the domain free of infrastructure imports, including alias spellings and type-only imports. | A realistic package used aliased `import` and `from` forms, a relative aliased import, and an aliased `TYPE_CHECKING` import. The same four `DomainOuterImport` findings appeared on both clean replays and in JSON (four findings, zero errors). Removing the aliases still produced four findings. | Explored |
| J3 | Analyze a source tree without importing or executing project code. | Scanned one module that writes a marker and raises at module scope, plus one with a marker write under `if __name__ == "__main__"`. Text and JSON scans both exited 0 with no findings/errors; neither marker existed after either run. | Explored |

### J1: class cohesion

- **Starting conditions:** custom ruleset loading only `LackOfCohesionOfMethods`; the `FulfilmentDesk` class had one group using `pending` and another using `currency`.
- **Replay:** from the evidence directory, run `messpy j1/disconnected.py text j1/cohesion.xml` twice. The output was identical: `LackOfCohesionOfMethods` at line 1 with value 2; exit 2, stderr empty.
- **Variation:** `connected.py` adds receiver calls linking the groups. It returned 0 with empty output. `accessors.py` exercises properties, static/class methods, and an abstract method; it also returned 0.
- **Lasting effect:** the `--reportfile` JSON output is preserved as `j1/disconnected.json` and contains the same single finding.

### J2: onion boundary imports

- **Starting conditions:** `domain` is `*/shop/domain/*`; `outer-layers` is `shop.infra`. Package `__init__.py` files make the relative import resolvable.
- **Replay:** `messpy j2/shop/domain text j2/onion.xml`, twice. Each run exited 2 with four findings at `orders.py:1`, `orders.py:2`, `orders.py:5`, and `pricing.py:1`; stderr was empty. `j2/packaged-imports.json` has the same four findings and zero errors.
- **Variation:** removing import aliases preserved all four findings.
- **Rejected setup candidate:** before adding package `__init__.py` files, the relative import could not be resolved to `shop.infra`; that is an explicitly documented resolution precondition. After creating a realistic package and infrastructure modules, the same relative import was reported on both replays. This was a test-fixture issue, not a product failure.

### J3: source execution boundary

- **Starting conditions:** `effectful.py` has a top-level marker write followed by `raise RuntimeError`; `guarded.py` has a marker write under the main guard.
- **Replay:** `messpy j3/src text python` and `messpy j3/src json python --reportfile j3/portable-scan.json`. Both exited 0, stdout/stderr were empty, and both marker paths remained absent. The JSON report has zero findings and zero errors.
- **Variation:** the report-file/JSON path produced the same non-execution result as text output.

## Findings

**Confirmed bugs:** none. No candidate violated the documented behavior after correcting the package fixture. There are no unresolved candidates and no issues were filed.

**Usability observations:** none from these journeys.

## Scope limits

This was a focused pass over class cohesion, onion import boundaries, and non-execution through the CLI. It did not sweep every rule, test other Python versions, or exercise the Homebrew standalone binary. The machine-readable check used JSON; other report formats were outside this pass.
