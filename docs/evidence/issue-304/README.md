# Issue 304 evidence

Class dependency analysis rescanned the class body for each
method reference and copied all class-local names per method.
PR #317 fixes both and collects dependencies without copying
the growing result; this directory records the diagnosis and
the verification for that fix.

Start with the [run log](run-log.md). Attached logs: locked
install, scaling loops before/after, profile before/after,
regression tests before/after, differential dumps, full test
run, self-analysis, accumulator guard, generated-docs check,
and state-machine parity check.
