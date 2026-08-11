from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ElementTree


@dataclass(frozen=True)
class LoadedRule:
    name: str
    priority: int
    properties: dict[str, str]


class RulesetError(Exception):
    pass


_CATALOG = {
    "shortclassname": LoadedRule(
        name="ShortClassName",
        priority=3,
        properties={"minimum": "3"},
    ),
    "longclassname": LoadedRule(
        name="LongClassName",
        priority=3,
        properties={"maximum": "40"},
    ),
    "shortvariable": LoadedRule(
        name="ShortVariable",
        priority=3,
        properties={"minimum": "3"},
    ),
    "longvariable": LoadedRule(
        name="LongVariable",
        priority=3,
        properties={"maximum": "20"},
    ),
    "shortmethodname": LoadedRule(
        name="ShortMethodName",
        priority=3,
        properties={"minimum": "3"},
    ),
    "constantnamingconventions": LoadedRule(
        name="ConstantNamingConventions",
        priority=3,
        properties={},
    ),
    "booleangetmethodname": LoadedRule(
        name="BooleanGetMethodName",
        priority=3,
        properties={},
    ),
    "constructorwithnameasenclosingclass": LoadedRule(
        name="ConstructorWithNameAsEnclosingClass",
        priority=3,
        properties={},
    ),
    "cyclomaticcomplexity": LoadedRule(
        name="CyclomaticComplexity",
        priority=3,
        properties={"reportlevel": "10"},
    ),
    "npathcomplexity": LoadedRule(
        name="NPathComplexity",
        priority=3,
        properties={"minimum": "200"},
    ),
    "excessiveparameterlist": LoadedRule(
        name="ExcessiveParameterList",
        priority=3,
        properties={"minimum": "10"},
    ),
    "excessivemethodlength": LoadedRule(
        name="ExcessiveMethodLength",
        priority=3,
        properties={"minimum": "100"},
    ),
    "excessiveclasslength": LoadedRule(
        name="ExcessiveClassLength",
        priority=3,
        properties={"minimum": "1000", "ignore-whitespace": "false"},
    ),
    "excessivepubliccount": LoadedRule(
        name="ExcessivePublicCount",
        priority=3,
        properties={"minimum": "45"},
    ),
    "toomanyfields": LoadedRule(
        name="TooManyFields",
        priority=3,
        properties={"maxfields": "15"},
    ),
    "toomanymethods": LoadedRule(
        name="TooManyMethods",
        priority=3,
        properties={"maxmethods": "25", "ignorepattern": "(^(set|get|is|has|with))i"},
    ),
    "toomanypublicmethods": LoadedRule(
        name="TooManyPublicMethods",
        priority=3,
        properties={"maxmethods": "10", "ignorepattern": "(^(set|get|is|has|with))i"},
    ),
    "excessiveclasscomplexity": LoadedRule(
        name="ExcessiveClassComplexity",
        priority=3,
        properties={"maximum": "50"},
    ),
    "unusedlocalvariable": LoadedRule(
        name="UnusedLocalVariable",
        priority=3,
        properties={},
    ),
    "unusedformalparameter": LoadedRule(
        name="UnusedFormalParameter",
        priority=3,
        properties={},
    ),
    "unusedprivatefield": LoadedRule(
        name="UnusedPrivateField",
        priority=3,
        properties={},
    ),
    "unusedprivatemethod": LoadedRule(
        name="UnusedPrivateMethod",
        priority=3,
        properties={},
    ),
    "booleanargumentflag": LoadedRule(
        name="BooleanArgumentFlag", priority=1, properties={"exceptions": "", "ignorepattern": ""}
    ),
    "elseexpression": LoadedRule(name="ElseExpression", priority=1, properties={}),
    "staticaccess": LoadedRule(
        name="StaticAccess", priority=1, properties={"exceptions": "", "ignorepattern": ""}
    ),
    "ifstatementassignment": LoadedRule(name="IfStatementAssignment", priority=1, properties={}),
    "duplicatedarraykey": LoadedRule(name="DuplicatedArrayKey", priority=2, properties={}),
}
_BUILT_IN_RULESETS = {
    "naming": (
        "ShortClassName",
        "LongClassName",
        "ShortVariable",
        "LongVariable",
        "ShortMethodName",
        "ConstantNamingConventions",
        "BooleanGetMethodName",
        "ConstructorWithNameAsEnclosingClass",
    ),
    "unusedcode": (
        "UnusedPrivateField",
        "UnusedLocalVariable",
        "UnusedPrivateMethod",
        "UnusedFormalParameter",
    ),
    "cleancode": (
        "BooleanArgumentFlag",
        "ElseExpression",
        "StaticAccess",
        "IfStatementAssignment",
        "DuplicatedArrayKey",
    ),
    "python": (
        "IfStatementAssignment",
        "DuplicatedArrayKey",
    ),
    "opinionated": (
        "BooleanArgumentFlag",
        "ElseExpression",
        "StaticAccess",
        "IfStatementAssignment",
        "DuplicatedArrayKey",
    ),
    "codesize": (
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
    )
}


def load_rulesets(references: Iterable[str]) -> list[LoadedRule]:
    loaded: dict[str, LoadedRule] = {}
    for reference in references:
        try:
            _merge(loaded, _load_reference(reference, Path.cwd(), ()))
        except RulesetError as error:
            if str(error) == f"Unknown ruleset reference '{reference}'.":
                raise RulesetError(f"Unknown ruleset '{reference}'.") from error
            raise
    return list(loaded.values())


def filter_rules(
    rules: Iterable[LoadedRule],
    only: Iterable[str],
    enable: Iterable[str],
    disable: Iterable[str],
    minimum_priority: int,
    maximum_priority: int,
) -> list[LoadedRule]:
    loaded = list(rules)
    names = {_identity(rule.name): rule.name for rule in loaded}
    requested = [*only, *enable, *disable]
    for name in requested:
        if _identity(name) not in names:
            raise RulesetError(f"Unknown loaded rule '{name}'.")

    selected = {_identity(name) for name in [*only, *enable]}
    disabled = {_identity(name) for name in disable}
    return [
        rule
        for rule in loaded
        if (not selected or _identity(rule.name) in selected)
        and _identity(rule.name) not in disabled
        and minimum_priority <= rule.priority <= maximum_priority
    ]


def _load_reference(
    reference: str, directory: Path, ancestry: tuple[Path, ...]
) -> list[LoadedRule]:
    identity = _built_in_identity(reference)
    if identity in _BUILT_IN_RULESETS:
        return [_catalog_rule(name) for name in _BUILT_IN_RULESETS[identity]]
    if identity in _CATALOG:
        return [_catalog_rule(reference)]

    candidate = Path(reference)
    if not candidate.is_absolute():
        candidate = directory / candidate
    if not candidate.is_file():
        raise RulesetError(f"Unknown ruleset reference '{reference}'.")
    resolved = candidate.resolve()
    if resolved in ancestry:
        raise RulesetError(f"Ruleset reference cycle at '{resolved}'.")
    return _load_xml(resolved, (*ancestry, resolved))


def _load_xml(path: Path, ancestry: tuple[Path, ...]) -> list[LoadedRule]:
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError) as error:
        raise RulesetError(f"Unable to load ruleset '{path}': {error}") from error
    if _tag(root) != "ruleset":
        raise RulesetError(f"Ruleset '{path}' must have a ruleset root element.")

    loaded: dict[str, LoadedRule] = {}
    for element in root:
        if _tag(element) == "exclude":
            _exclude(loaded, _required_name(element, path))
            continue
        if _tag(element) != "rule":
            continue
        reference = element.get("ref")
        if not reference:
            raise RulesetError(f"Rule reference in '{path}' is missing ref.")
        referenced = _load_reference(reference, path.parent, ancestry)
        excluded = [_required_name(item, path) for item in element if _tag(item) == "exclude"]
        referenced_names = {_identity(rule.name) for rule in referenced}
        for name in excluded:
            if _identity(name) not in referenced_names:
                raise RulesetError(f"Unknown rule exclusion '{name}'.")
        referenced = [
            rule for rule in referenced if _identity(rule.name) not in {_identity(name) for name in excluded}
        ]
        _merge_reference(loaded, referenced, element, path)
    return list(loaded.values())


def _overrides(rules: Iterable[LoadedRule], element: ElementTree.Element, path: Path) -> list[LoadedRule]:
    priority = _priority(element, path)
    properties = _properties(element, path)
    if priority is None and not properties:
        return list(rules)
    return [
        replace(
            rule,
            priority=priority if priority is not None else rule.priority,
            properties={**rule.properties, **properties},
        )
        for rule in rules
    ]


def _priority(element: ElementTree.Element, path: Path) -> int | None:
    priority_element = next((item for item in element if _tag(item) == "priority"), None)
    if priority_element is None:
        return None
    try:
        priority = int(priority_element.text or "")
    except ValueError as error:
        raise RulesetError(f"Priority in '{path}' must be between 1 and 5.") from error
    if not 1 <= priority <= 5:
        raise RulesetError(f"Priority in '{path}' must be between 1 and 5.")
    return priority


def _properties(element: ElementTree.Element, path: Path) -> dict[str, str]:
    properties: dict[str, str] = {}
    for container in element:
        if _tag(container) != "properties":
            continue
        for property_element in container:
            if _tag(property_element) != "property":
                continue
            name = property_element.get("name")
            value = property_element.get("value")
            if not name or value is None:
                raise RulesetError(f"Property in '{path}' requires name and value.")
            properties[name.casefold()] = value
    return properties


def _merge(target: dict[str, LoadedRule], rules: Iterable[LoadedRule]) -> None:
    for rule in rules:
        target[_identity(rule.name)] = rule


def _merge_reference(
    target: dict[str, LoadedRule], referenced: Iterable[LoadedRule], element: ElementTree.Element, path: Path
) -> None:
    for rule in referenced:
        existing = target.get(_identity(rule.name), rule)
        target[_identity(rule.name)] = _overrides([existing], element, path)[0]


def _exclude(rules: dict[str, LoadedRule], name: str) -> None:
    identity = _identity(name)
    if identity not in rules:
        raise RulesetError(f"Unknown rule exclusion '{name}'.")
    rules.pop(identity)


def _catalog_rule(name: str) -> LoadedRule:
    rule = _CATALOG.get(_identity(name))
    if rule is None:
        raise RulesetError(f"Unknown ruleset reference '{name}'.")
    return rule


def _required_name(element: ElementTree.Element, path: Path) -> str:
    name = element.get("name")
    if not name:
        raise RulesetError(f"Exclude in '{path}' is missing name.")
    return name


def _identity(name: str) -> str:
    return name.casefold()


def _built_in_identity(reference: str) -> str:
    normalized = reference.replace("\\", "/")
    if normalized.casefold().startswith("rulesets/") and normalized.casefold().endswith(".xml"):
        normalized = normalized.rsplit("/", 1)[-1][:-4]
    return _identity(normalized)


def _tag(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].casefold()
