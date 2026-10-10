"""Private helpers shared down a small class hierarchy."""


class SignedDocument:
    def __init__(self, token):
        self._token = token

    def _sign(self):
        return self._token


class Receipt(SignedDocument):
    def export(self):
        return self._sign()


class UnrelatedStamp:
    def _sign(self):
        return "not-a-receipt"

    def apply(self):
        return "stamped"
