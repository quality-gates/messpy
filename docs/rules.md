# Rules

Each finding names a stable rule id you can suppress, disable, or tune. Priorities run from **1 (highest)** to **5 (lowest)**. Property values below are catalogue defaults; finding messages state the comparison that fired.

Start with the built-in `python` policy. It keeps useful checks and raises `LongVariable.maximum` from `20` to `35` so descriptive names are not punished. Add `opinionated` when you want the stricter set `python` leaves out.

messpy only reads syntax. It does not import your packages, execute your code, or consult your type checker. Leading-underscore private names, dunder names, conventional receivers, short index/coordinate/exception names, constants, and type-parameter declarations are handled with ordinary Python expectations. Names that cannot be known statically are not guessed.

| Component | Rule | Priority | Default properties | What it catches |
|---|---|---:|---|---|
| `naming` | `ShortClassName` | 3 | `minimum=3` | Flags class names shorter than `minimum` so cryptic one- and two-letter types stand out. |
| `naming` | `LongClassName` | 3 | `maximum=40` | Flags class names longer than `maximum` so sprawling type names get shortened or split. |
| `naming` | `ShortVariable` | 3 | `minimum=3` | Flags parameter, property, and variable names shorter than `minimum`, with ordinary short-index exemptions. |
| `naming` | `LongVariable` | 3 | `maximum=20` | Flags parameter, property, and variable names longer than `maximum`. |
| `naming` | `ShortMethodName` | 3 | `minimum=3` | Flags function and method names shorter than `minimum`. |
| `naming` | `ConstantNamingConventions` | 3 | — | Flags module/class constants that are not `UPPER_CASE` when messpy can identify them statically. |
| `naming` | `BooleanGetMethodName` | 3 | — | Flags proven-boolean methods that still use a `get_` prefix instead of a Python boolean prefix. Needs an explicit `bool` annotation or a conservative literal-boolean body. Accepts prefixes such as `is_`, `has_`, `can_`, `should_`, `was_`, `will_`, and `did_`. |
| `naming` | `ConstructorWithNameAsEnclosingClass` | 3 | — | Does nothing on Python—there is no separately named constructor declaration to check. The id remains loadable so shared policies do not break; it never fires on Python. |
| `codesize` | `CyclomaticComplexity` | 3 | `reportlevel=10` | Flags callables whose decision count plus one is at least `reportlevel` (branches, loops, handlers, comprehensions, pattern matches, and similar). |
| `codesize` | `NPathComplexity` | 3 | `minimum=200` | Flags callables whose syntax-only independent path count is at least `minimum`. |
| `codesize` | `ExcessiveParameterList` | 3 | `minimum=10` | Flags callables with at least `minimum` parameters; positional-only, keyword-only, and variadic forms each count once. |
| `codesize` | `ExcessiveMethodLength` | 3 | `minimum=100` | Flags callables with at least `minimum` physical lines, including signature and body. |
| `codesize` | `ExcessiveClassLength` | 3 | `minimum=1000`, `ignore-whitespace=false` | Flags classes with at least `minimum` lines; set `ignore-whitespace=true` to count nonblank lines only. |
| `codesize` | `ExcessivePublicCount` | 3 | `minimum=45` | Flags classes whose public fields plus concrete methods reach at least `minimum`. |
| `codesize` | `TooManyFields` | 3 | `maxfields=15` | Flags classes with more than `maxfields` statically declared or assigned fields. |
| `codesize` | `TooManyMethods` | 3 | `maxmethods=25`, `ignorepattern=(^(set\|get\|is\|has\|with))i` | Flags classes with more than `maxmethods` concrete methods after `ignorepattern` exclusions (default skips common getter/setter-style names). |
| `codesize` | `TooManyPublicMethods` | 3 | `maxmethods=10`, `ignorepattern=(^(set\|get\|is\|has\|with))i` | Flags classes with more than `maxmethods` public concrete methods after `ignorepattern`. |
| `codesize` | `ExcessiveClassComplexity` | 3 | `maximum=50` | Flags classes whose summed concrete-method cyclomatic complexity is at least `maximum`. |
| `unusedcode` | `UnusedLocalVariable` | 3 | — | Flags locals and comprehension bindings with no proven use inside their lexical scope. |
| `unusedcode` | `UnusedFormalParameter` | 3 | — | Flags callable parameters with no proven use; conventional underscore-unused names stay quiet. |
| `unusedcode` | `UnusedPrivateField` | 3 | — | Flags underscore-private fields with no proven class use, backing off when dynamic access or framework patterns make certainty impossible. |
| `unusedcode` | `UnusedPrivateMethod` | 3 | — | Flags underscore-private methods with no proven class use, with the same conservative safeguards. |
| `cleancode` | `BooleanArgumentFlag` | 1 | `exceptions=`, `ignorepattern=` | Flags boolean parameters that often force forked call-site behavior; allowlist names with `exceptions` or `ignorepattern`. Uses annotations and defaults only—no runtime type lookup. |
| `cleancode` | `ElseExpression` | 1 | — | Flags an `else` that follows a branch which always returns, raises, continues, or breaks—usually dead or misleading structure. |
| `cleancode` | `StaticAccess` | 1 | `exceptions=`, `ignorepattern=` | Flags class-like static calls that are clearer as ordinary functions or instance methods; allowlist with `exceptions` or `ignorepattern`. |
| `cleancode` | `IfStatementAssignment` | 1 | — | Flags assignment expressions (`:=`) used directly in `if` or `while` conditions. Only the condition of `if` / `while`, not every `:=` in the file. |
| `cleancode` | `DuplicatedArrayKey` | 2 | — | Flags repeated statically equal, hashable keys in a dictionary literal (the shared rule name still says Array). Dictionary literals only; dynamic or unhashable keys are not guessed. |
| `design` | `ExitExpression` | 1 | — | Flags process-exit calls such as `sys.exit` / `os._exit` once per lexical scope, including common aliases. Follows visible `sys` / `os` / builtin exit aliases and respects local shadowing. |
| `design` | `GotoStatement` | 1 | — | Does nothing on Python—there is no goto statement. The id remains loadable so shared policies do not break; it never fires on Python. |
| `design` | `CountInLoopExpression` | 2 | — | Flags builtin `len(...)` calls inside `while` conditions. Ordinary `for` loops over `range(len(...))` stay quiet. |
| `design` | `DevelopmentCodeFragment` | 2 | `unwanted-functions=`, `markers=TODO,FIXME,HACK` | Flags leftover debug calls and comment markers. `breakpoint` and `pdb.set_trace` are always on; add more via `unwanted-functions`. Default markers: `TODO,FIXME,HACK` (case-insensitive). |
| `design` | `EmptyCatchBlock` | 2 | — | Flags `except` handlers whose body is only `pass` or `...`. |
| `design` | `CouplingBetweenObjects` | 2 | `maximum=13` | Flags classes that touch at least `maximum` distinct external types/modules via imports, bases, decorators, annotations, or references. Counts syntax references only—never imports the referenced modules. |
| `design` | `GlobalVariable` | 1 | `report-immutable=false` | Flags module bindings that are actually mutated. Set `report-immutable=true` to also report initialized module state, including `Final`. Mutation-based by default so imports and true constants stay quiet. |
| `design` | `LackOfCohesionOfMethods` | 3 | `maximum=1` | Flags classes whose methods form more than `maximum` disconnected groups (LCOM4) via shared instance state and receiver calls. Properties, trivial accessors, static/class methods, and abstract/protocol stubs do not inflate the score alone. |
| `controversial` | `CamelCaseClassName` | 1 | — | Flags non-private class names that are not Python CapWords. Rule id is historical; the check is CapWords for classes. |
| `controversial` | `CamelCaseMethodName` | 1 | `allow-underscore=false`, `allow-underscore-test=false` | Flags non-private function and method names that are not Python snake_case. Rule id is historical; the check is snake_case for functions and methods. Underscore-compatibility properties stay loadable and do not disable that requirement. |
| `controversial` | `CamelCasePropertyName` | 1 | `allow-underscore=false`, `allow-underscore-test=false` | Flags non-private property names that are not Python snake_case. Rule id is historical; the check is snake_case for properties. Underscore-compatibility properties stay loadable and do not disable that requirement. |
| `controversial` | `CamelCaseParameterName` | 1 | `allow-underscore=false` | Flags non-private parameter names that are not Python snake_case, after ordinary receiver and short-name exemptions. Rule id is historical; the check is snake_case for parameters. `self` / `cls`, short indexes/coordinates/exceptions, and `*args` / `**kwargs`-style names stay quiet. |
| `controversial` | `CamelCaseVariableName` | 1 | `allow-underscore=false` | Flags non-private, non-constant variable names that are not Python snake_case. Rule id is historical; the check is snake_case for variables. Keyword trailing underscores and conventional short names stay quiet. |

## Built-in rulesets

Pass one or more of these as the third CLI argument. Comma-separate to compose.

- **`naming`** — Whether names are long enough, short enough, and conventionally shaped. `ShortClassName`, `LongClassName`, `ShortVariable`, `LongVariable`, `ShortMethodName`, `ConstantNamingConventions`, `BooleanGetMethodName`, `ConstructorWithNameAsEnclosingClass`
- **`unusedcode`** — Locals, parameters, and private members that appear never used. `UnusedPrivateField`, `UnusedLocalVariable`, `UnusedPrivateMethod`, `UnusedFormalParameter`
- **`cleancode`** — Small structural smells that make code harder to read and change. `BooleanArgumentFlag`, `ElseExpression`, `StaticAccess`, `IfStatementAssignment`, `DuplicatedArrayKey`
- **`design`** — Module and class design hazards: exits, empties, coupling, globals, cohesion. `ExitExpression`, `GotoStatement`, `CountInLoopExpression`, `DevelopmentCodeFragment`, `EmptyCatchBlock`, `CouplingBetweenObjects`, `GlobalVariable`, `LackOfCohesionOfMethods`
- **`python`** — Recommended low-noise default for ordinary projects. `CyclomaticComplexity`, `NPathComplexity`, `ExcessiveMethodLength`, `ExcessiveClassLength`, `ExcessiveParameterList`, `ExcessivePublicCount`, `TooManyFields`, `TooManyMethods`, `TooManyPublicMethods`, `ExcessiveClassComplexity`, `ShortClassName`, `LongClassName`, `LongVariable` (maximum=35), `ShortMethodName`, `ConstantNamingConventions`, `BooleanGetMethodName`, `UnusedPrivateField`, `UnusedLocalVariable`, `UnusedPrivateMethod`, `IfStatementAssignment`, `DuplicatedArrayKey`, `DevelopmentCodeFragment`, `EmptyCatchBlock`, `CouplingBetweenObjects`, `GlobalVariable`, `LackOfCohesionOfMethods`, `CamelCaseClassName`, `CamelCaseMethodName`, `CamelCasePropertyName`, `CamelCaseParameterName`, `CamelCaseVariableName`
- **`controversial`** — Strict CapWords classes and snake_case identifiers. `CamelCaseClassName`, `CamelCaseMethodName`, `CamelCasePropertyName`, `CamelCaseParameterName`, `CamelCaseVariableName`
- **`opinionated`** — Stricter checks left out of `python`; combine as `python,opinionated`. `ShortVariable`, `UnusedFormalParameter`, `BooleanArgumentFlag`, `ElseExpression`, `StaticAccess`, `CountInLoopExpression`, `ExitExpression`
- **`codesize`** — How big and branchy callables and classes have become. `CyclomaticComplexity`, `NPathComplexity`, `ExcessiveMethodLength`, `ExcessiveClassLength`, `ExcessiveParameterList`, `ExcessivePublicCount`, `TooManyFields`, `TooManyMethods`, `TooManyPublicMethods`, `ExcessiveClassComplexity`
