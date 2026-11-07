from pathlib import Path
from xml.etree.ElementTree import Element

from messpy.rulesets import LoadedRule, _merge_reference


def nested_priority(first: int, later: int) -> None:
    assert 1 <= first <= 5
    assert 1 <= later <= 5
    name = "ExcessiveMethodLength"
    before = LoadedRule(name, first, {"minimum": "3"})
    after = LoadedRule(name, later, {"minimum": "3"})
    result = _merge_reference(
        {name.casefold(): before}, [after], Element("rule"), Path("wrapper.xml"), {}
    )
    assert result[name.casefold()].priority == later


def nested_minimum(first: int, later: int) -> None:
    assert 1 <= first <= 9
    assert 1 <= later <= 9
    name = "ExcessiveMethodLength"
    before = LoadedRule(name, 3, {"minimum": str(first)})
    after = LoadedRule(name, 3, {"minimum": str(later)})
    result = _merge_reference(
        {name.casefold(): before}, [after], Element("rule"), Path("wrapper.xml"), {}
    )
    assert result[name.casefold()].integer("minimum") == later
