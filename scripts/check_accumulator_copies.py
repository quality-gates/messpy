from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class CopyRule:
    module: str
    owner: str
    fields: frozenset[str]
    fix: str
    former_owners: tuple[str, ...] = ()


RULES = (
    CopyRule("analyzer.py", "_with_naming_target", frozenset({"targets", "target_names"}),
             "prepend a _Cons cell and deduplicate once in _naming_roles"),
    CopyRule("analyzer.py", "_naming_function", frozenset({"callables"}),
             "prepend a _Cons cell and collect once in _naming_roles"),
    CopyRule("ownership.py", "_allocated", frozenset({"heap", "evaluated"}),
             "use _with_entry to retain _LayeredMap sharing"),
    CopyRule("ownership.py", "_State.remember", frozenset({"evaluated"}),
             "use _with_entry to retain _LayeredMap sharing", ("_cached",)),
    CopyRule("ownership.py", "_CallMemo.replay", frozenset({"heap"}),
             "use _with_entries to retain _LayeredMap sharing", ("_memo_execution",)),
    CopyRule("ownership.py", "_ObservationReplay", frozenset({"pending"}),
             "link _TraceFrame.previous instead of copying the pending stack"),
    CopyRule("ownership.py", "_ComprehensionFrame", frozenset({"traces"}),
             "compose traces with _then instead of flattening accumulated traces"),
    CopyRule("captures.py", "_CaptureWalk", frozenset({"frames"}),
             "link _CaptureFrame.previous instead of copying the frame stack"),
    CopyRule("effects.py", "_EffectReports", frozenset({"identities"}),
             "collect identities with the owned mutable set in _EffectReports.collect"),
    CopyRule("names.py", "_NameLookup", frozenset({"scopes"}),
             "advance position while retaining the shared scopes tuple"),
    CopyRule("callgraph.py", "_CallableLookup", frozenset({"scopes"}),
             "advance position while retaining the shared scopes tuple"),
)


def bounded_slice(node: ast.Slice) -> bool:
    def integer(bound: ast.AST | None) -> int | None:
        try:
            value = ast.literal_eval(bound)
        except (ValueError, TypeError):
            return None
        return value if type(value) is int else None

    lower, upper = integer(node.lower), integer(node.upper)
    step = 1 if node.step is None else integer(node.step)
    return step is not None and step > 0 and (
        (upper is not None and upper >= 0) or (lower is not None and lower < 0)
    )


def copied_attributes(node: ast.AST) -> list[ast.Attribute]:
    values: list[ast.AST] = []
    if isinstance(node, ast.Starred):
        values.append(node.value)
    elif isinstance(node, ast.Dict):
        values.extend(value for key, value in zip(node.keys, node.values) if key is None)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.BitOr, ast.Add)):
        values.extend((node.left, node.right))
    elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
        values.append(node.target)
    elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice) and not bounded_slice(node.slice):
        values.append(node.value)
    return [value for value in values if isinstance(value, ast.Attribute)]


class CopyCheck(ast.NodeVisitor):
    def __init__(self, path: Path, rules: tuple[CopyRule, ...]) -> None:
        self.path = path
        self.rules = rules
        self.scope: list[str] = []
        self.errors: list[str] = []

    def visit(self, node: ast.AST) -> None:
        scoped = isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        if scoped:
            self.scope.append(node.name)
        owner = ".".join(self.scope)
        for attribute in copied_attributes(node):
            for rule in self.rules:
                owners = (rule.owner, *rule.former_owners)
                if attribute.attr in rule.fields and any(owner == name or owner.startswith(name + ".") for name in owners):
                    self.errors.append(
                        f"{self.path}:{node.lineno}: {owner} copies accumulated {attribute.attr}; {rule.fix}."
                    )
        super().visit(node)
        if scoped:
            self.scope.pop()


def check(source_root: Path) -> list[str]:
    errors = []
    for module in sorted({rule.module for rule in RULES}):
        relative = Path("src") / "messpy" / module
        tree = ast.parse((source_root / relative).read_text(encoding="utf-8"), filename=str(relative))
        checker = CopyCheck(relative, tuple(rule for rule in RULES if rule.module == module))
        checker.visit(tree)
        errors.extend(checker.errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject known whole-accumulator copy regressions in state owners.")
    parser.add_argument("--source-root", type=Path, default=Path.cwd(), help="repository root containing src/messpy")
    arguments = parser.parse_args()
    try:
        errors = check(arguments.source_root)
    except (OSError, SyntaxError) as error:
        parser.error(str(error))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("No known accumulator-copy regressions found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
