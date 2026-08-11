# Reports

messpy always builds one internal list of findings and one list of processing errors, then renders both into the format you asked for. Integrations should parse a structured format. Do not scrape `text` output.

## Shared rules every consumer can rely on

- Findings and processing errors are each sorted by normalized path and line. Findings also break ties by rule name, message, context, then priority.
- Single-stream formats (`text`, `ansi`, `html`, `github`, `gitlab`, `checkstyle`) emit the ordered findings group first, then the ordered processing-errors group.
- Paths use `/`. Relative paths are relative to the working directory; paths outside it are absolute.
- Lines and columns are 1-based. Current findings use column `1`.
- Suppressed findings appear only when you pass `--strict`.
- JSON, XML, and SARIF keep findings and processing errors in separate collections. Formats with one issue stream represent processing errors as `ProcessingError` records.
- Consumers must tolerate additional fields in future compatible releases.

## Canonical fields

Every structured finding or error carries these fields.

| Field | Type | Meaning |
|---|---|---|
| `path` | string | Normalized source path. |
| `line`, `column` | integer | Source location. |
| `ruleName` | string | Stable rule identity. Processing errors use `ProcessingError`. |
| `priority` | integer | 1 highest through 5 lowest. Processing errors use 1. |
| `message` | string | Human-readable explanation. |
| `context` | string | Class, callable, member, or name context. Empty for processing errors. |
| `suppressed` | boolean | Whether an in-source directive suppressed the finding. |

Tool metadata is always `{ "name": "messpy", "version": VERSION }`, using the same version source as package metadata and `messpy --version`.

## Priority mappings

When a host format needs a severity label, messpy maps priority like this:

| Priority | GitLab severity | Checkstyle severity | SARIF level |
|---:|---|---|---|
| 1 | `blocker` | `error` | `error` |
| 2 | `critical` | `error` | `error` |
| 3 | `major` | `warning` | `warning` |
| 4 | `minor` | `warning` | `warning` |
| 5 | `info` | `warning` | `warning` |

## Which format for which job

| Goal | Format |
|---|---|
| Read findings locally | `text` or `ansi` |
| Store a complete machine report | `json` or `xml` |
| Browse a simple HTML table | `html` |
| Annotate GitHub Actions logs / PRs | `github` |
| Feed GitLab Code Quality | `gitlab` |
| Feed a Checkstyle-compatible step | `checkstyle` |
| Upload to code scanning | `sarif` |

## Formats

### JSON

Best default for custom scripts and archives.

```json
{
  "tool": { "name": "messpy", "version": "VERSION" },
  "findings": [ { "path": "...", "line": 1, "column": 1, "ruleName": "...", "priority": 3, "message": "...", "context": "...", "suppressed": false } ],
  "errors": [ { "path": "...", "line": 1, "column": 1, "ruleName": "ProcessingError", "priority": 1, "message": "...", "context": "", "suppressed": false } ]
}
```

### XML

Same information as JSON, attribute-oriented.

Root `<messpy version="VERSION">` contains `<tool name="messpy" version="VERSION" />`, then `<findings>` of empty `<finding .../>` elements and `<errors>` of empty `<error .../>` elements. Attributes are the canonical fields, XML-escaped. Boolean `suppressed` attributes use Python `True`/`False` spelling.

### text / ANSI

Human output:

```text
path:line: RuleName [priority N] [suppressed] message
path:line: ProcessingError message
```

ANSI adds terminal color escapes only. The text content is otherwise identical. The `[suppressed]` marker appears only for suppressed findings in `--strict` runs.

### HTML

A findings table with Path, Line, Rule, Priority, Message, Context, and State (`suppressed` or empty), followed by a processing-error table when needed. All text cells are HTML-escaped.

### GitHub

One workflow command per record so Actions can attach annotations to source lines:

- finding: `::warning file=PATH,line=LINE,col=1,title=RuleName [priority N]::MESSAGE (context: CONTEXT) [suppressed]`
  The trailing ` [suppressed]` segment is present only when suppressed.
- error: `::error file=PATH,line=LINE,col=1,title=ProcessingError::MESSAGE`

`%`, CR, LF, `:`, and `,` in path, title, and message values are percent-escaped.

### GitLab Code Quality

A JSON array ready for `artifacts: reports: codequality`:

```json
{
  "type": "issue",
  "tool": { "name": "messpy", "version": "VERSION" },
  "check_name": "RuleName",
  "description": "MESSAGE (context: CONTEXT) [suppressed]",
  "fingerprint": "HEX",
  "severity": "major",
  "location": { "path": "PATH", "lines": { "begin": 1 } },
  "priority": 3,
  "context": "CONTEXT",
  "suppressed": false
}
```

`fingerprint` is the lowercase hex encoding of UTF-8 `path:line:1:ruleName:message`. Severity uses the priority table above. The description omits the trailing ` [suppressed]` segment when the finding is not suppressed. Processing errors use `check_name=ProcessingError`.

### Checkstyle

Useful when an existing pipeline already knows Checkstyle XML:

```xml
<checkstyle tool="messpy" version="VERSION">
  <file name="PATH">
    <error line="1" column="1" severity="warning" message="..." source="messpy.RuleName" context="..." priority="3" suppressed="false" />
  </file>
</checkstyle>
```

Files are sorted by path. `source` is `messpy.` plus `ruleName`. Severity uses the priority table above. Boolean `suppressed` attributes are lowercase `true`/`false`.

### SARIF 2.1.0

Use this for GitHub code scanning and other SARIF hosts:

```json
{
  "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
  "version": "2.1.0",
  "runs": [{
    "tool": {
      "driver": {
        "name": "messpy",
        "version": "VERSION",
        "rules": [{ "id": "RuleName", "name": "RuleName", "shortDescription": { "text": "RuleName" } }]
      }
    },
    "results": [{
      "ruleId": "RuleName",
      "level": "warning",
      "message": { "text": "MESSAGE" },
      "locations": [{
        "physicalLocation": {
          "artifactLocation": { "uri": "PATH" },
          "region": { "startLine": 1, "startColumn": 1 }
        }
      }],
      "properties": { "priority": 3, "context": "CONTEXT", "suppressed": false },
      "suppressions": [{ "kind": "inSource" }]
    }],
    "invocations": [{
      "executionSuccessful": true,
      "toolExecutionNotifications": [{
        "level": "error",
        "message": { "text": "PATH:LINE:1: MESSAGE" },
        "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "PATH" }, "region": { "startLine": 1, "startColumn": 1 } } }]
      }]
    }]
  }]
}
```

`level` uses the priority table. `suppressions` is present only for suppressed findings. `toolExecutionNotifications` is present only when processing errors exist; then `executionSuccessful` is `false`.
