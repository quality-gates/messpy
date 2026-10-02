# Fuzzing source analysis

messpy’s analyzer is a parser-facing surface: random and hostile bytes should not crash it. The fuzz target writes generated input to one temporary `source.py`, then runs the real command path with `text` format once for each ruleset in the shared scan profile. Clean runs, ordinary findings, and processing errors are all normal outcomes. Only an unexpected exception or exit status is a fuzz failure.

## The scan profile

`fuzz/scan_profile.py` is the one place the harnesses and the replay command get their scan settings:

- `RULESETS` holds every built-in ruleset from `messpy.rulesets.built_in_ruleset_names()`, plus one combined entry that loads them all together. A new built-in ruleset joins fuzzing automatically.
- `onion` cannot load bare, because it needs a `domain`. The profile scans it through `fuzz/onion_scan_ruleset.xml`, which puts every scanned file in the domain.
- `FORMATS` comes from `messpy.cli.REPORT_FORMATS`.
- `run_scan()` and `run_command()` run the command and reject any exit status other than 0, 1 or 2.

A findings-level target, `fuzz/fuzz_findings.py`, drives the same input through `messpy.analyzer.analyze()` with no render step and asserts the `Analysis` invariants (finding and error shapes) directly.

## Run a campaign

Linux:

```sh
uv run --python 3.11 --extra fuzz python fuzz/fuzz_source_file.py -runs=1000 fuzz/corpus/source-analysis
```

macOS builds Atheris from source. After `brew install llvm`:

```sh
CLANG_BIN="$(brew --prefix llvm)/bin/clang" uv run --python 3.11 --extra fuzz python fuzz/fuzz_source_file.py -runs=1000 fuzz/corpus/source-analysis
```

The seeded corpus already covers:

- clean source
- an `ExcessiveMethodLength` finding
- malformed source
- non-UTF-8 source

Atheris may add coverage-guided inputs into that corpus directory during a campaign.

## When something crashes

Atheris stops on an unexpected messpy exception and writes the crashing input to a `crash-*` file in the working directory. Replay that exact input with no campaign state:

```sh
uv run --python 3.11 python fuzz/replay_source_file.py crash-<input>
```

If the crash is a real defect:

1. Minimize the input if needed.
2. Store the raw bytes under `fuzz/regressions/source-analysis/` with a descriptive name. The file does not need to be valid Python or use a `.py` suffix.
3. Fix the analyzer.
4. Add a deterministic command acceptance test for the expected report and exit status.
5. Keep the regression input so future campaigns and CI can replay it.

Replay every stored regression:

```sh
uv run --python 3.11 python fuzz/replay_source_file.py fuzz/regressions/source-analysis
```

The replay command scans each stored input under every profile ruleset, so a regression found under `unusedcode` or `onion` is replayed there. It reads each stored input directly. It does not read an Atheris corpus or any local fuzz campaign state.
