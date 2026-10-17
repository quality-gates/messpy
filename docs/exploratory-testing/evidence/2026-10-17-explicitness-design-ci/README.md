# Evidence: 2026-10-17 explicitness, design review, and CI reports

Captured with `messpy` 0.1.21 from the editable `.venv` install at `d3736652324a658f2e1f9db7843fa3d64e6ba069`. Replay the confirmed bugs with the scripts in this directory. `MESS` defaults to `messpy` on `PATH`.

```sh
MESS=/path/to/messpy ./replay-live-loop-else.sh
MESS=/path/to/messpy ./replay-gitlab-fingerprint.sh
MESS=/path/to/messpy ./replay-checkstyle-order.sh
```

## Confirmed-bug captures

- `j2/src/review/live_else.py` and `j2/runs/live-else-1.stdout`, `live-else-2.stdout`: live `for`/`while` else flagged twice.
- `j1/src/billing/async_else.py`: the same false positive on `async for`.
- `replays/gitlab-left.json` and `replays/gitlab-right.json`: the same `pkg/broken.py` syntax error, different fingerprints.
- `replays/checkstyle-order.xml`: `ProcessingError` for `src/m_broken.py` sits between findings in `src/a_ok.py` and `src/z_ok.py`.

## Journeys

- `j1/`: explicitness package. `j1/runs/ordinary.stdout` is the first scan, before the later probe files existed. Later probes are `probes.stdout`, `captures.stdout`, `ownership.stdout`, `ambient.stdout`, `edges.stdout`. `onion.stdout` is the domain-layer ruleset. `corrected.stdout` and `corrected-strict.stdout` are the argument-passing and suppression variation.
- `j2/`: class-design review. `flow.stdout` is the dead-else scan. `meta.stdout` is the imported metaclass and keyword dependency at `maximum=1`. `cohesion2.stdout` is the split class. `names.stdout` is the opinionated name scan.
- `j3/`: CI report. `gate.status` is exit 1 with findings and a syntax error. `ignore-errors.status` is 2, `ignore-violations.status` is 1, `ignore-both.status` is 0. `mixed-locked.stdout` keeps the readable finding after a directory is locked. `fmt-*.stdout` are the same four files rendered in each format. `gitlab-err.stdout` keeps findings before the processing error.
