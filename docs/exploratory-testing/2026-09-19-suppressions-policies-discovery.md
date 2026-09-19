# Exploratory testing: suppressions, policy composition, and path discovery

**Date:** 2026-09-19
**Build:** messpy 0.1.13 at `170bc26`, installed non-editable from source into a scratch venv (`/tmp/messpy-et3/venv`, Python 3.12.12), macOS 25.6.0 (arm64)
**Interface driven:** the `messpy` CLI, as documented in `README.md`, `docs/usage.md`, `docs/reports.md`, `docs/rules.md`
**Baseline:** `.venv/bin/python -m unittest discover -s tests` — 179 tests, OK (1 expected Atheris skip)
**Scratch state:** `/tmp/messpy-et3` (exploration), `/tmp/messpy-repro3` (clean replays) — removed after the pass. Replay steps are self-contained in the issues.

This pass deliberately avoided the ground covered by [the 2026-09-12 pass](2026-09-12-cli-gate-adoption.md).

## Journeys exercised

### 1. Waive intentional findings and audit the waivers

Goal: suppress specific findings in source, confirm the gate passes, then confirm `--strict` shows every waiver in each report format.

Exercised: region `disable`/`enable` including nesting (inner `enable` leaves the outer region active, as documented), upper-case directive and rule names, a directive inside a string literal (correctly ignored), a trailing `disable-next-line` on the previous code line, a blank line between directive and target, decorated methods with stacked decorators (#137 fix holds), multi-line statements, and multi-line signatures. Under `--strict`, suppressed findings carry the documented marker in `text`, `github`, `gitlab`, `checkstyle`, and `sarif` (`suppressions: [{kind: inSource}]`).

**Found:** [#158](https://github.com/quality-gates/messpy/issues/158) — the documented placement above `def` does not waive parameter findings once the signature is wrapped over several lines (the default Black/Ruff shape).

**Found:** [#159](https://github.com/quality-gates/messpy/issues/159) — while checking the `github` rendering of waived findings: messages escape `,` and `:`, which GitHub Actions shows literally (`verbose%2C`, `(context%3A configure)`).

### 2. Compose a team policy from nested XML and built-ins

Goal: a team XML in a directory with a space in its name, referencing `sub/base.xml` by relative path, which references `rulesets/python.xml` with an `<exclude>` and a property override, then overridden again in the outer file.

Relative references, spaces in paths, `rulesets/name.xml` references, and "later references override" all behaved as documented, including both orders of `python,team.xml` and `team.xml,python`. `--only`/`--disable` reject names that are not loaded with `Error: Unknown loaded rule '…'` and exit 1. Non-integer, empty, and `1e3` property values fail clearly; surrounding whitespace is trimmed.

No bugs found.

### 3. Point the gate at a real checkout layout

Goal: scan a project from its root and from a subdirectory with `--ignore-tests`, `--exclude`, `--suffixes`, a symlinked input, and names containing spaces.

**Found:** [#157](https://github.com/quality-gates/messpy/issues/157) — `--ignore-tests` and `--exclude` match directory names *above* the scanned input. A checkout under `…/test/…`, or under any directory named in `--exclude`, is skipped entirely; messpy prints nothing and exits `0`. Default skipped directories do not have this problem (a checkout under `…/build/proj` scans normally).

Otherwise as documented: `--suffixes` accepts `py`, `.PY`, and `.py, .pyi`; an explicitly supplied directory symlink is resolved and reported with an absolute path when the target is outside the working directory; spaces in directory and file names work.

## Confirmed bugs filed

| Issue | Summary | Journey |
|---|---|---|
| [#157](https://github.com/quality-gates/messpy/issues/157) | `--ignore-tests` / `--exclude` match ancestors of the input and silently skip the whole project | 3 |
| [#158](https://github.com/quality-gates/messpy/issues/158) | `messpy-disable-next-line` above a multi-line `def` misses parameter findings | 1 |
| [#159](https://github.com/quality-gates/messpy/issues/159) | `github` format escapes `,` and `:` in messages; Actions displays them literally | 1 |

Each was reduced to a minimal file set and replayed twice from a clean directory. #159 was verified against the `actions/runner` source (`ActionCommand.cs`, `_escapeDataMappings` vs `_escapePropertyMappings`) and a local replica of `UnescapeData` applied to messpy's output — not in a live Actions run.

## Candidates examined and rejected

- **`BooleanArgumentFlag` apparently not firing.** My error: the rule is in `opinionated`, not `python`.
- **`# messpy-disable-line` not suppressing.** Not a documented directive; only `disable-next-line` and region forms exist.
- **`disable-next-line` above a multi-line *statement* not covering a finding on a continuation line.** The directive targets the next code line, as documented. Unlike #158, the docs make no promise for statements, and the waiver can be placed directly above the flagged line.
- **Nested region: the inner `enable` does not end the outer region.** Documented ("Region disables nest and must be enabled independently").
- **`--exclude src/legacy` does nothing.** `docs/usage.md` says `--exclude` matches path *components*; a multi-component value never matches. See usability notes.
- **Negative and zero `maximum` accepted.** Nonsensical but consistent, and not documented as invalid.

## Unresolved

- **`--strict` changes the exit code.** A run whose only findings are suppressed exits `0` normally and `2` under `--strict`. `docs/usage.md` describes `--strict` as keeping waivers "auditable", which reads like a reporting switch, but the name "strict" also reads like enforcement. The docs do not say which is intended.

## Usability observations

Observations from the journeys, followed by suggestions. None were filed.

- **A run that scans zero files is indistinguishable from a clean run.** `--suffixes ''`, `--suffixes pyw` on a `.py` tree, an empty directory, and every case in #157 print nothing and exit `0`; `--verbose` lists loaded rules but not how many files were analysed. *Suggestion:* report the analysed file count under `--verbose`, and consider exiting `1` when no source files were found.
- **An empty rule set also passes silently.** `--only LongVariable --disable LongVariable` exits `0` with no output. *Suggestion:* treat an empty loaded set as a configuration error.
- **`--exclude` help text and docs disagree on what it matches.** `--help` says "Skip matching source paths"; `docs/usage.md` says "normalized path components". Users who reach for `--exclude src/legacy` or `--exclude '*_pb2.py'` get no error and no effect. *Suggestion:* reject values containing `/` or glob characters, or support them.
- **`DevelopmentCodeFragment` marker findings do not name the marker.** "Development-only marker found in production source." with empty context; the user has to find which of `TODO`/`FIXME`/`HACK` on the line triggered it.

## Limitations of this pass

- Single platform (macOS arm64), single interpreter (3.12.12). Homebrew executable and Python 3.11 not exercised.
- #159's rendering was verified against runner source, not by running a workflow.
- The repository's `.venv/bin/messpy` entry point pointed at a deleted worktree interpreter (`/Users/jonathanbaldie/.fleet/worktrees/messpy-152/.venv/bin/python`). This is local environment state, not a product defect; the pass used a fresh scratch venv instead. `.venv/bin/python` itself worked, so the test baseline ran normally.
- No product configuration or instrumentation changes were made; every observation is from the documented CLI.
