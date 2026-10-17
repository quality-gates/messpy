def first(items):
    for item in items:
        return item
    else:
        raise LookupError("empty")


def pop_or_empty(items):
    while items:
        return items.pop()
    else:
        return "empty"
