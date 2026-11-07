from messpy.rulesets import LoadedRule, _ConfiguredRule, _merge


def nested_priority(first: int, later: int) -> None:
    assert 1 <= first <= 5
    assert 1 <= later <= 5
    name = "ExcessiveMethodLength"
    before = _ConfiguredRule(LoadedRule(name, first, {"minimum": "3"}), True, frozenset({"minimum"}))
    after = _ConfiguredRule(LoadedRule(name, later, {"minimum": "3"}), True, frozenset({"minimum"}))
    result = _merge({name.casefold(): before}, [after])
    assert result[name.casefold()].rule.priority == later


def nested_minimum(first: int, later: int) -> None:
    assert 1 <= first <= 9
    assert 1 <= later <= 9
    name = "ExcessiveMethodLength"
    before = _ConfiguredRule(LoadedRule(name, 3, {"minimum": str(first)}), True, frozenset({"minimum"}))
    after = _ConfiguredRule(LoadedRule(name, 3, {"minimum": str(later)}), True, frozenset({"minimum"}))
    result = _merge({name.casefold(): before}, [after])
    assert result[name.casefold()].rule.integer("minimum") == later


def omitted_priority(first: int, later: int) -> None:
    assert 1 <= first <= 5
    assert 1 <= later <= 9
    name = "ExcessiveMethodLength"
    before = _ConfiguredRule(LoadedRule(name, first, {"minimum": "3"}), True, frozenset({"minimum"}))
    after = _ConfiguredRule(LoadedRule(name, 3, {"minimum": str(later)}), False, frozenset({"minimum"}))
    result = _merge({name.casefold(): before}, [after])
    assert result[name.casefold()].rule.priority == first


def omitted_minimum(first: int, later: int) -> None:
    assert 1 <= first <= 9
    assert 1 <= later <= 5
    name = "ExcessiveMethodLength"
    before = _ConfiguredRule(LoadedRule(name, 3, {"minimum": str(first)}), True, frozenset({"minimum"}))
    after = _ConfiguredRule(LoadedRule(name, later, {"minimum": "100"}), True, frozenset())
    result = _merge({name.casefold(): before}, [after])
    assert result[name.casefold()].rule.integer("minimum") == first
