# Fuzzing source analysis

messpy’s analyzer is a parser-facing surface: random and hostile bytes should not crash it. The fuzz target writes generated input to one temporary `source.py`, then runs the real command path with `text` format and the `codesize` ruleset. Clean runs, ordinary findings, and processing errors are all normal outcomes. Only an unexpected exception is a fuzz failure.

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

The replay command reads each stored input directly. It does not read an Atheris corpus or any local fuzz campaign state.
