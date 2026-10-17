"""Ambient sources and deferred forcing a calculation review would include."""

import asyncio
import logging
import os
import random
import sys
from typing import Final

RATE: Final[float] = 0.2
BUCKET: Final[list[int]] = [1]
CACHE = {}


def read_final_scalar():
    return RATE


def read_final_list():
    return BUCKET[0]


def try_import():
    try:
        from missing_mod import value
    except ImportError:
        value = 0
    return value


def clock():
    return os.times()


def entropy():
    return random.random()


def args():
    return sys.argv[0]


def ask():
    return input("amount: ")


def write_log(total):
    logging.info("total %s", total)
    return total


def write_file(text):
    with open("out.txt", "w") as handle:
        handle.write(text)


def sort_reads(items):
    return sorted(items, key=lambda item: CACHE.get(item, 0))


def sort_prints(items):
    return sorted(items, key=lambda item: print(item) or item)


def run_note():
    async def read_note():
        with open("note.txt") as handle:
            return handle.read()

    return asyncio.run(read_note())


def yield_from_cold():
    def gen():
        yield print("inside")

    def outer():
        yield from gen()

    return outer()


def genexpr(items):
    return (print(item) or item for item in items)


def consume_genexpr(items):
    return list(print(item) or item for item in items)
