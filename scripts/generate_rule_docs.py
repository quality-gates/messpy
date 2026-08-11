from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.rulesets import BuiltInRuleReference, _BUILT_IN_RULESETS, _CATALOG


def _camel_case_adaptation(role: str) -> str:
    return (
        f"Enforces Python snake_case for {role}. "
        "The CamelCase* rule name is historical; underscore-compatibility properties stay loadable "
        "and do not turn off the snake_case requirement."
    )


BEHAVIOR = {
    "ShortClassName": "Flags class names shorter than `minimum` so cryptic one- and two-letter types stand out.",
    "LongClassName": "Flags class names longer than `maximum` so sprawling type names get shortened or split.",
    "ShortVariable": "Flags parameter, property, and variable names shorter than `minimum`, with ordinary short-index exemptions.",
    "LongVariable": "Flags parameter, property, and variable names longer than `maximum`.",
    "ShortMethodName": "Flags function and method names shorter than `minimum`.",
    "ConstantNamingConventions": "Flags module/class constants that are not `UPPER_CASE` when messpy can identify them statically.",
    "BooleanGetMethodName": "Flags proven-boolean methods that still use a `get_` prefix instead of a Python boolean prefix.",
    "ConstructorWithNameAsEnclosingClass": "Never reports: Python has no separately named constructor declaration.",
    "CyclomaticComplexity": "Flags callables whose decision count plus one is at least `reportlevel` (branches, loops, handlers, comprehensions, pattern matches, and similar).",
    "NPathComplexity": "Flags callables whose syntax-only independent path count is at least `minimum`.",
    "ExcessiveParameterList": "Flags callables with at least `minimum` parameters; positional-only, keyword-only, and variadic forms each count once.",
    "ExcessiveMethodLength": "Flags callables with at least `minimum` physical lines, including signature and body.",
    "ExcessiveClassLength": "Flags classes with at least `minimum` lines; set `ignore-whitespace=true` to count nonblank lines only.",
    "ExcessivePublicCount": "Flags classes whose public fields plus concrete methods reach at least `minimum`.",
    "TooManyFields": "Flags classes with more than `maxfields` statically declared or assigned fields.",
    "TooManyMethods": "Flags classes with more than `maxmethods` concrete methods after `ignorepattern` exclusions (default skips common getter/setter-style names).",
    "TooManyPublicMethods": "Flags classes with more than `maxmethods` public concrete methods after `ignorepattern`.",
    "ExcessiveClassComplexity": "Flags classes whose summed concrete-method cyclomatic complexity is at least `maximum`.",
    "UnusedLocalVariable": "Flags locals and comprehension bindings with no proven use inside their lexical scope.",
    "UnusedFormalParameter": "Flags callable parameters with no proven use; conventional underscore-unused names stay quiet.",
    "UnusedPrivateField": "Flags underscore-private fields with no proven class use, backing off when dynamic access or framework patterns make certainty impossible.",
    "UnusedPrivateMethod": "Flags underscore-private methods with no proven class use, with the same conservative safeguards.",
    "BooleanArgumentFlag": "Flags boolean parameters that often force forked call-site behavior; allowlist names with `exceptions` or `ignorepattern`.",
    "ElseExpression": "Flags an `else` that follows a branch which always returns, raises, continues, or breaks—usually dead or misleading structure.",
    "StaticAccess": "Flags class-like static calls that are clearer as ordinary functions or instance methods; allowlist with `exceptions` or `ignorepattern`.",
    "IfStatementAssignment": "Flags assignment expressions (`:=`) used directly in `if` or `while` conditions.",
    "DuplicatedArrayKey": "Flags repeated statically equal, hashable keys in a dictionary literal (the shared rule name still says Array).",
    "ExitExpression": "Flags process-exit calls such as `sys.exit` / `os._exit` once per lexical scope, including common aliases.",
    "GotoStatement": "Never reports: Python has no goto statement.",
    "CountInLoopExpression": "Flags builtin `len(...)` calls inside `while` conditions. Idiomatic `for ... in range(len(...))` stays quiet.",
    "DevelopmentCodeFragment": "Flags leftover debug calls and comment markers. Always includes `breakpoint` and `pdb.set_trace`; add more via `unwanted-functions`. Default markers: `TODO,FIXME,HACK` (case-insensitive).",
    "EmptyCatchBlock": "Flags `except` handlers whose body is only `pass` or `...`.",
    "CouplingBetweenObjects": "Flags classes that touch at least `maximum` distinct external types/modules via imports, bases, decorators, annotations, or references.",
    "GlobalVariable": "Flags module bindings that are actually mutated. Set `report-immutable=true` to also report initialized module state, including `Final`.",
    "LackOfCohesionOfMethods": "Flags classes whose methods form more than `maximum` disconnected groups (LCOM4) via shared instance state and receiver calls. Properties, trivial accessors, static/class methods, and abstract/protocol stubs do not inflate the score by themselves.",
    "CamelCaseClassName": "Flags non-private class names that are not Python CapWords.",
    "CamelCaseMethodName": "Flags non-private function and method names that are not Python snake_case.",
    "CamelCasePropertyName": "Flags non-private property names that are not Python snake_case.",
    "CamelCaseParameterName": "Flags non-private parameter names that are not Python snake_case, after ordinary receiver and short-name exemptions.",
    "CamelCaseVariableName": "Flags non-private, non-constant variable names that are not Python snake_case.",
}


DIFFERENCES = {
    "ConstructorWithNameAsEnclosingClass": (
        "Not applicable",
        "Kept loadable for shared policy compatibility; stays silent on Python source.",
    ),
    "GotoStatement": (
        "Not applicable",
        "Kept loadable for shared policy compatibility; stays silent on Python source.",
    ),
    "BooleanGetMethodName": (
        "Applicable",
        "Needs an explicit `bool` annotation or a conservative literal-boolean body. Accepts prefixes such as `is_`, `has_`, `can_`, `should_`, `was_`, `will_`, and `did_`.",
    ),
    "BooleanArgumentFlag": (
        "Applicable",
        "Uses annotations and defaults only—no runtime type lookup.",
    ),
    "ElseExpression": (
        "Applicable",
        "Looks at real Python `else` clauses after terminating branches.",
    ),
    "StaticAccess": (
        "Applicable",
        "Conservative class-like call detection with configurable exceptions.",
    ),
    "IfStatementAssignment": (
        "Applicable",
        "Only assignment expressions in `if` / `while` conditions, not general `:=` use.",
    ),
    "DuplicatedArrayKey": (
        "Applicable",
        "Dictionary literals only; dynamic or unhashable keys are not guessed.",
    ),
    "ExitExpression": (
        "Applicable",
        "Tracks visible `sys` / `os` / builtin exit aliases and local shadowing.",
    ),
    "CountInLoopExpression": (
        "Applicable",
        "`while` conditions only; not ordinary `for` loops over `range(len(...))`.",
    ),
    "DevelopmentCodeFragment": (
        "Applicable",
        "`breakpoint` and `pdb.set_trace` are always on, even when `unwanted-functions` is empty.",
    ),
    "EmptyCatchBlock": (
        "Applicable",
        "Treats `pass` and ellipsis-only handlers as empty.",
    ),
    "GlobalVariable": (
        "Applicable",
        "Mutation-based by default so imports and true constants stay quiet.",
    ),
    "CouplingBetweenObjects": (
        "Applicable",
        "Syntax-only dependency count—never imports the referenced modules.",
    ),
    "LackOfCohesionOfMethods": (
        "Applicable",
        "Python LCOM4 with protocol, abstract, property, and trivial-accessor handling.",
    ),
    "CamelCaseClassName": (
        "Adapted",
        "Stable rule id; Python behavior is CapWords classes.",
    ),
    "CamelCaseMethodName": (
        "Adapted",
        _camel_case_adaptation("functions and methods"),
    ),
    "CamelCasePropertyName": (
        "Adapted",
        _camel_case_adaptation("properties"),
    ),
    "CamelCaseParameterName": (
        "Adapted",
        _camel_case_adaptation("parameters")
        + " `self` / `cls`, short indexes/coordinates/exceptions, and `*args` / `**kwargs`-style names stay quiet.",
    ),
    "CamelCaseVariableName": (
        "Adapted",
        _camel_case_adaptation("variables")
        + " Keyword trailing underscores and conventional short names stay quiet.",
    ),
}


COMPONENT_BLURBS = {
    "codesize": "How big and branchy callables and classes have become.",
    "naming": "Whether names are long enough, short enough, and conventionally shaped.",
    "unusedcode": "Locals, parameters, and private members that appear never used.",
    "cleancode": "Small structural smells that make code harder to read and change.",
    "design": "Module and class design hazards: exits, empties, coupling, globals, cohesion.",
    "controversial": "Strict CapWords / snake_case enforcement under historical CamelCase rule ids.",
    "python": "Recommended low-noise default for ordinary projects.",
    "opinionated": "Stricter checks left out of `python`; combine as `python,opinionated`.",
}


def render() -> str:
    component_for = {
        name: component
        for component in ["codesize", "naming", "unusedcode", "cleancode", "design", "controversial"]
        for reference in _BUILT_IN_RULESETS[component]
        for name in [_reference_name(reference)]
    }
    lines = [
        "# Rules",
        "",
        "Each finding names a stable rule id you can suppress, disable, or tune. Priorities run from **1 (highest)** to **5 (lowest)**. Property values below are catalogue defaults; finding messages state the comparison that fired.",
        "",
        "Start with the built-in `python` policy. It keeps useful checks and raises `LongVariable.maximum` from `20` to `35` so descriptive names are not punished. Add `opinionated` when you want the stricter set `python` leaves out.",
        "",
        "messpy only reads syntax. It does not import your packages, execute your code, or consult your type checker. Leading-underscore private names, dunder names, conventional receivers, short index/coordinate/exception names, constants, and type-parameter declarations are handled with ordinary Python expectations. Names that cannot be known statically are not guessed.",
        "",
        "| Component | Rule | Priority | Default properties | What it catches |",
        "|---|---|---:|---|---|",
    ]
    for rule in _CATALOG.values():
        applicability, difference = DIFFERENCES.get(
            rule.name,
            (
                "Applicable",
                "Reads Python syntax only; no import or execution of the target.",
            ),
        )
        properties = ", ".join(
            f"`{_markdown(name)}={_markdown(value)}`" for name, value in rule.properties.items()
        ) or "—"
        details = f"{BEHAVIOR[rule.name]} **{applicability}.** {difference}"
        lines.append(
            f"| `{component_for[rule.name]}` | `{rule.name}` | {rule.priority} | {properties} | {_markdown(details)} |"
        )
    lines.extend(
        [
            "",
            "## Built-in rulesets",
            "",
            "Pass one or more of these as the third CLI argument. Comma-separate to compose.",
            "",
        ]
    )
    for component, references in _BUILT_IN_RULESETS.items():
        blurb = COMPONENT_BLURBS.get(component, "")
        rendered = []
        for reference in references:
            name = _reference_name(reference)
            if isinstance(reference, BuiltInRuleReference):
                overrides = ", ".join(f"{key}={value}" for key, value in reference.properties.items())
                rendered.append(f"`{name}` ({overrides})")
            else:
                rendered.append(f"`{name}`")
        lines.append(f"- **`{component}`** — {blurb} {', '.join(rendered)}")
    lines.append("")
    return "\n".join(lines)


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _reference_name(reference: str | BuiltInRuleReference) -> str:
    return reference if isinstance(reference, str) else reference.name


if __name__ == "__main__":
    output = ROOT / "docs" / "rules.md"
    generated = render()
    if "--check" in sys.argv:
        if not output.is_file() or output.read_text(encoding="utf-8") != generated:
            raise SystemExit("docs/rules.md is stale; run scripts/generate_rule_docs.py")
    else:
        output.write_text(generated, encoding="utf-8")
