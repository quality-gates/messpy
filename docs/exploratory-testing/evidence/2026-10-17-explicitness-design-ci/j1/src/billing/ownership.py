"""Ownership cases from the explicitness contract."""

import datetime
import secrets
import time


def clock():
    return time.time()


def now():
    return datetime.datetime.now()


def token():
    return secrets.token_hex()


def alias_append(items):
    a, b = items, []
    a.append(1)
    return b


def swapped_alias(items):
    a, b = [], items
    b.append(1)
    return a


def branch_join(flag, items):
    if flag:
        target = []
    else:
        target = items
    target.append(1)
    return target


def both_fresh(flag):
    if flag:
        target = []
    else:
        target = []
    target.append(1)
    return target


def loop_rebind(items):
    target = []
    for _step in items:
        target = items
    target.append(1)
    return target


def dead_rebind(items):
    target = []
    while False:
        target = items
    target.append(1)
    return target


def retained_rebind(items):
    target = []
    while not True:
        target = items
    target.append(1)
    return target


def dict_copy(values):
    copied = dict(values)
    copied["local"] = 1
    return copied


def dict_nested(values):
    copied = dict(values)
    copied["row"].append(1)
    return copied


def list_sort(items, cache):
    items.sort(key=lambda item: cache.get(item, 0))
    return items


def fresh_sort():
    items = [3, 1, 2]
    items.sort(key=lambda item: item)
    return items
