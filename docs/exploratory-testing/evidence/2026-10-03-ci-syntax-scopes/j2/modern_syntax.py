# PEP 695 type aliases and generic function
type UserId = int
type Container[T] = list[T]

def get_first[T](items: list[T]) -> T | None:
    if not items:
        return None
    return items[0]

# Pattern matching with guards and unused variable bindings
def process_event(event):
    match event:
        case {"type": "login", "user": user}:
            return user
        case {"type": "logout", **rest}:
            return None
        case [x, y] if x > y:
            return x
        case _:
            return False

# Walrus in if condition and duplicate array keys
def build_config(flag):
    if option := flag.get("opt"):
        options = {1: "first", 1.0: "duplicate", (True, False): "tup", (True, False): "dup_tup"}
        return options
    return None
