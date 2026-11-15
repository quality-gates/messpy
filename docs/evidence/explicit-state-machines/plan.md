# Make messpy's state machines explicit

The user wants every machine in the preceding inventory made explicit, preserving behavior, with independent agy Gemini 4 review and an auditable decision trail.

## Workflow

- [x] Read the Principles section of the poteto-mode skill.
- [x] Phase A: Frame.
- [x] Phase B: Design the workflow.
- [x] Phase C: Run the loop.
- [x] Phase D: Keep the audit trail.
- [ ] Phase E: Verify and hand back.

Done means all 39 inventory entries have authoritative named state and transitions used by runtime callers, or an existing explicit representation verified against current main. Prose, unused models, and a registry alone do not complete an entry. Public behavior must match the baseline on the existing acceptance suite and a differential corpus. Required gates, ruleset formal verification correspondence, and independent Gemini 4 code and trail review must pass. Then land through the repository PR workflow and verify sync.

## Execution units

1. Read current-main code and compare two architecture candidates. Prefer local domain types over a universal machine framework.
2. Capture baseline acceptance and public CLI observations. Create a complete inventory mapping with executable evidence.
3. Refactor ownership, deferred execution, effects, captures, and reachability. Verify the unit.
4. Refactor CLI, rulesets, file discovery, and suppression. Verify the unit and ruleset verifier.
5. Refactor binding, naming, rule proofs, graph algorithms, and caches. Verify the unit.
6. Integrate and check every inventory entry against the real source and behavior. Add verification coverage for important transitions and mutation-check that coverage.
7. Obtain agy Gemini 4 independent code and trail review. Resolve substantiated findings and repeat affected gates.
8. Audit the decision trail against this workspace's transcript, run final checks, land through a PR, verify remote and local state, and clean up owned worktrees.

## Throughput checkpoint

There are 39 inventory entries across the original 16 production modules. Current main has added four modules and changed several owners since the inventory. Grounding and baseline are blocking. Design candidates are read-only and have separate output files. Implementation workers use separate worktrees, split by module ownership, with one integration writer. Each unit must pass its relevant checks before integration. Runtime tests, self-analysis, differential observations, and independent coverage review jointly establish the result; none alone proves completeness.

Base is origin/main at 3448957. The original checkout and its two branch-local commits remain untouched.
