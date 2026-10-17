# Exploratory testing: performance and user-facing run behavior

**Date:** 2026-10-17
**Build:** `messpy` 0.1.21 at `256e270c214866e85921c78f09d7589ad1da7cce` (`main`, clean tree, 0 commits behind `origin/main` at the last fetch), editable `.venv` on Python 3.14.5, macOS 26.6.2 arm64, 16 GiB RAM.
**Interface:** the documented `messpy` CLI, plus `analyze` and `select_rules` imported from the package for per-file timing and counters. No product file was edited.
**Configuration:** default. Counters and profiles were taken by wrapping functions from outside the package.
**Machine state:** shared and loaded. Load average ranged from 3 to 79, and 5 to 21 in the last stretch.
**Evidence:** reproducers are in the filed issues. Raw run logs and scripts were kept outside the repository. See [Evidence](#evidence).

## How the numbers were taken

- **Primary metric is CPU time** (user plus sys from `/usr/bin/time -l`), because wall time moved with the load. Wall time appears only where it is the number a user waits on.
- **CPU time also drifted under load.** Re-running flagged shapes three times gave medians up to 1.9 times lower than the single sweep run on the same file. Examples are `class_methods` at 4000 elements (17.38 s sweep, 9.74 s median of 3) and the 4000-function flood (12.32 s, 6.64 s). Single-run seconds are labeled and are only indicative.
- **Where it matters the finding rests on counters and ratios.** These are calls, dictionary keys visited, items copied, and peak RSS. They do not move with load.
- **Work was confirmed in every cell.** Exit codes and output line counts were recorded for every batch. A run that timed out is marked as such.
- **cProfile is for attribution only.** It inflates absolute time.

## Journeys

| # | User goal and expected result | Actions and actual result | Status |
| --- | --- | --- | --- |
| J1 | Gate a whole repository with each ruleset and learn what it costs. Expected: seconds, not minutes. | Standard library, `--ignore-tests`. Most rulesets took 8 to 29 s of CPU. `explicitness` took 202 s and `strictexplicitness` 256 s. Discovery of 20,000 files and pruning of a 20,000-file `.git` were fast. | Explored |
| J2 | Add `explicitness` to CI for a test-heavy repository. Expected: about a minute at most. | One 637-line test file took 89 s. A 108-line reducer took 44 s. A 4,000-row data table peaked at 798 MB. | Explored |
| J3 | Scan one very large file under the default ruleset. Expected: time roughly in step with size. | Real files up to 30,454 lines took 1 to 4 s. A synthetic file with 4,000 small functions took 6.6 s and grew faster than linearly. | Explored |
| J4 | Interrupt a long scan, pipe it to `head`, and run it with stdout closed. Expected: a short message and a defined exit status. | Nothing was printed in the first 3 s of a long scan. Ctrl-C printed a traceback. A broken pipe printed one line and exited 1. A closed stdout crashed with an `AttributeError` traceback. | Explored |
| J5 | Scan generated code with very long expressions. Expected: analysis, or a per-file error while the scan continues. | A 326-term `+` chain or a 325-branch `elif` chain became a `ProcessingError` for that file. On Python 3.11 the `elif` limit is about 198. | Explored |

### J1: Whole-repository cost by ruleset

- **Starting conditions:** the Homebrew CPython 3.14.5 `lib/python3.14` tree, `messpy <tree> text <ruleset> --ignore-tests`, run one at a time.
- **Replay (1 run each unless stated):**

| Ruleset | CPU seconds |
| --- | --- |
| `python` | 29.05 (2 runs, 28.73 and 29.05) |
| `codesize` | 9.49 |
| `naming` | 10.02 |
| `unusedcode` | 14.67 |
| `cleancode` | 8.49 |
| `design` | 18.57 |
| `controversial` | 10.20 |
| `opinionated` | 18.63 |
| `explicitness` | 202.29 |
| `strictexplicitness` | 255.98 (wall 338.7 s) |
| `onion.xml` | 64.59 |

- **Variation:** A per-file timing loop over `analyze` (1 run, tests included, 1,849 files) put `explicitness` at 854 s in total. The slowest files were `test/test_format.py` (95.8 s), `test/test_buffer.py` (86.3 s), `test/test_descr.py` (23.8 s), `test/string_tests.py` (23.8 s), and `email/_header_value_parser.py` (19.7 s). Non-test modules are also slow. `inspect.py` took 13.1 s, `pydoc.py` 11.0 s, `re/_parser.py` 9.3 s, and `modulefinder.py` 8.1 s. The `email` package alone took 36.55 s of CPU under `explicitness`.
- **Discovery (3 runs each):** 20,000 small live files took 8.20 s of CPU. A tree with a 20,000-file `.git` and one source file took 0.09 s, so the `.git` pruning works. A tree with a 20,000-file `node_modules` and a 20,000-file `.git` took 6.69 s, and 4.76 s when I rebuilt it and re-measured at the end (3 runs each, the load differed). So `node_modules` is scanned at a cost of roughly 5 to 7 s per 20,000 files. `docs/usage.md:115` lists the skipped names and does not include it. A grep of `docs`, `README.md` and `src` finds no mention of `node_modules`.
- **Lasting effect:** none in the product.

### J2: `explicitness` in CI

- **Starting conditions:** `test/test_format.py` (637 lines, 29,806 bytes) and a generated reducer (the generator is in [#280](https://github.com/quality-gates/messpy/issues/280)).
- **Replay:** `messpy test_format.py text explicitness`. Exit 2, 85 output lines, CPU 89.24 s median of 3 (wall 82.9 to 118.2 s), peak RSS 79.8 MB. `strictexplicitness` took 84.02 s (1 run). `python` took 0.15 s (3 runs).
- **Reducer:** six functions call each other in a ring, with N calls each inside a `while` loop ([#280](https://github.com/quality-gates/messpy/issues/280)). CPU medians of 3 for N = 1, 2, 3, 4 were 0.25, 2.20, 7.74, and 44.24 s, at 54, 72, 90, and 108 lines.
- **Variation:** without the ring, N = 3 took 2.94 s and N = 4 took 7.39 s (3 runs each). Twelve functions with N = 4 and no loop took 2.03 s without a ring and 3.95 s with one. The looped chain took 69.97 s (1 run each). At 2, 3, and 4 calls the looped version was 16, 28, and 34 times slower than the unlooped one (12 functions, no ring, 1 run each). Real large files were fine. Under `explicitness`, pandas `frame.py` (16,710 lines) took 4.12 s and 89 MB, and the Kubernetes `core_v1_api.py` (30,454 lines) took 10.17 s and 173 MB (1 run each).
- **Why (counters, not time):** on the reducer with N = 1, 2, 3, `_execute_body` ran 150, 756, and 1,530 times, and `_joined_entries` visited 26,496, 495,000, and 2,320,422 keys. Both the number of body executions and the size of the state joined at each one grow. `cProfile` on `test_format.py` puts `_joined_entries` at 68 percent of cumulative time. That shows the same function dominates. It does not prove the reducer mechanism is the whole story for that file.
- **Memory:** a module-level `TABLE = [(0, 0), (1, 1), ...]` peaked at 42.7, 87.0, 238.4, and 798.4 MB for 500, 1,000, 2,000, and 4,000 rows (max of 3 runs). An empty `messpy --version` run peaks at 25.4 MB. The growth above that baseline is 3.6, 3.5, and 3.6 times per doubling. Flat lists of ints or strings stayed near 40 MB at 4,000 elements. Lists of pairs, lists, and dicts all reached about 795 MB (1 run each). A 4,000-row tuple table reached 671 MB under `explicitness` and 52.5 MB under `python` (1 run each). `tracemalloc` on the 1,000-row file, sampled at 79 percent of the run's peak, put 83 percent of the traced memory in two lines of `_allocated` in `ownership.py`. They copy the whole `heap` and `evaluated` dictionaries for each container literal.
- **Other shapes at 4,000 elements (3 runs each, `explicitness`):** `many_funcs` peaked at 2,448 MB, `chain_calls` at 2,443 MB, `many_suppressions` at 2,413 MB, `class_methods` at 1,353 MB, and `many_classes` at 1,290 MB. Under `python` the same shapes peaked at 103 to 141 MB in the sweep (1 run each). I did not check whether they share the `_allocated` cause.
- **Lasting effect:** none in the product.

### J3: One very large file under the default ruleset

- **Starting conditions:** `f500.py`, `f1000.py`, `f2000.py`, and `f4000.py`, made by the generator in [#282](https://github.com/quality-gates/messpy/issues/282). Each function is `def f<i>(a, b, c)` with two unused locals and a return, 5 lines each.
- **Replay:** CPU medians of 3 were 0.38, 0.81, 2.03, and 6.64 s for 2,500, 5,000, 10,000, and 20,000 lines. The ratios per doubling were 2.1, 2.5, and 3.3.
- **Why:** `analyzer._with_naming_target` was called 3,000, 6,000, 12,000, and 24,000 times and copied 4.50 million, 18.0 million, 72.0 million, and 288 million items. The copy count quadruples at each doubling. Under cProfile at 2,000 functions, `_naming_roles` was about 45 percent of the run.
- **Variation:** at 4,000 elements `class_methods` took 9.74 s, `many_classes` 4.76 s, and `many_funcs` 3.44 s (medians of 3). In the single-run sweep over 23 shapes, 11 had a log-log slope between 1.11 and 1.81 from 1,000 to 4,000 elements. I did not diagnose those. A 20,000-function file (100,000 lines) had not finished after more than 150 s of CPU and has no completed measurement. Real files were fine. The Kubernetes client (30,454 lines) took 3.82 s and pandas `frame.py` took 1.06 s (3 runs each). Large data files were fast under `python` (1 run each). `aws_managed_policies.py` (119,049 lines) took 0.23 s with exit 0, `twemoji_db.py` (21,597 lines) took 1.20 s, `common_methods_invocations.py` (24,759 lines) took 5.16 s, and `_torch_docs.py` (14,046 lines) took 0.22 s.
- **Lasting effect:** none in the product.

### J4: Interrupt, pipe, and closed stdout

- **Replay:**
  - A SIGINT sent 3.0 s into a scan of the whole standard library (`--ignore-tests`, `python`) ended the process 0.07 s later with a `KeyboardInterrupt` traceback and death by SIGINT. Nothing had been written to stdout by then (0 bytes).
  - `messpy f1000.py text python | head -1` on the 1,000-function generated file printed `Error: [Errno 32] Broken pipe` on stderr. The messpy exit status was 1.
  - `messpy messy.py text unusedcode >&-` exited 1 with `AttributeError: 'NoneType' object has no attribute 'write'` raised at `cli.py:140`. I reproduced it again while writing this report. With stdout open the same command printed the finding and exited 2.
- **Inferred, not measured:** time to first byte equals total time. The only write of the report is `stdout.write(report)` at `cli.py:140`, and the 3 s probe saw 0 bytes. My time-to-first-byte probe did not complete, so there is no measured figure.
- **Not tested:** a full disk. `/dev/full` is blocked in this sandbox.
- **Lasting effect:** none in the product.

### J5: Very long expressions

- **Starting conditions:** `def f(): return a0 + a1 + ...` with N terms, and an `if`/`elif` chain with N branches. A bisection finds the smallest N that becomes a `ProcessingError`.
- **Replay on Python 3.14.5, first failing N by ruleset (accurate to about 1 because the probe adds stack frames):**

| Ruleset | `+` chain | `elif` chain |
| --- | --- | --- |
| `design`, `python`, `opinionated`, `explicitness` | 326 | 325 |
| `naming`, `controversial` | 492 | 491 |
| `unusedcode`, `cleancode` | 986 | 985 |
| `codesize` | 986 | 493 |

- **Python 3.11.14:** every cell is within 1 of the 3.14 value except the `elif` chain under `design`, `python`, `opinionated`, and `explicitness`. There the first failing N is 197 (198 in a clean script), against 325 on 3.14.5. Python 3.12.13 and 3.13.5 were bisected only for `python`, and gave 326 and 325. Why 3.11 differs is a guess. It may be how that version counts C recursion.
- **Behavior:** a 400-term `+` chain next to a second file under `python` gave `deep.py:1: ProcessingError Could not process ...: maximum recursion depth exceeded`, a normal finding for the second file, and exit 1. The scan continues. This is the contract from the closed issue #132.
- **Lasting effect:** none in the product.

## Findings

### Confirmed

1. **`explicitness` is superlinear in calls per function and takes minutes on ordinary files.** [#280](https://github.com/quality-gates/messpy/issues/280)
   - **Impact:** a team that adds `explicitness` to CI waits about 90 s for one 637-line file, and about 200 s for the standard library without its tests. The run prints nothing until it ends, so it looks like a hang.
   - **Replay:** the reducer generator in [#280](https://github.com/quality-gates/messpy/issues/280), then `messpy ring_calls4.py text explicitness`.
   - **Expected:** time roughly in step with file size.
   - **Actual:** 44.24 s for 108 lines. Each extra call per function multiplied the time by 3.5 to 9.
   - **Repeat:** 3 runs for the key figures.

2. **`explicitness` memory is quadratic in container literals.** [#281](https://github.com/quality-gates/messpy/issues/281)
   - **Impact:** a 4,000-row table module peaks at about 800 MB, against about 50 MB under the default ruleset. Whether a CI memory limit kills it is a guess I did not test.
   - **Replay:** the generator in [#281](https://github.com/quality-gates/messpy/issues/281), then `/usr/bin/time -l messpy pairs_4000.py text explicitness`.
   - **Expected:** peak memory linear in file size.
   - **Actual:** memory above the 25.4 MB baseline grew 3.5 to 3.6 times per doubling.
   - **Repeat:** 3 runs per size.

3. **The naming pass is quadratic in names per file under the default ruleset.** [#282](https://github.com/quality-gates/messpy/issues/282)
   - **Impact:** low. A 4,000-function, 20,000-line generated file takes 6.6 s. Real files up to 30,454 lines took under 4 s.
   - **Replay:** the generator in [#282](https://github.com/quality-gates/messpy/issues/282).
   - **Actual:** the copy count quadruples at each doubling, which is exact.
   - **Repeat:** 3 runs per size for time. The copy counts are deterministic.

4. **A closed stdout ends in an `AttributeError` traceback.** [#283](https://github.com/quality-gates/messpy/issues/283)
   - **Impact:** low. A supervisor that starts the tool with fd 1 closed gets a traceback and exit 1.
   - **Replay:** `messpy messy.py text unusedcode >&-`.
   - **Repeat:** three times in total, on two different input files. Same traceback.

### Rejected

- **A long expression chain aborts the scan.** It does not. The file becomes one `ProcessingError` and the scan continues. That is the contract from the closed issue #132. The limit depends on the ruleset (326 to 986 terms), so this is a coverage limit, not a defect I will file.
- **Discovery of large trees is slow.** It is not. 20,000 files took 8.20 s of CPU and a pruned `.git` cost 0.09 s.
- **`onion` is slow on test files.** Not on `test_format.py`, where it took 0.48 s with a real ruleset file.
- **Large data files are slow under the default ruleset.** They are not. See J3.

### Unresolved

- **`onion` took 64.59 s over the standard library** (1 run) and I did not diagnose it.
- **The 20,000-function file has no completed measurement.** It ran past 150 s of CPU.
- **Other shapes also grow faster than linearly under `python`.** `class_methods`, `many_classes`, `many_funcs`, and the design pass were not diagnosed.
- **Some `explicitness` shapes are slow and undiagnosed.** `effect_diamond` took 39.24 s at 1,000 elements and `effect_chain` 39.20 s at 2,000 (1 run each). `effect_diamond` took 2.76 s at 250 and 10.19 s at 500 (3 runs each). `many_loops` took 30.31 s at 2,000, and that shape is unrealistic.
- **`explicitness` memory in the shapes listed in J2** may or may not share the `_allocated` cause.
- **Whether the reducer fully explains `test_format.py`.** The profile shows the same hot function and nothing more.

## Usability observations

These are not confirmed bugs, and none is filed.

- There is no progress output. A multi-minute `explicitness` run looks like a hang. `--verbose` shows ruleset diagnostics, not progress.
- Ctrl-C prints a long traceback instead of one line.
- A broken pipe exits 1, which is also the status for errors.
- `node_modules` is scanned by default and the docs do not say so.
- On Python 3.11 the default ruleset gives up on an `elif` ladder of about 198 branches. On 3.12 and later it is 325.

## Scope limits

- Single machine. Python 3.14.5 for most runs. The recursion bisection also ran on 3.11, 3.12, and 3.13.
- Synthetic shapes stress one construct each. They show scaling, not what a typical repository costs. The `nested_closures` shape stops growing at 91 lines, so its flat line says nothing about nesting.
- The standard library totals and the sweep cells are mostly single runs on a loaded machine.
- The CLI help lists no parallelism option, so I did not test one.
- No memory limit was applied. Out-of-memory behavior is untested.
- I did not look for fixes. No product code or docs were changed.

## Mistakes made during the pass

- I passed an output path as the wrong argument to a profiling script and overwrote one generated input file. I regenerated it and checked it matched the generator byte for byte. No product file was touched.
- I assumed `node_modules` was ignored and ran an "ignored tree" test that scanned it. I re-ran it with `.git` only.
- I first reported flood timings from single runs. Re-running them three times lowered them by up to 1.9 times, and the filed issues use the repeated figures.
- I first noted that the recursion threshold was stable on Python 3.11 to 3.14. The `elif` threshold on 3.11 is 197, so I re-measured it per ruleset and per version.
- My first draft of this report had figures I could not trace to a recorded run. I checked each against the recorded runs and corrected them.

## Evidence

- Reproducers are inline in the filed issues. [#280](https://github.com/quality-gates/messpy/issues/280), [#281](https://github.com/quality-gates/messpy/issues/281), [#282](https://github.com/quality-gates/messpy/issues/282), [#283](https://github.com/quality-gates/messpy/issues/283).
- The raw run records (one JSON line per timed batch), the counter logs, the 23-shape sweep, the recursion bisection log, and the timing and counting scripts were kept outside the repository and are not committed here.
- A maintainer who needs a figure can re-take it from the issue reproducers. The deterministic counters in [#280](https://github.com/quality-gates/messpy/issues/280) and [#282](https://github.com/quality-gates/messpy/issues/282) do not depend on machine load.
