"""A calculation. Should stay quiet under onion."""


def quote_total(amount: float, rate: float) -> float:
    return round(amount * (1 + rate), 2)
