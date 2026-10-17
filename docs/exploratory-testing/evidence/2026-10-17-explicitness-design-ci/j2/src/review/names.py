"""Names a reviewer would expect the recommended and opinionated gates to treat differently."""


def walk(items, i, x, y, e, name):
    total = 0
    for i, x in enumerate(items):
        total += x
    try:
        total += name
    except TypeError as e:
        total = 0
    return total, y


class Flags:
    def get_ready(self) -> bool:
        return True

    def get_user(self) -> str:
        return "ada"

    def is_ready(self) -> bool:
        return True


LIMIT = 10
tax_rate = 0.2


class Receipt:
    def __init__(self):
        self._token = 1

    def _sign(self):
        return self._token

    def show(self):
        return self._sign()


class Invoice(Receipt):
    def render(self):
        return self._sign()
