# messpy

Catch maintainability problems in Python before they calcify: oversized functions and classes, tangled dependencies, dead private code, muddy naming, and other mess that reviews keep rediscovering.

`messpy` is a local CLI. It reads source as text, never imports or runs your project, and needs no project dependencies installed. Python 3.11+.

## Quick start

```console
python -m pip install messpy
messpy src text python --ignore-tests
```

That scans `src` with the recommended low-noise policy and prints findings on stdout. Exit `0` is clean, `2` means findings, `1` means the tool or a source file failed.

Common next steps:

```console
messpy src text python,opinionated --ignore-tests
messpy src sarif python --ignore-tests --reportfile reports/messpy.sarif
messpy src github python --ignore-tests
```

Full command syntax, options, and discovery: [docs/usage.md](docs/usage.md).
What each rule checks: [docs/rules.md](docs/rules.md).
Machine-readable report shapes: [docs/reports.md](docs/reports.md).

## Install

```console
python -m pip install messpy
# or: pipx install messpy
# or: uv tool install messpy
messpy --version
```

## Tune the gate

Start with `python`. Add `opinionated` when you want the stricter checks the recommended set leaves out. Point at a custom XML ruleset when thresholds or membership need to live in the repo:

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

```console
messpy src text path/to/team-policy.xml --ignore-tests
```

## Suppress one intentional exception

```python
# messpy-disable-next-line RuleName
value = deliberate_exception()
```

Region form: `messpy-disable` / `messpy-enable`. Names are case-insensitive. `--strict` keeps suppressed findings visible in the report.

## Drop it into CI

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

Release process: [docs/releasing.md](docs/releasing.md). Fuzzing: [docs/fuzzing.md](docs/fuzzing.md).
