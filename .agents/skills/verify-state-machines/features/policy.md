# Arguments and exit policy

## Sub-features

Help, version, missing arguments, unknown options, invalid priority, repeated suffixes, and ignore-exit flags.

## How to get to it (user POV)

Run `messpy --help`, or append options to a normal analysis command.

## Driving it with the parity helper

Run `python scripts/verify_state_machine_parity.py`. It compares scans and invalid invocations, including an ignore-errors flag before and after an unknown option. Scan cases exercise all three exit codes: processing errors win by default, ignoring errors exposes findings, and ignoring both errors and violations produces zero. The helper asserts that the baseline reaches each expected code before comparing the candidate. Then run the negative control to show that stopping the cursor after its first token is detected.

## Gotchas

Flags consumed before a parse error affect its exit policy. The helper intentionally preserves token ordering; broad argument normalization would change this behavior.
