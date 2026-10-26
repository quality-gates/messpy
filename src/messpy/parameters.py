"""Bind a call's arguments to the parameters of the callable it calls.

One binding answers "which argument gives this parameter its value?" for heap
execution, storage-origin instantiation, effect substitution and callback
substitution. Binding reads syntax only. Each caller interprets the bound
arguments, defaults and packs as its own values.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence, Set as AbstractSet
from dataclasses import dataclass
from typing import Generic, TypeVar

__all__ = ["Bound", "bind_arguments", "bind_call"]

T = TypeVar("T")
SlotKey = tuple[str, str | int]

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


@dataclass(frozen=True)
class Bound(Generic[T]):
    """Where one parameter's value comes from.

    A parameter takes the argument passed for it, or its default expression,
    which Python evaluated where the callable was defined. A *args or **kwargs
    parameter is a fresh "tuple" or "dict" pack of the extra arguments, each
    keyed by its storage slot key.
    """

    argument: T | None = None
    default: ast.expr | None = None
    pack: str = ""
    items: tuple[tuple[SlotKey, T], ...] = ()


def bind_call(function: ast.AST, call: ast.Call, receiver: bool) -> dict[str, Bound[ast.expr]] | None:
    """Bind the call's argument expressions to the function's parameters.

    The receiver flag says the function is a method with a bound receiver, so
    an attribute call passes the attribute's object as the first argument.
    Return None for a call that unpacks arguments or that Python would reject.
    """
    if not isinstance(function, _FUNCTIONS) or _spread_arguments(call):
        return None
    positional = list(call.args)
    if receiver and isinstance(call.func, ast.Attribute):
        positional.insert(0, call.func.value)
    return bind_arguments(function.args, positional, [(keyword.arg, keyword.value) for keyword in call.keywords])


def bind_arguments(
    arguments: ast.arguments, positional: Sequence[T], keywords: Sequence[tuple[str, T]]
) -> dict[str, Bound[T]] | None:
    """Bind known positional and keyword arguments, or return None when Python would raise TypeError."""
    parameters = [*arguments.posonlyargs, *arguments.args]
    if len(positional) > len(parameters) and arguments.vararg is None:
        return None
    bound: dict[str, Bound[T]] = {parameter.arg: Bound(value) for parameter, value in zip(parameters, positional)}
    passed = _keyword_arguments(arguments, bound.keys(), keywords)
    if passed is None:
        return None
    named, extra = passed
    bound = {**_defaults(arguments, parameters), **bound, **named}
    if any(parameter.arg not in bound for parameter in [*parameters, *arguments.kwonlyargs]):
        return None
    return {**bound, **_packs(arguments, positional[len(parameters):], extra)}


def _keyword_arguments(
    arguments: ast.arguments, filled: AbstractSet[str], keywords: Sequence[tuple[str, T]]
) -> tuple[dict[str, Bound[T]], tuple[tuple[SlotKey, T], ...]] | None:
    """Split keywords into named parameters and the extra keywords that **kwargs collects."""
    names = {parameter.arg for parameter in [*arguments.args, *arguments.kwonlyargs]}
    named = {name: Bound(value) for name, value in keywords if name in names}
    extra = tuple((("item", name), value) for name, value in keywords if name not in names)
    if named.keys() & filled or extra and arguments.kwarg is None:
        return None
    return named, extra


def _defaults(arguments: ast.arguments, parameters: Sequence[ast.arg]) -> dict[str, Bound]:
    positional = zip(parameters[len(parameters) - len(arguments.defaults):], arguments.defaults)
    keyword = zip(arguments.kwonlyargs, arguments.kw_defaults)
    return {parameter.arg: Bound(default=default) for parameter, default in [*positional, *keyword] if default is not None}


def _packs(
    arguments: ast.arguments, positional: Sequence[T], keywords: tuple[tuple[SlotKey, T], ...]
) -> dict[str, Bound[T]]:
    packs = {}
    if arguments.vararg is not None:
        packs[arguments.vararg.arg] = Bound(pack="tuple", items=tuple((("item", index), value) for index, value in enumerate(positional)))
    if arguments.kwarg is not None:
        packs[arguments.kwarg.arg] = Bound(pack="dict", items=keywords)
    return packs


def _spread_arguments(call: ast.Call) -> bool:
    return any(isinstance(value, ast.Starred) for value in call.args) or any(keyword.arg is None for keyword in call.keywords)
