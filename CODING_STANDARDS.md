# Coding standards

## Tests

- Strongly prefer integration tests and end-to-end tests over unit tests.
- Strongly prefer exercising real system behaviour over "the tests pass so it must work."
- Only mock third-party services we cannot control. Do not mock code we own.
- For this codebase, the default proof is: run the real CLI/analyzer on real (or fixture) source and assert findings, exit codes, and report output.

## Comments and docs

- Code comments use ASD-STE100 Simplified Technical English.
- Ground terms in `CONTEXT.md` domain language when that file exists. Do not invent synonyms for glossary terms.
- Do not write comments that only repeat what the code already makes clear.
- Do not put brittle references in README or comments (versions, line numbers, temporary paths, "as of today" claims) when those details are allowed to change.

## Common footguns

- Tautological tests (asserting the mock was called the way the test just configured it).
- Mocks of modules/services we own.
- "Green suite" treated as proof the product works for a user.
- Narrating comments and README drift magnets.
- Cheating complexity or quality gates with denser syntax, hidden branching, or indirection that does not reduce real complexity.

## Python

- Runtime stays stdlib-only. New third-party runtime dependencies need an explicit decision; optional extras (e.g. fuzz) stay optional.
- Target the supported Python range in `pyproject.toml` (`requires-python`). Dev self-analysis assumes 3.12+; keep the development interpreter aligned with CI.
- Annotate public functions and non-obvious locals. Prefer `from __future__ import annotations` only if the file already uses that style.
- Prefer `pathlib.Path` over raw path strings.
- Prefer frozen `@dataclass` (or other immutable value objects) for loaded config, ruleset data, and report intermediates.
- Use `typing`/`collections.abc` protocols for seams; do not invent runtime dependency-injection frameworks.
- Parse and analyze via the stdlib `ast` (and existing project helpers). Do not add a second parsing stack.
- Tests use `unittest` and live under `tests/`. Prefer acceptance-style tests that invoke the installed/`messpy` entrypoint or public package APIs.
- Keep production-code self-analysis clean across the `codesize`, `design`, and `unusedcode` rulesets; fix new findings rather than suppressing them.
- No `# type: ignore` or broad `except:` without a short comment that states why it is safe.
