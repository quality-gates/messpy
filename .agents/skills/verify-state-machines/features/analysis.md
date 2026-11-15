# Source analysis

## Sub-features

Finding order, syntax errors, suppression, strict mode, suffix selection.

## How to get to it (user POV)

Run `messpy <directory> json codesize,design,naming,unusedcode,explicitness,cleancode`.

## Driving it with the parity helper

Run `python scripts/verify_state_machine_parity.py`. It creates real `.py` inputs from the test corpus plus a malformed source, then repeats the directory scan under strict mode and suffix options. Baseline and candidate must produce identical findings, processing errors, streams, and exit status.

## Gotchas

The corpus is finite and inherits gaps from the existing tests. Changes to ownership precision, traversal order, or suppression need focused behavior tests as well as parity. Run timing-sensitive tests without competing analysis processes.
