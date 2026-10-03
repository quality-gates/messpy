def validate_nested(x: int) -> int:
    if x > 0:
        if x > 10:
            return 10
        else:
            return 5
    else:
        return 0

def non_dead_else(x: int) -> int:
    if x > 0:
        if x > 10:
            return 10
        x += 1
    else:
        return 0
    return x
