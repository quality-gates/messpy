class FulfilmentDesk:
    def __init__(self):
        self.pending = []
        self.currency = "GBP"

    def reserve(self, order):
        self.pending.append(order)

    def release_all(self):
        self.pending.clear()

    def currency_label(self):
        return self.currency

    def announce_currency(self):
        print(self.currency_label())

    @property
    def pending_count(self):
        return len(self.pending)
