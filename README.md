# messpy

`messpy` is a dependency-free Python mess detector with PHPMD-compatible rule identities, composable policies, deterministic reports, and syntax-only analysis. It supports every released Python minor from 3.11 onward.

## Install

```console
python -m pip install messpy
# or: pipx install messpy
# or: uv tool install messpy
messpy --version
```

## Run

```console
messpy <path[,path...]> <format> <ruleset[,ruleset...]> [options]
messpy src text python --ignore-tests
messpy src sarif python,opinionated --reportfile reports/messpy.sarif
```

Full command syntax, options, exit codes, and discovery behavior: [docs/usage.md](docs/usage.md).
Rule catalogue, thresholds, and Python adaptations: [docs/rules.md](docs/rules.md).
Machine report schemas: [docs/reports.md](docs/reports.md).

## Policies and custom XML

`python` is the recommended low-noise policy. Combine `python,opinionated` for every applicable built-in. Non-applicable identities such as `GotoStatement` remain loadable and quiet.

```xml
<ruleset name="team policy">
  <rule ref="python">
    <exclude name="DevelopmentCodeFragment" />
  </rule>
  <rule ref="LongVariable">
    <priority>2</priority>
    <properties>
      <property name="maximum" value="50" />
    </properties>
  </rule>
</ruleset>
```

References are case-insensitive and may name a built-in, one rule, or another XML file. Rulesets can nest; later overrides win; `<exclude name="..."/>` removes a loaded rule.

## Suppressions

```python
# messpy-disable-next-line RuleName,OtherRule
value = risky_operation()

# messpy-disable RuleName
# nested disable regions are supported
# messpy-enable RuleName
```

Names are case-insensitive. Malformed directives are ignored. Normal reports omit suppressed findings; `--strict` keeps them marked suppressed.

## Automation

```yaml
# GitHub Actions
- run: pip install messpy
- run: messpy src github python --ignore-tests
```

```yaml
# GitLab Code Quality
script: messpy src gitlab python --reportfile gl-code-quality-report.json
artifacts:
  reports:
    codequality: gl-code-quality-report.json
```

## Maintainers

CI builds and tests the package across supported Python minors and platforms, inspects wheel/sdist contents, and dogfoods the installed command. Publishing uses already-tested CI artifacts through trusted publishing; see [docs/releasing.md](docs/releasing.md). Fuzzing notes live in [docs/fuzzing.md](docs/fuzzing.md).
