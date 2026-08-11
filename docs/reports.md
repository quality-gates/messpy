# Report contract

Findings and processing errors are each deterministically ordered by normalized path and line (with rule/message/context/priority tie-breakers for findings). Single-stream formats emit the ordered findings group before the ordered processing-errors group. Relative paths are relative to the working directory; outside paths are absolute. Separators are `/`. Lines and columns are 1-based; current findings use column `1`.

Suppressed findings appear only with `--strict`. Processing errors remain separate in JSON, XML, and SARIF and are represented as `ProcessingError` records in formats with one issue collection. Consumers must tolerate additional fields in future compatible releases.

## Canonical fields

| Field | Type | Meaning |
|---|---|---|
| `path` | string | Normalized source path. |
| `line`, `column` | integer | Source location. |
| `ruleName` | string | Stable rule identity; errors use `ProcessingError`. |
| `priority` | integer | 1 highest through 5 lowest; processing errors use 1. |
| `message` | string | Human-readable explanation. |
| `context` | string | Class/callable/member/name context, or empty for errors. |
| `suppressed` | boolean | Whether an in-source directive suppressed the finding. |

Tool metadata is always `{ "name": "messpy", "version": VERSION }`, where `VERSION` is the single package version source.

## Priority mappings

| Priority | GitLab severity | Checkstyle severity | SARIF level |
|---:|---|---|---|
| 1 | `blocker` | `error` | `error` |
| 2 | `critical` | `error` | `error` |
| 3 | `major` | `warning` | `warning` |
| 4 | `minor` | `warning` | `warning` |
| 5 | `info` | `warning` | `warning` |

## Formats

### JSON

```json
{
  "tool": { "name": "messpy", "version": "VERSION" },
  "findings": [ { "path": "...", "line": 1, "column": 1, "ruleName": "...", "priority": 3, "message": "...", "context": "...", "suppressed": false } ],
  "errors": [ { "path": "...", "line": 1, "column": 1, "ruleName": "ProcessingError", "priority": 1, "message": "...", "context": "", "suppressed": false } ]
}
```

### XML

Root `<messpy version="VERSION">` contains `<tool name="messpy" version="VERSION" />`, then `<findings>` of empty `<finding .../>` elements and `<errors>` of empty `<error .../>` elements. Attributes are the canonical fields, XML-escaped. Boolean `suppressed` attributes use Python `True`/`False` spelling.

### text / ANSI

`path:line: RuleName [priority N] [suppressed] message`

Processing errors: `path:line: ProcessingError message`. ANSI adds terminal color escapes only; the text content is otherwise identical.

### HTML

A findings table with Path, Line, Rule, Priority, Message, Context, and State (`suppressed` or empty), followed by a processing-error table when needed. All text cells are HTML-escaped.

### GitHub

One annotation per record:

- finding: `::warning file=PATH,line=LINE,col=1,title=RuleName [priority N]::MESSAGE (context: CONTEXT) [suppressed]`
  The trailing ` [suppressed]` segment is present only when suppressed.
- error: `::error file=PATH,line=LINE,col=1,title=ProcessingError::MESSAGE`

`%`, CR, LF, `:`, and `,` in path/title/message values are percent-escaped.

### GitLab Code Quality

A JSON array of objects:

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

```xml
<checkstyle tool="messpy" version="VERSION">
  <file name="PATH">
    <error line="1" column="1" severity="warning" message="..." source="messpy.RuleName" context="..." priority="3" suppressed="false" />
  </file>
</checkstyle>
```

Files are sorted by path. `source` is `messpy.` plus `ruleName`. Severity uses the priority table above. Boolean `suppressed` attributes are lowercase `true`/`false`.

### SARIF 2.1.0

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
