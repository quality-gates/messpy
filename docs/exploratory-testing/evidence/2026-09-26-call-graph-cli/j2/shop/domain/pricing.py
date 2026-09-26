from ..infra.rates import lookup as lookup_rate

def exchange(amount):
    return lookup_rate(amount)
