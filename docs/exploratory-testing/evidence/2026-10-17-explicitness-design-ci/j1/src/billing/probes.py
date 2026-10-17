"""Follow-up cases after the first explicitness scan."""

ITEMS = [1]


def read_shared():
    return ITEMS[0]


def caller_of_read():
    return read_shared()


def announce(total):
    print(total)
    return total


def shout(total):
    return announce(total)


def rebind(items):
    items = []
    items.append(1)
    return items


def write_global():
    global ITEMS
    ITEMS = [2]


def capture_box(box):
    def inner():
        box.append(1)

    inner()


def generator_body():
    yield print("cold")


def force_generator():
    for _item in generator_body():
        return _item


def module_print():
    print("load")


module_print()
