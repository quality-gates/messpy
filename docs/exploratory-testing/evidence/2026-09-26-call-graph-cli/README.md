# Captured evidence

Build under exploration: `messpy` 0.1.15 at `3323e964f38568483b356ff9ecdf83a693c1a750`, installed editable in the project `.venv` (Python 3.12.12), on macOS arm64. All runs drove the public `messpy` CLI.

To replay, run these commands from this directory with `messpy` on `PATH`:

```console
messpy j1/disconnected.py text j1/cohesion.xml
messpy j1/disconnected.py json j1/cohesion.xml --reportfile j1/disconnected.json
messpy j1/connected.py text j1/cohesion.xml
messpy j1/accessors.py text j1/cohesion.xml
messpy j2/shop/domain text j2/onion.xml
messpy j2/shop/domain json j2/onion.xml --reportfile j2/packaged-imports.json
messpy j2-unaliased/shop/domain text j2/onion.xml
messpy j3/src text python
messpy j3/src json python --reportfile j3/portable-scan.json
```

The command outcomes below were transcribed from captured stdout, stderr, and exit status. The three JSON reports are in `runs/`; marker state after each J3 run is in `runs/j3-*.markers.json`.

## J1: class cohesion

| Command | Exit | Captured result |
|---|---:|---|
| `messpy j1/disconnected.py text j1/cohesion.xml` (both runs) | 2 | Same output on both runs; stderr empty. |
| `messpy j1/disconnected.py json j1/cohesion.xml --reportfile j1/disconnected.json` | 2 | stdout and stderr empty; JSON report has one finding, zero errors. |
| `messpy j1/connected.py text j1/cohesion.xml` | 0 | stdout and stderr empty. |
| `messpy j1/accessors.py text j1/cohesion.xml` | 0 | stdout and stderr empty. |

Disconnected class output:

```text
j1/disconnected.py:1: LackOfCohesionOfMethods [priority 3] The class FulfilmentDesk has a Lack of Cohesion Of Methods (LCOM4) value of 2. Consider to split this class into 2 smaller classes.
```

## J2: domain import boundaries

With package `__init__.py` files present, both `messpy j2/shop/domain text j2/onion.xml` replays exited 2, emitted the same four findings, and had empty stderr:

```text
j2/shop/domain/orders.py:1: DomainOuterImport [priority 2] The module imports shop.infra.repository, which belongs to the outer layer shop.infra. The domain layer must not know about the interaction layer.
j2/shop/domain/orders.py:2: DomainOuterImport [priority 2] The module imports shop.infra.repository, which belongs to the outer layer shop.infra. The domain layer must not know about the interaction layer.
j2/shop/domain/orders.py:5: DomainOuterImport [priority 2] The module imports shop.infra.models, which belongs to the outer layer shop.infra. The domain layer must not know about the interaction layer.
j2/shop/domain/pricing.py:1: DomainOuterImport [priority 2] The module imports shop.infra.rates, which belongs to the outer layer shop.infra. The domain layer must not know about the interaction layer.
```

The JSON report contains four findings and zero errors. The unaliased variation exited 2 with the same four findings under `j2-unaliased/shop/domain`.

The first scratch package omitted `__init__.py` files. That run exited 2 with only the three non-relative findings; its captured output and status are `runs/j2-incomplete-package-initial.*.txt`. Adding the documented package markers and infrastructure modules made the relative import resolvable; both subsequent clean replays reported it. This was a fixture setup issue, not a product failure.

## J3: source is not executed

Text and JSON scans both exited 0 with empty stdout/stderr. The JSON report has zero findings and errors. The source modules would write marker files if run, but both markers were absent after each scan.
