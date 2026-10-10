# Evidence: 2026-10-10 production gate, team policy, and onion

Captured with `messpy` 0.1.20 from the editable `.venv` install. Replay from this directory.

## Unreadable directory

`replay-unreadable-directory.sh` restores permissions, scans `j1/mixed`, locks `j1/mixed/secret`, and scans again. It also contrasts an unreadable file.

```sh
MESS=/path/to/messpy ./replay-unreadable-directory.sh
```

Committed captures are in `j1/runs/baseline*`, `j1/runs/locked*`, `j1/runs/two-paths*`, and `j1/runs/file-contrast*`. `locked-ignore.json` is absent because `--reportfile` was never written.

## Other journeys

- `j1/`: production package, syntax error, generated tree, tests. `j1/runs/ordinary.*`, `with-tests.*`, `flow.*`, `gate.json`.
- `j2/`: team XML policy. `j2/runs/team.*`, `default.*`, `broken.*`, `only-missing.*`.
- `j3/`: onion ruleset. `j3/runs/onion.*`, `missing-domain.*`, `boot.*`, `pricing.*`.
