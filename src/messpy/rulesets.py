from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from typing import Iterable, Union, cast
import xml.etree.ElementTree as ElementTree


_INTEGER_PROPERTIES = frozenset({"minimum", "maximum", "reportlevel", "maxfields", "maxmethods"})
_BOOLEAN_PROPERTIES = frozenset(
    {"ignore-whitespace", "report-immutable", "allow-underscore", "allow-underscore-test"}
)
_PATTERN_PROPERTIES = frozenset({"ignorepattern"})
_PropertyValue = Union[int, bool, "re.Pattern[str]", list[str]]
_REQUIRED_ITEMS = {
    "DomainAction": (("domain", "path pattern"),),
    "DomainOuterImport": (("domain", "path pattern"), ("outer-layers", "module")),
}


@dataclass(frozen=True)
class LoadedRule:
    """A rule whose property values are parsed when it is built, so the typed
    reads detectors use cannot fail."""

    name: str
    priority: int
    properties: dict[str, str]
    _values: dict[str, _PropertyValue] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        values = {key: _parse(self.name, key, value) for key, value in self.properties.items()}
        object.__setattr__(self, "_values", values)

    def integer(self, property_name: str) -> int:
        return cast(int, self._values[property_name])

    def boolean(self, property_name: str) -> bool:
        return cast(bool, self._values.get(property_name, False))

    def pattern(self, property_name: str) -> re.Pattern[str]:
        return cast(re.Pattern[str], self._values.get(property_name, _MATCH_NOTHING))

    def items(self, property_name: str, default: str = "") -> list[str]:
        return cast(list[str], self._values.get(property_name, _items(default)))


@dataclass(frozen=True)
class BuiltInRuleReference:
    name: str
    properties: dict[str, str]


class RulesetError(Exception):
    pass


@dataclass(frozen=True)
class RuleSelection:
    rulesets: tuple[str, ...]
    only: tuple[str, ...] = ()
    enable: tuple[str, ...] = ()
    disable: tuple[str, ...] = ()
    minimum_priority: int = 1
    maximum_priority: int = 5

    def __post_init__(self) -> None:
        for priority in (self.minimum_priority, self.maximum_priority):
            if type(priority) is not int or not 1 <= priority <= 5:
                raise RulesetError("Priority must be an integer between 1 and 5.")
        if self.minimum_priority > self.maximum_priority:
            raise RulesetError("Minimum priority must not exceed maximum priority.")


_MATCH_NOTHING = re.compile(r"(?!)")


def _parse(rule_name: str, property_name: str, value: str) -> _PropertyValue:
    if property_name in _INTEGER_PROPERTIES:
        return _integer(rule_name, property_name, value)
    if property_name in _BOOLEAN_PROPERTIES:
        return _boolean(rule_name, property_name, value)
    if property_name in _PATTERN_PROPERTIES:
        return _pattern(rule_name, property_name, value)
    return _items(value)


def _items(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _integer(rule_name: str, property_name: str, value: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise RulesetError(f"{rule_name} property '{property_name}' must be an integer.") from error


def _boolean(rule_name: str, property_name: str, value: str) -> bool:
    folded = value.casefold()
    if folded not in ("true", "false"):
        raise RulesetError(f"{rule_name} property '{property_name}' must be true or false.")
    return folded == "true"


def _pattern(rule_name: str, property_name: str, value: str) -> re.Pattern[str]:
    stripped = value.strip()
    ignore_case = stripped.endswith(")i")
    pattern = stripped[:-1].strip() if ignore_case else stripped
    if not pattern:
        # An empty (or whitespace-only) pattern would match every name, so it
        # excludes nothing: fall back to a pattern that never matches.
        return _MATCH_NOTHING
    try:
        return re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as error:
        raise RulesetError(f"{rule_name} property '{property_name}' must be a valid regular expression.") from error


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
    "exitexpression": LoadedRule(name="ExitExpression", priority=1, properties={}),
    "gotostatement": LoadedRule(name="GotoStatement", priority=1, properties={}),
    "countinloopexpression": LoadedRule(name="CountInLoopExpression", priority=2, properties={}),
    "developmentcodefragment": LoadedRule(
        name="DevelopmentCodeFragment",
        priority=2,
        properties={"unwanted-functions": "", "markers": "TODO,FIXME,HACK"},
    ),
    "emptycatchblock": LoadedRule(name="EmptyCatchBlock", priority=2, properties={}),
    "couplingbetweenobjects": LoadedRule(
        name="CouplingBetweenObjects", priority=2, properties={"maximum": "13"}
    ),
    "globalvariable": LoadedRule(
        name="GlobalVariable", priority=1, properties={"report-immutable": "false"}
    ),
    "lackofcohesionofmethods": LoadedRule(
        name="LackOfCohesionOfMethods", priority=3, properties={"maximum": "1"}
    ),
    "camelcaseclassname": LoadedRule(name="CamelCaseClassName", priority=1, properties={}),
    "camelcasemethodname": LoadedRule(
        name="CamelCaseMethodName",
        priority=1,
        properties={"allow-underscore": "false", "allow-underscore-test": "false"},
    ),
    "camelcasepropertyname": LoadedRule(
        name="CamelCasePropertyName",
        priority=1,
        properties={"allow-underscore": "false", "allow-underscore-test": "false"},
    ),
    "camelcaseparametername": LoadedRule(
        name="CamelCaseParameterName", priority=1, properties={"allow-underscore": "false"}
    ),
    "camelcasevariablename": LoadedRule(
        name="CamelCaseVariableName", priority=1, properties={"allow-underscore": "false"}
    ),
    "implicitinput": LoadedRule(name="ImplicitInput", priority=3, properties={}),
    "implicitoutput": LoadedRule(name="ImplicitOutput", priority=3, properties={}),
    "implicitinstanceinput": LoadedRule(name="ImplicitInstanceInput", priority=3, properties={}),
    "implicitinstanceoutput": LoadedRule(name="ImplicitInstanceOutput", priority=3, properties={}),
    "domainaction": LoadedRule(name="DomainAction", priority=2, properties={"domain": ""}),
    "domainouterimport": LoadedRule(
        name="DomainOuterImport",
        priority=2,
        properties={"domain": "", "outer-layers": ""},
    ),
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
    "design": (
        "ExitExpression",
        "GotoStatement",
        "CountInLoopExpression",
        "DevelopmentCodeFragment",
        "EmptyCatchBlock",
        "CouplingBetweenObjects",
        "GlobalVariable",
        "LackOfCohesionOfMethods",
    ),
    "python": (
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
        BuiltInRuleReference("LongVariable", {"maximum": "35"}),
        "ShortMethodName",
        "ConstantNamingConventions",
        "BooleanGetMethodName",
        "UnusedPrivateField",
        "UnusedLocalVariable",
        "UnusedPrivateMethod",
        "IfStatementAssignment",
        "DuplicatedArrayKey",
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
    ),
    "controversial": (
        "CamelCaseClassName",
        "CamelCaseMethodName",
        "CamelCasePropertyName",
        "CamelCaseParameterName",
        "CamelCaseVariableName",
    ),
    "opinionated": (
        "ShortVariable",
        "UnusedFormalParameter",
        "BooleanArgumentFlag",
        "ElseExpression",
        "StaticAccess",
        "CountInLoopExpression",
        "ExitExpression",
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
    ),
    "explicitness": (
        "ImplicitInput",
        "ImplicitOutput",
    ),
    "strictexplicitness": (
        "ImplicitInput",
        "ImplicitOutput",
        "ImplicitInstanceInput",
        "ImplicitInstanceOutput",
    ),
    "onion": (
        "DomainAction",
        "DomainOuterImport",
    ),
}


def built_in_ruleset_names() -> tuple[str, ...]:
    return tuple(_BUILT_IN_RULESETS)


def load_rulesets(references: Iterable[str]) -> list[LoadedRule]:
    loaded: dict[str, LoadedRule] = {}
    for reference in references:
        try:
            loaded = _merge(loaded, _load_reference(reference, Path.cwd(), ()))
        except RulesetError as error:
            if str(error) == f"Unknown ruleset reference '{reference}'.":
                raise RulesetError(f"Unknown ruleset '{reference}'.") from error
            raise
    rules = list(loaded.values())
    _validate_required_items(rules)
    return rules


def _validate_required_items(rules: Iterable[LoadedRule]) -> None:
    for rule in rules:
        for property_name, kind in _REQUIRED_ITEMS.get(rule.name, ()):
            if not rule.items(property_name):
                raise RulesetError(f"{rule.name} property '{property_name}' must name at least one {kind}.")


def select_rules(selection: RuleSelection) -> list[LoadedRule]:
    loaded = load_rulesets(selection.rulesets)
    names = {_identity(rule.name): rule.name for rule in loaded}
    _validate_rule_names((*selection.only, *selection.enable, *selection.disable), names)

    selected = {_identity(name) for name in (*selection.only, *selection.enable)}
    disabled = {_identity(name) for name in selection.disable}
    return [
        rule
        for rule in loaded
        if _rule_is_selected(
            rule,
            selected,
            disabled,
            selection.minimum_priority,
            selection.maximum_priority,
        )
    ]


def _validate_rule_names(requested: Iterable[str], loaded_names: dict[str, str]) -> None:
    for name in requested:
        if _identity(name) not in loaded_names:
            raise RulesetError(f"Unknown loaded rule '{name}'.")


def _rule_is_selected(
    rule: LoadedRule,
    selected: set[str],
    disabled: set[str],
    minimum_priority: int,
    maximum_priority: int,
) -> bool:
    identity = _identity(rule.name)
    return (
        (not selected or identity in selected)
        and identity not in disabled
        and minimum_priority <= rule.priority <= maximum_priority
    )


def _load_reference(
    reference: str, directory: Path, ancestry: tuple[Path, ...]
) -> list[LoadedRule]:
    identity = _built_in_identity(reference)
    if identity in _BUILT_IN_RULESETS:
        return [_built_in_rule(reference) for reference in _BUILT_IN_RULESETS[identity]]
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
        loaded = _merge_ruleset_element(loaded, element, path, ancestry)
    return list(loaded.values())


def _merge_ruleset_element(
    loaded: dict[str, LoadedRule],
    element: ElementTree.Element,
    path: Path,
    ancestry: tuple[Path, ...],
) -> dict[str, LoadedRule]:
    if _tag(element) == "exclude":
        return _exclude(loaded, _required_name(element, path))
    if _tag(element) != "rule":
        return loaded
    reference = element.get("ref")
    if not reference:
        raise RulesetError(f"Rule reference in '{path}' is missing ref.")
    referenced = _load_reference(reference, path.parent, ancestry)
    referenced = _without_rule_exclusions(referenced, element, path)
    properties = _properties(element, path)
    _validate_property_names(properties, referenced, reference)
    return _merge_reference(loaded, referenced, element, path, properties)


def _without_rule_exclusions(
    referenced: list[LoadedRule], element: ElementTree.Element, path: Path
) -> list[LoadedRule]:
    excluded = [_required_name(item, path) for item in element if _tag(item) == "exclude"]
    referenced_names = {_identity(rule.name) for rule in referenced}
    for name in excluded:
        if _identity(name) not in referenced_names:
            raise RulesetError(f"Unknown rule exclusion '{name}'.")
    excluded_names = {_identity(name) for name in excluded}
    return [rule for rule in referenced if _identity(rule.name) not in excluded_names]


def _overrides(
    rules: Iterable[LoadedRule],
    element: ElementTree.Element,
    path: Path,
    properties: dict[str, str],
) -> list[LoadedRule]:
    priority = _priority(element, path)
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


def _validate_property_names(
    properties: dict[str, str], referenced: list[LoadedRule], reference: str
) -> None:
    known_names = {name for rule in referenced for name in rule.properties}
    for name in properties:
        if name in known_names:
            continue
        if len(referenced) == 1:
            target = f"rule '{referenced[0].name}'"
        else:
            target = f"ruleset reference '{reference}'"
        raise RulesetError(f"Unknown property '{name}' for {target}.")


def _merge(current: dict[str, LoadedRule], rules: Iterable[LoadedRule]) -> dict[str, LoadedRule]:
    merged = dict(current)
    for rule in rules:
        merged[_identity(rule.name)] = rule
    return merged


def _merge_reference(
    current: dict[str, LoadedRule],
    referenced: Iterable[LoadedRule],
    element: ElementTree.Element,
    path: Path,
    properties: dict[str, str],
) -> dict[str, LoadedRule]:
    merged = dict(current)
    for rule in referenced:
        identity = _identity(rule.name)
        existing = merged.get(identity, rule)
        merged[identity] = _overrides([existing], element, path, properties)[0]
    return merged


def _exclude(rules: dict[str, LoadedRule], name: str) -> dict[str, LoadedRule]:
    identity = _identity(name)
    if identity not in rules:
        raise RulesetError(f"Unknown rule exclusion '{name}'.")
    return {key: rule for key, rule in rules.items() if key != identity}


def _built_in_rule(reference: str | BuiltInRuleReference) -> LoadedRule:
    if isinstance(reference, str):
        return _catalog_rule(reference)
    rule = _catalog_rule(reference.name)
    return replace(rule, properties={**rule.properties, **reference.properties})


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
