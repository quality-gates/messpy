## Agent skills

### Issue tracker

Issues are tracked in the `quality-gates/messpy` GitHub repository. See `docs/agents/issue-tracker.md`.

### Triage labels

The repository uses the five default canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses the single-context domain-doc layout. See `docs/agents/domain.md`.

## Cursor Cloud specific instructions

`messpy` is a self-contained, pure-Python CLI mess detector for Python (no third-party runtime dependencies). The "application" is the `messpy` command.

### Dev environment

- A `uv`-managed virtual environment lives at `.venv` (Python 3.12) with `messpy` installed editable. The startup update script recreates it, so use `.venv/bin/messpy` and `.venv/bin/python` directly (or activate `.venv`). `uv` lives at `~/.local/bin/uv`.
- The `.venv` is built from a `uv`-managed standalone Python (`--python-preference only-managed --seed`) because the distribution test (`tests/test_distribution.py`) shells out to `python -m pip wheel` and `python -m venv`; the system `python3.12` lacks `pip`/`ensurepip`, so a plain system venv fails those tests.

### Run the app

- `messpy <paths> <format> <ruleset[,ruleset...]> [options]`; `messpy --help` lists formats and options. Exit codes: `0` clean, `1` errors, `2` findings.

### Test / lint / build

- Tests (same as CI, see `.github/workflows/ci.yml`): `.venv/bin/python -m unittest discover -s tests`. The fuzz-target test skips unless Atheris is installed — that skip is expected.
- There is no separate linter. The quality gate requires clean self-analysis: `.venv/bin/python scripts/verify_self_analysis.py .venv/bin/messpy`.
- GOTCHA: `UnusedLocalVariable` detection differs on Python 3.11, so the dev venv must stay on Python 3.12+ to match the self-analysis result verified in CI.
- Distribution build (from the CI `distribution` job): `python -m build` then `twine check dist/*`; not needed for normal dev.

### Optional: source-analysis fuzzing (`docs/fuzzing.md`)

- Requires Python 3.11 + Atheris. The Atheris wheel builds from source and needs the system packages `libclang-rt-18-dev` and `g++` (already present in the snapshot), plus `CLANG_BIN=/usr/bin/clang-18` and `CFLAGS`/`CXXFLAGS=--gcc-install-dir=/usr/lib/gcc/x86_64-linux-gnu/13` so Clang can find the GCC libstdc++ toolchain.
- GOTCHA: the documented `uv run --python 3.11 --extra fuzz ...` command recreates the project `.venv` as Python 3.11 (which then breaks the self-analysis check above). Run fuzzing in an isolated environment instead, e.g. prefix with `UV_PROJECT_ENVIRONMENT=.venv-fuzz`, and keep `.venv` on 3.12.
