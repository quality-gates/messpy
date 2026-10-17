"""Pricing helpers a reviewer would gate with the explicitness ruleset."""

import os
from dataclasses import dataclass

TAX_RATE = 0.2
IMMUTABLE = (1, 2)
MUTABLE_TUPLE = ([1], 2)
CACHE = {}
UPPER = [1, 2, 3]


def net(gross, rate):
    return gross * (1 - rate)


def taxed(gross):
    return net(gross, TAX_RATE)


def read_immutable():
    return IMMUTABLE[0]


def read_mutable_tuple():
    return MUTABLE_TUPLE[0][0]


def remember(gross):
    if gross in CACHE:
        return CACHE[gross]
    value = taxed(gross)
    CACHE[gross] = value
    return value


def announce(total):
    print(total)
    print(total)
    return total


def stamp(items):
    items.append("stamped")
    return items


def copy_and_stamp(items):
    copied = list(items)
    copied.append("stamped")
    return copied


def mutate_nested(items):
    copied = list(items)
    copied[0].append("stamped")
    return copied


def push(target, mark):
    target.append(mark)


def via_helper(items):
    fresh = []
    push(fresh, "local")
    push(items, "caller")
    return fresh


def scale(rate):
    def apply(gross):
        return gross * rate

    return apply(10)


def leak(items):
    def read():
        return items[0]

    return read()


def read_upper():
    return UPPER[0]


def read_env():
    return os.environ["TAX_REGION"]


async def read_note():
    with open("note.txt") as handle:
        return handle.read()


async def load_note():
    return await read_note()


def schedule_only():
    return read_note()


def inject(callback, value):
    return callback(value)


def rank(items):
    return sorted(items, key=lambda item: item.score)


@dataclass(frozen=True)
class Money:
    cents: int


def add(left, right):
    return Money(left.cents + right.cents)


def dead_branch(flag):
    if False:
        print("pruned")
    if not True:
        print("retained")
    return flag


def alias_print(total):
    say = print
    say(total)
    return total
