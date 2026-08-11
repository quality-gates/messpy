# Command usage

```console
messpy <path[,path...]> <format> <ruleset[,ruleset...]> [options]
```

Supported Python versions are every released minor from 3.11 onward. Syntax acceptance follows the running interpreter; unsupported newer syntax becomes a per-file processing error.

## Formats

`text`, `ansi`, `xml`, `json`, `html`, `github`, `gitlab`, `checkstyle`, `sarif`.

## Rulesets

Built-ins: `codesize`, `naming`, `unusedcode`, `cleancode`, `design`, `controversial`, recommended `python`, and stricter `opinionated`. Comma-separated values may mix built-ins and custom XML paths. See [rules.md](rules.md) for membership, defaults, thresholds, and Python adaptations.

## Options

| Option | Meaning |
|---|---|
| `-h`, `--help` | Show command help. |
| `-v`, `--version` | Show the package version. |
| `--suffixes LIST` | Replace the default `.py,.pyi` suffix list. |
| `--exclude LIST` | Exclude matching normalized paths. |
| `--ignore-tests` | Skip conventional test directories and `test_*.py` / `*_test.py` modules. |
| `--only LIST`, `--enable LIST` | Keep only named rules already present in loaded policy. |
| `--disable LIST` | Remove named loaded rules. |
| `--minimumpriority 1-5`, `--maximumpriority 1-5` | Inclusive priority filters. Kebab-case aliases are accepted. |
| `--reportfile PATH` | Atomically replace a report file instead of writing stdout. `--report-file` is accepted. |
| `--color auto\|always\|never` | Control text color; `ansi` always uses color. |
| `--strict` | Include findings hidden by source suppressions. |
| `--verbose` | Write loaded-rule diagnostics to stderr. |
| `--ignore-errors-on-exit` | Return success despite operational or processing errors. |
| `--ignore-violations-on-exit` | Return success despite findings. |

Value options accept `--option value` or `--option=value`.

## Exit status

| Code | Meaning |
|---:|---|
| 0 | Clean, or every relevant failure was explicitly ignored. |
| 1 | Command, configuration, discovery, report-write, or source processing error. Errors take precedence over findings. |
| 2 | Selected findings and no non-ignored processing error. |

Ignore-on-exit flags change only the process status; report contents stay complete.

## Discovery

- Paths are resolved, walked recursively, normalized to `/`, sorted, and deduplicated.
- Default suffixes are `.py` and `.pyi`; `--suffixes` replaces that list for both explicit files and discovered files.
- Nested directory symlinks are not followed; an explicitly supplied directory symlink is resolved and scanned.
- Default skipped directory names include VCS directories, virtual environments, `site-packages`, `__pycache__`, Python tool caches, and common build, dist, coverage, generated, output, and temporary directories.
- Tests are included unless `--ignore-tests` is set.
- A malformed or unreadable file becomes a `ProcessingError`; other valid files still analyze.
