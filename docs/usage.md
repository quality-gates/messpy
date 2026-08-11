# Using messpy

Point messpy at Python source, pick a report format, pick a policy, and read the findings. It never imports your code, never installs your dependencies, and never runs your tests.

```console
messpy <path[,path...]> <format> <ruleset[,ruleset...]> [options]
```

Examples:

```console
messpy src text python --ignore-tests
messpy app,lib json python,opinionated --reportfile messpy.json
messpy . github path/to/team-policy.xml --exclude generated --ignore-tests
```

Supported interpreters are every released Python minor from 3.11 onward. Syntax acceptance follows the interpreter running messpy: if that interpreter cannot parse a file, messpy records a processing error for that file and continues with the rest.

## Choose a format

| Format | Use it when |
|---|---|
| `text` | You are reading findings in a terminal. |
| `ansi` | Same as `text`, always with color. |
| `json` / `xml` | You are writing a custom consumer or storing a full machine report. |
| `html` | You want a simple browsable table. |
| `github` | GitHub Actions should annotate the relevant lines. |
| `gitlab` | GitLab Code Quality should show findings on the merge request. |
| `checkstyle` | An existing Checkstyle-compatible CI step will ingest the file. |
| `sarif` | You are uploading to code scanning or another SARIF consumer. |

Field-level shapes for every format are in [reports.md](reports.md).

## Choose a policy

| Ruleset | Intent |
|---|---|
| `python` | Recommended default. Low noise on ordinary Python. |
| `opinionated` | The stricter checks `python` deliberately omits. Combine as `python,opinionated`. |
| `codesize` | Size and complexity only. |
| `naming` | Name length, constants, boolean getters. |
| `unusedcode` | Unused locals, parameters, and private members. |
| `cleancode` | Boolean flags, dead `else`, static access, walrus-in-condition, duplicate dict keys. |
| `design` | Exits, empty handlers, coupling, globals, cohesion, development leftovers. |
| `controversial` | CapWords classes and snake_case identifiers. |

Comma-separated values may mix built-ins and custom XML paths:

```console
messpy src text python,path/to/extra.xml --ignore-tests
```

Membership, defaults, thresholds, and Python-specific behavior for every rule are in [rules.md](rules.md).

## Options

| Option | Meaning |
|---|---|
| `-h`, `--help` | Show command help. |
| `-v`, `--version` | Show the package version. |
| `--suffixes LIST` | Replace the default `.py,.pyi` suffix list. |
| `--exclude LIST` | Exclude matching normalized paths (generated trees, vendored code, one awkward package). |
| `--ignore-tests` | Skip conventional test directories and `test_*.py` / `*_test.py` modules. Use this for a production-code gate. |
| `--only LIST`, `--enable LIST` | Keep only named rules already present in the loaded policy. Useful for bisecting a noisy run. |
| `--disable LIST` | Remove named loaded rules without writing new XML. |
| `--minimumpriority 1-5`, `--maximumpriority 1-5` | Inclusive priority filters. Start enforcement at priority 1–2, then widen. Kebab-case aliases are accepted. |
| `--reportfile PATH` | Atomically replace a report file instead of writing stdout. `--report-file` is accepted. |
| `--color auto\|always\|never` | Control text color; `ansi` always uses color. |
| `--strict` | Include findings hidden by source suppressions so exceptions stay auditable. |
| `--verbose` | Write loaded-rule diagnostics to stderr when a ruleset is not loading as expected. |
| `--ignore-errors-on-exit` | Return success despite operational or processing errors. Report contents still include the errors. |
| `--ignore-violations-on-exit` | Return success despite findings. Useful while adopting; report contents stay complete. |

Value options accept `--option value` or `--option=value`.

## Exit status

Wire these into CI the same way you would any other quality gate.

| Code | Meaning |
|---:|---|
| 0 | Clean, or every relevant failure was explicitly ignored. |
| 1 | Command, configuration, discovery, report-write, or source processing error. Errors take precedence over findings. |
| 2 | Selected findings and no non-ignored processing error. |

Ignore-on-exit flags change only the process status. They never remove rows from the report.

## What gets scanned

- Paths are resolved, walked recursively, normalized to `/`, sorted, and deduplicated so repeated inputs do not double findings.
- Default suffixes are `.py` and `.pyi`. `--suffixes` replaces that list for both explicit files and discovered files.
- Nested directory symlinks are not followed. An explicitly supplied directory symlink is resolved and scanned.
- Default skipped directory names include VCS directories, virtual environments, `site-packages`, `__pycache__`, Python tool caches, and common build, dist, coverage, generated, output, and temporary directories.
- Tests are included unless `--ignore-tests` is set, so excluding test quality is an explicit choice.
- A malformed or unreadable file becomes a `ProcessingError`. Other valid files still analyze.

## Custom XML policy

Keep team thresholds next to the code:

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

References are case-insensitive and may name a built-in, one rule, `rulesets/name.xml`, or another XML file relative to the current file. Rulesets can nest; cycles and unknown references fail. Later references override earlier priority and property values. `<exclude name="..."/>` removes a rule from the referenced set.

## Suppressions in source

Waive one intentional finding without weakening the whole gate:

```python
# messpy-disable-next-line LongVariable,CyclomaticComplexity
def deliberately_dense_helper(...):
    ...

# messpy-disable DevelopmentCodeFragment
# ... temporary debug region ...
# messpy-enable DevelopmentCodeFragment
```

Names are case-insensitive. Region disables nest and must be enabled independently. Malformed directives are ignored and never reinterpret `noqa`, type-checker, formatter, or coverage comments. Normal reports omit suppressed findings; `--strict` keeps them marked suppressed.
