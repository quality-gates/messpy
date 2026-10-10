"""Pure tax calculation."""


def tax_due(amount: float, rate: float) -> float:
    return round(amount * rate, 2)
