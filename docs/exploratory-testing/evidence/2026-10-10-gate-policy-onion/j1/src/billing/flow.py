"""Control flow checked with the opinionated ruleset."""


def classify(value):
    if value is None:
        try:
            return "missing"
        finally:
            value = "logged"
    else:
        return "present"
    return "unreachable"


def route(flag, value):
    if flag:
        match value:
            case 1:
                return "one"
            case _:
                return "other"
    else:
        return "skipped"
