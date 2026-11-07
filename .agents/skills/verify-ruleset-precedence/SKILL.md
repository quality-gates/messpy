---
name: verify-ruleset-precedence
description: Verify messpy's nested XML ruleset precedence when changing ruleset loading, rule overrides, or the related CLI behavior.
---

# Verify ruleset precedence

When two nested XML policies explicitly set the priority and `minimum` of `ExcessiveMethodLength`, the later policy's values must win. A lost threshold can make a CI gate pass code that the configured policy should report.

When a later reference overrides only one field, it must preserve earlier values for omitted fields. An explicit value equal to a catalog default must still override an earlier value. These rules apply to top-level and nested references.

## Coverage and sync

The verification describes commit `9e3eff3aa622d6ad9ca472c29269f7feaaf9f30a`. Review these paths and functions when they change:

- `src/messpy/rulesets.py`: `load_rulesets`, `select_rules`, `_load_reference`, `_load_xml`, `_merge_ruleset_element`, `_overrides`, `_merge`, and `_ConfiguredRule`.
- `src/messpy/cli.py`: `run`, `_run_analysis`, and `_exit_status`.
- `src/messpy/analyzer.py`: `analyze`, `_findings`, and `_excessive_method_length_findings`.
- `docs/usage.md`: the ruleset precedence and exit-status contracts.
- `tests/test_cli.py` and `tests/test_rulesets.py`: the nested ruleset and override cases.

From the repository root, inspect committed and working-tree changes against the sync commit:

```sh
git diff 9e3eff3aa622d6ad9ca472c29269f7feaaf9f30a -- src/messpy/rulesets.py src/messpy/cli.py src/messpy/analyzer.py docs/usage.md tests/test_cli.py tests/test_rulesets.py
```

Check that each symbolic input still represents the values from an explicitly configured nested policy. If the loader changes its internal representation or merge boundary, move the contracts to the new production boundary and keep the XML behavior checks. Move the sync commit forward only after confirming that the verification describes the code at that commit.

## Run the check

From the repository root, run:

```sh
uv run --no-project --python 3.12.12 --with crosshair-tool==0.0.110 python .agents/skills/verify-ruleset-precedence/scripts/verify.py
```

The command uses `uv` to run CrossHair 0.0.110 on CPython 3.12.12. It may need network access to install them. The command exits nonzero for a counterexample or an inconclusive symbolic check. CrossHair must explicitly confirm each contract over all paths. A zero exit code from CrossHair alone is not a confirmation.

The XML check executes `load_rulesets` on 15 single policies and all 225 ordered pairs. Each policy explicitly sets a priority in `1..5` and a minimum in `{3, 5, 50}`. The expected values come from the last policy in each sequence. Separate cases check a direct priority override and partial policies that set only priority, only minimum, or both catalog defaults. The partial policies run as top-level references, inside a wrapper, and through two wrapper levels. A CLI case checks a four-line function with nested minimum values `50` then `3`.

CrossHair executes the production `_merge` with two `_ConfiguredRule` values representing policy inputs. The contracts quantify priority pairs in `1..5` and minimum pairs in `1..9`. They check later explicit values and preservation of a priority or minimum omitted by the later input. A counterexample stops that contract; a confirmed result covers its bounded symbolic paths under CrossHair's Python and solver semantics. It does not symbolically check XML parsing, field markers produced by the loader, or file I/O.

The checks do not cover other rules, properties, exclusions, nesting deeper than the stated cases, malformed XML, or arbitrary Python source. A pass applies only to the stated inputs and assumptions.

## Interpret the result

At the sync commit, all cases and four symbolic contracts pass. In the CLI case, the later minimum `3` produces a finding and exit `2` for the four-line function, despite the earlier minimum `50`.

For a new failure, compare the generated policy values, the loaded values, and the documented contract. Reproduce the case through the real loader or CLI. If the helper contract no longer matches the loader, update the contract and explain the changed boundary. If the code violates the documented behavior, report the counterexample. Preserve the property rather than changing it to match a defect.

Treat a missing contract, a timeout, an unsupported operation, a verifier error, or an `INCONCLUSIVE` result as an unfinished check. Fix the verification or report the limitation. After relevant changes that were not rechecked, use `/maintain-formal-verification-skill` to bring the verification back in line.
