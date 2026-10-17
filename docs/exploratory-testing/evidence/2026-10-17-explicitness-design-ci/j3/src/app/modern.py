type Point = tuple[int, int]


def identity[T](value: T) -> T:
    return value


def grouped(value):
    try:
        return int(value)
    except* ValueError:
        return 0
    else:
        return 1
