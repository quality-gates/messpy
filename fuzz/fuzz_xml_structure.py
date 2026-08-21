from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    import messpy.cli as cli
    import messpy.rulesets as rulesets

TAGS = ["ruleset", "rule", "exclude", "priority", "properties", "property", "description", "custom", "bogus"]
ATTRS = ["name", "ref", "value", "minimum", "maximum", "maxmethods", "maxfields", "reportlevel", "ignorepattern", "markers", "unwanted-functions"]
RULES = [
    "CyclomaticComplexity",
    "NPathComplexity",
    "ExcessiveMethodLength",
    "ExcessiveClassLength",
    "ExcessiveParameterList",
    "ExcessivePublicCount",
    "TooManyFields",
    "TooManyMethods",
    "TooManyPublicMethods",
    "ExcessiveClassComplexity",
    "ShortClassName",
    "LongClassName",
    "ShortVariable",
    "LongVariable",
    "ShortMethodName",
    "ConstantNamingConventions",
    "BooleanGetMethodName",
    "ConstructorWithNameAsEnclosingClass",
    "UnusedPrivateField",
    "UnusedLocalVariable",
    "UnusedPrivateMethod",
    "UnusedFormalParameter",
    "BooleanArgumentFlag",
    "ElseExpression",
    "StaticAccess",
    "IfStatementAssignment",
    "DuplicatedArrayKey",
    "ExitExpression",
    "GotoStatement",
    "CountInLoopExpression",
    "DevelopmentCodeFragment",
    "EmptyCatchBlock",
    "CouplingBetweenObjects",
    "GlobalVariable",
    "LackOfCohesionOfMethods",
    "CamelCaseClassName",
    "CamelCaseMethodName",
    "CamelCasePropertyName",
    "CamelCaseParameterName",
    "CamelCaseVariableName",
    "codesize",
    "naming",
    "unusedcode",
    "cleancode",
    "design",
    "controversial",
    "opinionated",
    "python",
]


def generate_xml_element(fdp: atheris.FuzzedDataProvider, depth: int = 0) -> str:
    if depth > 4 or fdp.ConsumeBool():
        leaf = fdp.ConsumeIntInRange(0, 3)
        if leaf == 0:
            return f'<rule ref="{fdp.PickValueInList(RULES)}" />'
        elif leaf == 1:
            return f'<exclude name="{fdp.PickValueInList(RULES)}" />'
        elif leaf == 2:
            return f'<priority>{fdp.ConsumeIntInRange(-5, 10)}</priority>'
        else:
            return f'<property name="{fdp.PickValueInList(ATTRS)}" value="{fdp.ConsumeUnicode(15)}" />'

    tag = fdp.PickValueInList(TAGS)
    attrs = ""
    if fdp.ConsumeBool():
        attrs += f' ref="{fdp.PickValueInList(RULES)}"'
    if fdp.ConsumeBool():
        attrs += f' name="{fdp.ConsumeUnicode(10)}"'

    inner = "\n".join(generate_xml_element(fdp, depth + 1) for _ in range(fdp.ConsumeIntInRange(1, 4)))
    return f"<{tag}{attrs}>\n{inner}\n</{tag}>"


def fuzz_xml_structure(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    xml_content = f'<?xml version="1.0"?>\n<ruleset name="test">\n'
    for _ in range(fdp.ConsumeIntInRange(1, 5)):
        xml_content += generate_xml_element(fdp, 0) + "\n"
    xml_content += "</ruleset>\n"

    with TemporaryDirectory() as temporary_directory:
        xml_file = Path(temporary_directory) / "rules.xml"
        xml_file.write_text(xml_content, encoding="utf-8", errors="replace")
        try:
            loaded = rulesets.load_rulesets([str(xml_file)])
            if loaded:
                rulesets.filter_rules(
                    loaded,
                    only=[fdp.ConsumeUnicode(10) for _ in range(fdp.ConsumeIntInRange(0, 2))],
                    enable=[fdp.ConsumeUnicode(10) for _ in range(fdp.ConsumeIntInRange(0, 2))],
                    disable=[fdp.ConsumeUnicode(10) for _ in range(fdp.ConsumeIntInRange(0, 2))],
                    minimum_priority=fdp.ConsumeIntInRange(0, 6),
                    maximum_priority=fdp.ConsumeIntInRange(0, 6),
                )
        except rulesets.RulesetError:
            pass


def main() -> None:
    atheris.Setup(sys.argv, fuzz_xml_structure)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
