from typing import Final, TypeVar

ValueType = TypeVar("ValueType")
DEFAULT_LIMIT: Final = 3


class HTTPClient:
    def fetch_value(self, value, /, *, default_value=None):
        current_value = value
        for i in range(DEFAULT_LIMIT):
            current_value += i
        return current_value if current_value else default_value


def use_length(values):
    descriptive_name_exactly_boundaryxx = len(values)
    return [value for value in values if value][:descriptive_name_exactly_boundaryxx]
