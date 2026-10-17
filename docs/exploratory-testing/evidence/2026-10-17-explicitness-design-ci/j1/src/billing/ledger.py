"""Instance state a strict explicitness gate would separate from calculations."""


class Ledger:
    def __init__(self, balance):
        self.balance = balance

    def preview(self, amount):
        return self.balance + amount

    def post(self, amount):
        self.balance += amount
        return self.balance

    def pure(self, amount):
        return amount * 2
