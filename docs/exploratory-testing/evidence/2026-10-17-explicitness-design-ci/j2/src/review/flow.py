"""Dead-else cases a reviewer would expect the opinionated gate to catch."""


def always_exiting_try(value):
    if value:
        try:
            return int(value)
        except ValueError:
            return 0
        else:
            return 1
    else:
        return -1


def falling_except(value):
    if value:
        try:
            return int(value)
        except ValueError:
            value = 0
        else:
            return 1
    else:
        return -1
    return value


def try_finally(value):
    if value:
        try:
            return int(value)
        finally:
            value = 0
    else:
        return -1
    return value


def try_except_finally(value):
    if value:
        try:
            return int(value)
        except ValueError:
            return 0
        finally:
            value = 1
    else:
        return -1


def loop_else(items, target):
    for item in items:
        if item == target:
            break
    else:
        return None
    return item


def always_break(items):
    for item in items:
        break
    else:
        return None
    return items[0]


def match_exit(value):
    if value is None:
        match value:
            case None:
                return 0
            case _:
                return 1
    else:
        return -1
