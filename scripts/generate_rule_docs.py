from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.rulesets import BuiltInRuleReference, _BUILT_IN_RULESETS, _CATALOG


def _camel_case_adaptation(role: str) -> str:
    return (
        f"The stable family identity enforces snake_case {role}; "
        "family underscore-compatibility properties remain loadable and do not disable required snake_case."
    )


BEHAVIOR = {
    "ShortClassName": "Reports non-exempt class names shorter than `minimum`.",
    "LongClassName": "Reports non-exempt class names longer than `maximum`.",
    "ShortVariable": "Reports non-exempt parameter/property/variable names shorter than `minimum`.",
    "LongVariable": "Reports non-exempt parameter/property/variable names longer than `maximum`.",
    "ShortMethodName": "Reports non-exempt function/method names shorter than `minimum`.",
    "ConstantNamingConventions": "Reports statically identified constants that are not `UPPER_CASE`.",
    "BooleanGetMethodName": "Reports proven-boolean methods using a `get` prefix instead of a Python boolean prefix.",
    "ConstructorWithNameAsEnclosingClass": "Never reports because Python has no separately named constructor declaration.",
    "CyclomaticComplexity": "Reports callables whose Python decision count plus one is greater than or equal to `reportlevel`.",
    "NPathComplexity": "Reports callables whose syntax-only path count is greater than or equal to `minimum`.",
    "ExcessiveParameterList": "Reports callables with at least `minimum` parameters; every Python parameter form is counted once.",
    "ExcessiveMethodLength": "Reports callables with at least `minimum` physical lines.",
    "ExcessiveClassLength": "Reports classes with at least `minimum` lines; `ignore-whitespace=true` counts nonblank lines only.",
    "ExcessivePublicCount": "Reports classes with at least `minimum` public fields plus concrete methods.",
    "TooManyFields": "Reports classes with more than `maxfields` statically declared/assigned fields.",
    "TooManyMethods": "Reports classes with more than `maxmethods` concrete methods after the regular-expression `ignorepattern` exclusion.",
    "TooManyPublicMethods": "Reports classes with more than `maxmethods` public concrete methods after `ignorepattern`.",
    "ExcessiveClassComplexity": "Reports classes whose summed concrete-method cyclomatic complexity is at least `maximum`.",
    "UnusedLocalVariable": "Reports conservative lexical local/comprehension bindings with no proven use.",
    "UnusedFormalParameter": "Reports conservative callable parameters with no proven use.",
    "UnusedPrivateField": "Reports underscore-private fields with no proven class use, subject to framework/dynamic-access safeguards.",
    "UnusedPrivateMethod": "Reports underscore-private methods with no proven class use, subject to framework/dynamic-access safeguards.",
    "BooleanArgumentFlag": "Reports boolean parameters except comma-separated `exceptions` or names matching `ignorepattern`.",
    "ElseExpression": "Reports `else` after an always-terminating preceding branch.",
    "StaticAccess": "Reports class-like static calls except comma-separated `exceptions` or names matching `ignorepattern`.",
    "IfStatementAssignment": "Reports assignment expressions in `if` or `while` conditions.",
    "DuplicatedArrayKey": "Reports repeated statically equal, hashable dictionary-literal keys.",
    "ExitExpression": "Reports conservative Python process-exit calls, once per lexical scope.",
    "GotoStatement": "Never reports because Python has no goto statement.",
    "CountInLoopExpression": "Reports builtin `len()` calls in `while` conditions.",
    "DevelopmentCodeFragment": "Always reports `breakpoint` and `pdb.set_trace` calls, plus any additional comma-separated `unwanted-functions`, and case-insensitive comma-separated comment `markers` (default `TODO,FIXME,HACK`).",
    "EmptyCatchBlock": "Reports exception handlers containing only `pass` or ellipsis.",
    "CouplingBetweenObjects": "Reports classes with at least `maximum` deduplicated syntax-only external dependencies.",
    "GlobalVariable": "Reports observed mutated module bindings; `report-immutable=true` reports all initialized module bindings, including `Final`.",
    "LackOfCohesionOfMethods": "Reports classes whose Python LCOM4 connected-component value is greater than `maximum`.",
    "CamelCaseClassName": "Reports non-private class names that are not Python CapWords.",
    "CamelCaseMethodName": "Reports non-private function/method names that are not Python snake_case.",
    "CamelCasePropertyName": "Reports non-private property names that are not Python snake_case.",
    "CamelCaseParameterName": "Reports non-private, non-conventional parameter names that are not Python snake_case.",
    "CamelCaseVariableName": "Reports non-private, non-constant variable names that are not Python snake_case.",
}


DIFFERENCES = {
    "ConstructorWithNameAsEnclosingClass": ("Not applicable", "Python has no separately named constructor declaration; the rule loads and stays quiet."),
    "GotoStatement": ("Not applicable", "Python has no goto statement; the rule loads and stays quiet."),
    "BooleanGetMethodName": ("Applicable", "Requires an explicit bool annotation or conservative literal-boolean proof; accepts prefixes such as `is_`, `has_`, `can_`, `should_`, `was_`, `will_`, and `did_`."),
    "BooleanArgumentFlag": ("Applicable", "Uses boolean annotations/defaults and configurable exceptions without runtime type resolution."),
    "ElseExpression": ("Applicable", "Checks Python else clauses after terminating branches."),
    "StaticAccess": ("Applicable", "Checks conservative class-like static calls with configurable exceptions."),
    "IfStatementAssignment": ("Applicable", "Checks assignment expressions only in if/while condition contexts."),
    "DuplicatedArrayKey": ("Applicable", "The family identity checks duplicate statically knowable dictionary-literal keys."),
    "ExitExpression": ("Applicable", "Checks conservative Python exit-call syntax and visible aliases."),
    "CountInLoopExpression": ("Applicable", "Checks repeated len() calls in while conditions, not idiomatic for/range constructs."),
    "DevelopmentCodeFragment": ("Applicable", "Always includes `breakpoint` and `pdb.set_trace` even when `unwanted-functions` is empty; markers stay case-insensitive."),
    "EmptyCatchBlock": ("Applicable", "Checks pass- and ellipsis-only exception handlers."),
    "GlobalVariable": ("Applicable", "Checks observed mutable module state; report-immutable broadens the check."),
    "CouplingBetweenObjects": ("Applicable", "Counts syntax-only Python imports, bases, decorators, annotations, and external references."),
    "LackOfCohesionOfMethods": ("Applicable", "Uses LCOM4 connections through instance state and receiver calls with Python protocol/accessor exclusions."),
    "CamelCaseClassName": ("Adapted", "The stable family identity enforces Python CapWords."),
    "CamelCaseMethodName": ("Adapted", _camel_case_adaptation("functions and methods")),
    "CamelCasePropertyName": ("Adapted", _camel_case_adaptation("properties")),
    "CamelCaseParameterName": ("Adapted", _camel_case_adaptation("parameters") + " Conventional `self`/`cls`, short indexes/coordinates/exceptions, and `*args`/`**kwargs`-style names stay quiet."),
    "CamelCaseVariableName": ("Adapted", _camel_case_adaptation("variables") + " Keyword trailing underscores and conventional short names stay quiet."),
}


def render() -> str:
    component_for = {
        name: component
        for component in ["codesize", "naming", "unusedcode", "cleancode", "design", "controversial"]
        for reference in _BUILT_IN_RULESETS[component]
        for name in [_reference_name(reference)]
    }
    lines = [
        "# Rules and built-in rulesets",
        "",
        "Rule names are stable public identities. Priorities run from 1 (highest) to 5 (lowest). A threshold comparison is described by each finding message; property values below are catalogue defaults. `python` overrides `LongVariable.maximum` to `35`.",
        "",
        "| Component | Rule | Priority | Default properties | Behavior, trigger, applicability, and Python differences |",
        "|---|---|---:|---|---|",
    ]
    for rule in _CATALOG.values():
        applicability, difference = DIFFERENCES.get(
            rule.name,
            ("Applicable", "Uses direct Python syntax; no dependency import or execution is required."),
        )
        properties = ", ".join(
            f"`{_markdown(name)}={_markdown(value)}`" for name, value in rule.properties.items()
        ) or "—"
        details = f"{BEHAVIOR[rule.name]} **{applicability}.** {difference}"
        lines.append(
            f"| `{component_for[rule.name]}` | `{rule.name}` | {rule.priority} | {properties} | {_markdown(details)} |"
        )
    lines.extend(["", "## Membership", ""])
    for component, references in _BUILT_IN_RULESETS.items():
        rendered = []
        for reference in references:
            name = _reference_name(reference)
            if isinstance(reference, BuiltInRuleReference):
                overrides = ", ".join(f"{key}={value}" for key, value in reference.properties.items())
                rendered.append(f"`{name}` ({overrides})")
            else:
                rendered.append(f"`{name}`")
        lines.append(f"- **{component}**: {', '.join(rendered)}")
    lines.extend(
        [
            "",
            "Leading-underscore private names, dunder names, conventional receivers and short index/coordinate/exception names are handled conservatively. Constants and type-parameter declarations retain their Python roles. Computed names are not guessed.",
            "",
        ]
    )
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
