from __future__ import annotations

import ast
from io import StringIO
from pathlib import Path
import random
import sys
from tempfile import TemporaryDirectory
import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    import messpy.cli as cli
    import messpy.rulesets as rulesets

RULESETS = [
    "codesize",
    "naming",
    "unusedcode",
    "cleancode",
    "design",
    "controversial",
    "opinionated",
    "python",
]

FORMATS = [
    "text",
    "xml",
    "json",
    "html",
    "ansi",
    "github",
    "gitlab",
    "checkstyle",
    "sarif",
]

NAMES = ["x", "y", "z", "foo", "bar", "baz", "LongClassNameForTesting", "Short", "a", "b", "c", "_private", "__dunder__", "CONST", "get_value", "getValue", "is_valid", "self", "cls", "len", "sys", "os", "exit", "breakpoint", "pdb"]
TYPES = ["int", "str", "bool", "list[int]", "dict[str, int]", "Optional[bool]", "Union[int, bool]", "Final[int]", "Any"]


def generate_expression(fdp: atheris.FuzzedDataProvider, depth: int = 0) -> str:
    if depth > 4 or fdp.ConsumeBool():
        leaf_type = fdp.ConsumeIntInRange(0, 6)
        if leaf_type == 0:
            return str(fdp.ConsumeIntInRange(-100, 100))
        elif leaf_type == 1:
            return repr(fdp.ConsumeUnicode(10))
        elif leaf_type == 2:
            return str(fdp.ConsumeBool())
        elif leaf_type == 3:
            return "None"
        elif leaf_type == 4:
            return "..."
        elif leaf_type == 5:
            return fdp.PickValueInList(NAMES)
        else:
            return f"({generate_expression(fdp, depth + 1)}, {generate_expression(fdp, depth + 1)})"

    op = fdp.ConsumeIntInRange(0, 9)
    if op == 0:
        return f"({generate_expression(fdp, depth + 1)} + {generate_expression(fdp, depth + 1)})"
    elif op == 1:
        return f"({generate_expression(fdp, depth + 1)} == {generate_expression(fdp, depth + 1)})"
    elif op == 2:
        return f"not {generate_expression(fdp, depth + 1)}"
    elif op == 3:
        return f"({generate_expression(fdp, depth + 1)} if {generate_expression(fdp, depth + 1)} else {generate_expression(fdp, depth + 1)})"
    elif op == 4:
        return f"[{generate_expression(fdp, depth + 1)} for {fdp.PickValueInList(NAMES)} in {generate_expression(fdp, depth + 1)}]"
    elif op == 5:
        return f"{{{generate_expression(fdp, depth + 1)}: {generate_expression(fdp, depth + 1)} for {fdp.PickValueInList(NAMES)} in {generate_expression(fdp, depth + 1)}}}"
    elif op == 6:
        return f"{{{generate_expression(fdp, depth + 1)}: {generate_expression(fdp, depth + 1)}, {generate_expression(fdp, depth + 1)}: {generate_expression(fdp, depth + 1)}}}"
    elif op == 7:
        return f"{fdp.PickValueInList(NAMES)}({generate_expression(fdp, depth + 1)})"
    elif op == 8:
        return f"({fdp.PickValueInList(NAMES)} := {generate_expression(fdp, depth + 1)})"
    else:
        return f"lambda {fdp.PickValueInList(NAMES)}: {generate_expression(fdp, depth + 1)}"


def generate_statement(fdp: atheris.FuzzedDataProvider, indent: int = 0, depth: int = 0) -> list[str]:
    sp = "    " * indent
    if depth > 4:
        return [f"{sp}pass"]

    choice = fdp.ConsumeIntInRange(0, 11)
    if choice == 0:
        return [f"{sp}{fdp.PickValueInList(NAMES)} = {generate_expression(fdp)}"]
    elif choice == 1:
        ann = fdp.PickValueInList(TYPES)
        return [f"{sp}{fdp.PickValueInList(NAMES)}: {ann} = {generate_expression(fdp)}"]
    elif choice == 2:
        lines = [f"{sp}if {generate_expression(fdp)}:"]
        lines.extend(generate_statement(fdp, indent + 1, depth + 1))
        if fdp.ConsumeBool():
            lines.append(f"{sp}else:")
            lines.extend(generate_statement(fdp, indent + 1, depth + 1))
        return lines
    elif choice == 3:
        lines = [f"{sp}while {generate_expression(fdp)}:"]
        lines.extend(generate_statement(fdp, indent + 1, depth + 1))
        return lines
    elif choice == 4:
        lines = [f"{sp}for {fdp.PickValueInList(NAMES)} in {generate_expression(fdp)}:"]
        lines.extend(generate_statement(fdp, indent + 1, depth + 1))
        return lines
    elif choice == 5:
        lines = [f"{sp}try:"]
        lines.extend(generate_statement(fdp, indent + 1, depth + 1))
        lines.append(f"{sp}except Exception as {fdp.PickValueInList(NAMES)}:")
        lines.extend(generate_statement(fdp, indent + 1, depth + 1))
        return lines
    elif choice == 6:
        params = ", ".join(f"{fdp.PickValueInList(NAMES)}: {fdp.PickValueInList(TYPES)} = {generate_expression(fdp, 3)}" for _ in range(fdp.ConsumeIntInRange(0, 4)))
        ret_type = fdp.PickValueInList(TYPES)
        fn_name = fdp.PickValueInList(NAMES)
        lines = []
        if fdp.ConsumeBool():
            lines.append(f"{sp}@property")
        elif fdp.ConsumeBool():
            lines.append(f"{sp}@staticmethod")
        lines.append(f"{sp}def {fn_name}({params}) -> {ret_type}:")
        lines.extend(generate_statement(fdp, indent + 1, depth + 1))
        lines.append(f"{sp}    return {generate_expression(fdp)}")
        return lines
    elif choice == 7:
        cls_name = fdp.PickValueInList(NAMES).capitalize()
        base = f"({fdp.PickValueInList(NAMES)})" if fdp.ConsumeBool() else ""
        lines = [f"{sp}class {cls_name}{base}:"]
        for _ in range(fdp.ConsumeIntInRange(1, 3)):
            lines.extend(generate_statement(fdp, indent + 1, depth + 1))
        return lines
    elif choice == 8:
        return [f"{sp}return {generate_expression(fdp)}"]
    elif choice == 9:
        directive = fdp.PickValueInList(["# messpy-disable", "# messpy-disable-next-line", "# messpy-enable", "# TODO", "# FIXME", "# normal comment"])
        rule = fdp.PickValueInList(RULESETS)
        return [f"{sp}{directive} {rule}"]
    elif choice == 10:
        lines = [f"{sp}match {generate_expression(fdp)}:"]
        lines.append(f"{sp}    case {fdp.PickValueInList(NAMES)} if {generate_expression(fdp)}:")
        lines.extend(generate_statement(fdp, indent + 2, depth + 1))
        lines.append(f"{sp}    case _:")
        lines.extend(generate_statement(fdp, indent + 2, depth + 1))
        return lines
    else:
        return [f"{sp}pass"]


def fuzz_python_grammar(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    ruleset = fdp.PickValueInList(RULESETS)
    report_format = fdp.PickValueInList(FORMATS)

    num_stmts = fdp.ConsumeIntInRange(1, 15)
    code_lines = ["import sys, os, typing, builtins, dataclasses", "from typing import *"]
    for _ in range(num_stmts):
        code_lines.extend(generate_statement(fdp, 0, 0))

    code = "\n".join(code_lines) + "\n"

    with TemporaryDirectory() as temporary_directory:
        source_file = Path(temporary_directory) / "source.py"
        source_file.write_text(code, encoding="utf-8", errors="replace")
        stdout = StringIO()
        stderr = StringIO()
        try:
            status = cli.run([str(source_file), report_format, ruleset], stdout, stderr)
            if status not in {0, 1, 2}:
                raise AssertionError(f"Unexpected exit status {status} on generated code:\n{code}")
        except (cli.CliError, rulesets.RulesetError):
            pass


def main() -> None:
    atheris.Setup(sys.argv, fuzz_python_grammar)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
