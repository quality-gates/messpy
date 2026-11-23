# Issue 302 evidence

Call-graph indexing copied growing scope maps per transition,
and call resolution rescanned the module per callable. PR #316
fixed both; this directory records the diagnosis, the locked
install, and the verification for that fix.

Start with the [run log](run-log.md). Attached logs: frozen
install, scaling before/after, full test run, self-analysis,
accumulator guard, and generated-docs check.
