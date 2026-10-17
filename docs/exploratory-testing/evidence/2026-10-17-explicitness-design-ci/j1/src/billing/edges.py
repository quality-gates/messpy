"""Edges a calculation review hits: decorators, recursion, star-args, streams."""

import subprocess
import sys


def star(args):
    args.append(1)


def starred(*args):
    args[0].append(1)


def keyworded(**kwargs):
    kwargs["row"].append(1)


def a(items):
    return b(items)


def b(items):
    items.append(1)
    return a(items)


def deco(fn):
    def wrapper(*args, **kwargs):
        print("call")
        return fn(*args, **kwargs)

    return wrapper


@deco
def pure(value):
    return value + 1


def use(value):
    return pure(value)


def streams():
    sys.stdout.write("x")
    return sys.stdin.read()


def launch():
    subprocess.run(["echo", "hi"])


class Box[T]:
    def __init__(self, value: T):
        self.value = value


def unpack(point):
    match point:
        case (x, y):
            return x + y
        case _:
            return 0
