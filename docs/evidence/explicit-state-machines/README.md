# Explicit state machine refactor: recorded evidence

This directory contains sanitized evidence attachments for the 39-machine refactor. See [the runtime mapping](../../state-machines.md). The generated [verification panel](verification.png) summarizes recorded command results; it is not a terminal screenshot.

## Candidate and comparison

- Baseline: `344895769043bb0f8cb87c4d24855348464932c6` (origin/main when the work began).
- Last production change: `a5b7ca4` (streaming observations and bounded candidate allocation).
- Final verification harness: `fc350bf` (all three scan exit states).
- Later commits in this PR package evidence only. Source, test and verifier commits remain reachable in the merge history.

## Verification

| Check | Recorded result | Evidence |
| --- | --- | --- |
| Acceptance suite | 503 tests, OK; 2 optional Atheris skips | [Final output](final-tests.log) |
| Public CLI comparison | 519 source samples and 19 CLI cases match baseline; exit 0/1/2 asserted | [Final expanded parity](review-parity.log), [checker](../../../scripts/verify_state_machine_parity.py) |
| Cursor negative control | Deliberately stopping after the first argument is detected | [Expanded negative control](review-parity-negative.log) |
| Analyzer resource controls | Both reject buffered933a1bc and pass final-productiona5b7ca4 | [Reproduction helper](resource-negative-control.py), [output](resource-negative-control.log) |
| Ruleset verification | 240 XML combinations and 4 symbolic contracts pass | [Final output](final-formal.log) |
| Precedence negative control | Ignoring a later priority produces counterexamples | [Negative output](ruleset-formal-negative.log) |
| Distribution | Fresh wheel builds, installs in an isolated environment, and passes self-analysis | [Command statuses](final-checks.tsv), [build](final-wheel-build.log), [install](final-wheel-install.log), [isolation](final-wheel-isolation.log), [self-analysis](final-self-analysis.log) |
| Generated documentation | Check exits 0 without differences | [Command statuses](final-checks.tsv), [output](final-docs.log) |

The full suite used Python 3.14.10. The formal verifier used CPython 3.12.12 and CrossHair 0.0.110. Empty output files are successful silent commands; their exit statuses are recorded in the manifest. The manifest's original parity run had 17 cases; the later review-driven harness run has 19. The two skipped fuzz tests require optional Atheris. No rule exemptions or timing thresholds were relaxed.

The initial baseline suite had one failure in an existing two-second timing assertion while other checks ran concurrently. Its [isolated rerun](baseline-timing-rerun.log) passed in 0.996s; the final candidate also passes that unchanged assertion. [Initial output](baseline-tests.log) is retained. The first final-check controller was stopped during parity before build/install when its virtualenv interpreter path was found to be incorrectly resolved; the corrected controller uses the virtualenv path and asserts installation isolation. The [interrupted manifest](interrupted-final-checks.tsv) has no completed commands.

## Independent review

[agy Gemini 4 Argon High's code review](agy-code-review.txt) inspected all 39 runtime mappings and the production delta through `a5b7ca4`. It found no production bugs. Its low-severity harness finding is fixed in `fc350bf`; the working-tree verification-sync observation was already fixed in `69575e8`. Optional preferences about private collector mutability and recursive traversal were declined after checking ownership and accumulation costs. [The independent design review](agy-design-review.txt) and both architecture candidates ([A](design-a.md), [B](design-b.md)) are retained alongside the [chosen design](design.md).

Read the [trail review](agy-trail-review.txt) together with the [resolution and corrections](review-resolution.md). Its three useful low-severity findings were addressed; sections2/4 contain unsupported exact details and are not accepted as source evidence. The completed [focused correction review](agy-trail-correction-review.txt) verifies these resolutions and corrects the unsupported claims. Reviews inspect source and captured execution evidence; they do not independently rerun the heavy suite. Finite differential observations and four bounded ruleset merge contracts do not prove equivalence over every Python program or formally prove all 39 machines.

## Decision trail and privacy

`decisions.tsv` is a sanitized snapshot of the append-only canonical local log, with its cutoff recorded below. Rows preserve failed attempts and later corrections. Historical `open` results are followed by resolution rows. Paths to private transcript records and opaque native-agent messages are marked `LOCAL_ONLY`; raw chat transcripts are not published. Native-agent payloads could not be read by the external reviewer, so the final claims rely on committed source and root-executed verification. A sanitized [permission-denial excerpt](permission-denial.txt) preserves the corrected retry evidence. The canonical log and active-run transcript remain in the local task audit directory. Future PR, CI, merge and cleanup actions will be recorded there after this snapshot.

Snapshot cutoff: final local review resolution (last row in decisions.tsv). PR, CI and landing are not yet claimed complete.
