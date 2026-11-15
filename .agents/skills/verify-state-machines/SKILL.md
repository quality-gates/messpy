---
name: verify-state-machines
description: Verify messpy CLI behavior when refactoring the state owners mapped in docs/state-machines.md.
---

# Verify state machines

## Launch

From the repository root, use a Python 3.12+ environment. No server, runtime dependencies, or external data is required. Each drive invokes the production `messpy.cli.run` in a fresh subprocess. The helper inserts this checkout's `src` explicitly.

```sh
python scripts/verify_state_machine_parity.py
```

## Doctor

```sh
PYTHONPATH=src python -c 'from messpy.cli import main; main()' --version
git cat-file -t 3448957
```

The first command must print the version and exit zero; the second must print `commit`. The baseline is the main revision preceding the state refactor. Keep that revision fixed when checking preservation.

## Drive

Run the helper above to cover [analysis](features/analysis.md), [argument and exit policy](features/policy.md), and [report publication](features/reports.md). It extracts a baseline into a temporary directory, builds a source corpus from test inputs and fixtures, and compares status, stdout, stderr, and report contents with the candidate. Every case must match.

Check that the harness can fail:

```sh
python scripts/verify_state_machine_parity.py --negative-control
```

This command breaks the argument cursor in a temporary source copy and must report detection. A missing mutation anchor, subprocess failure, or unexpected exception fails the command.

Also run the complete unit suite, self-analysis, and the separate [ruleset precedence verification](../verify-ruleset-precedence/SKILL.md). The parity corpus does not prove all Python programs equivalent. Review each changed transition against [the inventory](../../../docs/state-machines.md) and add a behavioral case for a newly exposed ordering or precision boundary.

## Evidence

Redirect each command's stdout and stderr into the task's `.audit/` directory outside this checkout. Record the checked commit, Python version, command, exit status, sample count, and case count. The helper drives the production CLI and observes report files after publication. It uses no mocked analysis results.

## Cleanup

Temporary source trees, corpus files, and reports are removed by the helper's context manager, including on failure. No persistent process is started. Keep the captured evidence after cleanup and confirm it still exists. Use `/maintain-verification-skill` when the CLI or feature map changes.

## Helpers

`scripts/verify_state_machine_parity.py` accepts `--baseline REV`, `--candidate CHECKOUT`, and `--negative-control`. A candidate supplies `src`; the corpus comes from the checkout containing the helper. Alternate baselines require an explicit preservation target recorded with the evidence.
